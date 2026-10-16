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
        assert result == 'UnknownArtist - UnknownTitle.mp3'

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


class TestMetadataCleaner:

    def test_clean_promo_text(self):
        from media_utils import clean_promo_text

        raw = "🔥 01. Meduza - Piece Of Your Heart (Club Mix) [320 kbps] @deep_house [t.me/music] 🎧"
        cleaned = clean_promo_text(raw)
        assert cleaned == "Meduza - Piece Of Your Heart (Club Mix)"

        raw2 = "[EXCLUSIVE] FISHER - LOSING IT (Original Mix) https://t.me/drop"
        assert clean_promo_text(raw2) == "FISHER - LOSING IT (Original Mix)"

    def test_smart_title_case(self):
        from media_utils import smart_title_case

        all_caps = "FISHER - LOSING IT (EXTENDED MIX) VIP"
        res = smart_title_case(all_caps)
        assert "Fisher" in res
        assert "VIP" in res
        assert "Extended Mix" in res

        # Does not destroy stylized mixed case
        mixed = "deadmau5 - Ghosts 'n' Stuff"
        assert smart_title_case(mixed) == mixed

    def test_clean_track_metadata(self):
        from media_utils import clean_track_metadata

        # Channel name as artist with "Artist - Title" in title field
        artist, title = clean_track_metadata("@house_club", "🔥 02. ARTIST - TRACK NAME [320 KBPS]")
        assert artist == "Artist"
        assert title == "Track Name"

        # Defaults for empty
        assert clean_track_metadata("", "") == ("UnknownArtist", "UnknownTitle")

    def test_clean_filename(self):
        from media_utils import clean_filename

        raw_fname = "@chan - 🔥 01. TEST ARTIST - TEST TRACK [320 KBPS].mp3"
        cleaned = clean_filename(raw_fname)
        assert "@chan" not in cleaned
        assert "320" not in cleaned
        assert cleaned.endswith(".mp3")


class TestID3TagWriter:

    def test_write_and_read_id3_tags(self, tmp_path):
        from audio_converter import write_id3_tags, read_id3_tags
        from pydub.generators import Sine

        test_file = str(tmp_path / "test_track.mp3")
        tone = Sine(440).to_audio_segment(duration=100)
        tone.export(test_file, format="mp3")

        dummy_artwork = b"\xff\xd8\xff\xe0" + b"\x00" * 32

        success = write_id3_tags(
            test_file,
            title="Losing It",
            artist="Fisher",
            album="Club Hits",
            year=2024,
            genre="Tech House",
            bpm=125,
            key="8A",
            comment="Telegram: @edm_pool",
            artwork_bytes=dummy_artwork,
            artwork_mime="image/jpeg",
        )
        assert success is True

        read = read_id3_tags(test_file)
        assert read.get("title") == "Losing It"
        assert read.get("artist") == "Fisher"
        assert read.get("album") == "Club Hits"
        assert read.get("genre") == "Tech House"
        assert read.get("bpm") == "125"
        assert read.get("key") == "8A"
        assert "2024" in read.get("year", "")
        assert "@edm_pool" in read.get("comment", "")
        assert read.get("has_artwork") is True

    def test_safe_fallbacks_nonexistent(self):
        from audio_converter import write_id3_tags, read_id3_tags

        assert write_id3_tags("/nonexistent/file.mp3", title="A") is False
        assert read_id3_tags("/nonexistent/file.mp3") == {}



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


class TestSelectedIds:
    @pytest.mark.asyncio
    async def test_start_only_counts_and_processes_selected_ids(self, recorder, monkeypatch):
        from unittest.mock import AsyncMock
        from datetime import datetime, timezone

        msg1 = MagicMock()
        msg1.id = 10
        msg1.audio = MagicMock()
        msg1.document = None
        msg1.date = datetime.now(timezone.utc)

        msg2 = MagicMock()
        msg2.id = 20
        msg2.audio = MagicMock()
        msg2.document = None
        msg2.date = datetime.now(timezone.utc)

        async def _iter(*a, **kw):
            yield msg1
            yield msg2

        recorder.client.iter_messages = _iter
        recorder.client.get_entity = AsyncMock()
        processed = []

        async def _mock_download(msg, path, sem):
            processed.append(msg.id)

        recorder.download_with_limit = _mock_download
        recorder.selected_ids = {20}

        await recorder.start()

        assert recorder._cnt_audio == 1
        assert processed == [20]


