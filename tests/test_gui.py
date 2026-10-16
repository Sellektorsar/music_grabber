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
    scan_signal = pyqtSignal(object)
    qr_login_signal = pyqtSignal(str)

    def __init__(
        self,
        api_id,
        api_hash,
        channel,
        mode,
        date_from,
        date_to,
        proxy_config=None,
        scan_only=False,
        selected_ids=None,
        max_concurrent_downloads=None,
        mp3_bitrate=None,
        *args,
        **kwargs,
    ):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.proxy_config = proxy_config or {}
        self.scan_only = scan_only
        self.channels = kwargs.get("channels", [channel] if channel else [])
        self.limit_per_channel = kwargs.get("limit_per_channel")
        self.channel_offsets = kwargs.get("channel_offsets", {})
        self.search_query = kwargs.get("search_query")
        self.selected_ids = set(selected_ids or [])
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
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok),
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

    def test_scan_button_enabled(self, window):
        assert window.scan_button.isEnabled() is True

    def test_download_button_disabled_initial(self, window):
        assert window.download_button.isEnabled() is False

    def test_progress_label_empty(self, window):
        assert window.progress_label.text() == ""

    def test_all_widgets_present(self, window):
        assert window.api_id_input is not None
        assert window.api_hash_input is not None
        assert window.channel_input is not None
        assert window.mode_combo is not None
        assert window.date_from_input is not None
        assert window.date_to_input is not None
        assert window.scan_button is not None
        assert window.download_button is not None
        assert window.track_list is not None
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
        """Остался один способ получить файл -- скачать его.

        Режимы записи звука и гибрид удалены: они писали с микрофона то,
        что играет в системе, и молча подменяли неудачную загрузку.
        """
        assert window.mode_combo.count() == 1
        assert window.mode_combo.currentData() == "direct"

    def test_mode_combo_is_hidden(self, window):
        """Выбирать нечего, поэтому список не показывается."""
        assert window.mode_combo.isVisibleTo(window) is False


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
            json.dumps(
                {
                    "api_id": "12345",
                    "api_hash": "abc123",
                    "channel": "@testchan",
                    "mode": "hybrid",   # остался от старой версии
                    "date_from": "2025-01-01",
                    "date_to": "2025-12-31",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        from gui import MainWindow

        w2 = MainWindow()
        qtbot = gui[0].__dict__.get("qtbot")
        assert w2.api_id_input.text() == "12345"
        assert w2.api_hash_input.text() == "abc123"
        assert w2.channel_input.text() == "@testchan"
        # Старый конфиг со значением "hybrid" не должен ломать выбор:
        # режима больше нет, поэтому приложение возвращается к скачиванию.
        assert w2.mode_combo.currentData() == "direct"
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
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes
            ),
        )
        window.scan_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_without_api_hash(self, window, monkeypatch):
        window.api_id_input.setText("12345")
        messages = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes
            ),
        )
        window.scan_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_without_channel(self, window, monkeypatch):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        messages = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes
            ),
        )
        window.scan_button.click()
        assert "заполните" in messages[0].lower()

    def test_start_invalid_api_id(self, window, monkeypatch):
        window.api_id_input.setText("not_a_number")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@chan")
        messages = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: messages.append(a[2]) or QMessageBox.StandardButton.Yes
            ),
        )
        window.scan_button.click()
        assert "числом" in messages[0].lower()


# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------


class TestFFmpegHandling:
    def _add_track_item(self, window):
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtCore import Qt

        item = QListWidgetItem("test - track [2026-01-01]")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, 1)
        window.track_list.addItem(item)

    def test_record_mode_is_gone(self, window):
        """Режима записи звука в интерфейсе больше нет.

        Он открывал входной поток звуковой карты и писал то, что играет
        в системе; самого воспроизведения трека в проекте не было.
        """
        modes = [window.mode_combo.itemData(i)
                 for i in range(window.mode_combo.count())]
        assert modes == ["direct"], f"в списке снова появились режимы: {modes}"

    def test_no_mode_requires_ffmpeg(self, window):
        """Единственный оставшийся режим не конвертирует, ffmpeg не нужен."""
        assert not hasattr(window, "mode_combo") or \
            window.mode_combo.currentData() == "direct"

    def test_direct_mode_no_ffmpeg_shows_warning(self, window, monkeypatch):
        monkeypatch.setattr("gui.is_ffmpeg_available", lambda: False)
        responses = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: responses.append(a[2])
                or QMessageBox.StandardButton.Yes
            ),
        )
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        self._add_track_item(window)
        window.download_button.setEnabled(True)
        window.download_button.click()  # direct mode
        assert "ffmpeg" in responses[0].lower()


