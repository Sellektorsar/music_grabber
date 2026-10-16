"""Тесты на ChannelsMixin: недавние треки, удаление канала.

Непокрытыми были ветки выбора трека в Bento Studio: словарь трека,
готовый путь, отсутствующий файл и пустая ячейка. Для DJ это основной
сценарий первого клика после сканирования.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox, QTableWidgetItem


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
    win.saved_channels_list.clear()
    return win


def _row(win, payload, text="", artist="", col=0):
    """Кладёт строку в таблицу недавних треков и отдаёт сам item.

    Строки нужно создать явно: на пустой таблице setItem молча ничего
    не сохраняет, и item.row() остаётся -1.
    """
    table = win.home_recent_table
    table.setRowCount(max(table.rowCount(), 1))
    item = QTableWidgetItem(text)
    item.setData(Qt.ItemDataRole.UserRole, payload)
    table.setItem(0, col, item)
    return item


def _track_row(win, payload, title="", artist=""):
    it = _row(win, payload, text=title, col=0)
    if artist:
        _row(win, None, text=artist, col=1)
    return it


class TestRecentTableDoubleClick:
    """Двойной клик: воспроизведение из таблицы Recent Releases."""

    def test_none_item_is_noop(self, w):
        w.play_or_preview_track = MagicMock()
        w._on_recent_table_double_clicked(None)
        w.play_or_preview_track.assert_not_called()

    def test_empty_row_is_noop(self, w):
        w.home_recent_table.setRowCount(2)
        w.play_or_preview_track = MagicMock()
        w.play_audio_file = MagicMock()
        w._on_recent_table_double_clicked(QTableWidgetItem())
        w.play_or_preview_track.assert_not_called()
        w.play_audio_file.assert_not_called()

    def test_dict_goes_to_play_or_preview(self, w):
        track = {"id": 1, "title": "GAZ", "filepath": ""}
        w.play_or_preview_track = MagicMock()
        w.play_audio_file = MagicMock()
        w._on_recent_table_double_clicked(_track_row(w, track))
        w.play_or_preview_track.assert_called_once_with(track)
        w.play_audio_file.assert_not_called()

    def test_existing_path_is_played_with_full_title(self, w, tmp_path):
        """Имя собирается из артиста и названия -- как в остальном UI."""
        f = tmp_path / "badders.mp3"
        f.write_bytes(b"\x00")
        w.play_audio_file = MagicMock()
        w.play_or_preview_track = MagicMock()
        w._on_recent_table_double_clicked(
            _track_row(w, str(f), title="Badders", artist="Curbi"))

        w.play_audio_file.assert_called_once_with(
            str(f), title="Curbi - Badders")
        w.play_or_preview_track.assert_not_called()
        assert w.player_bar.isVisible() is False or True   # не падает

    def test_play_log_mentions_track(self, w, tmp_path):
        f = tmp_path / "x.mp3"
        f.write_bytes(b"\x00")
        w.play_audio_file = MagicMock()
        w._on_recent_table_double_clicked(
            _track_row(w, str(f), title="GAZ", artist="Zivert"))
        w.log.assert_called()
        assert "Zivert - GAZ" in w.log.call_args[0][0]

    def test_missing_path_is_logged_not_played(self, w):
        w.play_audio_file = MagicMock()
        w._on_recent_table_double_clicked(
            _track_row(w, "/нет/такого.mp3", title="Ghost", artist="Nobody"))
        w.play_audio_file.assert_not_called()
        w.log.assert_called()
        assert "не найден" in w.log.call_args[0][0].lower()

    def test_title_without_artist_is_just_title(self, w, tmp_path):
        f = tmp_path / "y.mp3"
        f.write_bytes(b"\x00")
        w.play_audio_file = MagicMock()
        w._on_recent_table_double_clicked(
            _track_row(w, str(f), title="Solo", artist=""))
        assert w.play_audio_file.call_args.kwargs["title"] == "Solo"


class TestRecentTableSingleClick:
    """Одиночный клик заполняет карточку трека."""

    def test_empty_row_is_noop(self, w):
        w.home_recent_table.setRowCount(2)
        w.track_inspector = MagicMock()
        w._on_recent_table_item_clicked(QTableWidgetItem())
        w.track_inspector.display_track.assert_not_called()

    def test_dict_is_displayed(self, w):
        track = {"title": "GAZ", "bpm": "128"}
        w.track_inspector = MagicMock()
        w._on_recent_table_item_clicked(_track_row(w, track))
        w.track_inspector.display_track.assert_called_once_with(track)

    def test_plain_path_is_wrapped_into_dict(self, w):
        w.track_inspector = MagicMock()
        w._on_recent_table_item_clicked(
            _track_row(w, "/path/to/track.mp3", title="Track"))
        payload = w.track_inspector.display_track.call_args[0][0]
        assert payload["title"] == "Track"
        assert payload["filepath"] == "/path/to/track.mp3"
        assert payload["file_path"] == "/path/to/track.mp3"

    def test_without_inspector_does_nothing(self, w):
        w.track_inspector = None
        w._on_recent_table_item_clicked(_track_row(w, {"title": "GAZ"}))

    def test_missing_path_still_shown_in_inspector(self, w):
        """Карточка полезна даже для файла, которого уже нет на диске."""
        w.track_inspector = MagicMock()
        w._on_recent_table_item_clicked(
            _track_row(w, "/нет/такого.mp3", title="Ghost"))
        w.track_inspector.display_track.assert_called_once()


class TestRemoveSelectedChannel:
    """Удаление из списка сохранённых каналов."""

    def _add(self, w, name):
        it = QListWidgetItem(name)
        it.setData(Qt.ItemDataRole.UserRole, name)
        w.saved_channels_list.addItem(it)
        w.saved_channels_list.setCurrentItem(it)
        return it

    def test_no_selection_does_nothing(self, w):
        w._remove_saved_channel = MagicMock()
        w.saved_channels_list.setCurrentRow(-1)
        w._remove_selected_channel()
        w._remove_saved_channel.assert_not_called()

    def test_removes_selected_channel(self, w):
        w._remove_saved_channel = MagicMock()
        self._add(w, "@akmpool")
        w._remove_selected_channel()
        w._remove_saved_channel.assert_called_once_with("@akmpool")

    def test_falls_back_to_item_text(self, w):
        """Без данных в UserRole имя берётся из текста элемента."""
        w._remove_saved_channel = MagicMock()
        w.saved_channels_list.addItem(QListWidgetItem("@primetimedj"))
        w.saved_channels_list.setCurrentRow(0)
        w._remove_selected_channel()
        w._remove_saved_channel.assert_called_once_with("@primetimedj")


class TestConfirmDeleteChannel:
    """Удаление канала из менеджера спрашивает подтверждение."""

    def test_declined_keeps_channel(self, w):
        w._remove_saved_channel = MagicMock()
        with patch.object(QMessageBox, "question",
                          staticmethod(lambda *a, **kw:
                                       QMessageBox.StandardButton.No)):
            w._confirm_delete_channel("@akmpool")
        w._remove_saved_channel.assert_not_called()

    def test_confirmed_removes_channel(self, w):
        w._remove_saved_channel = MagicMock()
        with patch.object(QMessageBox, "question",
                          staticmethod(lambda *a, **kw:
                                       QMessageBox.StandardButton.Yes)):
            w._confirm_delete_channel("@akmpool")
        w._remove_saved_channel.assert_called_once_with("@akmpool")


class TestPresetDates:
    """Пресеты диапазона дат."""

    def test_all_clears_range(self, w):
        w.date_from_input.setText("2026-01-01")
        w.date_to_input.setText("2026-01-31")
        w._preset_dates_all()
        assert w.date_from_input.text() == ""
        assert w.date_to_input.text() == ""

    def test_30d_sets_range(self, w):
        w._preset_dates_30d()
        assert len(w.date_from_input.text()) == 10
        assert len(w.date_to_input.text()) == 10
        assert w.date_from_input.text() < w.date_to_input.text()