"""Тесты на TreeControllerMixin: фильтры, отбор, пересчёт счётчиков.

Непокрытыми были не дефолты, а рабочие ветки: семь измерений фильтра
(текст, канал, статус, длительность, BPM, качество, тональность) и
операции отбора треков. Это ровно та логика, по которой DJ решает, что
скачивать, поэтому проверяется подробно.
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt


def _track(**kw):
    base = {
        "id": 1, "channel": "akmpool", "title": "GAZ", "performer": "Zivert",
        "filename": "Zivert - GAZ.mp3", "duration": 240, "bpm": "128",
        "size": 9_000_000, "already_exists": False, "is_duplicate": False,
        "key": "8A", "status": "READY", "filepath": "",
    }
    base.update(kw)
    return base


@pytest.fixture
def w(monkeypatch, tmp_path, qtbot):
    cfg_dir = tmp_path / "telegram_audio"
    cfg_dir.mkdir()
    monkeypatch.setattr("config.CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(cfg_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    from gui import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w._updating_tree = False
    w._active_camelot_key = None
    w._filter_tracks_text = MagicMock()
    w._update_download_button_counter = MagicMock()
    return w


class TestCheckTrackFilterText:
    """Текстовый поиск ищет по артисту, названию, имени файла и сырым полям."""

    def _m(self, w, t, query, chan="", st=0, dur=0, bpm=0, br=0):
        return w._check_track_filter_match(t, query, chan, st, dur, bpm, br)

    def test_empty_track_passes_everything(self, w):
        assert self._m(w, None, "что угодно") is True
        assert self._m(w, {}, "abc") is True

    def test_no_query_passes(self, w):
        assert self._m(w, _track(), "") is True

    def test_match_by_performer(self, w):
        assert self._m(w, _track(), "zivert") is True

    def test_match_by_title(self, w):
        assert self._m(w, _track(), "gaz") is True

    def test_match_by_filename(self, w):
        assert self._m(w, _track(), "zivert - gaz.mp3") is True

    def test_match_by_raw_fields(self, w):
        t = _track(performer="", title="", filename="",
                   raw_performer="Zivert live", raw_title="GAZ acoustic")
        assert self._m(w, t, "acoustic") is True

    def test_no_match_rejected(self, w):
        assert self._m(w, _track(), "нет такого") is False

    def test_all_words_required(self, w):
        assert self._m(w, _track(), "zivert gaz") is True
        assert self._m(w, _track(), "zivert отсутствующее") is False

    def test_query_is_lowercased_by_the_filter_layer(self, w):
        """Нормализация регистра -- забота _apply_all_filters.

        Сам _check_track_filter_match получает уже приведённый к нижнему
        регистру запрос, поэтому проверяется именно слой выше.
        """
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        w.search_filter_input.setText("  ZIVERT  ")
        seen = {}
        w._check_track_filter_match = lambda t, q, *a: seen.setdefault("q", q)
        w._apply_all_filters()
        assert seen["q"] == "zivert"


class TestCheckTrackFilterChannel:

    def test_matching_channel_passes(self, w):
        assert w._check_track_filter_match(
            _track(channel="akmpool"), "", "akmpool", 0, 0, 0, 0) is True

    def test_other_channel_rejected(self, w):
        assert w._check_track_filter_match(
            _track(channel="other"), "", "akmpool", 0, 0, 0, 0) is False


class TestCheckTrackFilterStatus:
    """0 -- все, 1 -- новые, 2 -- на диске, 3 -- дубликаты."""

    def test_all_statuses_pass(self, w):
        assert w._check_track_filter_match(_track(), "", "", 0, 0, 0, 0) is True

    def test_new_excludes_on_disk(self, w):
        assert w._check_track_filter_match(
            _track(already_exists=True), "", "", 1, 0, 0, 0) is False
        assert w._check_track_filter_match(
            _track(is_duplicate=True), "", "", 1, 0, 0, 0) is False

    def test_new_includes_fresh(self, w):
        assert w._check_track_filter_match(_track(), "", "", 1, 0, 0, 0) is True

    def test_on_disk_requires_existing(self, w):
        assert w._check_track_filter_match(
            _track(already_exists=True), "", "", 2, 0, 0, 0) is True
        assert w._check_track_filter_match(_track(), "", "", 2, 0, 0, 0) is False

    def test_on_disk_excludes_duplicate(self, w):
        assert w._check_track_filter_match(
            _track(already_exists=True, is_duplicate=True), "", "", 2, 0, 0, 0) is False

    def test_duplicates_only(self, w):
        assert w._check_track_filter_match(
            _track(is_duplicate=True), "", "", 3, 0, 0, 0) is True
        assert w._check_track_filter_match(_track(), "", "", 3, 0, 0, 0) is False


class TestCheckTrackFilterDuration:
    """1 -- DJ-треки 3:00-8:00, 2 -- Extended > 5:00, 3 -- Radio < 3:30, 4 -- Set > 20:00."""

    def _m(self, w, dur_sec, idx):
        return w._check_track_filter_match(
            _track(duration=dur_sec), "", "", 0, idx, 0, 0)

    def test_dj_range_bounds(self, w):
        assert self._m(w, 179, 1) is False
        assert self._m(w, 180, 1) is True
        assert self._m(w, 480, 1) is True
        assert self._m(w, 481, 1) is False

    def test_extended_mix(self, w):
        assert self._m(w, 299, 2) is False
        assert self._m(w, 300, 2) is True

    def test_radio_edit(self, w):
        assert self._m(w, 0, 3) is False
        assert self._m(w, 210, 3) is True
        assert self._m(w, 211, 3) is False

    def test_dj_set(self, w):
        assert self._m(w, 1199, 4) is False
        assert self._m(w, 1200, 4) is True

    def test_zero_duration_handled(self, w):
        assert self._m(w, None, 1) in (True, False)   # без исключения


class TestCheckTrackFilterBpm:

    def _m(self, w, bpm, idx):
        return w._check_track_filter_match(_track(bpm=bpm), "", "", 0, 0, idx, 0)

    def test_no_filter_passes(self, w):
        assert self._m(w, "999", 0) is True

    def test_unparsable_bpm_rejected_when_filter_active(self, w):
        assert self._m(w, "не число", 1) is False

    def test_bpm_falls_back_to_title(self, w):
        t = _track(bpm=None, title="Track 124 BPM")
        assert w._check_track_filter_match(t, "", "", 0, 0, 2, 0) is True

    def test_tech_house_120_130(self, w):
        assert self._m(w, "128", 1) is True
        assert self._m(w, "140", 1) is False

    def test_house_115_124(self, w):
        assert self._m(w, "120", 2) is True
        assert self._m(w, "128", 2) is False

    def test_trap_130_145(self, w):
        assert self._m(w, "140", 3) is True
        assert self._m(w, "128", 3) is False

    def test_dnb_160_180(self, w):
        assert self._m(w, "170", 4) is True
        assert self._m(w, "128", 4) is False

    def test_below_115(self, w):
        assert self._m(w, "110", 5) is True
        assert self._m(w, "120", 5) is False


class TestCheckTrackFilterQuality:

    def _m(self, w, idx, **kw):
        return w._check_track_filter_match(_track(**kw), "", "", 0, 0, 0, idx)

    def test_hq_needs_320_marker_or_big_file(self, w):
        assert self._m(w, 1, filename="track [320k].mp3") is True
        assert self._m(w, 1, title="320 kbps") is True
        assert self._m(w, 1, filename="small.mp3", size=1_000_000,
                       duration=100) is False

    def test_lossless_extension(self, w):
        assert self._m(w, 2, filename="track.flac") is True
        assert self._m(w, 2, filename="track.wav") is True
        assert self._m(w, 2, filename="track.mp3") is False

    def test_standard_192(self, w):
        assert self._m(w, 3, filename="t.mp3", size=6_000_000, duration=300) is True
        assert self._m(w, 3, filename="t.mp3", size=1_000_000, duration=300) is False


class TestCheckTrackFilterCamelot:

    def test_no_filter_passes(self, w):
        assert w._check_track_filter_match(_track(), "", "", 0, 0, 0, 0) is True

    def test_compatible_key_passes(self, w):
        w._active_camelot_key = "8A"
        with patch("ui.bento_widgets.CamelotWheelWidget.get_compatible_keys",
                   staticmethod(lambda k: ["8A", "9A"])):
            assert w._check_track_filter_match(_track(key="9A"), "", "", 0, 0, 0, 0) is True

    def test_incompatible_key_rejected(self, w):
        w._active_camelot_key = "8A"
        with patch("ui.bento_widgets.CamelotWheelWidget.get_compatible_keys",
                   staticmethod(lambda k: ["8A"])):
            assert w._check_track_filter_match(_track(key="2B"), "", "", 0, 0, 0, 0) is False

    def test_missing_key_rejected(self, w):
        w._active_camelot_key = "8A"
        assert w._check_track_filter_match(_track(key="—"), "", "", 0, 0, 0, 0) is False
        assert w._check_track_filter_match(_track(key=""), "", "", 0, 0, 0, 0) is False

    def test_key_extracted_from_title(self, w):
        w._active_camelot_key = "8A"
        with patch("ui.bento_widgets.CamelotWheelWidget.get_compatible_keys",
                   staticmethod(lambda k: ["8A"])):
            t = _track(key=None, title="Track [8A]")
            assert w._check_track_filter_match(t, "", "", 0, 0, 0, 0) is True


class TestTrackSelectionCommands:
    """Операции отбора: «только новые», «все», «снять», «сброс фильтров»."""

    def _items(self, w):
        return [w.library_tree.topLevelItem(i)
                for i in range(w.library_tree.topLevelItemCount())]

    def test_select_only_new_runs(self, w):
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        w._select_only_new_tracks()

    def test_select_all_runs(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        w._select_all_tracks()

    def test_clear_selection_runs(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        w._clear_selection()

    def test_reset_filters_clears_camelot(self, w):
        w._active_camelot_key = "8A"
        w._reset_dj_filters()
        assert getattr(w, "_active_camelot_key", None) in (None, "")

    def test_expand_and_collapse(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        w._expand_all_groups()
        w._collapse_all_groups()


class TestCheckedTracksCollection:
    """Сбор отмеченных треков -- то, что реально уходит в загрузку."""

    def test_no_items_returns_empty(self, w):
        assert w.get_checked_tracks() == []

    def test_reads_mirror_not_tree(self, w):
        """Геттер читает скрытое зеркало track_list, а не дерево.

        Это зафиксировано намеренно: сборщик в start_download обходит
        library_tree, а этот метод остаётся для других сценариев.
        """
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        assert w.track_list.count() == 2
        got = w.get_checked_tracks()
        assert all(t["id"] in (1, 2) for t in got)

    def test_unchecked_mirror_item_excluded(self, w):
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        w.track_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        got = w.get_checked_tracks()
        assert all(t["id"] != 1 for t in got)


class TestTreeScrollAndRefresh:

    def test_scroll_triggers_load_more_near_bottom(self, w):
        """Подгрузка срабатывает у нижней границы списка."""
        w._render_tracks_in_tree([_track(id=i) for i in range(40)])
        sb = w.library_tree.verticalScrollBar()
        sb.setMaximum(1000)
        w._load_more_tracks = MagicMock()
        w._on_tree_scroll(sb.maximum())
        w._load_more_tracks.assert_called_once()

    def test_scroll_inside_range_does_nothing(self, w):
        w._render_tracks_in_tree([_track(id=i) for i in range(40)])
        sb = w.library_tree.verticalScrollBar()
        sb.setMaximum(1000)
        w._load_more_tracks = MagicMock()
        w._on_tree_scroll(1)
        w._load_more_tracks.assert_not_called()

    def test_scroll_without_tree_is_noop(self, w):
        w._load_more_tracks = MagicMock()
        del w.library_tree
        w._on_tree_scroll(9999)
        w._load_more_tracks.assert_not_called()

    def test_toggle_check_state_changes_item(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        item = w.library_tree.topLevelItem(0)
        before = item.checkState(0)
        w.toggle_item_check_state(item)
        assert item.checkState(0) != before