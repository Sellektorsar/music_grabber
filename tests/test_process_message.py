"""Тесты на учёт результата обработки одного сообщения.

``process_message`` решает, что пользователь увидит в колонке STATUS и
что попадёт в базу. Отсюда два важных свойства, которые и проверяются:

* запись с звуковой карты, не создавшая файл, не должна считаться успехом;
* любая ошибка (сеть, теги, база) не должна обрывать цикл загрузки.

Ошибки пишутся в лог, счётчики обновляются в ``finally`` -- поэтому после
сбоя трек всё равно попадает в список неудачных, а не зависает в
оранжевом состоянии.
"""

import asyncio
import os
from unittest.mock import MagicMock

import pytest

import recorder as rec


@pytest.fixture
def r(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "db_module", MagicMock())
    recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan", mode="direct")
    recorder.log = MagicMock()
    recorder._cancelled = False
    recorder.base_folder = str(tmp_path)
    # Метаданные и длительность берутся из Telegram; на заглушке сообщения
    # они дают не строки, а объекты Mock, что уводит проверку в сторону.
    recorder._get_audio_meta = MagicMock(return_value=("Zivert", "GAZ"))
    recorder.get_audio_duration = MagicMock(return_value=180.0)
    return recorder


def _message(msg_id=1, title="GAZ", performer="Zivert", date=None):
    message = MagicMock()
    message.id = msg_id
    message.title = title
    message.performer = performer
    message.date = date
    return message


def _run(coro):
    return asyncio.run(coro)


