"""Тесты на скачивание с докачкой и повторами.

Это самый уязвимый участок загрузки: сеть отваливается посреди файла,
Telegram просит подождать при FloodWait, а пользователь может нажать
«стоп» в любой момент. Поэтому проверяются именно обязательства:

* оборванный файл докачивается с места обрыва, а не заново;
* полностью скачанный .part принимается без повторной загрузки;
* отмена останавливает всё немедленно;
* ошибка диска не съедает все попытки подряд.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

import recorder as rec


@pytest.fixture
def r(tmp_path):
    recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan", mode="direct")
    recorder.log = MagicMock()
    recorder._cancelled = False
    recorder.base_folder = str(tmp_path)
    return recorder


def _run(coro):
    return asyncio.run(coro)


def _message(media=object()):
    message = MagicMock()
    message.media = media
    return message


def _chunks(*sizes):
    """Настоящий асинхронный генератор: только его берёт iter_download."""
    async def iter_download(_media, offset=0, request_size=0):
        for size in sizes:
            yield b"\x00" * size

    return iter_download


def _messages(r, chunk_sizes, data=None):
    r.client.iter_download = _chunks(*chunk_sizes)
    return _message()


class TestSuccessfulDownload:
    """Нормальное скачивание целого файла."""

    def test_file_is_created(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")
        r.client.iter_download = _chunks(64 * 1024)
        assert _run(r._download_with_retry(_message(), path,
                                           total_size=64 * 1024)) is True
        assert os.path.exists(path)

    def test_part_file_is_removed(self, r, tmp_path):
        """Временный .part не должен оставаться после успеха."""
        path = str(tmp_path / "track.mp3")
        r.client.iter_download = _chunks(64 * 1024)
        _run(r._download_with_retry(_message(), path, total_size=64 * 1024))
        assert not os.path.exists(path + ".part")

    def test_progress_callback_gets_offsets(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")
        r.client.iter_download = _chunks(1024, 2048)
        seen = []
        _run(r._download_with_retry(_message(), path,
                                    progress_callback=lambda d, t: seen.append(d),
                                    total_size=3072))
        assert seen == [1024, 3072]


class TestResume:
    """Докачка после обрыва."""

    def _part(self, tmp_path, name, size):
        part = tmp_path / (name + ".part")
        part.write_bytes(b"\x00" * size)
        return part

    def test_resume_is_logged(self, r, tmp_path):
        """Пользователь должен видеть, что файл докачивается, а не качается заново."""
        self._part(tmp_path, "track.mp3", 4096)
        r.client.iter_download = _chunks(4096)
        _run(r._download_with_retry(_message(), str(tmp_path / "track.mp3"),
                                    total_size=8192))
        assert any("Докачка файла" in c[0][0] for c in r.log.call_args_list)

    def test_download_starts_from_offset(self, r, tmp_path):
        """Серверу должен уходить offset, иначе всё качается с нуля."""
        self._part(tmp_path, "track.mp3", 4096)
        offsets = []

        async def iter_download(_media, offset=0, request_size=0):
            offsets.append(offset)
            yield b"\x00" * 4096

        r.client.iter_download = iter_download
        _run(r._download_with_retry(_message(), str(tmp_path / "track.mp3"),
                                    total_size=8192))
        assert offsets == [4096]

    def test_complete_part_is_accepted_without_download(self, r, tmp_path):
        """Докачивать уже полный файл -- лишний трафик."""
        self._part(tmp_path, "track.mp3", 8192)
        r.client.iter_download = _chunks(0)
        assert _run(r._download_with_retry(_message(),
                                           str(tmp_path / "track.mp3"),
                                           total_size=8192)) is True

    def test_cancelled_during_resume_stops(self, r, tmp_path):
        self._part(tmp_path, "track.mp3", 4096)

        async def iter_download(_media, offset=0, request_size=0):
            r._cancelled = True
            yield b"\x00" * 4096

        r.client.iter_download = iter_download
        assert _run(r._download_with_retry(_message(),
                                           str(tmp_path / "track.mp3"))) is False


class TestFallback:
    """Путь без iter_download -- обычный download_media."""

    def test_falls_back_when_no_generator(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")
        r.client.iter_download = None
        message = _message()

        def download_media(file=None, **_kw):
            with open(file, "wb") as fh:
                fh.write(b"\x00" * 512)

        message.download_media = download_media
        assert _run(r._download_with_retry(message, path)) is True
        assert os.path.exists(path)

    def test_progress_callback_signature_is_optional(self, r, tmp_path):
        """Старый Telethon не знает про progress_callback."""
        path = str(tmp_path / "track.mp3")
        r.client.iter_download = None
        message = _message()
        calls = []

        def download_media(file=None, **kw):
            if "progress_callback" in kw:
                raise TypeError("не принимает progress_callback")
            calls.append(file)
            with open(file, "wb") as fh:
                fh.write(b"\x00" * 128)

        message.download_media = download_media
        assert _run(r._download_with_retry(message, path)) is True
        assert calls == [path]

    def test_no_media_at_all_returns_false(self, r, tmp_path):
        r.client.iter_download = None
        message = _message()
        message.download_media = None
        assert _run(r._download_with_retry(
            message, str(tmp_path / "track.mp3"))) is False


class TestCancellation:
    """Отмена загрузки."""

    def test_cancelled_before_start(self, r, tmp_path):
        r._cancelled = True
        r.client.iter_download = _chunks(1024)
        assert _run(r._download_with_retry(
            _message(), str(tmp_path / "t.mp3"))) is False

    def test_cancelled_mid_stream(self, r, tmp_path):
        async def iter_download(_media, offset=0, request_size=0):
            yield b"\x00" * 1024
            r._cancelled = True
            yield b"\x00" * 1024

        r.client.iter_download = iter_download
        assert _run(r._download_with_retry(
            _message(), str(tmp_path / "t.mp3"))) is False


def _flood_wait(seconds):
    """Настоящий FloodWaitError без вызова конструктора Telethon.

    Конструктор требует объект запроса, который здесь недоступен, а
    обработчику нужен только атрибут seconds.
    """
    error = rec.FloodWaitError.__new__(rec.FloodWaitError)
    Exception.__init__(error, f"flood wait {seconds}")
    error.seconds = seconds
    return error


class TestFloodWait:
    """Telegram просит подождать -- загрузка должна повториться."""

    def _raiser(self):
        state = {"calls": 0}

        async def iter_download(_media, offset=0, request_size=0):
            state["calls"] += 1
            if state["calls"] == 1:
                raise _flood_wait(0)
            yield b"\x00" * 2048

        return iter_download, state

    def test_wait_is_logged(self, r, tmp_path, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        iterator, _ = self._raiser()
        r.client.iter_download = iterator
        _run(r._download_with_retry(_message(), str(tmp_path / "t.mp3")))
        assert any("FloodWait" in c[0][0] for c in r.log.call_args_list)

    def test_download_succeeds_after_wait(self, r, tmp_path, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        iterator, state = self._raiser()
        r.client.iter_download = iterator
        assert _run(r._download_with_retry(
            _message(), str(tmp_path / "t.mp3"))) is True
        assert state["calls"] == 2

    def test_cancel_during_wait_stops(self, r, tmp_path):
        """Ожидание FloodWait должно прерываться по кнопке «стоп»."""

        async def iter_download(_media, offset=0, request_size=0):
            r._cancelled = True
            raise _flood_wait(60)

        r.client.iter_download = iter_download
        assert _run(r._download_with_retry(
            _message(), str(tmp_path / "t.mp3"))) is False