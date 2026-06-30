from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
    QComboBox, QVBoxLayout, QHBoxLayout, QMessageBox, QDialog, QDialogButtonBox,
    QCheckBox, QGroupBox, QFormLayout
)
from PyQt6.QtCore import pyqtSignal
from downloader import DownloadThread
from config import load_config, save_config
import shutil
import logging

logger = logging.getLogger(__name__)


def is_ffmpeg_available() -> bool:
    """Проверяет доступность ffmpeg в PATH. Нужен для конвертации в MP3 (pydub)."""
    return shutil.which("ffmpeg") is not None

class InputCodeDialog(QDialog):
    code_entered = pyqtSignal(str)

    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ввод данных")
        self.setModal(True)
        self.resize(400, 120)

        self.label = QLabel(prompt)
        self.label.setStyleSheet("font-weight: bold; font-size: 14px; color: darkblue;")
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Normal)
        self.input.setPlaceholderText("Введите значение...")

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.input)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        self.buttons.accepted.connect(self.on_accept)
        self.buttons.rejected.connect(self.reject)

        logger.info(f"Открыто окно ввода: {prompt}")

    def on_accept(self):
        text = self.input.text().strip()
        if not text:
            QMessageBox.warning(self, "Ошибка", "Пожалуйста, введите значение.")
            logger.warning("Пустой ввод в окне ввода, запрос повторяется")
            return
        logger.info(f"Введено: {text}")
        self.code_entered.emit(text)
        self.accept()


class ProxySettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки прокси")
        self.setModal(True)
        self.resize(400, 300)

        self.enabled_cb = QCheckBox("Использовать прокси")

        self.type_label = QLabel("Тип прокси:")
        self.type_combo = QComboBox()
        self.type_combo.addItem("SOCKS5", "socks5")
        self.type_combo.addItem("HTTP", "http")
        self.type_combo.addItem("MTProto", "mtproto")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.host_label = QLabel("Хост:")
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("127.0.0.1")

        self.port_label = QLabel("Порт:")
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("10808")

        self.username_label = QLabel("Логин (опционально):")
        self.username_input = QLineEdit()

        self.password_label = QLabel("Пароль (опционально):")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self._on_type_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(self.enabled_cb)
        form.addRow(self.type_label, self.type_combo)
        form.addRow(self.host_label, self.host_input)
        form.addRow(self.port_label, self.port_input)
        form.addRow(self.username_label, self.username_input)
        form.addRow(self.password_label, self.password_input)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_type_changed(self):
        is_mtproto = self.type_combo.currentData() == "mtproto"
        self.username_label.setVisible(not is_mtproto)
        self.username_input.setVisible(not is_mtproto)
        self.password_label.setText("Secret" if is_mtproto else "Пароль (опционально):")
        self.password_input.setPlaceholderText("MTProto secret" if is_mtproto else "")
        self.host_label.setText("Хост:" if not is_mtproto else "Хост/URL:")

    def set_proxy_config(self, cfg):
        self.enabled_cb.setChecked(cfg.get("enabled", False))
        idx = self.type_combo.findData(cfg.get("type", "socks5"))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.host_input.setText(cfg.get("host", ""))
        self.port_input.setText(str(cfg.get("port", "")))
        self.username_input.setText(cfg.get("username", ""))
        self.password_input.setText(cfg.get("password", ""))

    def get_proxy_config(self):
        return {
            "enabled": self.enabled_cb.isChecked(),
            "type": self.type_combo.currentData(),
            "host": self.host_input.text().strip(),
            "port": self.port_input.text().strip(),
            "username": self.username_input.text().strip(),
            "password": self.password_input.text().strip(),
        }


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Audio Downloader")

        self.api_id_label = QLabel("API ID:")
        self.api_id_input = QLineEdit()
        self.api_id_input.setToolTip("ID приложения из my.telegram.org/apps")

        self.api_hash_label = QLabel("API Hash:")
        self.api_hash_input = QLineEdit()
        # api_hash — полу-секретные данные, маскируем как пароль
        self.api_hash_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_hash_input.setToolTip("Hash приложения из my.telegram.org/apps")

        self.channel_label = QLabel("Канал (@channelname):")
        self.channel_input = QLineEdit()
        self.channel_input.setToolTip("Username канала или ссылка вида @channelname")

        self.mode_label = QLabel("Режим:")
        self.mode_combo = QComboBox()
        # Подписи на русском для пользователя; техническое значение хранится в UserRole
        # и используется как контракт с recorder.process_message.
        self.mode_combo.addItem("Прямое скачивание", "direct")
        self.mode_combo.addItem("Запись звука", "record")
        self.mode_combo.addItem("Гибрид (прямое, затем запись)", "hybrid")
        self.mode_combo.setToolTip(
            "Прямое скачивание — получает файл с сервера Telegram.\n"
            "Запись звука — записывает аудио через звуковое устройство.\n"
            "Гибрид — сначала пробует прямое скачивание, при неудаче — запись."
        )

        self.date_from_label = QLabel("Дата с (YYYY-MM-DD):")
        self.date_from_input = QLineEdit()
        self.date_from_input.setToolTip("Начальная дата (включительно). Пример: 2025-01-01")

        self.date_to_label = QLabel("Дата по (YYYY-MM-DD):")
        self.date_to_input = QLineEdit()
        self.date_to_input.setToolTip("Конечная дата (включительно). Пример: 2025-12-31")

        self.start_button = QPushButton("Запустить скачивание")
        self.stop_button = QPushButton("Остановить")
        self.stop_button.setEnabled(False)

        # Прогресс-панель
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 12px; color: #333; padding: 4px;")
        self.progress_label.setWordWrap(True)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        layout = QVBoxLayout()
        form_layout = QVBoxLayout()

        for label, widget in [
            (self.api_id_label, self.api_id_input),
            (self.api_hash_label, self.api_hash_input),
            (self.channel_label, self.channel_input),
            (self.mode_label, self.mode_combo),
            (self.date_from_label, self.date_from_input),
            (self.date_to_label, self.date_to_input),
        ]:
            hl = QHBoxLayout()
            hl.addWidget(label)
            hl.addWidget(widget)
            form_layout.addLayout(hl)

        layout.addLayout(form_layout)

        proxy_layout = QHBoxLayout()
        self.proxy_button = QPushButton("Настройки прокси...")
        proxy_layout.addWidget(self.proxy_button)
        layout.addLayout(proxy_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.start_button)
        btn_layout.addWidget(self.stop_button)
        layout.addLayout(btn_layout)

        layout.addWidget(self.progress_label)

        layout.addWidget(self.log_output)

        self.setLayout(layout)

        self.start_button.clicked.connect(self.start_download)
        self.stop_button.clicked.connect(self.stop_download)
        self.proxy_button.clicked.connect(self.open_proxy_settings)

        self._load_settings()

        self.download_thread = None
        self.input_dialog = None
        # Флаг «ответ диалога ввода уже отправлен worker-у» — защита от двойной
        # отправки (баг, когда on_dialog_closed затирал правильный ответ пустой строкой).
        self._input_answered = False
        self._proxy_config = {}

    def _load_settings(self):
        cfg = load_config()
        if cfg.get("api_id"):
            self.api_id_input.setText(cfg["api_id"])
        if cfg.get("api_hash"):
            self.api_hash_input.setText(cfg["api_hash"])
        if cfg.get("channel"):
            self.channel_input.setText(cfg["channel"])
        mode = cfg.get("mode", "direct")
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        if cfg.get("date_from"):
            self.date_from_input.setText(cfg["date_from"])
        if cfg.get("date_to"):
            self.date_to_input.setText(cfg["date_to"])
        self._proxy_config = {
            "enabled": cfg.get("proxy_enabled", False),
            "type": cfg.get("proxy_type", "socks5"),
            "host": cfg.get("proxy_host", ""),
            "port": cfg.get("proxy_port", ""),
            "username": cfg.get("proxy_username", ""),
            "password": cfg.get("proxy_password", ""),
        }

    def log(self, message):
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
        logger.debug(f"GUI log: {message}")

    def open_proxy_settings(self):
        dialog = ProxySettingsDialog(self)
        dialog.set_proxy_config(self._proxy_config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._proxy_config = dialog.get_proxy_config()
            save_config(
                proxy_enabled=self._proxy_config["enabled"],
                proxy_type=self._proxy_config["type"],
                proxy_host=self._proxy_config["host"],
                proxy_port=self._proxy_config["port"],
                proxy_username=self._proxy_config["username"],
                proxy_password=self._proxy_config["password"],
            )
            status = "включён" if self._proxy_config["enabled"] else "выключен"
            self.log(f"Прокси {status}")

    def update_progress(self, data):
        scanned = data.get("total_scanned", 0)
        audio = data.get("audio_found", 0)
        downloaded = data.get("downloaded", 0)
        skipped = data.get("skipped", 0)
        exists = data.get("already_exists", 0)
        eta_sec = data.get("eta_seconds", 0)
        eta_str = f"{int(eta_sec // 60)} мин {int(eta_sec % 60)} сек" if eta_sec > 0 else "—"
        parts = [
            f"Просмотрено: {scanned}",
            f"Аудио: {audio}",
            f"Загружено: {downloaded}",
            f"Пропущено: {skipped}",
            f"Уже есть: {exists}",
            f"ETA: {eta_str}",
        ]
        current = data.get("current_file", "")
        if current:
            parts.append(f"Файл: {current}")
        self.progress_label.setText(" | ".join(parts))
        logger.debug(f"Progress: {data}")

    def start_download(self):
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        channel = self.channel_input.text().strip()
        # Берём техническое значение режима (UserRole), а не отображаемый текст
        mode = self.mode_combo.currentData() or 'direct'
        date_from = self.date_from_input.text().strip() or None
        date_to = self.date_to_input.text().strip() or None

        if not api_id or not api_hash or not channel:
            QMessageBox.warning(self, "Ошибка", "Пожалуйста, заполните API ID, API Hash и канал.")
            return

        try:
            api_id = int(api_id)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "API ID должен быть числом.")
            return

        # Конвертация в MP3 идёт через ffmpeg (вызывается pydub).
        # Для режимов direct/hybrid без ffmpeg сохранение в MP3 невозможно — предупредим.
        if not is_ffmpeg_available():
            if mode == 'record':
                QMessageBox.critical(
                    self, "ffmpeg не найден",
                    "ffmpeg не обнаружен в PATH. Режим записи звука требует ffmpeg "
                    "для конвертации в MP3.\n\nОперация не может быть выполнена."
                )
                return
            reply = QMessageBox.warning(
                self, "ffmpeg не найден",
                "ffmpeg не обнаружен в PATH. Конвертация в MP3 будет недоступна "
                "(скачанные файлы сохранятся в исходном формате).\n\nПродолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        save_config(
            api_id=str(api_id), api_hash=api_hash, channel=channel,
            mode=mode, date_from=self.date_from_input.text().strip(),
            date_to=self.date_to_input.text().strip(),
        )

        self.log_output.clear()
        self.progress_label.clear()
        self.log("Запуск загрузки...")

        self.download_thread = DownloadThread(api_id, api_hash, channel, mode, date_from, date_to, self._proxy_config)
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.request_code_signal.connect(self.show_input_dialog)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_download(self):
        if self.download_thread:
            self.log("Запрос на остановку загрузки...")
            self.download_thread.cancel()
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

    def download_finished(self):
        self.log("Загрузка завершена.")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.download_thread = None

    def closeEvent(self, event):
        self.stop_download()
        event.accept()

    def show_input_dialog(self, prompt):
        logger.debug(f"show_input_dialog called with prompt: {prompt}")
        if self.input_dialog is None:
            self.input_dialog = InputCodeDialog(prompt, self)
            self.input_dialog.code_entered.connect(self.on_code_entered)
            self.input_dialog.finished.connect(self.on_dialog_closed)
            self.input_dialog.show()
            self.input_dialog.raise_()
            self.input_dialog.activateWindow()
        else:
            self.input_dialog.label.setText(prompt)
            self.input_dialog.input.clear()
            self.input_dialog.show()
            self.input_dialog.raise_()
            self.input_dialog.activateWindow()
        # Сбрасываем флаг отправки ответа для нового запроса ввода.
        self._input_answered = False

    def on_code_entered(self, text):
        logger.debug(f"on_code_entered received: {text}")
        # Единая точка отправки ответа worker-у. Флаг защищает от повторной отправки
        # пустой строки в on_dialog_closed, который сработает после закрытия диалога.
        if self._input_answered:
            return
        if self.download_thread and text:
            self._input_answered = True
            self.download_thread.code_response_signal.emit(text)
        if self.input_dialog:
            self.input_dialog.close()

    def on_dialog_closed(self):
        logger.debug("Input dialog closed")
        # Если пользователь закрыл окно НЕ вводя ответа (Esc/X), отправляем пустую строку,
        # чтобы worker не завис в ожидании. Но только если ответ ещё не был отправлен.
        if self._input_answered:
            return
        if self.download_thread:
            self._input_answered = True
            self.download_thread.code_response_signal.emit("")