class TestDirectModeSuccess:
    """Успешная прямая загрузка."""

    def _succeed(self, r, path):
        async def _ok(message, file_path):
            with open(file_path, "wb") as fh:
                fh.write(b"\x00" * 4096)
            return True
        r.try_direct_download = _ok
        return _run(r.process_message(_message(), path))

    def test_counters_updated(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")
        self._succeed(r, path)
        assert r._downloaded == 1
        assert r._skipped == 0
        assert r._last_completed_id == 1
        assert r._last_failed_id is None

    def test_database_record_written(self, r, tmp_path):
        """Скачанный трек обязан появиться в базе со статусом completed."""
        path = str(tmp_path / "track.mp3")
        self._succeed(r, path)
        rec.db_module.record_download.assert_called_once()
        kwargs = rec.db_module.record_download.call_args.kwargs
        assert kwargs["status"] == "completed"
        assert kwargs["channel_id"] == "@chan"
        assert kwargs["filename"] == "track.mp3"
        assert kwargs["file_size"] == 4096

    def test_playlist_entry_added(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")
        self._succeed(r, path)
        assert len(r._downloaded_playlist_entries) == 1
        entry = r._downloaded_playlist_entries[0]
        assert entry["artist"] == "Zivert"
        assert entry["title"] == "GAZ"

    def test_unknown_metadata_falls_back_to_raw(self, r, tmp_path):
        """Без распознанных тегов в базу идёт то, что есть."""
        path = str(tmp_path / "track.mp3")

        async def _ok(message, file_path):
            with open(file_path, "wb") as fh:
                fh.write(b"\x00" * 16)
            return True

        r.try_direct_download = _ok
        message = _message()
        message.title = ""
        message.performer = ""
        r._get_audio_meta = MagicMock(return_value=("", ""))
        _run(r.process_message(message, path))

        entry = r._downloaded_playlist_entries[0]
        assert entry["artist"] == ""
        assert entry["title"] == ""

    def test_database_failure_does_not_lose_the_track(self, r, tmp_path):
        """Падение записи в базу не должно отменять сам факт загрузки."""
        path = str(tmp_path / "track.mp3")
        rec.db_module.record_download.side_effect = RuntimeError("БД занята")
        self._succeed(r, path)
        assert r._downloaded == 1
        assert r._last_completed_id == 1


class TestHybridModeFallback:
    """В гибридном режиме неудача прямой загрузки не fatal."""

    def test_falls_back_to_recording(self, r, tmp_path):
        r.mode = "hybrid"
        path = str(tmp_path / "track.mp3")
        calls = []

        async def _fail(message, file_path):
            return False

        def _record(duration, file_path):
            calls.append(duration)
            with open(file_path, "wb") as fh:
                fh.write(b"\x00" * 2048)

        r.try_direct_download = _fail
        r.record_audio = _record
        r.get_audio_duration = MagicMock(return_value=180.0)

        _run(r.process_message(_message(), path))

        assert calls == [180.0], "запись с карты должна быть вызвана"
        assert r._downloaded == 1

    def test_recording_without_file_is_not_success(self, r, tmp_path):
        """Карта молчала -- файл не создан, трек не должен считаться скачанным.

        Именно на этом уже находился дефект: исключение PortAudioError
        перехватывалось внутри record_audio, и трек помечался успешным.
        """
        r.mode = "hybrid"
        path = str(tmp_path / "missing.mp3")

        async def _fail(message, file_path):
            return False

        r.try_direct_download = _fail
        r.record_audio = MagicMock(return_value=None)   # файл не создан
        r.get_audio_duration = MagicMock(return_value=180.0)

        _run(r.process_message(_message(), path))

        assert r._downloaded == 0
        assert r._last_failed_id == 1
        assert any("Запись аудио не удалась" in c[0][0]
                   for c in r.log.call_args_list)

    def test_unknown_duration_is_reported(self, r, tmp_path):
        r.mode = "hybrid"
        path = str(tmp_path / "track.mp3")

        async def _fail(message, file_path):
            return False

        r.try_direct_download = _fail
        r.record_audio = MagicMock()
        r.get_audio_duration = MagicMock(return_value=0)

        _run(r.process_message(_message(), path))

        assert any("Не удалось определить длительность" in c[0][0]
                   for c in r.log.call_args_list)
        assert r._downloaded == 0


class TestFailurePaths:
    """Неудачные треки должны попадать в список отказов."""

    def test_failed_download_is_counted(self, r, tmp_path):
        path = str(tmp_path / "track.mp3")

        async def _fail(message, file_path):
            return False

        r.try_direct_download = _fail
        _run(r.process_message(_message(msg_id=77), path))

        assert r._downloaded == 0
        assert r._skipped == 1
        assert r._last_failed_id == 77
        assert 77 in r._failed_ids
        assert r._last_completed_id is None

    def test_exception_is_logged_with_traceback(self, r, tmp_path):
        """Сбой не должен выйти наружу -- цикл загрузки обязан продолжиться."""
        path = str(tmp_path / "track.mp3")

        async def _boom(message, file_path):
            raise RuntimeError("соединение сброшено")

        r.try_direct_download = _boom
        _run(r.process_message(_message(msg_id=5), path))

        messages = [c[0][0] for c in r.log.call_args_list]
        assert any("Ошибка обработки сообщения" in m for m in messages)
        assert any("Traceback" in m for m in messages)
        assert r._failed_ids == {5}

    def test_missing_file_after_success_still_recorded(self, r, tmp_path):
        """Отсутствующий файл не должно ломать запись в базу."""
        path = str(tmp_path / "ghost.mp3")

        async def _ok(message, file_path):
            return True    # вернули успех, но файл не создали

        r.try_direct_download = _ok
        _run(r.process_message(_message(), path))

        kwargs = rec.db_module.record_download.call_args.kwargs
        assert kwargs["file_size"] == 0


class TestPathHelpers:
    """Пути и фильтры по датам."""

    def test_date_folder_uses_base_folder(self, r, tmp_path):
        import datetime

        folder = r._get_date_folder(datetime.datetime(2026, 4, 4))
        assert folder.startswith(str(tmp_path))
        assert "2026-04-04" in folder

    def test_date_range_check_uses_configured_bounds(self, r):
        import datetime

        r.date_from = datetime.datetime(2026, 1, 1)
        r.date_to = datetime.datetime(2026, 2, 1)

        inside = _message(date=datetime.datetime(2026, 1, 15))
        outside = _message(date=datetime.datetime(2025, 1, 15))

        assert r._message_in_date_range(inside) is True
        assert r._message_in_date_range(outside) is False

    def test_older_than_start_date(self, r):
        import datetime

        r.date_from = datetime.datetime(2026, 1, 1)
        assert r._is_older_than_from(
            _message(date=datetime.datetime(2025, 12, 31))) is True
        assert r._is_older_than_from(
            _message(date=datetime.datetime(2026, 1, 2))) is False

    def test_track_path_follows_export_pattern(self, r, tmp_path, monkeypatch):
        """Имя файла строится по шаблону из настроек, а не жёстко."""
        monkeypatch.setattr(
            rec, "load_config",
            MagicMock(return_value={"export_pattern": "{artist} - {title} ({bpm}).mp3"}),
        )
        path = r.get_track_filepath(_message(), "Zivert", "GAZ 128")
        assert os.path.basename(path).startswith("Zivert - GAZ")
        assert path.endswith(".mp3")
        assert "—" not in path, "шаблон не должен оставлять пустых меток"

    def test_track_path_falls_back_to_message_tags(self, r):
        path = r.get_track_filepath(_message())
        assert os.path.basename(path).endswith(".mp3")


class TestRecentAudioProbe:
    """Проверка наличия аудио в канале без полного сканирования."""

    def test_found_audio_stops_search(self, r):
        async def iter_messages(channel, limit=0):
            for message in (MagicMock(), _message()):
                yield message

        r.client.iter_messages = iter_messages
        r.is_audio_message = MagicMock(side_effect=[False, True])
        assert _run(r._has_audio_in_recent("@chan")) is True

    def test_no_audio_returns_false(self, r):
        async def iter_messages(channel, limit=0):
            yield _message()

        r.client.iter_messages = iter_messages
        r.is_audio_message = MagicMock(return_value=False)
        assert _run(r._has_audio_in_recent("@chan")) is False


class TestRedirectFollowing:
    """Поиск канала-редиректа по ссылкам в сообщениях.

    Возвращается сама сущность канала (а не имя), и только если в канале
    действительно есть аудио: переход на рекламный или пустой канал
    сломал бы всю последующую загрузку.
    """

    def _iter(self, first_messages, later_messages=()):
        """Первый проход ищет ссылку, второй -- проверяет канал на аудио.

        Один и тот же iter_messages используется дважды, поэтому фазы
        различаются по номеру вызова.
        """
        state = {"call": 0}

        async def iter_messages(_channel, limit=0):
            state["call"] += 1
            messages = first_messages if state["call"] == 1 else later_messages
            for message in messages:
                yield message

        return iter_messages

    def _urls(self, monkeypatch, mapping):
        monkeypatch.setattr(
            rec, "extract_tme_urls",
            MagicMock(side_effect=lambda text: mapping.get(text, [])),
        )

    def _entity(self, is_broadcast=True):
        entity = MagicMock()
        entity.broadcast = is_broadcast
        return entity

    def test_redirect_found_in_message_text(self, r, monkeypatch):
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "mirror here"
        message.buttons = []
        r.client.iter_messages = self._iter([message], [_message()])
        self._urls(monkeypatch, {"mirror here": ["https://t.me/realchannel"]})

        entity = self._entity()
        r.client.get_entity = AsyncMock(return_value=entity)
        r.is_audio_message = MagicMock(return_value=True)

        assert _run(r._maybe_follow_redirect("@oldchannel")) is entity

    def test_redirect_found_in_button_url(self, r, monkeypatch):
        from unittest.mock import AsyncMock

        button = MagicMock()
        button.url = "https://t.me/frombutton"
        message = _message()
        message.raw_text = ""
        message.buttons = [[button]]
        self._urls(monkeypatch,
                   {"https://t.me/frombutton": ["https://t.me/frombutton"]})

        entity = self._entity()
        r.client.get_entity = AsyncMock(return_value=entity)
        r.client.iter_messages = self._iter([message], [_message()])
        r.is_audio_message = MagicMock(return_value=True)

        assert _run(r._maybe_follow_redirect("@oldchannel")) is entity

    def test_broken_buttons_do_not_break_search(self, r, monkeypatch):
        """Капризные кнопки Telegram не должны срывать поиск редиректа."""
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "plain text"
        message.buttons = None
        r.client.iter_messages = self._iter([message], [_message()])
        self._urls(monkeypatch, {"plain text": ["https://t.me/foundhere"]})

        entity = self._entity()
        r.client.get_entity = AsyncMock(return_value=entity)
        r.is_audio_message = MagicMock(return_value=True)

        assert _run(r._maybe_follow_redirect("@oldchannel")) is entity

    def test_boost_links_are_ignored(self, r, monkeypatch):
        """Рекламные ссылки boost не должны уводить загрузку не туда."""
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "boost"
        message.buttons = []
        r.client.iter_messages = self._iter([message])
        self._urls(monkeypatch, {"boost": ["https://t.me/boost/channel/1"]})

        r.client.get_entity = AsyncMock()
        assert _run(r._maybe_follow_redirect("@oldchannel")) is None
        r.client.get_entity.assert_not_called()

    def test_non_broadcast_channel_is_rejected(self, r, monkeypatch):
        """Обычный чат, даже с аудио, каналом-источником не является."""
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "link"
        message.buttons = []
        r.client.iter_messages = self._iter([message])
        self._urls(monkeypatch, {"link": ["https://t.me/notchannel"]})

        r.client.get_entity = AsyncMock(return_value=self._entity(False))
        r.client.iter_messages = self._iter([_message()])
        r.is_audio_message = MagicMock(return_value=True)

        assert _run(r._maybe_follow_redirect("@oldchannel")) is None

    def test_channel_without_audio_is_rejected(self, r, monkeypatch):
        """Пустой канал не годится: переходить на него незачем."""
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "link"
        message.buttons = []
        r.client.iter_messages = self._iter([message])
        self._urls(monkeypatch, {"link": ["https://t.me/emptychannel"]})

        r.client.get_entity = AsyncMock(return_value=self._entity(True))
        r.client.iter_messages = self._iter([_message()])
        r.is_audio_message = MagicMock(return_value=False)

        assert _run(r._maybe_follow_redirect("@oldchannel")) is None

    def test_entity_lookup_error_is_skipped(self, r, monkeypatch):
        """Ошибка разбора ссылки не должна обрывать поиск."""
        from unittest.mock import AsyncMock

        message = _message()
        message.raw_text = "link"
        message.buttons = []
        r.client.iter_messages = self._iter([message])
        self._urls(monkeypatch, {"link": ["https://t.me/broken"]})

        r.client.get_entity = AsyncMock(side_effect=RuntimeError("нет"))
        assert _run(r._maybe_follow_redirect("@oldchannel")) is None

    def test_no_redirect_returns_none(self, r, monkeypatch):
        message = _message()
        message.raw_text = "просто пост"
        message.buttons = []
        r.client.iter_messages = self._iter([message])
        self._urls(monkeypatch, {"просто пост": []})
        assert _run(r._maybe_follow_redirect("@oldchannel")) is None