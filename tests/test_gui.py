"""
GUI-тесты для TelegramAudioDownloader.

Все внешние зависимости замоканы:
  - DownloadThread → MockDownloadThread (QObject-заглушка с совместимыми сигналами)
  - is_ffmpeg_available → True (кроме тестов, проверяющих его отсутствие)
  - QMessageBox.warning/critical → возвращают Yes/Ok без показа окна
  - config → пишет/читает во временную директорию
"""

import json
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal, Qt


class MockDownloadThread(QObject):
    """Заглушка DownloadThread с совместимыми pyqtSignal."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    request_code_signal = pyqtSignal(str)
    code_response_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(object)

    def __init__(self, api_id, api_hash, channel, mode, date_from, date_to, proxy_config=None):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.proxy_config = proxy_config or {}
        self._cancel_requested = False
        self.started = False
        self.recorder = None

    def start(self):
        self.started = True

    def cancel(self):
        self._cancel_requested = True
        if self.recorder:
            self.recorder.cancel()


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def gui(qtbot, monkeypatch, tmp_path):
    """Создаёт MainWindow с изолированными зависимостями."""
    config_dir = tmp_path / "telegram_audio"
    config_dir.mkdir()
    monkeypatch.setattr("config.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(config_dir / "config.json"))

    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    _orig_warning = QMessageBox.warning
    _orig_critical = QMessageBox.critical
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)
    )

    monkeypatch.setattr("gui.DownloadThread", MockDownloadThread)

    from gui import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)

    yield window, monkeypatch, tmp_path

    monkeypatch.setattr(QMessageBox, "warning", _orig_warning)
    monkeypatch.setattr(QMessageBox, "critical", _orig_critical)


@pytest.fixture
def window(gui):
    return gui[0]


@pytest.fixture
def monkeypatch_restore(gui):
    return gui[1]


# ---------------------------------------------------------------------------
# Инициализация
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_window_title(self, window):
        assert window.windowTitle() == "Telegram Audio Downloader"

    def test_stop_button_disabled(self, window):
        assert window.stop_button.isEnabled() is False

    def test_start_button_enabled(self, window):
        assert window.start_button.isEnabled() is True

    def test_progress_label_empty(self, window):
        assert window.progress_label.text() == ""

    def test_all_widgets_present(self, window):
        assert window.api_id_input is not None
        assert window.api_hash_input is not None
        assert window.channel_input is not None
        assert window.mode_combo is not None
        assert window.date_from_input is not None
        assert window.date_to_input is not None
        assert window.start_button is not None
        assert window.stop_button is not None
        assert window.log_output is not None
        assert window.progress_label is not None

    def test_api_hash_masked(self, window):
        from PyQt6.QtWidgets import QLineEdit
        assert window.api_hash_input.echoMode() == QLineEdit.EchoMode.Password

    def test_log_output_readonly(self, window):
        assert window.log_output.isReadOnly() is True

    def test_download_thread_none(self, window):
        assert window.download_thread is None

    def test_input_dialog_none(self, window):
        assert window.input_dialog is None

    def test_input_answered_false(self, window):
        assert window._input_answered is False

    def test_mode_combo_items(self, window):
        assert window.mode_combo.count() == 3
        assert window.mode_combo.currentData() == "direct"


# ---------------------------------------------------------------------------
# _load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_empty_config_leaves_fields_empty(self, window):
        assert window.api_id_input.text() == ""
        assert window.api_hash_input.text() == ""
        assert window.channel_input.text() == ""

    def test_load_settings_from_file(self, gui):
        window, monkeypatch, tmp_path = gui
        config_file = tmp_path / "telegram_audio" / "config.json"
        config_file.write_text(
            json.dumps({
                "api_id": "12345",
                "api_hash": "abc123",
                "channel": "@testchan",
                "mode": "hybrid",
                "date_from": "2025-01-01",
                "date_to": "2025-12-31",
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        from gui import MainWindow
        w2 = MainWindow()
        qtbot = gui[0].__dict__.get("qtbot")
        assert w2.api_id_input.text() == "12345"
        assert w2.api_hash_input.text() == "abc123"
        assert w2.channel_input.text() == "@testchan"
        assert w2.mode_combo.currentData() == "hybrid"
        assert w2.date_from_input.text() == "2025-01-01"
        assert w2.date_to_input.text() == "2025-12-31"

    def test_invalid_mode_defaults_to_direct(self, gui):
        window, monkeypatch, tmp_path = gui
        config_file = tmp_path / "telegram_audio" / "config.json"
        config_file.write_text(
            json.dumps({"mode": "invalid_mode"}),
            encoding="utf-8",
        )
        from gui import MainWindow
        w2 = MainWindow()
        assert w2.mode_combo.currentData() == "direct"


# ---------------------------------------------------------------------------
# Валидация полей
# ---------------------------------------------------------------------------

class TestValidation:
    def test_start_without_api_id(self, window, monkeypatch):
        messages = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes)
        )
        window.start_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_without_api_hash(self, window, monkeypatch):
        window.api_id_input.setText("12345")
        messages = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes)
        )
        window.start_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_without_channel(self, window, monkeypatch):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        messages = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes)
        )
        window.start_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_invalid_api_id(self, window, monkeypatch):
        window.api_id_input.setText("not_a_number")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@chan")
        messages = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes)
        )
        window.start_button.click()
        assert "числом" in messages[0].lower()


# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------

class TestFFmpegHandling:
    def test_record_mode_no_ffmpeg_shows_critical(self, window, monkeypatch):
        monkeypatch.setattr("gui.is_ffmpeg_available", lambda: False)
        messages = []
        monkeypatch.setattr(
            QMessageBox, "critical",
            staticmethod(lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Ok)
        )
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.mode_combo.setCurrentIndex(1)  # record
        window.start_button.click()
        assert "ffmpeg" in messages[0].lower()
        assert not hasattr(window, "_thread_started") or not window._thread_started

    def test_direct_mode_no_ffmpeg_shows_warning(self, window, monkeypatch):
        monkeypatch.setattr("gui.is_ffmpeg_available", lambda: False)
        responses = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: responses.append(a[2]) or QMessageBox.StandardButton.Yes)
        )
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.start_button.click()  # direct mode
        assert "ffmpeg" in responses[0].lower()


# ---------------------------------------------------------------------------
# Запуск скачивания
# ---------------------------------------------------------------------------

class TestStartDownload:
    def test_start_creates_and_starts_thread(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        assert window.download_thread is not None
        assert window.download_thread.started is True

    def test_start_thread_has_correct_params(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.mode_combo.setCurrentIndex(1)  # record
        window.date_from_input.setText("2025-01-01")
        window.date_to_input.setText("2025-12-31")
        window.start_button.click()
        t = window.download_thread
        assert t.api_id == 12345
        assert t.api_hash == "hash123"
        assert t.channel == "@testchan"
        assert t.mode == "record"
        assert t.date_from == "2025-01-01"
        assert t.date_to == "2025-12-31"

    def test_start_clears_log_and_progress(self, window):
        window.log_output.append("old log")
        window.progress_label.setText("old progress")
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        assert window.log_output.toPlainText() == "Запуск загрузки..."
        assert window.progress_label.text() == ""

    def test_start_disables_start_enables_stop(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        assert window.start_button.isEnabled() is False
        assert window.stop_button.isEnabled() is True

    def test_signal_connections(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        t = window.download_thread
        assert t.log_signal is not None
        assert t.finished_signal is not None
        assert t.request_code_signal is not None
        assert t.progress_signal is not None


# ---------------------------------------------------------------------------
# Остановка
# ---------------------------------------------------------------------------

class TestStopDownload:
    def test_stop_calls_cancel_on_thread(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        window.stop_button.click()
        assert window.download_thread._cancel_requested is True

    def test_stop_resets_buttons(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        window.stop_button.click()
        assert window.start_button.isEnabled() is True
        assert window.stop_button.isEnabled() is False

    def test_stop_without_thread_no_error(self, window):
        window.stop_button.click()
        assert True

    def test_stop_logs_message(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        window.stop_button.click()
        assert "остановку" in window.log_output.toPlainText().lower()


# ---------------------------------------------------------------------------
# closeEvent
# ---------------------------------------------------------------------------

class TestCloseEvent:
    def test_close_stops_download(self, window):
        from PyQt6.QtGui import QCloseEvent
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        evt = QCloseEvent()
        window.closeEvent(evt)
        assert window.download_thread._cancel_requested is True
        assert evt.isAccepted()

    def test_close_without_thread(self, window):
        from PyQt6.QtGui import QCloseEvent
        evt = QCloseEvent()
        window.closeEvent(evt)
        assert evt.isAccepted()


# ---------------------------------------------------------------------------
# download_finished
# ---------------------------------------------------------------------------

class TestDownloadFinished:
    def test_resets_buttons_and_thread(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        window.download_finished()
        assert window.start_button.isEnabled() is True
        assert window.stop_button.isEnabled() is False
        assert window.download_thread is None

    def test_logs_message(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.start_button.click()
        window.download_finished()
        assert "завершен" in window.log_output.toPlainText().lower()


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

class TestLogging:
    def test_log_appends_text(self, window):
        window.log("test message")
        assert "test message" in window.log_output.toPlainText()

    def test_log_auto_scrolls(self, window):
        for i in range(10):
            window.log(f"line {i}")
        sb = window.log_output.verticalScrollBar()
        assert sb.value() == sb.maximum()


# ---------------------------------------------------------------------------
# Прогресс
# ---------------------------------------------------------------------------

class TestProgress:
    def test_update_progress_shows_stats(self, window):
        data = {
            "total_scanned": 100,
            "audio_found": 50,
            "downloaded": 30,
            "skipped": 5,
            "already_exists": 15,
            "current_file": "",
            "mode": "hybrid",
            "eta_seconds": 120,
        }
        window.update_progress(data)
        text = window.progress_label.text()
        assert "Просмотрено: 100" in text
        assert "Аудио: 50" in text
        assert "Загружено: 30" in text
        assert "Пропущено: 5" in text
        assert "Уже есть: 15" in text
        assert "ETA:" in text

    def test_update_progress_shows_current_file(self, window):
        data = {
            "total_scanned": 10,
            "audio_found": 5,
            "downloaded": 2,
            "skipped": 0,
            "already_exists": 3,
            "current_file": "song.mp3",
            "mode": "direct",
            "eta_seconds": 0,
        }
        window.update_progress(data)
        assert "Файл: song.mp3" in window.progress_label.text()

    def test_update_progress_zero_eta_shows_dash(self, window):
        data = {
            "total_scanned": 0,
            "audio_found": 0,
            "downloaded": 0,
            "skipped": 0,
            "already_exists": 0,
            "current_file": "",
            "mode": "direct",
            "eta_seconds": 0,
        }
        window.update_progress(data)
        assert "ETA: —" in window.progress_label.text()

    def test_update_progress_formats_eta(self, window):
        data = {
            "total_scanned": 100,
            "audio_found": 50,
            "downloaded": 10,
            "skipped": 0,
            "already_exists": 0,
            "current_file": "",
            "mode": "hybrid",
            "eta_seconds": 3661,
        }
        window.update_progress(data)
        assert "ETA: 61 мин 1 сек" in window.progress_label.text()


# ---------------------------------------------------------------------------
# InputCodeDialog
# ---------------------------------------------------------------------------

class TestInputCodeDialog:
    def test_dialog_creation(self, qtbot):
        from gui import InputCodeDialog
        dlg = InputCodeDialog("Enter code:")
        qtbot.addWidget(dlg)
        assert dlg.label.text() == "Enter code:"
        assert dlg.input.text() == ""
        assert dlg.windowTitle() == "Ввод данных"

    def test_accept_with_text_emits_signal(self, qtbot):
        from gui import InputCodeDialog
        dlg = InputCodeDialog("Enter:")
        qtbot.addWidget(dlg)
        result = []
        dlg.code_entered.connect(result.append)
        dlg.input.setText("my_value")
        dlg.on_accept()
        assert result == ["my_value"]

    def test_accept_empty_shows_warning(self, qtbot, monkeypatch):
        from gui import InputCodeDialog
        dlg = InputCodeDialog("Enter:")
        qtbot.addWidget(dlg)
        warned = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: warned.append(True) or QMessageBox.StandardButton.Ok)
        )
        dlg.on_accept()
        assert warned == [True]

    def test_reject_closes_dialog(self, qtbot):
        from gui import InputCodeDialog
        dlg = InputCodeDialog("Enter:")
        qtbot.addWidget(dlg)
        assert dlg.isVisible() is False  # not shown yet by default
        dlg.reject()
        assert dlg.result() == dlg.DialogCode.Rejected

    def test_modal(self, qtbot):
        from gui import InputCodeDialog
        dlg = InputCodeDialog("Enter:")
        qtbot.addWidget(dlg)
        assert dlg.isModal() is True


# ---------------------------------------------------------------------------
# show_input_dialog
# ---------------------------------------------------------------------------

class TestShowInputDialog:
    def test_creates_dialog_on_first_call(self, window):
        assert window.input_dialog is None
        window.show_input_dialog("Enter phone:")
        assert window.input_dialog is not None
        assert window.input_dialog.label.text() == "Enter phone:"

    def test_reuses_dialog_on_second_call(self, window):
        window.show_input_dialog("Enter phone:")
        first = window.input_dialog
        window.show_input_dialog("Enter code:")
        assert window.input_dialog is first
        assert window.input_dialog.label.text() == "Enter code:"

    def test_resets_input_answered(self, window):
        window._input_answered = True
        window.show_input_dialog("Enter:")
        assert window._input_answered is False


# ---------------------------------------------------------------------------
# on_code_entered
# ---------------------------------------------------------------------------

class TestOnCodeEntered:
    def test_sends_code_to_thread(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.start_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window.on_code_entered("mycode")
        assert result == ["mycode"]

    def test_second_call_ignored(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.start_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window.on_code_entered("first")
        window.on_code_entered("second")
        assert result == ["first"]

    def test_without_thread_no_error(self, window):
        window.on_code_entered("test")
        assert True


# ---------------------------------------------------------------------------
# on_dialog_closed
# ---------------------------------------------------------------------------

class TestOnDialogClosed:
    def test_sends_empty_string(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.start_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window.on_dialog_closed()
        assert result == [""]

    def test_already_answered_skips(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.start_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window._input_answered = True
        window.on_dialog_closed()
        assert result == []

    def test_without_thread_no_error(self, window):
        window.on_dialog_closed()
        assert True
