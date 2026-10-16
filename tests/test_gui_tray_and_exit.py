"""Тесты на трей, авторизацию по QR и выход из приложения.

Это те места, где пользователь теряет управление: значок в трее не
реагирует, окно не выходит на передний план, после закрытия остаётся
висящий поток загрузки. Поэтому проверяется поведение, а не факт вызова:

* клик по трею возвращает окно на передний план и снимает свёрнутость;
* повторный QR-вход закрывает прежнее окно, а не открывает второе;
* выход из приложения гасит плеер и не бросает зависший поток;
* отмена QR-диалога останавливает загрузку.
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QSystemTrayIcon


@pytest.fixture
def w(monkeypatch, tmp_path, qtbot):
    base = tmp_path / "telegram_audio"
    base.mkdir()
    monkeypatch.setattr("config.BASE_PATH", str(base))
    monkeypatch.setattr("config.CONFIG_DIR", str(base))
    monkeypatch.setattr("config.CONFIG_FILE", str(base / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    from gui import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.log = MagicMock()
    win.qr_dialog = None
    win.input_dialog = None
    win.download_thread = None
    return win


class TestTrayActivation:
    """Клик по значку в трею."""

    def test_single_click_activates_window(self, w):
        w.show_and_activate_window = MagicMock()
        w._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        w.show_and_activate_window.assert_called_once()

    def test_double_click_activates_window(self, w):
        w.show_and_activate_window = MagicMock()
        w._on_tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        w.show_and_activate_window.assert_called_once()

    def test_other_reasons_are_ignored(self, w):
        """Клик правой кнопкой открывает меню, а не окно."""
        w.show_and_activate_window = MagicMock()
        w._on_tray_activated(QSystemTrayIcon.ActivationReason.Context)
        w.show_and_activate_window.assert_not_called()

    def test_hidden_window_is_restored(self, w):
        calls = []
        w.show_and_activate_window = MagicMock(
            side_effect=lambda: calls.append("shown"))
        w.hide()
        w._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert calls == ["shown"]


class TestShowAndActivate:
    """Возврат окна на передний план."""

    def test_minimized_state_is_cleared(self, w):
        from PyQt6.QtCore import Qt

        w.showMinimized()
        w.show_and_activate_window()

        assert not w.isMinimized()
        assert Qt.WindowState.WindowMinimized not in w.windowState()


class TestQrDialog:
    """Окно авторизации по QR-коду."""

    def test_dialog_is_created_and_shown(self, w):
        with patch("gui.QRCodeDialog") as dialog_cls:
            dialog = dialog_cls.return_value
            w.show_qr_dialog("https://t.me/qr")
        dialog_cls.assert_called_once()
        dialog.show.assert_called_once()

    def test_repeated_login_replaces_previous_dialog(self, w):
        """Второе окно не должно остаться висеть поверх первого."""
        first = MagicMock()
        second = MagicMock()
        with patch("gui.QRCodeDialog", side_effect=[first, second]):
            w.show_qr_dialog("url-1")
            w.show_qr_dialog("url-2")

        first.close.assert_called_once()
        assert w.qr_dialog is second

    def test_rejection_stops_download(self, w):
        """Отмена авторизации обязана остановить загрузку, а не висеть."""
        dialog = MagicMock()
        w.stop_download = MagicMock()
        with patch("gui.QRCodeDialog", return_value=dialog):
            w.show_qr_dialog("https://t.me/qr")

        dialog.rejected.connect.call_args[0][0]()
        w.stop_download.assert_called_once()

    def test_qr_closes_open_input_dialog(self, w):
        """Два окна ввода кода одновременно сбивают пользователя с толку."""
        dialog = MagicMock()
        input_dialog = MagicMock()
        w.input_dialog = input_dialog
        with patch("gui.QRCodeDialog", return_value=dialog):
            w.show_qr_dialog("https://t.me/qr")
        input_dialog.close.assert_called_once()


class TestCodeEntered:
    """Ответ на запрос кода авторизации."""

    def test_code_is_forwarded_to_thread(self, w):
        w.download_thread = MagicMock()
        w._input_answered = False
        w.on_code_entered("54321")
        w.download_thread.code_response_signal.emit.assert_called_once_with("54321")

    def test_second_code_is_ignored(self, w):
        """Повторный ввод не должен перебивать уже принятый код."""
        w.download_thread = MagicMock()
        w._input_answered = True
        w.on_code_entered("00000")
        w.download_thread.code_response_signal.emit.assert_not_called()

    def test_empty_code_is_ignored(self, w):
        w.download_thread = MagicMock()
        w._input_answered = False
        w.on_code_entered("")
        w.download_thread.code_response_signal.emit.assert_not_called()

    def test_without_thread_is_safe(self, w):
        w.download_thread = None
        w._input_answered = False
        w.on_code_entered("12345")     # не должно упасть


class TestCleanupOnExit:
    """Освобождение ресурсов при выходе."""

    def test_player_is_stopped(self, w):
        w.player_bar = MagicMock()
        w._cleanup_on_exit()
        w.player_bar.stop_playback.assert_called_once()

    def test_broken_player_does_not_block_exit(self, w):
        """Упавший плеер не должен мешать закрытию приложения."""
        w.player_bar = MagicMock()
        w.player_bar.stop_playback.side_effect = RuntimeError("уже остановлен")
        w._cleanup_on_exit()      # не должно поднять исключение

    def test_download_is_stopped(self, w):
        w.stop_download = MagicMock()
        w._cleanup_on_exit()
        w.stop_download.assert_called_once()

    def test_stuck_thread_is_kept_alive(self, w):
        """Поток, который не завершился, нельзя просто отпустить.

        Иначе Qt уничтожит QThread на лету, и приложение упадёт при
        следующей загрузке.
        """
        import gui

        thread = MagicMock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        w.download_thread = thread
        gui._LINGERING_THREADS.clear()

        w._cleanup_on_exit()

        assert thread in gui._LINGERING_THREADS
        thread.finished.connect.assert_called_once()

    def test_finished_thread_is_released(self, w):
        import gui

        thread = MagicMock()
        thread.isRunning.return_value = False
        w.download_thread = thread
        gui._LINGERING_THREADS.clear()

        w._cleanup_on_exit()

        assert thread not in gui._LINGERING_THREADS

    def test_tray_icon_is_hidden(self, w):
        w.tray_icon = MagicMock()
        w._cleanup_on_exit()
        w.tray_icon.hide.assert_called_once()


class TestQuitApplication:
    """Выход из приложения через меню."""

    def test_force_flag_is_set_before_close(self, w):
        """Без флага closeEvent свернёт окно в трей вместо выхода."""
        w._force_close = False
        w.close = MagicMock(side_effect=lambda: None)
        w.quit_application()
        assert w._force_close is True

    def test_window_is_closed(self, w):
        w.close = MagicMock()
        w.quit_application()
        w.close.assert_called_once()


class TestMediaSlots:
    """Слоты плеера: должны переживать пустые значения."""

    def test_state_change_without_media(self, w):
        w._on_media_state_changed(MagicMock())   # не должно упасть

    def test_position_change_without_media(self, w):
        w._on_media_position_changed(MagicMock())

    def test_duration_change_without_media(self, w):
        w._on_media_duration_changed(MagicMock())

    def test_seek_is_delegated_to_player_bar(self, w):
        """Прокрутка шкалы доезжает до плеера, а не теряется в окне."""
        w.player_bar = MagicMock()
        w._on_seek_slider_moved(42)
        w.player_bar._on_seek_slider_moved.assert_called_once_with(42)

    def test_volume_is_delegated_to_player_bar(self, w):
        w.player_bar = MagicMock()
        w._on_volume_changed(50)
        w.player_bar._on_volume_changed.assert_called_once_with(50)