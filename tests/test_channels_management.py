"""Тесты на управление сохранёнными каналами и статистику Bento.

Три независимых сюжета одного модуля:

* контекстное меню списка каналов -- выбор или удаление;
* удаление канала, включая очистку активного поля (DEFECT-016: поле
  хранило имя, которого больше нет в списке);
* счётчики DUP и HQ на главном экране, где HQ считается по реальному
  битрейту, а не по расширению файла.
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QListWidgetItem

import ui.controllers.channels_controller as cc


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
    win._saved_channels = []
    win._refresh_channels_view = MagicMock()
    return win


def _add(win, name):
    item = QListWidgetItem(name)
    item.setData(Qt.ItemDataRole.UserRole, name)
    win.saved_channels_list.addItem(item)
    return item


class TestChannelContextMenu:
    """Контекстное меню сохранённого канала."""

    def _run(self, w, item, chosen):
        created = {}

        class _Menu:
            def __init__(self, *a, **kw):
                self.pick = None
                created["menu"] = self

            def setStyleSheet(self, *_a):
                pass

            def addAction(self, text):
                action = MagicMock()
                action.text = text
                if chosen == "select" and "Выбрать" in text:
                    self.pick = action
                if chosen == "delete" and "Удалить" in text:
                    self.pick = action
                return action

            def exec(self, *_a):
                return self.pick

        w.saved_channels_list.itemAt = MagicMock(return_value=item)
        with patch.object(cc, "QMenu", _Menu):
            w._show_channel_context_menu(QPoint(5, 5))

    def test_no_item_opens_nothing(self, w):
        w.saved_channels_list.itemAt = MagicMock(return_value=None)
        w._on_saved_channel_clicked = MagicMock()
        w._show_channel_context_menu(QPoint(5, 5))
        w._on_saved_channel_clicked.assert_not_called()

    def test_select_opens_library(self, w):
        item = _add(w, "@akmpool")
        w._on_saved_channel_clicked = MagicMock()
        self._run(w, item, "select")
        w._on_saved_channel_clicked.assert_called_once_with(item)

    def test_delete_removes_channel(self, w):
        item = _add(w, "@akmpool")
        w._remove_saved_channel = MagicMock()
        self._run(w, item, "delete")
        w._remove_saved_channel.assert_called_once_with("@akmpool")

    def test_dismiss_changes_nothing(self, w):
        item = _add(w, "@akmpool")
        w._on_saved_channel_clicked = MagicMock()
        w._remove_saved_channel = MagicMock()
        self._run(w, item, None)
        w._on_saved_channel_clicked.assert_not_called()
        w._remove_saved_channel.assert_not_called()


class TestRemoveSavedChannel:
    """Удаление канала из сохранённых."""

    def test_empty_name_is_noop(self, w):
        w._saved_channels = ["@akmpool"]
        w._remove_saved_channel("")
        assert w._saved_channels == ["@akmpool"]

    def test_unknown_channel_is_noop(self, w):
        w._saved_channels = ["@akmpool"]
        w._remove_saved_channel("@другой")
        assert w._saved_channels == ["@akmpool"]

    def test_removed_from_list(self, w):
        w._saved_channels = ["@akmpool", "@primetimedj"]
        w._remove_saved_channel("@akmpool")
        assert w._saved_channels == ["@primetimedj"]
        assert any("удален из сохраненных" in c[0][0]
                   for c in w.log.call_args_list)

    def test_active_channel_field_is_cleared(self, w):
        """DEFECT-016: удалённый канал не должен оставаться в поле ввода."""
        w._saved_channels = ["@akmpool"]
        w.channel_input.setText("@akmpool")
        w._remove_saved_channel("@akmpool")
        assert w.channel_input.text() == ""

    def test_other_channel_field_is_kept(self, w):
        """Чужой канал в поле трогать нельзя."""
        w._saved_channels = ["@akmpool", "@primetimedj"]
        w.channel_input.setText("@primetimedj")
        w._remove_saved_channel("@akmpool")
        assert w.channel_input.text() == "@primetimedj"

    def test_channels_view_refreshed(self, w):
        w._saved_channels = ["@akmpool"]
        w._remove_saved_channel("@akmpool")
        w._refresh_channels_view.assert_called()


class TestPromptAddChannel:
    """Диалог быстрого добавления канала."""

    def _dialog(self, w, entered):
        """Подменяет диалог и отвечает указанным текстом."""
        holder = {}

        class _Dlg:
            def __init__(self, *a, **kw):
                self.code_entered = MagicMock()

            def setWindowTitle(self, *_a):
                pass

            def exec(self):
                holder["signal"] = self.code_entered.connect.call_args[0][0]
                holder["signal"](entered)
                return 1

        with patch.object(cc, "InputCodeDialog", _Dlg):
            w._prompt_add_channel()
        return holder

    def test_bare_name_gets_at_sign(self, w):
        self._dialog(w, "akmpool")
        assert w._saved_channels == ["@akmpool"]
        assert w.channel_input.text() == "@akmpool"

    def test_link_is_kept_as_is(self, w):
        self._dialog(w, "https://t.me/akmpool")
        assert w._saved_channels == ["https://t.me/akmpool"]

    def test_at_name_is_kept(self, w):
        self._dialog(w, "@akmpool")
        assert w._saved_channels == ["@akmpool"]

    def test_whitespace_is_trimmed(self, w):
        self._dialog(w, "   @akmpool   ")
        assert w._saved_channels == ["@akmpool"]

    def test_duplicate_is_not_added_twice(self, w):
        w._saved_channels = ["@akmpool"]
        self._dialog(w, "@akmpool")
        assert w._saved_channels == ["@akmpool"]

    def test_empty_input_changes_nothing(self, w):
        self._dialog(w, "   ")
        assert w._saved_channels == []

    def test_added_channel_is_logged(self, w):
        self._dialog(w, "akmpool")
        assert any("добавлен в сохраненные" in c[0][0]
                   for c in w.log.call_args_list)


class TestHomeStatistics:
    """Счётчики DUP и HQ на главном экране."""

    def _stat(self, w, records):
        import ui.controllers.channels_controller as module
        monkey = patch.object(module, "db_module")
        db = monkey.start()
        db.get_downloads.return_value = records
        try:
            w._refresh_home_view()
        finally:
            monkey.stop()

    def test_duplicate_counter(self, w):
        self._stat(w, [
            {"status": "duplicate"},
            {"status": "completed", "is_duplicate": True},
            {"status": "completed"},
        ])
        assert w.home_dup_val.text() == "2 DUP"

    def test_hq_from_calculated_bitrate(self, w):
        """320 кбит/с считается по размеру и длительности, а не по имени."""
        record = {
            "status": "completed", "filename": "track.mp3",
            "duration": 240, "file_size": 10 * 1024 * 1024,
        }
        self._stat(w, [record])
        assert w.home_hq_val.text() == "1 HQ"

    def test_low_bitrate_is_not_hq(self, w):
        record = {
            "status": "completed", "filename": "track.mp3",
            "duration": 240, "file_size": 2 * 1024 * 1024,
        }
        self._stat(w, [record])
        assert w.home_hq_val.text() == "0 HQ"

    def test_hq_by_name_marker(self, w):
        """Файл без метаданных, но помеченный 320, тоже HQ."""
        self._stat(w, [{
            "status": "completed", "filename": "Artist - Track [320k].mp3",
            "duration": 0, "file_size": 0,
        }])
        assert w.home_hq_val.text() == "1 HQ"

    def test_missing_duration_is_not_counted(self, w):
        """Нулевая длительность не должна делить на ноль."""
        self._stat(w, [{
            "status": "completed", "filename": "a.mp3",
            "duration": None, "file_size": 5_000_000,
        }])
        assert w.home_hq_val.text() == "0 HQ"

    def test_database_failure_does_not_crash(self, w):
        import ui.controllers.channels_controller as module

        with patch.object(module, "db_module") as db:
            db.get_downloads.side_effect = RuntimeError("БД недоступна")
            w._refresh_home_view()   # не должно поднять исключение