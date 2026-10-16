"""Тесты на database.py: нормализация, запросы, отказоустойчивость, дедуп.

Закрывает непокрытые ветки: аварийные пути всех функций (неверные
аргументы, отказ БД), альтернативные ветки ``find_duplicate_download`` и
нечёткое сравнение треков.

Каждый тест работает на своей временной базе -- рабочая downloads.db не
затрагивается.
"""

import sqlite3
from unittest.mock import patch

import pytest

import database as db


@pytest.fixture
def dbfile(tmp_path):
    path = str(tmp_path / "downloads.db")
    db.init_db(path)
    return path


def _add(path, channel="akmpool", msg=1, artist="A", title="T",
         duration=180, status="completed"):
    db.record_download(channel, msg, filename=f"{msg}.mp3",
                       file_path=f"C:/{msg}.mp3", file_size=100,
                       artist=artist, title=title, duration=duration,
                       status=status, db_path=path)


class TestNormalizeChannelId:

    @pytest.mark.parametrize("raw,expected", [
        ("https://t.me/kutsuevpool", "kutsuevpool"),
        ("http://t.me/kutsuevpool", "kutsuevpool"),
        ("t.me/kutsuevpool", "kutsuevpool"),
        ("@kutsuevpool", "kutsuevpool"),
        ("kutsuevpool", "kutsuevpool"),
        ("  https://t.me/KutsuevPool/  ", "kutsuevpool"),
        ("@KutsuevPool", "kutsuevpool"),
    ])
    def test_forms(self, raw, expected):
        assert db.normalize_channel_id(raw) == expected

    def test_empty_inputs(self):
        assert db.normalize_channel_id("") == ""
        assert db.normalize_channel_id(None) == ""


class TestSafeIntAndPaths:

    def test_safe_int_accepts(self):
        assert db._safe_int("42") == 42
        assert db._safe_int(42) == 42

    def test_safe_int_rejects(self):
        assert db._safe_int("не число") is None
        assert db._safe_int(None) is None

    def test_db_path_explicit(self, tmp_path):
        assert db.get_db_path(str(tmp_path / "x.db")) == str(tmp_path / "x.db")

    def test_db_path_defaults_to_config(self):
        assert db.get_db_path() == db.get_db_path(None)

    def test_pragma_failure_does_not_break_connection(self, tmp_path):
        """Ошибка PRAGMA не должна мешать открыть базу."""
        path = str(tmp_path / "p.db")
        real_connect = sqlite3.connect

        class _Boom:
            def __init__(self, *a, **kw):
                self._c = real_connect(path, timeout=5.0)

            def execute(self, sql, *a):
                if sql.startswith("PRAGMA"):
                    raise sqlite3.DatabaseError("pragma запрещена")
                return self._c.execute(sql, *a)

            def __getattr__(self, n):
                return getattr(self._c, n)

        with patch("sqlite3.connect", return_value=_Boom()):
            conn = db.get_db_connection(path)
        conn.close()  # ошибок быть не должно


class TestInitDb:

    def test_second_call_is_short_circuited(self, dbfile):
        # файл уже есть и путь в кэше -- повторная инициализация не нужна
        db.init_db(dbfile)
        db.init_db(dbfile)

    def test_failure_is_raised(self, tmp_path):
        bad = str(tmp_path / "sub" / "nope.db")
        with patch.object(db, "get_db_path", return_value=bad), \
             patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("нет")):
            with pytest.raises(sqlite3.DatabaseError):
                db.init_db(bad)