class TestRecorderDatabaseIntegration:
    @pytest.mark.asyncio
    async def test_scan_marks_already_exists_when_in_database(self, recorder):
        import database as db

        # Record message ID 500 in db
        db.record_download(recorder.channel_username, 500, title="Database Song")

        msg = MagicMock()
        msg.id = 500
        msg.audio = MagicMock(performer="DB Artist", title="DB Song")
        msg.document = None
        msg.date = datetime.now(timezone.utc)

        async def _iter(*a, **kw):
            yield msg

        recorder.client.iter_messages = _iter
        recorder.client.get_entity = AsyncMock()

        tracks = await recorder.scan()
        assert len(tracks) == 1
        assert tracks[0]["id"] == 500
        assert tracks[0]["already_exists"] is True
        assert tracks[0]["in_db"] is True

    @pytest.mark.asyncio
    async def test_start_skips_download_when_in_database(self, recorder):
        import database as db

        db.record_download(recorder.channel_username, 777, title="Already Grabbed")

        msg = MagicMock()
        msg.id = 777
        msg.audio = MagicMock()
        msg.document = None
        msg.date = datetime.now(timezone.utc)

        async def _iter(*a, **kw):
            yield msg

        recorder.client.iter_messages = _iter
        recorder.client.get_entity = AsyncMock()
        downloaded = []

        async def _mock_download(m, p, s):
            downloaded.append(m.id)

        recorder.download_with_limit = _mock_download

        await recorder.start()
        assert recorder._already_exists == 1
        assert downloaded == []

    @pytest.mark.asyncio
    async def test_channel_entity_cache(self, recorder):
        from recorder import _CHANNEL_ENTITY_CACHE
        _CHANNEL_ENTITY_CACHE.clear()

        fake_channel = MagicMock(username="cached_chan")
        recorder.client.get_entity = AsyncMock(return_value=fake_channel)
        recorder.channel_username = "@cached_chan"

        async def _empty_iter(*a, **kw):
            if False:
                yield None

        recorder.client.iter_messages = _empty_iter

        # Первый вызов — вызывает client.get_entity
        await recorder.scan()
        assert recorder.client.get_entity.call_count == 1
        assert _CHANNEL_ENTITY_CACHE["@cached_chan"] is fake_channel

        # Второй вызов — берет из кэша, не дергая client.get_entity повторно
        await recorder.scan()
        assert recorder.client.get_entity.call_count == 1