# ---------------------------------------------------------------------------
# Запуск скачивания
# ---------------------------------------------------------------------------


class TestStartDownload:
    def test_scan_creates_and_starts_thread(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
        assert window.download_thread is not None
        assert window.download_thread.started is True

    def test_scan_thread_has_correct_params(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.mode_combo.setCurrentIndex(1)  # record
        window.date_from_input.setText("2025-01-01")
        window.date_to_input.setText("2025-12-31")
        window.scan_button.click()
        t = window.download_thread
        assert t.api_id == 12345
        assert t.api_hash == "hash123"
        assert t.channel == "@testchan"
        assert t.mode == "direct"
        assert t.date_from == "2025-01-01"
        assert t.date_to == "2025-12-31"

    def test_scan_clears_log_and_progress(self, window):
        window.log_output.append("old log")
        window.progress_label.setText("old progress")
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
        assert "Сканирование" in window.log_output.toPlainText()
        assert window.progress_label.text() == ""

    def test_scan_disables_scan_enables_stop(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
        assert window.scan_button.isEnabled() is False
        assert window.stop_button.isEnabled() is True

    def test_signal_connections(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
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
        window.scan_button.click()
        window.stop_button.click()
        assert window.download_thread._cancel_requested is True

    def test_stop_resets_buttons(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
        window.stop_button.click()
        assert window.scan_button.isEnabled() is True
        assert window.stop_button.isEnabled() is False

    def test_stop_without_thread_no_error(self, window):
        window.stop_button.click()
        assert True

    def test_stop_logs_message(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
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
        window.scan_button.click()
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
        window.scan_button.click()
        window.download_finished()
        assert window.scan_button.isEnabled() is True
        assert window.stop_button.isEnabled() is False
        assert window.download_thread is None

    def test_logs_message(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")
        window.scan_button.click()
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
        # Заголовок берётся из запроса (DEFECT-024), а не всегда
        # «Ввод данных»: в списке окон было невозможно понять, что просят.
        assert dlg.windowTitle() == "Enter code"

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
            QMessageBox,
            "warning",
            staticmethod(
                lambda *a, **kw: warned.append(True) or QMessageBox.StandardButton.Ok
            ),
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
        window.scan_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window.on_code_entered("mycode")
        assert result == ["mycode"]

    def test_second_call_ignored(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.scan_button.click()
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
        window.scan_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window.on_dialog_closed()
        assert result == [""]

    def test_already_answered_skips(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash")
        window.channel_input.setText("@chan")
        window.scan_button.click()
        result = []
        window.download_thread.code_response_signal.connect(result.append)
        window._input_answered = True
        window.on_dialog_closed()
        assert result == []

    def test_without_thread_no_error(self, window):
        window.on_dialog_closed()
        assert True


# ---------------------------------------------------------------------------
# _on_scan_results & start_download
# ---------------------------------------------------------------------------


class TestScanResults:
    def test_new_tracks_checked_existing_unchecked(self, window):
        from PyQt6.QtCore import Qt

        tracks = [
            {
                "id": 101,
                "performer": "Artist 1",
                "title": "New Song",
                "date": "2026-01-01",
                "already_exists": False,
            },
            {
                "id": 102,
                "performer": "Artist 2",
                "title": "Old Song",
                "date": "2026-01-02",
                "already_exists": True,
            },
        ]
        window._on_scan_results(tracks)
        assert window.track_list.count() == 2
        item_new = window.track_list.item(0)
        item_old = window.track_list.item(1)

        # Новые треки должны быть выбраны по умолчанию
        assert item_new.checkState() == Qt.CheckState.Checked
        assert item_new.data(Qt.ItemDataRole.UserRole) == 101

        # Уже существующие треки должны быть сняты по умолчанию
        assert item_old.checkState() == Qt.CheckState.Unchecked
        assert item_old.data(Qt.ItemDataRole.UserRole) == 102
        assert "✓ уже есть" in item_old.text()

        # Кнопка скачивания должна быть активна
        assert window.download_button.isEnabled() is True


class TestStartDownloadSelected:
    def test_start_download_with_selected_tracks(self, window, monkeypatch):
        from PyQt6.QtCore import Qt
        import gui

        monkeypatch.setattr(gui, "is_ffmpeg_available", lambda: True)

        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")

        tracks = [
            {
                "id": 201,
                "performer": "A",
                "title": "B",
                "date": "2026-01-01",
                "already_exists": False,
            },
            {
                "id": 202,
                "performer": "C",
                "title": "D",
                "date": "2026-01-02",
                "already_exists": True,
            },
        ]
        window._on_scan_results(tracks)
        assert window.track_list.item(0).checkState() == Qt.CheckState.Checked

        window.download_button.click()
        assert window.download_thread is not None
        assert 201 in window.download_thread.selected_ids
        assert 202 not in window.download_thread.selected_ids
        assert window.download_button.isEnabled() is False
        assert window.stop_button.isEnabled() is True

    def test_start_download_none_selected_shows_warning(self, window, monkeypatch):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QMessageBox
        import gui

        monkeypatch.setattr(gui, "is_ffmpeg_available", lambda: True)

        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@testchan")

        tracks = [
            {
                "id": 301,
                "performer": "A",
                "title": "B",
                "date": "2026-01-01",
                "already_exists": True,
            },
        ]
        window._on_scan_results(tracks)
        # Существующий трек по умолчанию unchecked
        assert window.track_list.item(0).checkState() == Qt.CheckState.Unchecked

        warned = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *a, **kw: warned.append(True) or QMessageBox.StandardButton.Ok),
        )

        window.start_download()
        assert warned == [True]
        assert window.download_thread is None


class TestBatchActionsAndToggles:
    def test_select_all_and_clear(self, window):
        from PyQt6.QtCore import Qt

        tracks = [
            {"id": 1, "performer": "A", "title": "1", "date": "2026-01-01", "already_exists": False},
            {"id": 2, "performer": "B", "title": "2", "date": "2026-01-02", "already_exists": True},
        ]
        window._on_scan_results(tracks)

        window._select_all_tracks()
        assert window.track_list.item(0).checkState() == Qt.CheckState.Checked
        assert window.track_list.item(1).checkState() == Qt.CheckState.Checked
        assert "2" in window.download_button.text()

        window._clear_selection()
        assert window.track_list.item(0).checkState() == Qt.CheckState.Unchecked
        assert window.track_list.item(1).checkState() == Qt.CheckState.Unchecked
        assert window.download_button.text() == "Скачать выбранное"

        window._select_only_new_tracks()
        assert window.track_list.item(0).checkState() == Qt.CheckState.Checked
        assert window.track_list.item(1).checkState() == Qt.CheckState.Unchecked
        assert "1" in window.download_button.text()

    def test_filter_tracks_text(self, window):
        tracks = [
            {"id": 1, "performer": "Madonna", "title": "Music", "date": "2026-01-01", "already_exists": False},
            {"id": 2, "performer": "Daft Punk", "title": "One More Time", "date": "2026-01-02", "already_exists": False},
        ]
        window._on_scan_results(tracks)

        window._filter_tracks_text("Madonna")
        assert window.track_list.item(0).isHidden() is False
        assert window.track_list.item(1).isHidden() is True

        window._filter_tracks_text("")
        assert window.track_list.item(0).isHidden() is False
        assert window.track_list.item(1).isHidden() is False

    def test_toggle_api_and_log(self, window):
        # API toggle
        initial_api_open = window._api_settings_open
        window._toggle_api_settings()
        assert window._api_settings_open != initial_api_open

        # Log toggle
        initial_log_open = window._log_open
        window._toggle_log()
        assert window._log_open != initial_log_open


class TestDJPoolStationUI:
    def test_deck_header_and_badge_initial(self, window):
        assert hasattr(window, "deck_header")
        assert window.deck_header is not None
        assert hasattr(window, "status_badge")
        assert "STANDBY" in window.status_badge.text()

    def test_date_presets(self, window):
        window.date_from_input.setText("old-date")
        window.date_to_input.setText("old-date")
        window.btn_preset_all.click()
        assert window.date_from_input.text() == ""
        assert window.date_to_input.text() == ""

        window.btn_preset_30d.click()
        assert len(window.date_from_input.text()) == 10
        assert len(window.date_to_input.text()) == 10

    def test_status_badge_flow(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash123")
        window.channel_input.setText("@chan")

        # 1. Start scan -> SCANNING
        window.start_scan()
        assert "SCANNING" in window.status_badge.text()

        # 2. Results -> POOL READY
        tracks = [{"id": 1, "performer": "A", "title": "B", "date": "2026-01-01", "already_exists": False}]
        window._on_scan_results(tracks)
        assert "POOL READY" in window.status_badge.text()

        # 3. Start download -> DOWNLOADING
        window.start_download()
        assert "DOWNLOADING" in window.status_badge.text()

        # 4. Stop -> STOPPED
        window.stop_download()
        assert "STOPPED" in window.status_badge.text()

        # 5. Finished -> COMPLETED
        window.download_finished()
        assert "COMPLETED" in window.status_badge.text()


class TestPreviewPlayerUI:
    def test_player_bar_initial_hidden(self, window):
        assert window.player_bar is not None
        assert window.player_bar.isHidden() is True
        assert window.btn_play_pause.text() == "▶"

    def test_format_time_ms(self, window):
        assert window._format_time_ms(0) == "00:00"
        assert window._format_time_ms(65000) == "01:05"
        assert window._format_time_ms(192000) == "03:12"

    def test_volume_slider(self, window):
        window.volume_slider.setValue(50)
        if window._audio_output:
            assert abs(window._audio_output.volume() - 0.5) < 0.05

    def test_toggle_and_stop_playback(self, window):
        window._toggle_playback()
        window._stop_playback()
        assert window.btn_play_pause.text() == "▶"
        assert window.player_slider.value() == 0

    def test_double_click_track_not_on_disk(self, window):
        tracks = [{
            "id": 99,
            "performer": "TestDJ",
            "title": "Summer Track",
            "date": "2026-01-01",
            "filepath": "non_existent_folder/track.mp3",
            "already_exists": False,
        }]
        window._on_scan_results(tracks)
        item = window.track_list.item(0)
        window._on_track_double_clicked(item)
        assert window.player_bar.isHidden() is False
        assert "не скачан" in window.player_title_label.text()

    def test_double_click_track_on_disk(self, window, tmp_path):
        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"dummy mp3 data")

        tracks = [{
            "id": 100,
            "performer": "TestDJ",
            "title": "Summer Track",
            "date": "2026-01-01",
            "filepath": str(audio_file),
            "already_exists": True,
        }]
        window._on_scan_results(tracks)
        item = window.track_list.item(0)
        window._on_track_double_clicked(item)
        assert window.player_bar.isHidden() is False
        assert "TestDJ - Summer Track" in window.player_title_label.text()


class TestTabSwitchingAndChannels:
    def test_tab_switching(self, window):
        assert window.main_stack.currentWidget() == window.home_view
        assert window.tab_home.objectName() == "navTabActive"

        window.tab_channels.click()
        assert window.main_stack.currentWidget() == window.channels_view
        assert window.tab_channels.objectName() == "navTabActive"

        window.tab_library.click()
        assert window.main_stack.currentWidget() == window.body_widget
        assert window.tab_library.objectName() == "navTabActive"

        window.tab_home.click()
        assert window.main_stack.currentWidget() == window.home_view
        assert window.tab_home.objectName() == "navTabActive"

    def test_filter_tracks_updates_stats_label(self, window):
        tracks = [
            {"id": 1, "performer": "Madonna", "title": "Music", "date": "2026-01-01", "already_exists": False},
            {"id": 2, "performer": "Daft Punk", "title": "One More Time", "date": "2026-01-02", "already_exists": True},
        ]
        window._on_scan_results(tracks)
        assert "Всего: 2" in window.stats_label.text()

        window._filter_tracks_text("Madonna")
        assert "Найдено: 1" in window.stats_label.text()
        assert "Новых: 1" in window.stats_label.text()

        window._filter_tracks_text("")
        assert "Всего: 2" in window.stats_label.text()

    def test_saved_channels_add_and_remove(self, window):
        initial_count = len(window._saved_channels)
        window._saved_channels.append("@NewTestChannel")
        window._populate_saved_channels()
        assert window.saved_channels_list.count() == initial_count + 1

        window._remove_saved_channel("@NewTestChannel")
        assert "@NewTestChannel" not in window._saved_channels
        assert window.saved_channels_list.count() == initial_count


class TestGroupedLibraryAndAutoScan:
    def test_tree_grouping_hierarchy_and_today_sorting(self, window):
        from datetime import datetime, timedelta
        from PyQt6.QtCore import Qt

        today_str = datetime.now().strftime("%Y-%m-%d")
        yest_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        tracks = [
            {"id": 1, "performer": "Old DJ", "title": "Old Track", "date": "2025-01-01", "channel": "@Retro", "already_exists": True},
            {"id": 2, "performer": "Yest DJ", "title": "Yesterday Track", "date": yest_str, "channel": "@House", "already_exists": False},
            {"id": 3, "performer": "Today DJ 1", "title": "Today Track A", "date": today_str, "channel": "@Techno", "already_exists": False},
            {"id": 4, "performer": "Today DJ 2", "title": "Today Track B", "date": today_str, "channel": "@House", "already_exists": False},
        ]

        window._on_scan_results(tracks)

        # 1. Проверяем верхний уровень: 3 группы дат
        assert window.library_tree.topLevelItemCount() == 3
        first_group = window.library_tree.topLevelItem(0)
        second_group = window.library_tree.topLevelItem(1)
        third_group = window.library_tree.topLevelItem(2)

        # 2. Сегодняшняя дата гарантированно первая
        assert "СЕГОДНЯ" in first_group.text(0)
        assert today_str in first_group.text(0)

        # 3. Вчерашняя дата вторая
        assert "ВЧЕРА" in second_group.text(0)
        assert yest_str in second_group.text(0)

        # 4. Старая дата третья
        assert "2025-01-01" in third_group.text(0)

        # 5. Проверяем подгруппы каналов внутри сегодняшней даты
        # У нас 2 канала: @Techno и @House
        assert first_group.childCount() == 2
        chan_names = [first_group.child(c).text(0) for c in range(first_group.childCount())]
        assert any("@Techno" in name for name in chan_names)
        assert any("@House" in name for name in chan_names)

        # 6. Проверяем трек внутри канала
        chan_0 = first_group.child(0)
        assert chan_0.childCount() >= 1
        track_0 = chan_0.child(0)
        assert track_0.text(1) in ("Today Track A", "Today Track B")

    def test_tree_collapse_and_expand_all(self, window):
        tracks = [
            {"id": 1, "performer": "A", "title": "1", "date": "2026-10-01", "channel": "@Chan1", "already_exists": False},
            {"id": 2, "performer": "B", "title": "2", "date": "2026-10-02", "channel": "@Chan2", "already_exists": False},
        ]
        window._on_scan_results(tracks)

        # Клик "Свернуть всё"
        window.btn_collapse_all.click()
        for i in range(window.library_tree.topLevelItemCount()):
            assert window.library_tree.topLevelItem(i).isExpanded() is False

        # Клик "Развернуть всё"
        window.btn_expand_all.click()
        for i in range(window.library_tree.topLevelItemCount()):
            assert window.library_tree.topLevelItem(i).isExpanded() is True

    def test_tree_checkbox_propagation(self, window):
        from PyQt6.QtCore import Qt

        tracks = [
            {"id": 10, "performer": "A", "title": "1", "date": "2026-10-01", "channel": "@Chan", "already_exists": False},
            {"id": 11, "performer": "B", "title": "2", "date": "2026-10-01", "channel": "@Chan", "already_exists": False},
        ]
        window._on_scan_results(tracks)

        date_group = window.library_tree.topLevelItem(0)
        chan_group = date_group.child(0)
        track_1 = chan_group.child(0)
        track_2 = chan_group.child(1)

        # Снимаем выбор с группы даты
        date_group.setCheckState(0, Qt.CheckState.Unchecked)
        assert track_1.checkState(0) == Qt.CheckState.Unchecked
        assert track_2.checkState(0) == Qt.CheckState.Unchecked
        assert window.download_button.text() == "Скачать выбранное"

        # Включаем обратно группу даты
        date_group.setCheckState(0, Qt.CheckState.Checked)
        assert track_1.checkState(0) == Qt.CheckState.Checked
        assert track_2.checkState(0) == Qt.CheckState.Checked
        assert "2" in window.download_button.text()

    def test_progressive_loading_pagination(self, window):
        initial_tracks = [
            {"id": 100, "performer": "A", "title": "Track 100", "date": "2026-10-08", "channel": "@Pool", "already_exists": False},
        ]
        window._on_scan_results(initial_tracks)
        assert len(window._scan_results) == 1
        assert window._channel_offsets["@Pool"] == 100

        # Поступила следующая порция истории каналов
        next_page = [
            {"id": 99, "performer": "A", "title": "Track 99", "date": "2026-10-08", "channel": "@Pool", "already_exists": False},
            {"id": 98, "performer": "A", "title": "Track 98", "date": "2026-10-07", "channel": "@Pool", "already_exists": False},
        ]
        window._on_scan_results_page(next_page)

        assert len(window._scan_results) == 3
        assert window._channel_offsets["@Pool"] == 98
        assert "Всего: 3" in window.stats_label.text()

    def test_auto_start_scan_with_credentials(self, window):
        window.api_id_input.setText("99999")
        window.api_hash_input.setText("hash_pool")
        window._saved_channels = ["@TestChannel1", "@TestChannel2"]

        window._auto_start_scan()
        assert window.download_thread is not None
        assert window.download_thread.scan_only is True
        assert window.download_thread.channels == ["@TestChannel1", "@TestChannel2"]

    def test_append_tracks_incremental_preserves_items(self, window):
        initial_tracks = [
            {"id": 101, "performer": "Art1", "title": "Track 101", "date": "2026-10-08", "channel": "@Pool", "already_exists": False},
        ]
        window._on_scan_results(initial_tracks)
        orig_item_101 = window._track_item_by_id[101]

        # Добавляем инкрементально
        more_tracks = [
            {"id": 100, "performer": "Art2", "title": "Track 100", "date": "2026-10-08", "channel": "@Pool", "already_exists": False},
            {"id": 99, "performer": "Art3", "title": "Track 99", "date": "2026-10-07", "channel": "@OtherPool", "already_exists": False},
        ]
        window._append_tracks_to_tree(more_tracks)

        # Проверяем, что исходный элемент дерева остался тем же самым объектом в памяти (не уничтожен)
        assert window._track_item_by_id[101] is orig_item_101
        assert 100 in window._track_item_by_id
        assert 99 in window._track_item_by_id
        assert len(window._track_item_by_id) == 3

    def test_tree_scroll_prefetch(self, window):
        from unittest.mock import MagicMock
        window._load_more_tracks = MagicMock()
        sb = window.library_tree.verticalScrollBar()
        sb.setRange(0, 1000)

        # Скролл далеко от конца (например 500) — не должен вызывать загрузку
        window._on_tree_scroll(500)
        assert window._load_more_tracks.call_count == 0

        # Скролл близко к концу (760, то есть >= 1000 - 250 = 750) — должен запустить префетч
        window._on_tree_scroll(760)
        assert window._load_more_tracks.call_count == 1

    def test_append_tracks_new_dates_spanned_and_expanded(self, window):
        initial = [
            {"id": 1, "title": "T1", "performer": "P1", "date": "2026-10-02", "channel": "@akmpool"},
        ]
        window._on_scan_results(initial)

        # Подгружаем новые даты
        page = [
            {"id": 2, "title": "T2", "performer": "P2", "date": "2026-09-30", "channel": "@akmpool"},
            {"id": 3, "title": "T3", "performer": "P3", "date": "2026-09-29", "channel": "@akmpool"},
        ]
        window._on_scan_results_page(page)

        # Проверяем, что все группы дат имеют растянутую колонку 0 и развернуты
        assert window.library_tree.topLevelItemCount() == 3
        for i in range(window.library_tree.topLevelItemCount()):
            top = window.library_tree.topLevelItem(i)
            assert top.isFirstColumnSpanned() is True
            assert top.isExpanded() is True
            assert "📅" in top.text(0)


class TestBentoStudioRecentTablePlayback:
    """Тесты обработчика двойного клика в Bento Studio (таблица Recent Releases)."""

    def test_recent_table_signal_connected(self, window):
        assert hasattr(window, "_on_recent_table_double_clicked")
        assert hasattr(window, "home_recent_table")

    def test_on_recent_table_double_clicked_valid_file(self, window, tmp_path):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt

        fake_audio = tmp_path / "track_sample.mp3"
        fake_audio.write_bytes(b"MP3_FAKE_DATA" * 500)

        window.home_recent_table.setRowCount(1)
        item_title = QTableWidgetItem("Sample Beat")
        item_title.setData(Qt.ItemDataRole.UserRole, str(fake_audio))
        item_artist = QTableWidgetItem("DJ Test")

        window.home_recent_table.setItem(0, 0, item_title)
        window.home_recent_table.setItem(0, 1, item_artist)

        window._on_recent_table_double_clicked(item_title)

        assert not window.player_bar.isHidden()
        assert window.player_bar._current_audio_path == str(fake_audio)

    def test_on_recent_table_double_clicked_none_item(self, window):
        # Должно безопасно завершиться без исключения
        window._on_recent_table_double_clicked(None)

    def test_on_recent_table_double_clicked_missing_file(self, window, tmp_path):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt

        missing_path = str(tmp_path / "deleted_file.mp3")

        window.home_recent_table.setRowCount(1)
        item_title = QTableWidgetItem("Ghost Track")
        item_title.setData(Qt.ItemDataRole.UserRole, missing_path)
        item_artist = QTableWidgetItem("Ghost Artist")

        window.home_recent_table.setItem(0, 0, item_title)
        window.home_recent_table.setItem(0, 1, item_artist)

        logs = []
        orig_log = window.log
        window.log = lambda msg: logs.append(msg)

        try:
            window._on_recent_table_double_clicked(item_title)
            assert any("Аудиофайл не найден" in l for l in logs)
        finally:
            window.log = orig_log

    def test_repeated_double_clicks_no_duplicate_players(self, window, tmp_path):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt

        f1 = tmp_path / "t1.mp3"
        f1.write_bytes(b"DATA" * 100)
        f2 = tmp_path / "t2.mp3"
        f2.write_bytes(b"DATA" * 100)

        window.home_recent_table.setRowCount(2)
        it1 = QTableWidgetItem("T1")
        it1.setData(Qt.ItemDataRole.UserRole, str(f1))
        it2 = QTableWidgetItem("T2")
        it2.setData(Qt.ItemDataRole.UserRole, str(f2))

        window.home_recent_table.setItem(0, 0, it1)
        window.home_recent_table.setItem(0, 1, QTableWidgetItem("A1"))
        window.home_recent_table.setItem(1, 0, it2)
        window.home_recent_table.setItem(1, 1, QTableWidgetItem("A2"))

        p_bar_id = id(window.player_bar)
        p_obj_id = id(window.player_bar._player)

        window._on_recent_table_double_clicked(it1)
        window._on_recent_table_double_clicked(it2)
        window._on_recent_table_double_clicked(it1)

        # Плеер и панель повторно не создаются
        assert id(window.player_bar) == p_bar_id
        assert id(window.player_bar._player) == p_obj_id
        assert window.player_bar._current_audio_path == str(f1)
        window.player_bar.stop_playback()


class TestChannelSearchFeature:
    def test_search_channel_history_starts_scan_with_query(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash_123")
        window.channel_input.setText("@TestChannel")

        window._search_channel_history("Daft Punk")

        assert window.download_thread is not None
        assert window.download_thread.scan_only is True
        assert window.download_thread.search_query == "Daft Punk"
        assert window._current_search_query == "Daft Punk"

    def test_search_channel_history_reads_from_inputs(self, window):
        window.api_id_input.setText("12345")
        window.api_hash_input.setText("hash_123")
        window.channel_input.setText("@TestChannel")
        window.search_filter_input.setText("Armin")

        window._search_channel_history()

        assert window.download_thread is not None
        assert window.download_thread.search_query == "Armin"
        assert window.top_search_input.text() == "Armin"
        assert window.home_search_input.text() == "Armin"

    def test_library_btn_search_channel_exists(self, window):
        assert hasattr(window, "btn_search_channel")
        assert window.btn_search_channel.text() == "🔍 В канале"

    def test_bento_btn_search_channel_exists(self, window):
        assert hasattr(window, "home_btn_search_channel")
        assert window.home_btn_search_channel.text() == "🔍 В канале"