class TestIsDownloaded:

    def test_found(self, dbfile):
        _add(dbfile, msg=10)
        assert db.is_downloaded("akmpool", 10, dbfile) is True

    def test_wrong_channel_or_id(self, dbfile):
        _add(dbfile, msg=10)
        assert db.is_downloaded("other", 10, dbfile) is False
        assert db.is_downloaded("akmpool", 11, dbfile) is False

    def test_non_completed_status_is_not_downloaded(self, dbfile):
        _add(dbfile, msg=12, status="failed")
        assert db.is_downloaded("akmpool", 12, dbfile) is False

    def test_bad_arguments_return_false(self, dbfile):
        assert db.is_downloaded("", 10, dbfile) is False
        assert db.is_downloaded("akmpool", "не id", dbfile) is False

    def test_db_error_returns_false(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.is_downloaded("akmpool", 10, dbfile) is False


class TestDownloadedIds:

    def test_returns_set(self, dbfile):
        _add(dbfile, msg=1)
        _add(dbfile, msg=2)
        _add(dbfile, msg=3, status="failed")
        assert db.get_downloaded_ids("akmpool", dbfile) == {1, 2}

    def test_empty_channel_returns_empty_set(self, dbfile):
        assert db.get_downloaded_ids("", dbfile) == set()

    def test_db_error_returns_empty_set(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.get_downloaded_ids("akmpool", dbfile) == set()


class TestGetDownload:

    def test_returns_row_as_dict(self, dbfile):
        _add(dbfile, msg=20, artist="Zivert", title="GAZ")
        row = db.get_download("akmpool", 20, dbfile)
        assert row["artist"] == "Zivert"
        assert row["title"] == "GAZ"

    def test_missing_returns_none(self, dbfile):
        assert db.get_download("akmpool", 999, dbfile) is None

    def test_bad_arguments_return_none(self, dbfile):
        assert db.get_download("", 20, dbfile) is None
        assert db.get_download("akmpool", None, dbfile) is None

    def test_db_error_returns_none(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.get_download("akmpool", 20, dbfile) is None


class TestGetDownloadsAndCount:

    def test_lists_all_when_channel_is_none(self, dbfile):
        _add(dbfile, channel="a", msg=1)
        _add(dbfile, channel="b", msg=2)
        assert len(db.get_downloads(db_path=dbfile)) == 2

    def test_filters_by_channel(self, dbfile):
        _add(dbfile, channel="a", msg=1)
        _add(dbfile, channel="b", msg=2)
        got = db.get_downloads("a", db_path=dbfile)
        assert [r["message_id"] for r in got] == [1]

    def test_limit_and_offset(self, dbfile):
        for i in range(5):
            _add(dbfile, msg=i)
        page = db.get_downloads(limit=2, offset=1, db_path=dbfile)
        assert len(page) == 2

    def test_db_error_returns_empty_list(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.get_downloads(db_path=dbfile) == []

    def test_count_per_channel_and_status(self, dbfile):
        _add(dbfile, channel="a", msg=1)
        _add(dbfile, channel="a", msg=2, status="failed")
        assert db.get_download_count("a", db_path=dbfile) == 1
        assert db.get_download_count("a", status="failed", db_path=dbfile) == 1
        assert db.get_download_count(db_path=dbfile) == 1

    def test_count_db_error_returns_zero(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.get_download_count(db_path=dbfile) == 0


class TestDeleteAndClear:

    def test_delete_existing(self, dbfile):
        _add(dbfile, msg=30)
        assert db.delete_download("akmpool", 30, dbfile) is True
        assert db.get_download("akmpool", 30, dbfile) is None

    def test_delete_missing_returns_false(self, dbfile):
        assert db.delete_download("akmpool", 31, dbfile) is False

    def test_delete_bad_arguments(self, dbfile):
        assert db.delete_download("", 31, dbfile) is False
        assert db.delete_download("akmpool", "x", dbfile) is False

    def test_delete_db_error_returns_false(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.delete_download("akmpool", 30, dbfile) is False

    def test_clear_history_only_affects_one_channel(self, dbfile):
        _add(dbfile, channel="a", msg=1)
        _add(dbfile, channel="a", msg=2)
        _add(dbfile, channel="b", msg=3)
        assert db.clear_channel_history("a", dbfile) == 2
        assert db.get_download_count(db_path=dbfile) == 1

    def test_clear_empty_channel_returns_zero(self, dbfile):
        assert db.clear_channel_history("", dbfile) == 0

    def test_clear_db_error_returns_zero(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.clear_channel_history("a", dbfile) == 0


class TestRecordDownload:

    def test_bad_arguments_return_false(self, dbfile):
        assert db.record_download("", 1, db_path=dbfile) is False
        assert db.record_download("akmpool", "не id", db_path=dbfile) is False

    def test_db_error_returns_false(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.record_download("akmpool", 60, db_path=dbfile) is False

    def test_explicit_timestamp_is_kept(self, dbfile):
        db.record_download("akmpool", 61, filename="a.mp3", file_path="p",
                           downloaded_at="2026-10-15T00:00:00+00:00",
                           db_path=dbfile)
        assert db.get_download("akmpool", 61, dbfile)["downloaded_at"] \
            == "2026-10-15T00:00:00+00:00"

    def test_duplicate_is_updated_not_duplicated(self, dbfile):
        db.record_download("akmpool", 62, filename="a.mp3", file_path="p",
                           db_path=dbfile)
        db.record_download("akmpool", 62, filename="b.mp3", file_path="q",
                           db_path=dbfile)
        rows = db.get_downloads("akmpool", db_path=dbfile)
        assert len(rows) == 1
        assert rows[0]["filename"] == "b.mp3"


class TestNormalizeTrackText:

    def test_empty(self):
        assert db.normalize_track_text("") == ""

    def test_strips_links_and_handles(self):
        assert db.normalize_track_text("@kutsuevpool") == ""
        assert db.normalize_track_text("https://t.me/x") == ""

    def test_strips_quality_tags(self):
        assert "320" not in db.normalize_track_text("Track [320 kbps]")

    def test_strips_feat_clause(self):
        assert "feat" not in db.normalize_track_text("Artist feat. Someone - Song")

    def test_lowercases_and_squeezes_spaces(self):
        assert db.normalize_track_text("A   B!!") == "a b"


class TestFuzzyMatch:

    def test_exact_match(self):
        assert db.is_fuzzy_track_match("A", "T", 180, "a", "t", 180) is True

    def test_duration_tolerance_blocks_far_tracks(self):
        assert db.is_fuzzy_track_match("A", "T", 180, "A", "T", 300) is False

    def test_duration_within_tolerance_passes(self):
        assert db.is_fuzzy_track_match("A", "T", 180, "A", "T", 181) is True

    def test_zero_duration_skips_check(self):
        assert db.is_fuzzy_track_match("A", "T", 0, "A", "T", 999) is True

    def test_empty_metadata_never_matches(self):
        assert db.is_fuzzy_track_match("", "", 0, "A", "T", 180) is False

    def test_generic_signatures_never_match(self):
        assert db.is_fuzzy_track_match("Unknown Artist", "Unknown Title", 180,
                                        "A", "T", 180) is False

    def test_same_artist_close_title(self):
        # ratio_t = 2*3/(3+4) = 0.857 -- проходит порог 0.85,
        # а итоговая сигнатура даёт лишь 0.90, поэтому решение принимает
        # именно ветка «точный артист + близкое название».
        assert db.is_fuzzy_track_match("Zivert", "GAZ", 180,
                                        "Zivert", "GAZE", 180) is True

    def test_same_title_close_artist(self):
        assert db.is_fuzzy_track_match("Zivert", "GAZ", 180,
                                        "Zivertt", "GAZ", 180) is True

    def test_both_components_very_close(self):
        # Обе пары превышают 0.88, хотя ни одна не равна другой.
        assert db.is_fuzzy_track_match("Zivert", "Hello World", 180,
                                        "Zivertt", "Hello Worlds", 180) is True

    def test_matched_by_combined_signature(self):
        """Артист и название «переехали» друг в друга -- сигнатуры равны."""
        assert db.is_fuzzy_track_match("X", "", 0, "", "X", 0) is True

    def test_completely_different(self):
        assert db.is_fuzzy_track_match("Alpha", "One", 180,
                                        "Omega", "Nine", 180) is False


class TestFindDuplicate:

    def test_finds_existing(self, dbfile):
        _add(dbfile, msg=40, artist="Zivert", title="GAZ", duration=180)
        found = db.find_duplicate_download("Zivert", "GAZ", 180, db_path=dbfile)
        assert found is not None and found["message_id"] == 40

    def test_returns_none_for_new_track(self, dbfile):
        _add(dbfile, msg=41, artist="A", title="B", duration=180)
        assert db.find_duplicate_download("C", "D", 180, db_path=dbfile) is None

    def test_zero_duration_searches_without_filter(self, dbfile):
        """Без длительности берётся последние 500 записей."""
        _add(dbfile, msg=42, artist="A", title="B", duration=180)
        found = db.find_duplicate_download("A", "B", 0, db_path=dbfile)
        assert found is not None

    def test_skips_non_completed(self, dbfile):
        _add(dbfile, msg=43, artist="A", title="B", status="failed")
        assert db.find_duplicate_download("A", "B", 180, db_path=dbfile) is None

    def test_db_error_returns_none(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.find_duplicate_download("A", "B", 180, db_path=dbfile) is None


class TestCompletedTracksIndex:

    def test_includes_only_completed(self, dbfile):
        _add(dbfile, msg=50, status="completed")
        _add(dbfile, msg=51, status="failed")
        idx = db.get_completed_tracks_index(dbfile)
        assert [r["message_id"] for r in idx] == [50]

    def test_contains_expected_keys(self, dbfile):
        _add(dbfile, msg=52)
        row = db.get_completed_tracks_index(dbfile)[0]
        assert {"id", "channel_id", "message_id", "artist", "title",
                "duration", "filename", "file_path"} <= set(row)

    def test_db_error_returns_empty(self, dbfile):
        with patch.object(db, "db_session", side_effect=sqlite3.DatabaseError):
            assert db.get_completed_tracks_index(dbfile) == []