class TestExportPatternsAndPlaylists:

    def test_sanitize_path_segment(self):
        from media_utils import sanitize_path_segment
        assert sanitize_path_segment("Valid_Name") == "Valid_Name"
        assert sanitize_path_segment("A:B*C?D\"E<F>G|H/I\\J") == "A_B_C_D_E_F_G_H_I_J"
        assert sanitize_path_segment("../secret/path") == "secret_path"
        assert sanitize_path_segment("") == "Unknown"

    def test_format_export_path_default(self):
        from media_utils import format_export_path
        dt = datetime(2026, 10, 8, 12, 0, 0)
        p = format_export_path(
            base_folder="music",
            pattern="{date}/{artist} - {title}.mp3",
            date_val=dt,
            channel="electronic",
            artist="Deadmau5",
            title="Strobe",
        )
        assert os.path.normpath(p) == os.path.normpath("music/2026-10-08/Deadmau5 - Strobe.mp3")

    def test_format_export_path_custom_pattern(self):
        from media_utils import format_export_path
        dt = datetime(2026, 5, 1, 10, 0, 0)
        p = format_export_path(
            base_folder="music",
            pattern="{channel}/{year}/{artist}/{title}.{ext}",
            date_val=dt,
            channel="@dnb_channel",
            artist="Noisia",
            title="Outer Edges",
            ext="flac",
        )
        assert os.path.normpath(p) == os.path.normpath("music/dnb_channel/2026/Noisia/Outer Edges.flac")

    def test_generate_m3u8_playlist(self, tmp_path):
        from media_utils import generate_m3u8_playlist
        track1 = tmp_path / "song1.mp3"
        track2 = tmp_path / "song2.mp3"
        track1.write_bytes(b"dummy1")
        track2.write_bytes(b"dummy2")

        pl_path = tmp_path / "playlist.m3u8"
        entries = [
            {"filepath": str(track1), "artist": "Artist 1", "title": "Song 1", "duration": 185},
            {"filepath": str(track2), "artist": "Artist 2", "title": "Song 2", "duration": 240},
        ]

        out = generate_m3u8_playlist(str(pl_path), entries, relative=True)
        assert os.path.exists(out)
        content = pl_path.read_text(encoding="utf-8")
        assert "#EXTM3U" in content
        assert "#EXTINF:185,Artist 1 - Song 1" in content
        assert "song1.mp3" in content
        assert "#EXTINF:240,Artist 2 - Song 2" in content
        assert "song2.mp3" in content

    @pytest.mark.asyncio
    async def test_recorder_auto_generate_m3u8(self, recorder, tmp_path, monkeypatch):
        import recorder as rec_module
        monkeypatch.setattr(rec_module, "BASE_FOLDER", str(tmp_path))

        fake_msg = MagicMock()
        fake_msg.id = 555
        fake_msg.date = datetime(2026, 10, 8, 12, 0, 0)
        fake_msg.audio = MagicMock(performer="DJ Hero", title="Club Anthem", duration=210)
        fake_msg.document = None

        async def _iter(*a, **kw):
            yield fake_msg

        recorder.client.iter_messages = _iter
        recorder.client.get_entity = AsyncMock(return_value=MagicMock())
        recorder.channel_username = "@djclub"

        async def _mock_download(m, file_path, sem):
            recorder._downloaded += 1
            # Плейлист строится только по реально существующим файлам,
            # поэтому тест обязан создать файл на диске.
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as fh:
                fh.write(b"ID3" + b"\x00" * 64)
            recorder._downloaded_playlist_entries.append({
                "filepath": file_path,
                "artist": "DJ Hero",
                "title": "Club Anthem",
                "duration": 210,
            })

        recorder.download_with_limit = _mock_download
        await recorder.start()

        # Проверяем, что сгенерировался m3u8 плейлист
        m3u8_files = list(tmp_path.glob("*.m3u8"))
        assert len(m3u8_files) >= 1
        pl_content = m3u8_files[0].read_text(encoding="utf-8")
        assert "#EXTM3U" in pl_content
        assert "DJ Hero - Club Anthem" in pl_content


class TestBPMAndCamelotKeyDetection:

    def test_extract_camelot_key_direct(self):
        from media_utils import extract_key_meta
        assert extract_key_meta("Hit [8A - 124]") == "8A"
        assert extract_key_meta("Banger (11B)") == "11B"
        assert extract_key_meta("Track 128 BPM 4a") == "4A"
        assert extract_key_meta("Track 12A") == "12A"

    def test_extract_musical_key_mapping(self):
        from media_utils import extract_key_meta
        assert extract_key_meta("Track (Key: Am)") == "8A"
        assert extract_key_meta("Track [F#m]") == "11A"
        assert extract_key_meta("Track (Key: Gm)") == "6A"
        assert extract_key_meta("Track [C minor]") == "5A"
        assert extract_key_meta("Track [Eb Major]") == "5B"
        assert extract_key_meta("Track [D#m]") == "2A"

    def test_extract_key_fallback(self):
        from media_utils import extract_key_meta
        assert extract_key_meta("Regular Track Title") == "—"
        assert extract_key_meta("", "") == "—"

    def test_camelot_color(self):
        from media_utils import get_camelot_color
        assert get_camelot_color("8A") == "#F59E0B"
        assert get_camelot_color("1A") == "#00D2BE"
        assert get_camelot_color("—") == "#64748B"
        assert get_camelot_color("") == "#64748B"

    def test_id3_key_tag(self, tmp_path):
        from audio_converter import write_id3_tags, read_id3_tags
        from pydub.generators import Sine

        test_file = str(tmp_path / "test_key.mp3")
        tone = Sine(440).to_audio_segment(duration=50)
        tone.export(test_file, format="mp3")

        write_id3_tags(test_file, title="Harmonic Track", key="8A", bpm=128)
        meta = read_id3_tags(test_file)
        assert meta.get("key") == "8A"
        assert meta.get("bpm") == "128"


