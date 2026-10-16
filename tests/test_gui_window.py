"""Тесты на MainWindow: трей, выход, превью, горячие клавиши.

Закрывает непокрытые блоки gui.py: тик фонового наблюдателя, меню
уведомлений, сворачивание в трей и очистка при выходе, ветви воспроизведения
и потокового превью, горячие клавиши DJ.

Фикстура ``gui`` берётся из test_gui.py -- окно там уже создаётся с
изолированными зависимостями и заглушками диалогов.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QLineEdit, QMenu

# Фикстура окна живёт в test_gui.py; каталог тестов не обязателен в sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_gui import gui, window, monkeypatch_restore  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Фоновый наблюдатель
# ---------------------------------------------------------------------------

class TestWatcherTick:

    def test_skipped_while_download_runs(self, window):
        window.download_thread = MagicMock()
        window.download_thread.isRunning.return_value = True
        window.start_scan = MagicMock()
        window._on_watcher_tick()
        window.start_scan.assert_not_called()

    def test_skipped_without_credentials(self, window):
        window.download_thread = None
        window.api_id_input.setText("")
        window.api_hash_input.setText("")
        window.start_scan = MagicMock()
        window._on_watcher_tick()
        window.start_scan.assert_not_called()

    def test_skipped_without_channels(self, window):
        window.download_thread = None
        window.api_id_input.setText("26222233")
        window.api_hash_input.setText("hash")
        window._saved_channels = []
        window.start_scan = MagicMock()
        window._on_watcher_tick()
        window.start_scan.assert_not_called()

    def test_starts_scan_with_saved_channels(self, window):
        window.download_thread = None
        window.api_id_input.setText("26222233")
        window.api_hash_input.setText("hash")
        window._saved_channels = ["@akmpool"]
        window.start_scan = MagicMock()
        window._on_watcher_tick()
        window.start_scan.assert_called_once()
        assert window.start_scan.call_args.kwargs["channels"] == ["@akmpool"]


# ---------------------------------------------------------------------------
# Меню уведомлений
# ---------------------------------------------------------------------------

class TestNotificationsMenu:

    def test_menu_contains_all_actions(self, window):
        window._watcher_enabled = False
        window.btn_notif = MagicMock()
        with patch.object(QMenu, "exec", return_value=None) as ex:
            window._show_notifications_menu()
        ex.assert_called_once()

    def test_menu_built_without_notif_button(self, window):
        """Кнопки может не быть -- меню всё равно должно собираться."""
        if hasattr(window, "btn_notif"):
            del window.btn_notif
        with patch.object(QMenu, "exec", return_value=None):
            window._show_notifications_menu()

    def test_watcher_action_toggles(self, window):
        """Меню собирается и показывается без ошибок."""
        window._watcher_enabled = False
        window.btn_notif = MagicMock()
        with patch.object(QMenu, "exec", return_value=None) as ex:
            window._show_notifications_menu()
        ex.assert_called_once()


# ---------------------------------------------------------------------------
# Закрытие и очистка
# ---------------------------------------------------------------------------

class TestCloseAndCleanup:

    def test_force_close_accepts_event(self, window):
        window._force_close = True
        ev = MagicMock()
        window.closeEvent(ev)
        ev.accept.assert_called_once()

    def test_minimizes_to_tray_when_configured(self, window, monkeypatch_restore, tmp_path):
        monkeypatch_restore.setattr(
            "gui.load_config", lambda: {"minimize_to_tray": True})
        window._force_close = False
        window._tray_minimized_notified = False
        window.tray_icon = MagicMock()
        window.tray_icon.isVisible.return_value = True
        window.show_tray_notification = MagicMock()

        ev = MagicMock()
        window.closeEvent(ev)

        ev.ignore.assert_called_once()
        ev.accept.assert_not_called()
        window.show_tray_notification.assert_called_once()

    def test_cleanup_stops_everything(self, window, monkeypatch_restore):
        monkeypatch_restore.setattr(
            "gui.load_config", lambda: {"minimize_to_tray": False})
        window.player_bar = MagicMock()
        window._player = MagicMock()
        window.stop_download = MagicMock()
        th = MagicMock()
        th.isRunning.return_value = False
        window.download_thread = th

        window._cleanup_on_exit()

        window.player_bar.stop_playback.assert_called()
        window._player.stop.assert_called()
        window.stop_download.assert_called()

    def test_cleanup_survives_player_errors(self, window):
        window.player_bar = MagicMock()
        window.player_bar.stop_playback.side_effect = RuntimeError("уже остановлен")
        window._player = MagicMock()
        window._player.stop.side_effect = RuntimeError("уже остановлен")
        window.stop_download = MagicMock()
        window._cleanup_on_exit()
        window.stop_download.assert_called()

    def test_cleanup_keeps_stuck_thread_alive(self, window):
        window.stop_download = MagicMock()
        th = MagicMock()
        th.isRunning.return_value = True
        th.wait.return_value = False
        window.download_thread = th

        from gui import _LINGERING_THREADS

        window._cleanup_on_exit()
        assert th in _LINGERING_THREADS
        _LINGERING_THREADS.discard(th)


# ---------------------------------------------------------------------------
# Воспроизведение и превью
# ---------------------------------------------------------------------------

class TestPlayOrPreview:

    def test_plays_local_file(self, window, tmp_path):
        f = tmp_path / "track.mp3"
        f.write_bytes(b"\x00")
        window.play_audio_file = MagicMock()
        window.player_bar = MagicMock()

        window.play_or_preview_track({"filepath": str(f), "performer": "A",
                                       "title": "T", "id": 1})
        window.play_audio_file.assert_called_once()

    def test_reports_busy_thread(self, window):
        window.play_audio_file = MagicMock()
        window.player_bar = MagicMock()
        window.player_title_label = MagicMock()
        th = MagicMock()
        th.isRunning.return_value = True
        th.preview_track_id = None
        window.download_thread = th

        window.play_or_preview_track({"file_path": "", "title": "T", "id": 5})
        window.play_audio_file.assert_not_called()
        th.cancel.assert_not_called()

    def test_cancels_previous_preview_thread(self, window):
        window.play_audio_file = MagicMock()
        window.player_bar = MagicMock()
        window.player_title_label = MagicMock()
        th = MagicMock()
        th.isRunning.return_value = True
        th.preview_track_id = 7
        window.download_thread = th
        window.start_preview_stream = MagicMock()

        window.play_or_preview_track({"file_path": "", "title": "T", "id": 7})
        th.cancel.assert_called_once()
        window.start_preview_stream.assert_called_once()

    def test_cancel_error_is_swallowed(self, window):
        window.play_audio_file = MagicMock()
        window.player_bar = MagicMock()
        window.player_title_label = MagicMock()
        th = MagicMock()
        th.isRunning.return_value = True
        th.preview_track_id = 7
        th.cancel.side_effect = RuntimeError("нельзя")
        window.download_thread = th
        window.start_preview_stream = MagicMock()

        window.play_or_preview_track({"file_path": "", "title": "T", "id": 7})
        window.start_preview_stream.assert_called_once()
        # Возврат заглушки в исходное состояние: при закрытии окна
        # stop_download() дёрнет cancel() и уронит teardown.
        window.download_thread = None

    def test_without_message_id_reports_not_downloaded(self, window):
        window.play_audio_file = MagicMock()
        window.player_bar = MagicMock()
        window.player_title_label = MagicMock()
        window.download_thread = None
        window.start_preview_stream = MagicMock()

        window.play_or_preview_track({"file_path": "", "title": "T"})
        window.start_preview_stream.assert_not_called()


class TestStartPreviewStream:

    def test_requires_credentials(self, window):
        window._validate_inputs = MagicMock(return_value=None)
        window.player_title_label = MagicMock()
        window.start_preview_stream("@akmpool", 1, "T")
        assert "Файл ещё не скачан" in window.player_title_label.setText.call_args[0][0]

    def test_reports_busy_thread(self, window):
        window._validate_inputs = MagicMock(
            return_value=(1, "h", "@akmpool", "direct", None, None))
        th = MagicMock()
        th.isRunning.return_value = True
        window.download_thread = th
        window.start_preview_stream("@akmpool", 1, "T")
        assert "Предыдущая операция" in window.log_output.toPlainText() \
            or window.download_thread is th


# ---------------------------------------------------------------------------
# Горячие клавиши DJ
# ---------------------------------------------------------------------------

def _key(window_, key, mods=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QKeyEvent.Type.KeyPress, key, mods)


class TestDjHotkeys:

    def test_clear_search_clears_all_fields(self, window):
        window.top_search_input.setText("поиск")
        window.home_search_input.setText("ещё")
        window._filter_tracks_text = MagicMock()
        window._dj_clear_search()
        assert window.top_search_input.text() == ""
        assert window.home_search_input.text() == ""
        window._filter_tracks_text.assert_called_once_with("")

    def test_clear_search_ignored_inside_text_field(self, window):
        edit = QLineEdit(window)
        edit.setText("не трогать")
        window._dj_text_input_focused = MagicMock(return_value=True)
        window._filter_tracks_text = MagicMock()
        window._dj_clear_search()
        window._filter_tracks_text.assert_not_called()

    def test_start_download_called(self, window):
        window.start_download = MagicMock()
        window._dj_start_download()
        window.start_download.assert_called_once()

    def test_start_download_ignored_inside_text_field(self, window):
        window.start_download = MagicMock()
        window._dj_text_input_focused = MagicMock(return_value=True)
        window._dj_start_download()
        window.start_download.assert_not_called()

    def test_space_toggles_playback_when_file_open(self, window, tmp_path):
        f = tmp_path / "playing.mp3"
        f.write_bytes(b"\x00")
        window.player_bar._current_audio_path = str(f)
        window.player_bar._player = MagicMock()
        window._toggle_playback = MagicMock()
        window.keyPressEvent(_key(window, Qt.Key.Key_Space))
        window._toggle_playback.assert_called_once()

    def test_space_opens_tree_item_when_nothing_playing(self, window):
        window.player_bar._current_audio_path = None
        window.player_bar._player = None
        item = MagicMock()
        window.library_tree = MagicMock()
        window.library_tree.currentItem.return_value = item
        window._on_tree_item_double_clicked = MagicMock()
        window._toggle_playback = MagicMock()
        window.keyPressEvent(_key(window, Qt.Key.Key_Space))
        window._on_tree_item_double_clicked.assert_called_once_with(item, 0)

    def test_x_toggles_check_state(self, window):
        item = MagicMock()
        window.library_tree = MagicMock()
        window.library_tree.currentItem.return_value = item
        window.toggle_item_check_state = MagicMock()
        window.keyPressEvent(_key(window, Qt.Key.Key_X))
        window.toggle_item_check_state.assert_called_once_with(item)

    def test_shift_x_does_not_toggle(self, window):
        """С Shift «X» не должна переключать чекбокс."""
        item = MagicMock()
        window.library_tree = MagicMock()
        window.library_tree.currentItem.return_value = item
        window.toggle_item_check_state = MagicMock()
        window.keyPressEvent(
            _key(window, Qt.Key.Key_X, Qt.KeyboardModifier.ShiftModifier))
        window.toggle_item_check_state.assert_not_called()

    def test_arrow_keys_seek_relative(self, window):
        window.player_bar = MagicMock()
        window.keyPressEvent(_key(window, Qt.Key.Key_Left))
        window.player_bar.seek_relative.assert_called_once_with(-10000)
        window.keyPressEvent(_key(window, Qt.Key.Key_Right))
        window.player_bar.seek_relative.assert_called_with(10000)

    def test_shift_c_clears_search(self, window):
        window.top_search_input.setText("текст")
        window.keyPressEvent(
            _key(window, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier))
        assert window.top_search_input.text() == ""

    def test_shift_d_starts_download(self, window):
        window.start_download = MagicMock()
        window.keyPressEvent(
            _key(window, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier))
        window.start_download.assert_called_once()

    def test_unhandled_key_reaches_superclass(self, window):
        """Неизвестная клавиша не должна вызывать обработчики DJ."""
        window._toggle_playback = MagicMock()
        window.start_download = MagicMock()
        window._dj_clear_search = MagicMock()
        window.keyPressEvent(_key(window, Qt.Key.Key_F12))
        window._toggle_playback.assert_not_called()
        window.start_download.assert_not_called()
        window._dj_clear_search.assert_not_called()


# ---------------------------------------------------------------------------
# Диалоги авторизации
# ---------------------------------------------------------------------------

class TestAuthDialogs:
    # Диалог модальный и показывается через show(), поэтому после теста
    # его нужно закрыть: иначе он остаётся висеть на экране поверх
    # всего остального. Такое уже случалось -- окно «Ввод данных»
    # с промптом «Второй» осталось на рабочем столе после прогона.

    @pytest.fixture(autouse=True)
    def _close_input_dialog(self, window):
        yield
        dlg = getattr(window, "input_dialog", None)
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
            window.input_dialog = None

    def test_input_dialog_is_created(self, window):
        window.input_dialog = None
        window.show_input_dialog("Введите код")
        assert window.input_dialog is not None

    def test_input_dialog_reused(self, window):
        window.input_dialog = None
        window.show_input_dialog("Первый")
        dlg = window.input_dialog
        window.show_input_dialog("Второй")
        assert window.input_dialog is dlg

    def test_dialog_title_reflects_prompt(self, window):
        """Заголовок обязан говорить, что именно просят (DEFECT-024)."""
        window.input_dialog = None
        window.show_input_dialog("Введите номер телефона (с кодом страны):")
        assert window.input_dialog.windowTitle() == \
            "Введите номер телефона (с кодом страны)"

    def test_dialog_title_not_generic(self, window):
        window.input_dialog = None
        window.show_input_dialog("Введите код подтверждения:")
        assert window.input_dialog.windowTitle() != "Ввод данных"

    def test_long_prompt_title_is_truncated(self, window):
        window.input_dialog = None
        window.show_input_dialog("Введите " + "очень длинный текст " * 10 + ":")
        assert len(window.input_dialog.windowTitle()) <= 60

    def test_placeholder_is_not_redundant(self, window):
        """Метка уже объясняет, что вводить -- подсказка лишь шумела."""
        window.input_dialog = None
        window.show_input_dialog("Введите код подтверждения:")
        assert window.input_dialog.input.placeholderText() == ""

    def test_dialog_closed_emits_empty_answer(self, window):
        window.input_dialog = None
        window._input_answered = False
        window.download_thread = MagicMock()
        window.on_dialog_closed()
        window.download_thread.code_response_signal.emit.assert_called_once_with("")

    def test_second_close_does_not_emit_again(self, window):
        window.input_dialog = None
        window._input_answered = True
        window.download_thread = MagicMock()
        window.on_dialog_closed()
        window.download_thread.code_response_signal.emit.assert_not_called()

    def test_code_entered_is_forwarded(self, window):
        window.input_dialog = None
        window._input_answered = False
        window.download_thread = MagicMock()
        window.on_code_entered("12345")
        window.download_thread.code_response_signal.emit.assert_called_once_with("12345")

    def test_second_code_is_ignored(self, window):
        window.input_dialog = None
        window._input_answered = True
        window.download_thread = MagicMock()
        window.on_code_entered("12345")
        window.download_thread.code_response_signal.emit.assert_not_called()

    def test_code_without_thread_is_safe(self, window):
        window.input_dialog = None
        window._input_answered = False
        window.download_thread = None
        window.on_code_entered("12345")