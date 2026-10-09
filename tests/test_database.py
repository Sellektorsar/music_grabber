"""Тесты для модуля database.py (SQLite индекс загрузок)."""

import os
import pytest
import database as db


class TestNormalizeChannelId:
    def test_strip_at_symbol(self):
        assert db.normalize_channel_id("@my_channel") == "my_channel"

    def test_strip_https_tme(self):
        assert db.normalize_channel_id("https://t.me/kutsuevpool") == "kutsuevpool"
        assert db.normalize_channel_id("http://t.me/kutsuevpool/") == "kutsuevpool"

    def test_strip_tme(self):
        assert db.normalize_channel_id("t.me/music_hub") == "music_hub"

    def test_plain_username(self):
        assert db.normalize_channel_id("BestTracks") == "besttracks"

    def test_empty_and_none(self):
        assert db.normalize_channel_id("") == ""
        assert db.normalize_channel_id(None) == ""


class TestDatabaseCRUD:
    @pytest.fixture
    def test_db_path(self, tmp_path):
        return str(tmp_path / "test_downloads.db")

    def test_init_db(self, test_db_path):
        db.init_db(test_db_path)
        assert os.path.exists(test_db_path)

    def test_record_and_is_downloaded(self, test_db_path):
        assert not db.is_downloaded("@test_channel", 101, db_path=test_db_path)

        success = db.record_download(
            channel_id="@test_channel",
            message_id=101,
            filename="Artist - Song.mp3",
            file_path="/path/to/Artist - Song.mp3",
            file_size=5000000,
            artist="Artist",
            title="Song",
            duration=180,
            db_path=test_db_path,
        )
        assert success is True
        assert db.is_downloaded("@test_channel", 101, db_path=test_db_path)
        assert db.is_downloaded("test_channel", 101, db_path=test_db_path)
        assert not db.is_downloaded("test_channel", 999, db_path=test_db_path)

    def test_get_download(self, test_db_path):
        db.record_download(
            channel_id="https://t.me/ch1",
            message_id=42,
            filename="Test.mp3",
            file_size=1234,
            artist="DJ",
            title="Beat",
            db_path=test_db_path,
        )
        item = db.get_download("ch1", 42, db_path=test_db_path)
        assert item is not None
        assert item["channel_id"] == "ch1"
        assert item["message_id"] == 42
        assert item["artist"] == "DJ"
        assert item["title"] == "Beat"
        assert item["file_size"] == 1234
        assert item["status"] == "completed"

    def test_get_downloaded_ids(self, test_db_path):
        db.record_download("chan", 1, db_path=test_db_path)
        db.record_download("chan", 2, db_path=test_db_path)
        db.record_download("chan", 3, status="failed", db_path=test_db_path)
        db.record_download("other_chan", 4, db_path=test_db_path)

        ids = db.get_downloaded_ids("chan", db_path=test_db_path)
        assert ids == {1, 2}

    def test_get_downloads_and_count(self, test_db_path):
        for i in range(1, 6):
            db.record_download(
                "cool_channel",
                i,
                title=f"Track {i}",
                db_path=test_db_path,
            )

        assert db.get_download_count("cool_channel", db_path=test_db_path) == 5
        assert db.get_download_count(db_path=test_db_path) == 5

        list_items = db.get_downloads("cool_channel", limit=3, db_path=test_db_path)
        assert len(list_items) == 3

    def test_delete_download(self, test_db_path):
        db.record_download("chan", 10, db_path=test_db_path)
        assert db.is_downloaded("chan", 10, db_path=test_db_path)

        assert db.delete_download("chan", 10, db_path=test_db_path) is True
        assert not db.is_downloaded("chan", 10, db_path=test_db_path)

    def test_clear_channel_history(self, test_db_path):
        db.record_download("chan1", 1, db_path=test_db_path)
        db.record_download("chan1", 2, db_path=test_db_path)
        db.record_download("chan2", 3, db_path=test_db_path)

        deleted = db.clear_channel_history("chan1", db_path=test_db_path)
        assert deleted == 2
        assert db.get_download_count("chan1", db_path=test_db_path) == 0
        assert db.get_download_count("chan2", db_path=test_db_path) == 1


class TestCrossChannelDeduplication:
    @pytest.fixture
    def test_db_path(self, tmp_path):
        return str(tmp_path / "test_dedup.db")

    def test_normalize_track_text(self):
        raw = "🔥 Fisher - Losing It (Extended Mix) [320 kbps] @edm_drop"
        norm = db.normalize_track_text(raw)
        assert "fisher" in norm
        assert "losing it" in norm
        assert "@" not in norm
        assert "320" not in norm

    def test_is_fuzzy_track_match(self):
        # 1. Matches with 1s duration variance
        assert db.is_fuzzy_track_match(
            "Fisher", "Losing It (Extended Mix)", 308,
            "FISHER", "Losing It (Extended Mix) [320 kbps]", 309,
            tolerance_sec=2
        ) is True

        # 2. Rejects when duration difference > 2s (e.g. Radio Edit vs Extended Mix)
        assert db.is_fuzzy_track_match(
            "Fisher", "Losing It (Extended Mix)", 308,
            "Fisher", "Losing It (Radio Edit)", 195,
            tolerance_sec=2
        ) is False

        # 3. Rejects generic placeholder names
        assert db.is_fuzzy_track_match(
            "UnknownArtist", "UnknownTitle", 120,
            "UnknownArtist", "UnknownTitle", 120,
        ) is False

    def test_find_duplicate_download(self, test_db_path):
        # Track originally downloaded from Channel A
        db.record_download(
            channel_id="@house_sessions",
            message_id=50,
            artist="Meduza",
            title="Piece Of Your Heart",
            duration=182,
            db_path=test_db_path,
        )

        # Scanned in Channel B with slight variance
        dup = db.find_duplicate_download(
            artist="MEDUZA feat. Goodboys",
            title="Piece of Your Heart [320 kbps]",
            duration=183,
            tolerance_sec=2,
            db_path=test_db_path,
        )
        assert dup is not None
        assert dup["channel_id"] == "house_sessions"
        assert dup["message_id"] == 50

        # Completely different track
        no_dup = db.find_duplicate_download(
            artist="Swedish House Mafia",
            title="One",
            duration=165,
            db_path=test_db_path,
        )
        assert no_dup is None

    def test_get_completed_tracks_index(self, test_db_path):
        db.record_download("ch1", 10, artist="A1", title="T1", duration=100, db_path=test_db_path)
        db.record_download("ch2", 20, artist="A2", title="T2", duration=200, db_path=test_db_path)
        db.record_download("ch3", 30, artist="A3", title="T3", duration=300, status="failed", db_path=test_db_path)

        index = db.get_completed_tracks_index(db_path=test_db_path)
        assert len(index) == 2
        durations = {item["duration"] for item in index}
        assert durations == {100, 200}

