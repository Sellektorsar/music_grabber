import os
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from recorder import TelegramAudioRecorder


class TestMimeToExt:

    def test_known_types(self, recorder):
        cases = [
            ('audio/mpeg', '.mp3'),
            ('audio/ogg', '.ogg'),
            ('audio/x-wav', '.wav'),
            ('audio/wav', '.wav'),
            ('audio/x-flac', '.flac'),
            ('audio/flac', '.flac'),
            ('audio/aac', '.aac'),
            ('audio/mp4', '.m4a'),
            ('audio/x-m4a', '.m4a'),
        ]
        for mime, expected in cases:
            assert recorder._mime_to_ext(mime) == expected

    def test_case_insensitive(self, recorder):
        assert recorder._mime_to_ext('AUDIO/MPEG') == '.mp3'
        assert recorder._mime_to_ext('Audio/OGG') == '.ogg'

    def test_unknown_type(self, recorder):
        assert recorder._mime_to_ext('audio/unknown') == '.ogg'
        assert recorder._mime_to_ext('video/mp4') == '.ogg'

    def test_none_returns_default(self, recorder):
        assert recorder._mime_to_ext(None) == '.ogg'


class TestIsAudioMessage:

    def test_with_audio_attr(self, recorder):
        msg = MagicMock()
        msg.audio = MagicMock()
        msg.document = MagicMock(mime_type=None)
        assert recorder.is_audio_message(msg) is True

    def test_with_document_audio_mime(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock(mime_type='audio/ogg')
        assert recorder.is_audio_message(msg) is True

    def test_no_audio(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock(mime_type='text/plain')
        assert recorder.is_audio_message(msg) is False

    def test_no_audio_no_document(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = None
        assert recorder.is_audio_message(msg) is False


class TestToUtc:

    def test_none(self):
        assert TelegramAudioRecorder._to_utc(None) is None

    def test_naive_datetime(self):
        dt = datetime(2025, 6, 15, 12, 0, 0)
        result = TelegramAudioRecorder._to_utc(dt)
        assert result is not None
        assert result.tzinfo is not None
        assert result.tzinfo.utcoffset(result) == timezone.utc.utcoffset(result)

    def test_aware_utc(self):
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = TelegramAudioRecorder._to_utc(dt)
        assert result == dt

    def test_preserves_instant(self):
        dt = datetime(2025, 6, 15, 12, 0, 0)
        result = TelegramAudioRecorder._to_utc(dt)
        utc_dt = dt.astimezone(timezone.utc)
        assert result == utc_dt


class TestGetDateFolder:

    def test_aware_datetime(self, recorder, isolate_base_folder):
        dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        folder = recorder._get_date_folder(dt)
        assert folder.endswith('2025-06-15')

    def test_naive_datetime(self, recorder, isolate_base_folder):
        dt = datetime(2025, 12, 25, 8, 0, 0)
        folder = recorder._get_date_folder(dt)
        assert '2025-12-25' in folder


class TestGenerateFilename:

    def test_with_artist_title(self, recorder):
        audio = MagicMock()
        audio.performer = 'TestArtist'
        audio.title = 'TestTitle'
        msg = MagicMock()
        msg.audio = audio
        msg.document = None
        assert recorder.generate_filename(msg) == 'TestArtist - TestTitle.mp3'

    def test_missing_performer(self, recorder):
        audio = MagicMock()
        audio.performer = None
        audio.title = 'SomeSong'
        msg = MagicMock()
        msg.audio = audio
        msg.document = None
        assert 'UnknownArtist - SomeSong.mp3' == recorder.generate_filename(msg)

    def test_missing_title(self, recorder):
        audio = MagicMock()
        audio.performer = 'Artist'
        audio.title = None
        msg = MagicMock()
        msg.audio = audio
        msg.document = None
        assert recorder.generate_filename(msg) == 'Artist - UnknownTitle.mp3'

    def test_sanitize_invalid_chars(self, recorder):
        audio = MagicMock()
        audio.performer = 'A/B:C*D'
        audio.title = 'E"F<G>H|I'
        msg = MagicMock()
        msg.audio = audio
        msg.document = None
        result = recorder.generate_filename(msg)
        assert '/' not in result
        assert ':' not in result
        assert '*' not in result
        assert '"' not in result
        assert '<' not in result
        assert '>' not in result
        assert '|' not in result
        assert result == 'A_B_C_D - E_F_G_H_I.mp3'

    def test_fallback_on_exception(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = None
        result = recorder.generate_filename(msg)
        assert result.endswith('.mp3')
        assert result.startswith('track_')

    def test_uses_document_audio_attrs(self, recorder):
        from tests.conftest import _get_doc_attr
        attr = _get_doc_attr(duration=30, performer='DocArtist', title='DocTitle')
        doc = MagicMock()
        doc.mime_type = 'audio/ogg'
        doc.attributes = [attr]
        msg = MagicMock()
        msg.audio = None
        msg.document = doc
        assert recorder.generate_filename(msg) == 'DocArtist - DocTitle.mp3'


class TestMessageInDateRange:

    def test_no_range(self, recorder):
        recorder.date_from = None
        recorder.date_to = None
        msg = MagicMock()
        msg.date = datetime(2025, 6, 15, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is True

    def test_within_range(self, recorder):
        recorder.date_from = datetime(2025, 6, 1, tzinfo=timezone.utc)
        recorder.date_to = datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 15, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is True

    def test_before_from(self, recorder):
        recorder.date_from = datetime(2025, 6, 10, tzinfo=timezone.utc)
        recorder.date_to = None
        msg = MagicMock()
        msg.date = datetime(2025, 6, 5, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is False

    def test_after_to(self, recorder):
        recorder.date_from = None
        recorder.date_to = datetime(2025, 6, 10, 23, 59, 59, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 15, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is False

    def test_at_from_boundary(self, recorder):
        recorder.date_from = datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        recorder.date_to = None
        msg = MagicMock()
        msg.date = datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is True

    def test_at_to_boundary(self, recorder):
        recorder.date_from = None
        recorder.date_to = datetime(2025, 6, 10, 23, 59, 59, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 10, 23, 59, 59, tzinfo=timezone.utc)
        assert recorder._message_in_date_range(msg) is True

    def test_naive_message_date(self, recorder):
        recorder.date_from = datetime(2025, 6, 1, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 15)
        assert msg.date.tzinfo is None
        assert recorder._message_in_date_range(msg) is True


class TestIsOlderThanFrom:

    def test_no_date_from(self, recorder):
        recorder.date_from = None
        msg = MagicMock()
        msg.date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert recorder._is_older_than_from(msg) is False

    def test_message_older(self, recorder):
        recorder.date_from = datetime(2025, 6, 10, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 5, tzinfo=timezone.utc)
        assert recorder._is_older_than_from(msg) is True

    def test_message_newer(self, recorder):
        recorder.date_from = datetime(2025, 6, 10, tzinfo=timezone.utc)
        msg = MagicMock()
        msg.date = datetime(2025, 6, 15, tzinfo=timezone.utc)
        assert recorder._is_older_than_from(msg) is False


class TestGetAudioDuration:

    def test_from_message_audio(self, recorder):
        msg = MagicMock()
        msg.audio = MagicMock()
        msg.audio.duration = 42
        msg.document = MagicMock()
        assert recorder.get_audio_duration(msg) == 42

    def test_from_document_attributes(self, recorder):
        from tests.conftest import _get_doc_attr
        attr = _get_doc_attr(duration=99)
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock()
        msg.document.attributes = [attr]
        assert recorder.get_audio_duration(msg) == 99

    def test_no_audio(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock()
        msg.document.attributes = []
        assert recorder.get_audio_duration(msg) is None

    def test_no_document(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = None
        assert recorder.get_audio_duration(msg) is None


class TestExtractTmeUrls:

    def test_extract_valid(self, recorder):
        text = "Check this: https://t.me/channel/123 and t.me/another"
        urls = recorder._extract_tme_urls(text)
        assert 't.me/channel/123' in urls
        assert 't.me/another' in urls
        assert len(urls) == 2

    def test_skip_boost(self, recorder):
        text = "https://t.me/boost/channel and t.me/boost/another"
        urls = recorder._extract_tme_urls(text)
        assert len(urls) == 2
        assert 't.me/boost/channel' in urls
        assert 't.me/boost/another' in urls

    def test_empty_text(self, recorder):
        assert recorder._extract_tme_urls('') == []
        assert recorder._extract_tme_urls(None) == []

    def test_no_urls(self, recorder):
        assert recorder._extract_tme_urls('Just a normal message') == []

    def test_http_prefix_stripped(self, recorder):
        text = "http://t.me/channel/123"
        urls = recorder._extract_tme_urls(text)
        assert 't.me/channel/123' in urls


class TestCleanTempFiles:

    def test_cleans_wav_and_temp(self, recorder, isolate_base_folder):
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        wav_file = os.path.join(base, "test.wav")
        temp_file = os.path.join(base, "song.mp3.temp.mp3")
        mp3_file = os.path.join(base, "song.mp3")
        for f in [wav_file, temp_file, mp3_file]:
            with open(f, 'w') as fh:
                fh.write('data')
        recorder._clean_temp_files()
        assert not os.path.exists(wav_file)
        assert not os.path.exists(temp_file)
        assert os.path.exists(mp3_file)

    def test_no_dir_nothing_happens(self, recorder, isolate_base_folder):
        non_existent = str(isolate_base_folder / "nonexistent")
        recorder._clean_temp_files()


class TestCancel:

    def test_sets_cancelled_flag(self, recorder):
        assert recorder._cancelled is False
        recorder.cancel()
        assert recorder._cancelled is True

    def test_cancel_twice_no_error(self, recorder):
        recorder.cancel()
        recorder.cancel()
        assert recorder._cancelled is True


class TestDownloadWithRetry:

    @pytest.mark.asyncio
    async def test_success(self, recorder, isolate_base_folder):
        message = AsyncMock()
        message.download_media = AsyncMock()

        def _download_side_effect(file=None, **kw):
            with open(file, 'w') as f:
                f.write('data')

        message.download_media.side_effect = _download_side_effect
        path = str(isolate_base_folder / "telegram_audio" / "test.ogg")
        result = await recorder._download_with_retry(message, path)
        assert result is True
        assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_flood_wait_then_success(self, recorder, isolate_base_folder):
        from telethon.errors import FloodWaitError
        message = AsyncMock()
        call_count = [0]

        async def _fail_once(**kw):
            call_count[0] += 1
            if call_count[0] == 1:
                err = FloodWaitError()
                err.seconds = 1
                raise err
            with open(kw.get('file'), 'w') as f:
                f.write('data')

        message.download_media.side_effect = _fail_once
        path = str(isolate_base_folder / "telegram_audio" / "test.ogg")
        result = await recorder._download_with_retry(message, path)
        assert result is True

    @pytest.mark.asyncio
    async def test_all_attempts_fail(self, recorder, isolate_base_folder):
        message = AsyncMock()
        message.download_media = AsyncMock(return_value=None)
        path = str(isolate_base_folder / "telegram_audio" / "test.ogg")
        result = await recorder._download_with_retry(message, path)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancelled_during_retry(self, recorder, isolate_base_folder):
        from telethon.errors import FloodWaitError
        message = AsyncMock()
        message.download_media.side_effect = FloodWaitError()
        message.download_media.side_effect.seconds = 10
        recorder.cancel()
        path = str(isolate_base_folder / "telegram_audio" / "test.ogg")
        result = await recorder._download_with_retry(message, path)
        assert result is False

    @pytest.mark.asyncio
    async def test_network_error_retry(self, recorder, isolate_base_folder):
        message = AsyncMock()
        call_count = [0]

        async def _fail_twice(**kw):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ConnectionError("Network unstable")
            with open(kw.get('file'), 'w') as f:
                f.write('data')

        message.download_media.side_effect = _fail_twice
        path = str(isolate_base_folder / "telegram_audio" / "test.ogg")
        result = await recorder._download_with_retry(message, path)
        assert result is True


class TestTryDirectDownload:

    @pytest.mark.asyncio
    async def test_file_already_exists(self, recorder, isolate_base_folder):
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "test.mp3")
        with open(path, 'w') as f:
            f.write('existing')
        msg = MagicMock()
        msg.id = 1
        result = await recorder.try_direct_download(msg, path)
        assert result is True

    @pytest.mark.asyncio
    async def test_download_success_mp3(self, recorder, isolate_base_folder):
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "test.mp3")
        msg = MagicMock()
        msg.id = 12345
        msg.audio = MagicMock()
        msg.audio.mime_type = 'audio/mpeg'
        msg.document = MagicMock()
        msg.document.mime_type = 'audio/mpeg'
        msg.file = None
        temp_path = path + f".{msg.id}.temp.mp3"
        with open(temp_path, 'w') as f:
            f.write('data')
        result = await recorder.try_direct_download(msg, path)
        assert result is True
        assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_download_fails_fallback(self, recorder, isolate_base_folder):
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "test.mp3")
        msg = MagicMock()
        msg.id = 1
        msg.audio = MagicMock()
        msg.audio.mime_type = 'audio/ogg'
        msg.document = MagicMock()
        msg.document.mime_type = 'audio/ogg'
        msg.file = None
        result = await recorder.try_direct_download(msg, path)
        assert result is False


class TestProcessMessage:

    @pytest.mark.asyncio
    async def test_direct_mode(self, recorder, isolate_base_folder):
        recorder.mode = 'direct'
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "test.mp3")
        msg = AsyncMock()
        msg.id = 1
        msg.audio = MagicMock()
        msg.audio.mime_type = 'audio/mpeg'
        msg.document = MagicMock()
        msg.document.mime_type = 'audio/mpeg'
        msg.file = None
        await recorder.process_message(msg, path)

    @pytest.mark.asyncio
    async def test_hybrid_mode_exception_handled(self, recorder, isolate_base_folder):
        recorder.mode = 'hybrid'
        base = str(isolate_base_folder / "telegram_audio")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "test.mp3")
        msg = AsyncMock()
        msg.id = 1
        msg.audio = None
        msg.document = MagicMock()
        msg.document.mime_type = 'audio/ogg'
        msg.document.attributes = []
        msg.file = None
        await recorder.process_message(msg, path)


class TestHasAudioInRecent:

    @pytest.mark.asyncio
    async def test_has_audio(self, recorder):
        channel = MagicMock()
        msg_no_audio = MagicMock()
        msg_no_audio.audio = None
        msg_no_audio.document = MagicMock(mime_type='text/plain')
        msg_has_audio = MagicMock()
        msg_has_audio.audio = MagicMock()
        msg_has_audio.document = MagicMock(mime_type='audio/mpeg')

        async def _iter_mock(*args, **kwargs):
            for m in [msg_no_audio, msg_has_audio]:
                yield m

        recorder.client.iter_messages = _iter_mock
        result = await recorder._has_audio_in_recent(channel, sample=50)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_audio(self, recorder):
        channel = MagicMock()
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock(mime_type='text/plain')

        async def _iter_mock(*args, **kwargs):
            yield msg

        recorder.client.iter_messages = _iter_mock
        result = await recorder._has_audio_in_recent(channel, sample=50)
        assert result is False


class TestGetAudioExtension:

    def test_from_message_audio_mime(self, recorder):
        msg = MagicMock()
        msg.audio = MagicMock()
        msg.audio.mime_type = 'audio/flac'
        msg.document = None
        msg.file = None
        assert recorder._get_audio_extension(msg) == '.flac'

    def test_from_document_mime(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock()
        msg.document.mime_type = 'audio/aac'
        msg.file = None
        assert recorder._get_audio_extension(msg) == '.aac'

    def test_from_document_filename(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock()
        msg.document.mime_type = None
        msg.file = MagicMock()
        msg.file.name = 'song.m4a'
        assert recorder._get_audio_extension(msg) == '.m4a'

    def test_default_ogg(self, recorder):
        msg = MagicMock()
        msg.audio = None
        msg.document = MagicMock()
        msg.document.mime_type = None
        msg.file = None
        assert recorder._get_audio_extension(msg) == '.ogg'
