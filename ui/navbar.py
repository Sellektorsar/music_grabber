"""
Header navigation bar builder for Beatstorm Master Deck.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)
from ui.widgets import create_beatstorm_logo_pixmap, create_user_avatar_pixmap


def setup_deck_header(window) -> QFrame:
    """Создает и настраивает верхний навбар BEATSTORM (Master Deck Header)."""
    window.deck_header = QFrame()
    window.deck_header.setObjectName("deckHeader")
    window.deck_header.setFixedHeight(54)
    window.deck_header.setStyleSheet("""
        QFrame#deckHeader {
            background-color: #0A0D15;
            border-bottom: 1px solid #162030;
            border-radius: 0px;
        }
    """)
    header_layout = QHBoxLayout(window.deck_header)
    header_layout.setContentsMargins(16, 4, 16, 4)
    header_layout.setSpacing(16)

    # Логотип и брендинг слева
    logo_layout = QHBoxLayout()
    logo_layout.setSpacing(8)

    logo_icon = QLabel()
    logo_icon.setPixmap(create_beatstorm_logo_pixmap())
    logo_icon.setFixedSize(28, 28)

    title_box = QVBoxLayout()
    title_box.setSpacing(0)
    deck_title = QLabel("BEATSTORM")
    deck_title.setStyleSheet("font-size: 14px; font-weight: 900; color: #FFFFFF; letter-spacing: 1.2px;")
    deck_subtitle = QLabel("DJ Pool Workstation")
    deck_subtitle.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.6px;")
    title_box.addWidget(deck_title)
    title_box.addWidget(deck_subtitle)

    logo_layout.addWidget(logo_icon)
    logo_layout.addLayout(title_box)
    header_layout.addLayout(logo_layout)
    header_layout.addSpacing(16)

    # Навигационные вкладки: Home / Channels / Library
    tabs_layout = QHBoxLayout()
    tabs_layout.setSpacing(4)

    window.tab_home = QPushButton("Bento Studio")
    window.tab_home.setObjectName("navTabActive")
    window.tab_home.setToolTip("Bento Grid Studio — основной воркстейшн DJ пула")
    window.tab_home.clicked.connect(lambda: window.switch_tab("home"))

    window.tab_channels = QPushButton("Channels")
    window.tab_channels.setObjectName("navTab")
    window.tab_channels.setToolTip("Управление сохраненными каналами и пулами")
    window.tab_channels.clicked.connect(lambda: window.switch_tab("channels"))

    window.tab_library = QPushButton("Library")
    window.tab_library.setObjectName("navTab")
    window.tab_library.setToolTip("DJ Библиотека треков и монитор загрузок")
    window.tab_library.clicked.connect(lambda: window.switch_tab("library"))

    tabs_layout.addWidget(window.tab_home)
    tabs_layout.addWidget(window.tab_channels)
    tabs_layout.addWidget(window.tab_library)
    header_layout.addLayout(tabs_layout)
    header_layout.addStretch()

    # Правые элементы навбара: Поиск (pill), Профиль DJ KAiros, Колокольчик, Шестеренка
    right_nav_layout = QHBoxLayout()
    right_nav_layout.setSpacing(10)

    window.top_search_input = QLineEdit()
    window.top_search_input.setPlaceholderText("🔍 Search")
    window.top_search_input.setFixedWidth(160)
    window.top_search_input.setStyleSheet("""
        QLineEdit {
            background-color: #111722;
            border: 1px solid #1C2636;
            border-radius: 13px;
            padding: 4px 12px;
            color: #FFFFFF;
            font-size: 12px;
        }
        QLineEdit:focus {
            border-color: #00D2BE;
        }
    """)
    window.top_search_input.textChanged.connect(window._filter_tracks_text)

    user_widget = QWidget()
    u_layout = QHBoxLayout(user_widget)
    u_layout.setContentsMargins(4, 2, 6, 2)
    u_layout.setSpacing(6)
    u_avatar = QLabel()
    u_avatar.setPixmap(create_user_avatar_pixmap())
    u_avatar.setFixedSize(24, 24)
    u_name = QLabel("DJ KAIros ⌵")
    u_name.setStyleSheet("color: #CBD5E1; font-size: 11px; font-weight: 700;")
    u_layout.addWidget(u_avatar)
    u_layout.addWidget(u_name)

    window.status_badge = QLabel("● STANDBY")
    window.status_badge.setVisible(False)

    window.btn_notif = QPushButton("🔔")
    window.btn_notif.setObjectName("chipButton")
    window.btn_notif.setFixedSize(28, 28)
    window.btn_notif.setToolTip("Уведомления и фоновый мониторинг каналов")
    window.btn_notif.clicked.connect(lambda: window._show_notifications_menu() if hasattr(window, "_show_notifications_menu") else None)

    window.btn_top_settings = QPushButton("⚙")
    window.btn_top_settings.setObjectName("chipButton")
    window.btn_top_settings.setFixedSize(28, 28)
    window.btn_top_settings.setToolTip("Настройки Telegram API")
    window.btn_top_settings.clicked.connect(window._toggle_api_settings)

    right_nav_layout.addWidget(window.top_search_input)
    right_nav_layout.addWidget(user_widget)
    right_nav_layout.addWidget(window.btn_notif)
    right_nav_layout.addWidget(window.btn_top_settings)
    header_layout.addLayout(right_nav_layout)

    return window.deck_header
