"""Диалоговые окна авторизации и настроек приложения (PyQt6)."""

import io
import shutil
import logging
import qrcode

from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap

from ui.theme import DARK_STYLESHEET

logger = logging.getLogger(__name__)


def is_ffmpeg_available() -> bool:
    """Проверяет доступность ffmpeg в PATH."""
    return shutil.which("ffmpeg") is not None


class InputCodeDialog(QDialog):
    code_entered = pyqtSignal(str)

    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        # Заголовок окна берётся из самого запроса. Раньше он был всегда
        # «Ввод данных», и в списке окон и на панели задач невозможно было
        # понять, просят телефон, код из Telegram или пароль 2FA.
        head = (prompt or "").strip().rstrip(":")
        if len(head) > 60:
            head = head[:57] + "..."
        self.setWindowTitle(head or "Ввод данных")
        self.setStyleSheet(DARK_STYLESHEET)
        self.setModal(True)
        self.resize(400, 130)

        self.label = QLabel(prompt)
        self.label.setStyleSheet("font-weight: 700; font-size: 13px; color: #00E5FF;")
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Normal)
        # Подсказка «Введите значение...» ничего не добавляла к тексту
        # метки над полем и только занимала место.
        self.input.setPlaceholderText("")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setObjectName("primaryButton")

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


class QRCodeDialog(QDialog):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QR-авторизация")
        self.setStyleSheet(DARK_STYLESHEET)
        self.setModal(False)
        self.resize(360, 430)

        qr_img = qrcode.make(url, box_size=6)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())

        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "background-color: #FFFFFF; padding: 12px; border-radius: 8px; border: 2px solid #00E5FF;"
        )

        self.info_label = QLabel(
            "Отсканируйте этот QR-код в Telegram:\n"
            "Настройки → Устройства → Сканировать QR-код\n\n"
            "Окно закроется автоматически после сканирования."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #94A3B8; font-size: 12px;")

        self.close_button = QPushButton("Отмена")
        self.close_button.clicked.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.close_button)
        self.setLayout(layout)

    def reject(self):
        logger.info("QR-диалог закрыт пользователем")
        super().reject()


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

        self.username_label = QLabel("Имя пользователя (опционально):")
        self.username_input = QLineEdit()

        self.password_label = QLabel("Пароль (опционально):")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(self.enabled_cb)
        form.addRow(self.type_label, self.type_combo)
        form.addRow(self.host_label, self.host_input)
        form.addRow(self.port_label, self.port_input)
        form.addRow(self.username_label, self.username_input)
        form.addRow(self.password_label, self.password_input)
        form.addRow(self.buttons)
        self.setLayout(form)

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
