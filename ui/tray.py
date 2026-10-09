"""
System Tray & Desktop Notifications module for Beatstorm (BEATSTORM DJ Pool Workstation).
Encapsulates:
- QSystemTrayIcon initialization with BEATSTORM logo;
- Context menu (Show, Hide, Background Watcher toggle, Check updates now, Quit);
- Windows toast / native tray notifications;
- Clean exit handling.
"""

import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from config import load_config
from ui.widgets import create_beatstorm_logo_pixmap

logger = logging.getLogger(__name__)


def setup_system_tray(window) -> QSystemTrayIcon:
    """Инициализирует и настраивает системный трей (QSystemTrayIcon) для главного окна."""
    logo_pixmap = create_beatstorm_logo_pixmap()
    app_icon = QIcon(logo_pixmap)
    window.setWindowIcon(app_icon)

    tray_icon = QSystemTrayIcon(app_icon, window)
    tray_icon.setToolTip("BEATSTORM DJ Pool Workstation")

    # Контекстное меню системного трея
    tray_menu = QMenu()
    tray_menu.setStyleSheet("""
        QMenu {
            background-color: #121620;
            color: #FFFFFF;
            border: 1px solid #1E293B;
            border-radius: 6px;
            padding: 4px;
        }
        QMenu::item {
            padding: 6px 18px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #00D2BE;
            color: #000000;
            font-weight: 600;
        }
        QMenu::separator {
            height: 1px;
            background-color: #1E293B;
            margin: 4px 8px;
        }
    """)

    action_show = QAction("Показать BEATSTORM", window)
    action_show.triggered.connect(window.show_and_activate_window)
    tray_menu.addAction(action_show)

    action_hide = QAction("Скрыть в трей", window)
    action_hide.triggered.connect(window.hide)
    tray_menu.addAction(action_hide)

    tray_menu.addSeparator()

    window.action_tray_watcher = QAction("Фоновый мониторинг каналов", window)
    window.action_tray_watcher.setCheckable(True)
    window.action_tray_watcher.setChecked(bool(getattr(window, "_watcher_enabled", False)))
    window.action_tray_watcher.toggled.connect(window.toggle_background_watcher)
    tray_menu.addAction(window.action_tray_watcher)

    action_check_now = QAction("Проверить обновления сейчас", window)
    action_check_now.triggered.connect(window.check_channel_updates_now)
    tray_menu.addAction(action_check_now)

    tray_menu.addSeparator()

    action_quit = QAction("Выход из BEATSTORM", window)
    action_quit.triggered.connect(window.quit_application)
    tray_menu.addAction(action_quit)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.activated.connect(window._on_tray_activated)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray_icon.show()

    window.tray_icon = tray_icon
    return tray_icon


def show_tray_notification(
    window,
    title: str,
    message: str,
    icon=QSystemTrayIcon.MessageIcon.Information,
    timeout_ms: int = 4000,
):
    """Отправляет нативное уведомление (Windows toast / System Tray Notification)."""
    tray = getattr(window, "tray_icon", None)
    if not tray:
        return

    cfg = load_config()
    if not cfg.get("tray_notifications", True):
        return

    try:
        tray.showMessage(title, message, icon, timeout_ms)
    except Exception as e:
        logger.debug(f"Не удалось отправить уведомление трея: {e}")
