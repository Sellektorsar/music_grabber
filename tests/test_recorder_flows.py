"""Тесты на recorder.py: разбор трека, ретраи, конвертация, дедуп.

Закрывает непокрытые блоки: кросс-канальный поиск дубликата в
_parse_track_from_message, повторные попытки загрузки, ветку конвертации
в try_direct_download и вспомогательные методы в конце модуля.

Всё выполняется на подменённом клиенте: ни сети, ни Telegram.
"""

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import recorder as rec
from tests.conftest import make_audio, make_document, make_message


# ---------------------------------------------------------------------------
# Разбор сообщения в трек
# ---------------------------------------------------------------------------

class TestParseTrack:

    def test_non_audio_returns_none(self, recorder):
        assert recorder._parse_track_from_message(
            make_message(audio=None, document=None), set(), [], {}, 0) is None

    def test_basic_track_fields(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        msg = make_message(audio=make_audio(performer="Zivert", title="GAZ"),
                           msg_id=42,
                           date=datetime(2024, 4, 10, 12, 0, tzinfo=timezone.utc))
        track = recorder._parse_track_from_message(msg, set(), [], {}, 0)
        assert track["id"] == 42
        assert track["date"] == "2024-04-10"
        assert track["channel"] == "@testchannel"

    def test_known_id_is_already_downloaded(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        msg = make_message(audio=make_audio(), msg_id=7)
        track = recorder._parse_track_from_message(msg, {7}, [], {}, 0)
        assert track["already_exists"] is True
        assert track["in_db"] is True

    def test_cross_channel_duplicate_by_duration_bucket(self, recorder, tmp_path):
        """Тот же трек из другого канала не должен качаться повторно."""
        recorder.base_folder = str(tmp_path)
        candidates = [{"artist": "Zivert", "title": "GAZ", "duration": 30,
                       "channel_id": "otherpool"}]
        buckets = {30: candidates}
        msg = make_message(audio=make_audio(performer="Zivert", title="GAZ"),
                           msg_id=99)
        track = recorder._parse_track_from_message(msg, set(), candidates, buckets, 0)
        assert track["is_duplicate"] is True
        assert track["duplicate_channel"] == "otherpool"
        assert track["already_exists"] is True

    def test_cross_duplicate_searches_without_duration(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        candidates = [{"artist": "Zivert", "title": "GAZ", "duration": 30,
                       "channel_id": "otherpool"}]
        msg = make_message(audio=make_audio(duration=0, performer="Zivert",
                                            title="GAZ"), msg_id=98)
        track = recorder._parse_track_from_message(msg, set(), candidates, {}, 0)
        assert track["is_duplicate"] is True

    def test_cross_duplicate_not_flagged_when_already_present(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        candidates = [{"artist": "Zivert", "title": "GAZ", "duration": 30,
                       "channel_id": "otherpool"}]
        msg = make_message(audio=make_audio(performer="Zivert", title="GAZ"),
                           msg_id=97)
        track = recorder._parse_track_from_message(msg, {97}, candidates, {}, 0)
        assert track["is_duplicate"] is False

    def test_size_taken_from_document(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        doc = make_document()
        doc.size = 5_000_000
        msg = make_message(document=doc, msg_id=11)
        track = recorder._parse_track_from_message(msg, set(), [], {}, 0)
        assert track["size"] == 5_000_000

    def test_bpm_and_key_extracted_from_caption(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        msg = make_message(audio=make_audio(), msg_id=12)
        # подпись сообщения лежит в поле message, а не raw_text
        msg.message = "Track [8A] 128 BPM"
        track = recorder._parse_track_from_message(msg, set(), [], {}, 0)
        assert track["bpm"] == "128"
        assert track["key"] == "8A"

    def test_unparsable_date_does_not_break_track(self, recorder, tmp_path):
        """Дата без strftime и date() обрабатывается как обычная строка."""
        recorder.base_folder = str(tmp_path)
        recorder.get_track_filepath = MagicMock(return_value=str(tmp_path / "t.mp3"))
        msg = make_message(audio=make_audio(), msg_id=13)
        msg.date = "просто строка"
        track = recorder._parse_track_from_message(msg, set(), [], {}, 0)
        assert track["id"] == 13
        assert track["date"] == "просто строка"


# ---------------------------------------------------------------------------
# Загрузка с повторами
# ---------------------------------------------------------------------------

class TestDownloadWithRetry:
    """Проверяется запасной путь через ``message.download_media``.

    Подменённый клиент не проходит проверку ``is_gen``, поэтому
    срабатывает именно ветка отката -- та, что работает и в бою, если
    ``iter_download`` недоступен.
    """

    def _msg_writing(self, path, payload=b"media"):
        msg = MagicMock()
        msg.media = object()

        def _dl(file=None, progress_callback=None):
            with open(file, "wb") as fh:
                fh.write(payload)
            return None

        msg.download_media = _dl
        return msg

    def test_success_via_download_media(self, recorder, tmp_path):
        dst = str(tmp_path / "f.mp3")
        ok = asyncio.run(
            recorder._download_with_retry(self._msg_writing(dst), dst))
        assert ok is True
        assert os.path.exists(dst)

    def test_cancelled_before_start_returns_false(self, recorder, tmp_path):
        recorder._cancelled = True
        dst = str(tmp_path / "g.mp3")
        assert asyncio.run(
            recorder._download_with_retry(MagicMock(), dst)) is False

    def test_absent_media_returns_false(self, recorder, tmp_path):
        msg = MagicMock()
        msg.media = object()
        msg.download_media = MagicMock(return_value=None)
        dst = str(tmp_path / "h.mp3")
        assert asyncio.run(recorder._download_with_retry(msg, dst)) is False

    def test_coroutine_download_media_is_awaited(self, recorder, tmp_path):
        dst = str(tmp_path / "i.mp3")

        async def _dl(file=None, progress_callback=None):
            with open(file, "wb") as fh:
                fh.write(b"async media")

        msg = MagicMock()
        msg.media = object()
        msg.download_media = _dl
        assert asyncio.run(recorder._download_with_retry(msg, dst)) is True

    def test_download_media_without_callback_arg(self, recorder, tmp_path):
        """Старая подпись без progress_callback не должна ронять загрузку."""
        dst = str(tmp_path / "j.mp3")
        msg = MagicMock()
        msg.media = object()

        def _dl(file=None):
            with open(file, "wb") as fh:
                fh.write(b"legacy")

        msg.download_media = _dl
        assert asyncio.run(recorder._download_with_retry(msg, dst)) is True

    def test_network_error_is_retried(self, recorder, tmp_path):
        """Сетевая ошибка повторяется, а не пробрасывается наружу."""
        attempts = {"n": 0}
        dst = str(tmp_path / "k.mp3")
        msg = MagicMock()
        msg.media = object()

        def _boom(file=None, progress_callback=None):
            attempts["n"] += 1
            raise TimeoutError("сеть мигнула")

        msg.download_media = _boom
        with patch("asyncio.sleep", new=AsyncMock()):
            ok = asyncio.run(recorder._download_with_retry(msg, dst))
        assert ok is False
        assert attempts["n"] > 1, "попытка должна повторяться при сетевой ошибке"

    def test_non_network_error_propagates(self, recorder, tmp_path):
        """Неизвестная ошибка не должна молча повторяться MAX_DOWNLOAD_RETRIES раз."""
        attempts = {"n": 0}
        msg = MagicMock()
        msg.media = object()

        def _boom(file=None, progress_callback=None):
            attempts["n"] += 1
            raise ValueError("битое медиа")

        msg.download_media = _boom
        with pytest.raises(ValueError):
            asyncio.run(recorder._download_with_retry(msg, str(tmp_path / "l.mp3")))
        assert attempts["n"] == 1


# ---------------------------------------------------------------------------
# Ветка конвертации
# ---------------------------------------------------------------------------

class TestConversionBranch:

    def _recorder_for_conversion(self, tmp_path, ext, src_bytes=b"RIFFdata"):
        r = rec.TelegramAudioRecorder(MagicMock(), "@chan")
        r.log = MagicMock()
        r._cancelled = False
        r._get_audio_extension = MagicMock(return_value=ext)

        async def _write(message, path, progress_callback=None, total_size=0):
            with open(path, "wb") as fh:
                fh.write(src_bytes)
            return True

        r._download_with_retry = _write
        return r

    def test_opus_is_converted_to_mp3(self, tmp_path):
        r = self._recorder_for_conversion(tmp_path, ".opus")
        dest = tmp_path / "out" / "track.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)
        converted = {}

        def _fake_convert(s, d):
            converted["called"] = (s, d)
            with open(d, "wb") as fh:
                fh.write(b"ID3converted")

        r.convert_to_mp3 = _fake_convert
        ok = asyncio.run(r.try_direct_download(MagicMock(id=1), str(dest)))
        assert ok is True
        assert "called" in converted
        assert dest.exists()

    def test_conversion_failure_keeps_original(self, tmp_path):
        r = self._recorder_for_conversion(tmp_path, ".opus")
        dest = tmp_path / "out" / "track.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _boom(s, d):
            raise RuntimeError("ffmpeg не найден")

        r.convert_to_mp3 = _boom
        ok = asyncio.run(r.try_direct_download(MagicMock(id=2), str(dest)))
        assert ok is True
        fallback = dest.with_suffix(".opus")
        assert fallback.exists(), "оригинал должен остаться на диске"

    def test_existing_file_is_skipped(self, tmp_path):
        r = self._recorder_for_conversion(tmp_path, ".opus")
        dest = tmp_path / "already.mp3"
        dest.write_bytes("уже есть".encode("utf-8"))
        r.convert_to_mp3 = MagicMock()
        ok = asyncio.run(r.try_direct_download(MagicMock(id=3), str(dest)))
        assert ok is True
        r.convert_to_mp3.assert_not_called()

    def test_missing_media_returns_false(self, tmp_path):
        r = self._recorder_for_conversion(tmp_path, ".opus")
        dest = tmp_path / "out" / "none.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)

        async def _nothing(*a, **kw):
            return False

        r._download_with_retry = _nothing
        ok = asyncio.run(r.try_direct_download(MagicMock(id=4), str(dest)))
        assert ok is False

    def test_download_failure_returns_false(self, tmp_path):
        r = self._recorder_for_conversion(tmp_path, ".opus")
        dest = tmp_path / "out" / "x.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)

        async def _fail(*a, **kw):
            return False

        r._download_with_retry = _fail
        ok = asyncio.run(r.try_direct_download(MagicMock(id=5), str(dest)))
        assert ok is False


# ---------------------------------------------------------------------------
# Мелкие методы
# ---------------------------------------------------------------------------

class TestHelpers:

    @pytest.mark.parametrize("mime,expected", [
        ("audio/mpeg", ".mp3"),
        ("audio/ogg", ".ogg"),
        ("audio/x-m4a", ".m4a"),
        ("audio/flac", ".flac"),
        ("video/mp4", ".ogg"),   # не в таблице — безопасный откат на .ogg
        (None, ".ogg"),
    ])
    def test_mime_to_ext(self, recorder, mime, expected):
        assert recorder._mime_to_ext(mime) == expected

    def test_generate_filename(self, recorder):
        msg = make_message(audio=make_audio(performer="A", title="B"))
        assert recorder.generate_filename(msg).endswith(".mp3")

    def test_get_audio_duration(self, recorder):
        assert recorder.get_audio_duration(
            make_message(audio=make_audio(duration=42))) == 42

    def test_audio_duration_missing(self, recorder):
        assert recorder.get_audio_duration(make_message()) in (None, 0)

    def test_to_utc_conversion(self, recorder):
        naive = datetime(2024, 4, 10, 12, 0)
        assert recorder._to_utc(naive).tzinfo is not None

    def test_is_audio_message_true(self, recorder):
        assert recorder.is_audio_message(make_message(audio=make_audio())) is True

    def test_is_audio_message_false(self, recorder):
        assert recorder.is_audio_message(make_message()) is False

    def test_extract_tme_urls(self, recorder):
        got = recorder._extract_tme_urls("пост https://t.me/akmpool конец")
        assert any("akmpool" in u for u in got)


class TestRecentAudioAndRedirect:

    def test_has_audio_in_recent_true(self, recorder):
        async def _gen(*a, **kw):
            yield make_message(audio=make_audio())

        recorder.client.iter_messages = _gen
        assert asyncio.run(recorder._has_audio_in_recent("@chan")) is True

    def test_has_audio_in_recent_false(self, recorder):
        async def _gen(*a, **kw):
            yield make_message()

        recorder.client.iter_messages = _gen
        assert asyncio.run(recorder._has_audio_in_recent("@chan")) is False

    def test_redirect_follows_broadcast_channel(self, recorder):
        target = MagicMock()
        target.broadcast = True

        async def _first(*a, **kw):
            yield make_message(raw_text="https://t.me/akmpool")

        async def _target(*a, **kw):
            yield make_message(audio=make_audio())

        recorder.client.get_entity = AsyncMock(return_value=target)

        calls = {"n": 0}

        async def _iter(entity, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                async for m in _first():
                    yield m
            else:
                async for m in _target():
                    yield m

        recorder.client.iter_messages = _iter
        got = asyncio.run(recorder._maybe_follow_redirect("@chan"))
        assert got is target

    def test_redirect_skips_boost_links(self, recorder):
        async def _gen(*a, **kw):
            yield make_message(raw_text="https://t.me/boost/channel/1")

        recorder.client.iter_messages = _gen
        recorder.client.get_entity = AsyncMock()
        assert asyncio.run(recorder._maybe_follow_redirect("@chan")) is None
        recorder.client.get_entity.assert_not_called()

    def test_redirect_survives_button_errors(self, recorder):
        async def _gen(*a, **kw):
            m = make_message(raw_text="")
            type(m).buttons = property(lambda s: (_ for _ in ()).throw(RuntimeError))
            yield m

        recorder.client.iter_messages = _gen
        assert asyncio.run(recorder._maybe_follow_redirect("@chan")) is None

# ---------------------------------------------------------------------------
# DEFECT-022. Отказ файловой системы сообщался как сетевая ошибка
# ---------------------------------------------------------------------------

class TestFileSystemErrorsAreNotNetworkErrors:
    """Повтор файловой ошибки бесполезен, а слово «сетевая» вводит в заблуждение.

    ``PermissionError`` и прочие ошибки файловой системы являются
    подклассами ``OSError``, который входит в список повторяемых «сетевых»
    ошибок. Из-за этого отказ прав на папку показывался как «сетевая
    ошибка» и трижды повторялся подряд.
    """

    def _rec(self, exc):
        import recorder as rec_mod
        r = rec_mod.TelegramAudioRecorder(MagicMock(), "@chan")
        r.log = MagicMock()
        r._cancelled = False
        r.client = MagicMock()
        r.client.iter_download = None          # ветка iter_download отключена

        msg = MagicMock()
        msg.media = object()

        def _dl(file=None, progress_callback=None):
            raise exc

        msg.download_media = _dl
        return r, msg

    def _messages(self, r):
        return [c.args[0] for c in r.log.call_args_list]

    @pytest.mark.parametrize("exc", [
        PermissionError(13, "Permission denied"),
        FileNotFoundError(2, "No such file or directory"),
        IsADirectoryError(21, "Is a directory"),
        NotADirectoryError(20, "Not a directory"),
    ])
    def test_fs_error_is_not_reported_as_network(self, exc, tmp_path):
        r, msg = self._rec(exc)
        ok = asyncio.run(
            r._download_with_retry(msg, str(tmp_path / "t.mp3")))
        texts = " ".join(self._messages(r))
        assert ok is False
        assert "Сетевая ошибка" not in texts, \
            "ошибка файловой системы не должна называться сетевой"

    @pytest.mark.parametrize("exc", [
        PermissionError(13, "Permission denied"),
        FileNotFoundError(2, "No such file or directory"),
    ])
    def test_fs_error_is_not_retried(self, exc, tmp_path):
        """Три бесполезных попытки на каждый трек — этого быть не должно."""
        r, msg = self._rec(exc)
        attempts = {"n": 0}

        def _counting(file=None, progress_callback=None):
            attempts["n"] += 1
            raise exc

        msg.download_media = _counting
        with patch("asyncio.sleep", new=AsyncMock()):
            asyncio.run(r._download_with_retry(msg, str(tmp_path / "t.mp3")))
        assert attempts["n"] == 1, "файловая ошибка не должна повторяться"

    def test_permission_error_names_the_problem(self, tmp_path):
        r, msg = self._rec(PermissionError(13, "Permission denied"))
        asyncio.run(r._download_with_retry(msg, str(tmp_path / "t.mp3")))
        texts = " ".join(self._messages(r))
        assert "Ошибка доступа к файлу" in texts

    def test_real_network_error_still_retried(self, tmp_path):
        """Настоящие сетевые сбои продолжают повторяться."""
        r, msg = self._rec(ConnectionResetError("соединение сброшено"))
        attempts = {"n": 0}

        def _counting(file=None, progress_callback=None):
            attempts["n"] += 1
            raise ConnectionResetError("соединение сброшено")

        msg.download_media = _counting
        with patch("asyncio.sleep", new=AsyncMock()):
            asyncio.run(r._download_with_retry(msg, str(tmp_path / "t.mp3")))
        assert attempts["n"] > 1, "сетевой сбой обязан повторяться"

    def test_timeout_still_retried(self, tmp_path):
        r, msg = self._rec(TimeoutError("превышено время ожидания"))
        attempts = {"n": 0}

        def _counting(file=None, progress_callback=None):
            attempts["n"] += 1
            raise TimeoutError("превышено время ожидания")

        msg.download_media = _counting
        with patch("asyncio.sleep", new=AsyncMock()):
            asyncio.run(r._download_with_retry(msg, str(tmp_path / "t.mp3")))
        assert attempts["n"] > 1
