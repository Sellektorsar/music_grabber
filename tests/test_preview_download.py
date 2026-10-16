"""Тесты на потоковое предпрослушивание трека.

``download_track_preview`` качает первые килобайты аудио, чтобы DJ мог
нажать трек и сразу услышать начало, не дожидаясь полной загрузки.
Поэтому проверяется именно то, что важно: кэш не перекачивается зря,
объём ограничен, отмена не оставляет мусора, а любая ошибка Telegram
превращается в None, а не в исключение на весь интерфейс.
"""

import asyncio
import os
from unittest.mock import MagicMock

import pytest

import recorder as rec


@pytest.fixture(autouse=True)
def _clean_cache():
    rec._CHANNEL_ENTITY_CACHE.clear()
    yield
    rec._CHANNEL_ENTITY_CACHE.clear()


@pytest.fixture
def r(tmp_path):
    recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan")
    recorder.log = MagicMock()
    recorder._cancelled = False
    recorder.base_folder = str(tmp_path)
    return recorder


def _message(media=object()):
    message = MagicMock()
    message.media = media
    return message


def _async_chunks(*sizes):
    """Настоящий асинхронный генератор -- его и распознаёт inspect."""
    async def iter_download(*_a, **_kw):
        for size in sizes:
            yield b"\x00" * size

    return iter_download


def _run(coro):
    return asyncio.run(coro)


def _fetch(r, message_id=42, max_bytes=1024 * 1024):
    """Вызывает предпрослушивание с явным лимитом объёма."""
    return _run(r.download_track_preview("@chan", message_id, max_bytes))


class TestPreviewCache:
    """Кэш превью: повторный клик не должен качать заново."""

    def test_existing_preview_is_reused(self, r):
        previews = os.path.join(r.base_folder, "previews")
        os.makedirs(previews)
        cached = os.path.join(previews, "preview_42.mp3")
        with open(cached, "wb") as fh:
            fh.write(b"\x00" * 64 * 1024)

        got = _run(r.download_track_preview("@chan", 42))

        assert got == cached
        r.client.get_messages.assert_not_called()

    def test_truncated_cache_is_replaced(self, r):
        """Обрывок меньше 32KB бесполезен -- превью надо докачать."""
        previews = os.path.join(r.base_folder, "previews")
        os.makedirs(previews)
        stale = os.path.join(previews, "preview_42.mp3")
        with open(stale, "wb") as fh:
            fh.write(b"\x00" * 100)

        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = _async_chunks(64 * 1024)

        got = _run(r.download_track_preview("@chan", 42))

        assert got is not None
        assert os.path.getsize(got) >= 32 * 1024


class TestPreviewLookup:
    """Поиск сообщения в Telegram."""

    def test_no_messages_returns_none(self, r):
        r.client.get_messages = MagicMock(return_value=[])
        assert _run(r.download_track_preview("@chan", 7)) is None

    def test_message_without_media_returns_none(self, r):
        r.client.get_messages = MagicMock(return_value=[_message(media=None)])
        assert _run(r.download_track_preview("@chan", 7)) is None

    def test_lookup_error_is_logged_not_raised(self, r):
        """Ошибка Telegram не должна пробивать окно исключением."""
        r.client.get_messages = MagicMock(side_effect=RuntimeError("сеть"))
        assert _run(r.download_track_preview("@chan", 7)) is None
        assert "Ошибка при скачивании превью" in r.log.call_args[0][0]

    def test_entity_is_resolved_and_cached(self, r):
        """Сущность канала запрашивается один раз, а не на каждый клик."""
        entity = object()
        r.client.get_entity = MagicMock(return_value=entity)
        r.client.get_messages = MagicMock(return_value=[])
        r.client.iter_download = _async_chunks()

        _run(r.download_track_preview("@chan", 7))
        _run(r.download_track_preview("@chan", 8))

        assert r.client.get_entity.call_count == 1
        assert "@chan" in rec._CHANNEL_ENTITY_CACHE


class TestPreviewDownload:
    """Само скачивание превью."""

    def _prepare(self, r, chunk_sizes):
        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = _async_chunks(*chunk_sizes)

    def test_preview_is_written(self, r):
        self._prepare(r, [64 * 1024])
        got = _fetch(r)
        assert got is not None
        assert os.path.getsize(got) == 64 * 1024

    def test_size_is_capped(self, r):
        """Клик тянет только начало трека, а не файл целиком."""
        self._prepare(r, [64 * 1024, 64 * 1024, 64 * 1024])
        got = _fetch(r, max_bytes=128 * 1024)
        assert os.path.getsize(got) == 128 * 1024

    def test_part_file_is_removed(self, r):
        """После успеха временного .part на диске остаться не должно."""
        self._prepare(r, [64 * 1024])
        got = _fetch(r)
        assert not os.path.exists(got + ".part")

    def test_previews_dir_is_created(self, r):
        self._prepare(r, [64 * 1024])
        _fetch(r)
        assert os.path.isdir(os.path.join(r.base_folder, "previews"))

    def test_old_preview_is_overwritten(self, r):
        previews = os.path.join(r.base_folder, "previews")
        os.makedirs(previews)
        with open(os.path.join(previews, "preview_42.mp3"), "wb") as fh:
            fh.write(b"\x00" * 1024)

        self._prepare(r, [64 * 1024])
        got = _fetch(r)
        assert os.path.getsize(got) == 64 * 1024


class TestPreviewCancellation:
    """Отмена не должна оставлять огрызков на диске."""

    def _parts(self, r):
        previews = os.path.join(r.base_folder, "previews")
        os.makedirs(previews, exist_ok=True)
        return previews

    def test_cancel_stops_and_cleans_up(self, r):
        async def iter_download(*_a, **_kw):
            yield b"\x00" * 1024
            r._cancelled = True
            yield b"\x00" * 1024

        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = iter_download

        assert _fetch(r) is None

        leftovers = os.listdir(self._parts(r))
        assert leftovers == [], f"остался мусор: {leftovers}"

    def test_cancelled_before_start_returns_none(self, r):
        r._cancelled = True
        r.client.get_messages = MagicMock(return_value=[_message()])
        assert _fetch(r) is None


class TestPreviewFallback:
    """Если потоковая запись не сработала, есть запасной путь."""

    def test_falls_back_to_message_download_media(self, r):
        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = None      # старый Telethon без iter_download

        message = r.client.get_messages.return_value[0]

        def download_media(file=None, **_kw):
            with open(file, "wb") as fh:
                fh.write(b"\x00" * 40 * 1024)

        message.download_media = download_media

        got = _fetch(r)
        assert got is not None
        assert os.path.getsize(got) == 40 * 1024

    def test_no_data_at_all_returns_none(self, r):
        """Ни один способ не дал байтов -- это None, а не пустой файл."""
        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = None
        r.client.get_messages.return_value[0].download_media = None
        assert _fetch(r) is None

    def test_stream_error_still_leaves_preview(self, r):
        """Обрыв потока не должен отменять предпрослушивание."""

        async def iter_download(*_a, **_kw):
            yield b"\x00" * 40 * 1024
            raise ConnectionError("обрыв")

        r.client.get_messages = MagicMock(return_value=[_message()])
        r.client.iter_download = iter_download

        got = _fetch(r)
        assert got is not None, "уже скачанные байты должны сохраниться"
        assert os.path.getsize(got) == 40 * 1024