class TestResumableChunkDownloads:

    @pytest.mark.asyncio
    async def test_download_resumes_from_existing_part_file(self, recorder, tmp_path):
        target_file = str(tmp_path / "song.mp3")
        part_file = target_file + ".part"

        # Предварительно записываем первые 50 байт в .part файл
        with open(part_file, "wb") as f:
            f.write(b"X" * 50)

        fake_msg = MagicMock()
        fake_msg.id = 123
        fake_msg.media = MagicMock()

        called_offsets = []

        async def _mock_iter_download(media, offset=0, request_size=128*1024):
            called_offsets.append(offset)
            yield b"Y" * 50

        recorder.client.iter_download = _mock_iter_download

        res = await recorder._download_with_retry(
            fake_msg,
            target_file,
            total_size=100,
        )

        assert res is True
        # Проверяем, что скачивание продолжилось с 50-го байта
        assert called_offsets == [50]
        # И файл содержит ровно 100 байт (50 'X' + 50 'Y')
        assert os.path.exists(target_file)
        with open(target_file, "rb") as f:
            data = f.read()
        assert data == (b"X" * 50 + b"Y" * 50)

    def test_clean_temp_files_preserves_fresh_part(self, recorder, tmp_path, monkeypatch):
        import time as time_mod
        import recorder as rec_mod
        monkeypatch.setattr(rec_mod, "BASE_FOLDER", str(tmp_path))

        fresh_part = tmp_path / "downloading.mp3.part"
        stale_part = tmp_path / "stale.mp3.part"
        temp_file = tmp_path / "old.mp3.1.temp.mp3"

        fresh_part.write_bytes(b"active download data")
        stale_part.write_bytes(b"old dead data")
        temp_file.write_bytes(b"leftover temp")

        # Делаем stale_part старым (2 дня назад)
        old_time = time_mod.time() - 172800
        os.utime(str(stale_part), (old_time, old_time))

        recorder._clean_temp_files()

        assert fresh_part.exists() is True
        assert stale_part.exists() is False
        assert temp_file.exists() is False


