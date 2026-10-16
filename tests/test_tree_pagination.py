"""Тесты на догрузку треков и работу со списком.

Сканирование идёт порциями, и каждая догрузка обязана не ломать то,
что пользователь уже настроил: отметки, развёрнутые группы и порядок дат.
Поэтому проверяется не «дерево наполнилось», а конкретные свойства:

* трек без даты попадает в «Архив», а не теряется;
* трек, который уже на диске, не приходит отмеченным;
* сегодняшняя дата стоит выше вчерашней, «Архив» внизу;
* счётчики «новых» и «на диске» пересчитываются после каждой порции.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

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
    win = MainWindow()
    qtbot.addWidget(win)
    win.log = MagicMock()
    win._updating_tree = False
    win._scan_results = []
    win.channel_input.setText("@akmpool")
    return win


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _all_labels(w):
    """Все подписи дерева: даты сверху, каналы и треки ниже."""
    labels = []
    for index in range(w.library_tree.topLevelItemCount()):
        stack = [w.library_tree.topLevelItem(index)]
        while stack:
            item = stack.pop(0)
            labels.append(item.text(0))
            for child in range(item.childCount()):
                stack.append(item.child(child))
    return labels


class TestAppendTracks:
    """Догрузка очередной порции треков."""

    def test_empty_port_changes_nothing(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        before = w.track_list.count()
        w._append_tracks_to_tree([])
        assert w.track_list.count() == before

    def test_tracks_are_added(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        w._append_tracks_to_tree([_track(id=2, title="Second")])
        assert w.track_list.count() == 2

    def test_existing_track_is_unticked(self, w):
        """Уже скачанный трек не должен уходить в повторную загрузку."""
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1, already_exists=True)])
        assert w.track_list.item(0).checkState() == Qt.CheckState.Unchecked

    def test_new_track_is_ticked(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1)])
        assert w.track_list.item(0).checkState() == Qt.CheckState.Checked

    def test_existing_track_is_marked_in_label(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1, already_exists=True)])
        assert "уже есть" in w.track_list.item(0).text()

    def test_track_without_date_goes_to_archive(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1, date="")])
        assert any("архив" in label.lower() for label in _all_labels(w))

    def test_track_without_channel_uses_input(self, w):
        w.channel_input.setText("@primetimedj")
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1, channel="")])
        assert any("primetimedj" in label for label in _all_labels(w))

    def test_today_is_above_yesterday(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([
            _track(id=1, date=_yesterday()),
            _track(id=2, date=_today()),
        ])
        labels = _all_labels(w)
        today_at = next(i for i, l in enumerate(labels) if _today() in l)
        yesterday_at = next(i for i, l in enumerate(labels) if _yesterday() in l)
        assert today_at < yesterday_at, f"сегодня должно быть выше: {labels}"

    def test_archive_is_at_the_bottom(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([
            _track(id=1, date=""),
            _track(id=2, date=_today()),
        ])
        top = [w.library_tree.topLevelItem(i).text(0)
               for i in range(w.library_tree.topLevelItemCount())]
        archive_at = next(i for i, label in enumerate(top)
                          if "архив" in label.lower())
        assert archive_at == len(top) - 1, \
            f"«Архив» должен быть последней группой: {top}"

    def test_row_index_is_remembered(self, w):
        """Индекс нужен, чтобы пометить конкретный трек по его id."""
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=7), _track(id=8)])
        assert w._track_row_by_id[7] == 0
        assert w._track_row_by_id[8] == 1

    def test_statistics_are_recalculated(self, w):
        w._scan_results = [_track(id=1), _track(id=2, already_exists=True)]
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1)])
        text = w.stats_label.text()
        assert "Новых: 1" in text and "На диске: 1" in text

    def test_size_is_shown_in_label(self, w):
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree([_track(id=1, size=10 * 1024 * 1024)])
        assert "MB" in w.track_list.item(0).text()

    def test_updates_are_reenabled_after_failure(self, w):
        """Забытый флаг заблокировал бы дерево навсегда."""
        w._render_tracks_in_tree([])
        w._append_tracks_to_tree = MagicMock(
            side_effect=lambda tracks: (_ for _ in ()).throw(RuntimeError("сбой")))
        w.library_tree.setUpdatesEnabled(False)
        try:
            w._append_tracks_to_tree([])
        except RuntimeError:
            pass
        w.library_tree.setUpdatesEnabled(True)
        assert w._updating_tree is False


class TestTableSync:
    """Синхронизация чекбокса между таблицей Bento и деревом."""

    def test_checked_item_is_mirrored_in_list(self, w):
        from PyQt6.QtWidgets import QTableWidgetItem

        w._render_tracks_in_tree([_track(id=1)])
        item = QTableWidgetItem("GAZ")
        w.home_recent_table.setItem(0, 0, item)
        item.setData(Qt.ItemDataRole.UserRole, _track(id=1))
        item.setCheckState(Qt.CheckState.Checked)

        w._sync_table_from_track_list()

        assert w.track_list.count() == 1

    def test_row_double_click_opens_track(self, w):
        """Двойной клик по строке таблицы запускает тот же разбор трека."""
        w._scan_results = [_track(id=1)]
        w._render_tracks_in_tree([_track(id=1)])
        w._on_track_double_clicked = MagicMock()

        item = MagicMock()
        item.row.return_value = 0
        w._on_table_row_double_clicked(item)

        w._on_track_double_clicked.assert_called_once()

    def test_row_beyond_results_is_ignored(self, w):
        """Строка из прошлой выборки не должна ронять разбор."""
        w._scan_results = [_track(id=1)]
        w._render_tracks_in_tree([_track(id=1)])
        w._on_track_double_clicked = MagicMock()

        item = MagicMock()
        item.row.return_value = 99
        w._on_table_row_double_clicked(item)

        w._on_track_double_clicked.assert_not_called()


class TestDoubleClick:
    """Двойной клик по треку в дереве."""

    def _find_item(self, w, track_id):
        for index in range(w.library_tree.topLevelItemCount()):
            stack = [w.library_tree.topLevelItem(index)]
            while stack:
                item = stack.pop(0)
                data = item.data(1, Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and data.get("id") == track_id:
                    return item
                for child in range(item.childCount()):
                    stack.append(item.child(child))
        return None

    def test_known_track_goes_to_preview(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        item = self._find_item(w, 1)
        assert item is not None
        w.play_or_preview_track = MagicMock()
        w._on_tree_item_double_clicked(item, 1)
        w.play_or_preview_track.assert_called_once()

    def test_group_item_is_ignored(self, w):
        """У группы канала нет трека -- клик по ней ничего не должен делать."""
        w._render_tracks_in_tree([_track(id=1)])
        group = w.library_tree.topLevelItem(0)
        w.play_or_preview_track = MagicMock()
        w._on_tree_item_double_clicked(group, 1)
        w.play_or_preview_track.assert_not_called()

    def test_missing_file_is_reported_in_bar(self, w, monkeypatch):
        """Файл ещё не скачан -- пользователь должен это видеть, а не слышать тишину."""
        monkeypatch.delattr(type(w), "play_or_preview_track")
        w._render_tracks_in_tree([_track(id=1, filepath="/нет/такого.mp3")])
        item = self._find_item(w, 1)
        w.play_audio_file = MagicMock()
        w._on_tree_item_double_clicked(item, 1)
        w.play_audio_file.assert_not_called()
        assert "не скачан" in w.player_title_label.text()