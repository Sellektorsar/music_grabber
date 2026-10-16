"""Тесты на экспорт M3U8 и контекстное меню дерева.

Экспорт плейлиста -- способ унести треки из приложения в любой DJ-софт,
поэтому важен выбор источника треков: отмеченные, текущий или все
результаты сканирования. Проверяется именно он, а не сам факт записи
файла.

Контекстное меню проверяется через подменённый ``QMenu.exec``: сам
диалог блокирует, а вот набор действий и их привязка к элементу --
это то, что ломается при переработке дерева.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QMessageBox


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
    win._scan_results = []
    return win


def _track(**kw):
    base = {
        "id": 1, "channel": "akmpool", "title": "GAZ", "performer": "Zivert",
        "filename": "Zivert - GAZ.mp3", "duration": 240,
        "filepath": "C:/music/Zivert - GAZ.mp3", "size": 9_000_000,
        "already_exists": True, "is_duplicate": False,
    }
    base.update(kw)
    return base


def _playlist_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tick_all(w):
    """Отмечает все треки в зеркале -- как это делает пользователь."""
    for index in range(w.track_list.count()):
        w.track_list.item(index).setCheckState(Qt.CheckState.Checked)


def _first_track_item(w):
    """Находит элемент дерева, за которым стоит трек (не группу канала)."""
    for index in range(w.library_tree.topLevelItemCount()):
        item = w.library_tree.topLevelItem(index)
        stack = [item]
        while stack:
            current = stack.pop(0)
            if isinstance(current.data(1, Qt.ItemDataRole.UserRole), dict):
                return current
            for child in range(current.childCount()):
                stack.append(current.child(child))
    return None


class TestExportSelectionSource:
    """Откуда берутся треки для экспорта."""

    def test_nothing_to_export(self, w):
        assert w.export_selected_to_m3u8("out.m3u8") is None
        assert "Нет треков для экспорта" in w.log.call_args[0][0]

    def test_uses_checked_tracks(self, w, tmp_path):
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        _tick_all(w)
        out = w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        assert _playlist_text(out).count("#EXTINF") == 2

    def test_unticked_tracks_are_not_exported(self, w, tmp_path):
        """Отметка снята -- трек в плейлист не попадает."""
        w._render_tracks_in_tree([_track(id=1)])
        w.track_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        w._scan_results = []
        assert w.export_selected_to_m3u8(str(tmp_path / "p.m3u8")) is None

    def test_falls_back_to_current_item(self, w, tmp_path):
        """Без отметок берётся трек под курсором."""
        w._render_tracks_in_tree([_track(id=1, title="Solo")])
        w.track_list.setCurrentRow(-1)
        w.library_tree.setCurrentItem(_first_track_item(w))
        out = w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        assert "Solo" in _playlist_text(out)

    def test_falls_back_to_scan_results(self, w, tmp_path):
        """Если в дереве ничего нет -- используются результаты скана."""
        w._scan_results = [_track(id=9, title="FromScan")]
        out = w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        assert "FromScan" in _playlist_text(out)


class TestExportWriting:
    """Сама запись плейлиста."""

    def test_file_contains_standard_header(self, w, tmp_path):
        w._scan_results = [_track()]
        out = w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        assert _playlist_text(out).startswith("#EXTM3U")

    def test_entries_carry_metadata(self, w, tmp_path):
        w._scan_results = [_track(duration=210)]
        out = w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        text = _playlist_text(out)
        assert "#EXTINF:210" in text
        assert "Zivert" in text and "GAZ" in text

    def test_success_is_logged_with_count(self, w, tmp_path):
        w._scan_results = [_track(id=1), _track(id=2)]
        w.export_selected_to_m3u8(str(tmp_path / "p.m3u8"))
        assert any("Экспортирован M3U8" in c[0][0]
                   for c in w.log.call_args_list)

    def test_write_error_is_reported(self, w, tmp_path):
        """Недоступный путь не должен ронять приложение."""
        blocker = tmp_path / "файл-а-не-папка"
        blocker.write_text("я обычный файл", encoding="utf-8")
        w._scan_results = [_track()]
        assert w.export_selected_to_m3u8(str(blocker / "p.m3u8")) is None
        assert any("Ошибка при экспорте" in c[0][0]
                   for c in w.log.call_args_list)


class TestExportDialog:
    """Путь файла берётся из диалога сохранения."""

    def test_cancelled_dialog_returns_none(self, w):
        w._scan_results = [_track()]
        with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                   staticmethod(lambda *a, **kw: ("", ""))):
            assert w.export_selected_to_m3u8() is None

    def test_accepted_dialog_writes_file(self, w, tmp_path):
        target = tmp_path / "chosen.m3u8"
        w._scan_results = [_track()]
        with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                   staticmethod(lambda *a, **kw: (str(target), ""))):
            out = w.export_selected_to_m3u8()
        assert out == str(target)
        assert target.exists()

    def test_default_name_contains_channel_and_date(self, w, tmp_path,
                                                    monkeypatch):
        """Имя по умолчанию должно быть понятным: канал и дата."""
        import config as cfg

        monkeypatch.setattr(cfg, "BASE_PATH", str(tmp_path))
        w._scan_results = [_track()]
        w.channel_input.setText("@akmpool")
        seen = {}

        def _fake_dialog(parent, title, default_name, _filter):
            seen["default"] = default_name
            return ("", "")

        with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                   staticmethod(_fake_dialog)):
            w.export_selected_to_m3u8()

        assert "akmpool" in seen["default"]
        assert ".m3u8" in seen["default"]
        assert str(tmp_path) in seen["default"]

    def test_explicit_path_skips_dialog(self, w, tmp_path):
        """Готовый путь не должен спрашивать пользователя."""
        w._scan_results = [_track()]
        with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName",
                   staticmethod(MagicMock(
                       side_effect=AssertionError("диалог не нужен")))):
            assert w.export_selected_to_m3u8(
                str(tmp_path / "direct.m3u8")) is not None


class TestTreeContextMenu:
    """Контекстное меню дерева."""

    def _menu(self, w, item):
        """Готовит подменённое меню и возвращает список его действий."""
        created = {}

        class _Menu:
            def __init__(self, *a, **kw):
                created["menu"] = self
                self.actions = []
                self.handlers = []

            def setStyleSheet(self, *_a):
                pass

            def addAction(self, text):
                action = MagicMock()
                action.text = text
                self.actions.append(action)
                return action

            def addSeparator(self, *_a):
                return MagicMock()

            def exec(self, *_a):
                return None

        with patch("ui.controllers.tree_controller.QMenu", _Menu):
            w.library_tree.itemAt = MagicMock(return_value=item)
            w._show_tree_context_menu(QPoint(10, 10))
        return created["menu"]

    def _item(self, track_data=None):
        item = MagicMock()
        item.data.return_value = track_data
        return item

    def test_no_item_opens_nothing(self, w):
        w.library_tree.itemAt = MagicMock(return_value=None)
        w._show_tree_context_menu(QPoint(10, 10))   # не должно упасть

    def test_toggle_action_is_present(self, w):
        item = self._item()
        menu = self._menu(w, item)
        texts = [a.text for a in menu.actions]
        assert any("Отметить" in t for t in texts)

    def test_toggle_handler_receives_item(self, w):
        item = self._item()
        w.toggle_item_check_state = MagicMock()
        menu = self._menu(w, item)
        menu.actions[0].triggered.connect.call_args[0][0]()
        w.toggle_item_check_state.assert_called_once_with(item)

    def test_play_action_hidden_for_group_item(self, w):
        """У группы канала нет трека -- предлагать прослушивание незачем."""
        menu = self._menu(w, self._item(track_data=None))
        texts = [a.text for a in menu.actions]
        assert not any("Воспроизвести" in t for t in texts)

    def test_play_action_present_for_track(self, w):
        menu = self._menu(w, self._item(track_data=_track()))
        texts = [a.text for a in menu.actions]
        assert any("Воспроизвести" in t for t in texts)

    def test_export_action_calls_export(self, w):
        menu = self._menu(w, self._item(track_data=_track()))
        w.export_selected_to_m3u8 = MagicMock()
        export_action = menu.actions[-1]
        export_action.triggered.connect.call_args[0][0]()
        w.export_selected_to_m3u8.assert_called_once()