class TestStreamingAudioPreview:
    """Тестирование потокового предпрослушивания треков (Feature 10)."""

    @pytest.mark.asyncio
    async def test_preview_returns_existing_cache(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        preview_dir = tmp_path / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        cached_file = preview_dir / "preview_42.mp3"
        cached_file.write_bytes(b"MPEG_PREVIEW_DATA" * 3000)  # > 32KB

        result = await recorder.download_track_preview("@testchan", 42)
        assert result == str(cached_file)

    @pytest.mark.asyncio
    async def test_preview_streams_chunks(self, recorder, tmp_path):
        recorder.base_folder = str(tmp_path)
        fake_msg = MagicMock()
        fake_msg.id = 99
        fake_msg.media = MagicMock()
        fake_msg.audio = MagicMock()
        fake_msg.audio.mime_type = "audio/mpeg"

        async def _mock_get_messages(entity, ids):
            return [fake_msg]

        async def _mock_get_entity(name):
            return MagicMock()

        called_chunks = []

        async def _mock_iter_dl(media, offset=0, request_size=128*1024):
            called_chunks.append(1)
            yield b"ID3_AUDIO_CHUNK_1_" * 2000
            called_chunks.append(2)
            yield b"ID3_AUDIO_CHUNK_2_" * 2000

        recorder.client.get_entity = _mock_get_entity
        recorder.client.get_messages = _mock_get_messages
        recorder.client.iter_download = _mock_iter_dl

        res = await recorder.download_track_preview("@testchan", 99, max_bytes=30000)
        assert res is not None
        assert os.path.exists(res)
        assert "preview_99" in res
        with open(res, "rb") as f:
            data = f.read()
        assert b"ID3_AUDIO_CHUNK_1_" in data
        assert len(data) >= 30000

    @pytest.mark.asyncio
    async def test_scan_with_search_query_music_filter(self, recorder):
        from telethon.tl.types import InputMessagesFilterMusic

        fake_msg = MagicMock()
        fake_msg.id = 101
        fake_msg.audio = MagicMock(performer="Search Artist", title="Search Track")
        fake_msg.document = None
        fake_msg.date = datetime.now(timezone.utc)

        iter_calls = []

        async def _mock_iter(entity, **kwargs):
            iter_calls.append(kwargs)
            yield fake_msg

        recorder.client.get_entity = AsyncMock(return_value=MagicMock())
        recorder.client.iter_messages = _mock_iter

        tracks = await recorder.scan(limit=50, search_query="Search Track")

        assert len(tracks) == 1
        assert tracks[0]["id"] == 101
        assert tracks[0]["title"] == "Search Track"
        assert len(iter_calls) == 1
        assert iter_calls[0].get("search") == "Search Track"
        assert iter_calls[0].get("filter") == InputMessagesFilterMusic

    @pytest.mark.asyncio
    async def test_scan_with_search_query_fallback_when_empty(self, recorder):
        from telethon.tl.types import InputMessagesFilterMusic

        doc_msg = MagicMock()
        doc_msg.id = 202
        doc_msg.audio = None
        doc_msg.document = MagicMock(mime_type="audio/mpeg", size=1024)
        doc_msg.message = "Doc Audio Track"
        doc_msg.date = datetime.now(timezone.utc)

        iter_calls = []

        async def _mock_iter(entity, **kwargs):
            iter_calls.append(kwargs)
            if kwargs.get("filter") == InputMessagesFilterMusic:
                # First pass: returns empty
                return
            # Fallback pass: returns doc_msg
            yield doc_msg

        recorder.client.get_entity = AsyncMock(return_value=MagicMock())
        recorder.client.iter_messages = _mock_iter

        tracks = await recorder.scan(limit=50, search_query="Doc Audio")

        assert len(tracks) == 1
        assert tracks[0]["id"] == 202
        assert len(iter_calls) == 2
        assert iter_calls[0].get("filter") == InputMessagesFilterMusic
        assert iter_calls[1].get("filter") is None
        assert iter_calls[1].get("search") == "Doc Audio"

    @pytest.mark.asyncio
    async def test_scan_with_search_query_pagination(self, recorder):
        fake_msg = MagicMock()
        fake_msg.id = 303
        fake_msg.audio = MagicMock(performer="Paged Artist", title="Paged Track")
        fake_msg.document = None
        fake_msg.date = datetime.now(timezone.utc)

        iter_calls = []

        async def _mock_iter(entity, **kwargs):
            iter_calls.append(kwargs)
            yield fake_msg

        recorder.client.get_entity = AsyncMock(return_value=MagicMock())
        recorder.client.iter_messages = _mock_iter

        tracks = await recorder.scan(limit=25, offset_id=500, search_query="Paged")

        assert len(tracks) == 1
        assert len(iter_calls) == 1
        assert iter_calls[0].get("offset_id") == 500
        assert iter_calls[0].get("search") == "Paged"

    @pytest.mark.asyncio
    async def test_m3u8_playlist_name_sanitized_when_channel_is_url(self, recorder, tmp_path, monkeypatch):
        import recorder as rec_module
        monkeypatch.setattr(rec_module, "BASE_FOLDER", str(tmp_path))

        recorder.channel_username = "https://t.me/x"
        real_track = tmp_path / "track.mp3"
        real_track.write_bytes(b"ID3" + b"\x00" * 64)
        recorder._downloaded_playlist_entries = [
            {"filepath": str(real_track), "artist": "Artist", "title": "Track", "duration": 180}
        ]
        fake_msg = MagicMock()
        fake_msg.id = 1
        fake_msg.date = datetime(2026, 10, 10, 12, 0, 0)
        fake_msg.audio = MagicMock(performer="Artist", title="Track", duration=180)
        fake_msg.document = None

        async def _iter(*a, **kw):
            yield fake_msg

        recorder.client.iter_messages = _iter
        recorder.client.get_entity = AsyncMock(return_value=MagicMock())

        async def _mock_download(m, file_path, sem):
            pass

        recorder.download_with_limit = _mock_download

        # Запуск не должен вызывать исключений (WinError 123)
        await recorder.start()

        m3u8_files = list(tmp_path.glob("*.m3u8"))
        assert len(m3u8_files) == 1
        playlist_path = str(m3u8_files[0])
        assert ":" not in os.path.basename(playlist_path)

    @pytest.mark.asyncio
    async def test_start_with_selected_ids_uses_get_messages(self, recorder):
        msg = MagicMock()
        msg.id = 50
        msg.audio = MagicMock(performer="Artist", title="Track", duration=180)
        msg.document = None
        msg.date = datetime.now(timezone.utc)

        get_msgs_called = []

        async def _mock_get_messages(entity, ids):
            get_msgs_called.append(ids)
            return [msg]

        recorder.client.get_messages = _mock_get_messages
        recorder.client.get_entity = AsyncMock(return_value=MagicMock())
        recorder.selected_ids = {50}

        downloaded_ids = []

        async def _mock_download(m, file_path, sem):
            downloaded_ids.append(m.id)

        recorder.download_with_limit = _mock_download
        await recorder.start()

        assert len(get_msgs_called) == 1
        assert 50 in get_msgs_called[0]
        assert downloaded_ids == [50]

