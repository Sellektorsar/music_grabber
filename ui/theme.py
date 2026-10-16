"""Тема оформления и стили BEATSTORM Workstation (PyQt6 QSS)."""

DARK_STYLESHEET = """
QWidget {
    background-color: #07090E;
    color: #E2E8F0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QLabel {
    background-color: transparent;
}

/* Карточки панелей 3-колоночного интерфейса и Bento Grid Studio */
QFrame#panelCard, QFrame#bentoCard {
    background-color: #0B0E17;
    border: 1px solid #162030;
    border-radius: 10px;
}

QGroupBox {
    background-color: #0E131E;
    border: 1px solid #182234;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #00E5FF;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

QLineEdit, QComboBox, QSpinBox {
    background-color: #111622;
    border: 1px solid #1D2738;
    border-radius: 6px;
    padding: 5px 8px;
    color: #FFFFFF;
    font-size: 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #00D2BE;
    background-color: #141C2A;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background-color: #0B0E17;
    border-color: #131A26;
    color: #475569;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #0E131E;
    border: 1px solid #1C2638;
    color: #FFFFFF;
    selection-background-color: #00D2BE;
    selection-color: #07090E;
}

/* Кнопки */
QPushButton {
    background-color: #151B27;
    border: 1px solid #222D40;
    border-radius: 6px;
    padding: 6px 12px;
    color: #E2E8F0;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #1E2738;
    border-color: #2F3E57;
    color: #FFFFFF;
}
QPushButton:pressed {
    background-color: #101520;
}
QPushButton:disabled {
    background-color: #0C1018;
    border-color: #141A26;
    color: #475569;
}

/* Главная акцентная кнопка (Cyberpunk Turquoise / Cyan) */
QPushButton#primaryButton {
    background-color: #00E5FF;
    border: 1px solid #00E5FF;
    color: #050B14;
    font-weight: 700;
    font-size: 13px;
    border-radius: 7px;
}
QPushButton#primaryButton:hover {
    background-color: #33EBFF;
    border-color: #33EBFF;
    color: #000000;
}
QPushButton#primaryButton:pressed {
    background-color: #00B4D8;
    border-color: #00B4D8;
}
QPushButton#primaryButton:disabled {
    background-color: #0E2833;
    border-color: #0E2833;
    color: #1E4E63;
}

/* Вспомогательные кнопки-чипы */
QPushButton#chipButton {
    background-color: #101622;
    border: 1px solid #1B2433;
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 11px;
    color: #94A3B8;
}
QPushButton#chipButton:hover {
    background-color: #182030;
    color: #00D2BE;
    border-color: #00D2BE;
}

/* Навигационные вкладки в верхнем навбаре */
QPushButton#navTab {
    background: transparent;
    border: none;
    border-radius: 0px;
    color: #94A3B8;
    font-size: 13px;
    font-weight: 600;
    padding: 6px 14px;
}
QPushButton#navTab:hover {
    color: #FFFFFF;
}
QPushButton#navTabActive {
    background: transparent;
    border: none;
    border-bottom: 2px solid #00E5FF;
    border-radius: 0px;
    color: #00E5FF;
    font-size: 13px;
    font-weight: 700;
    padding: 6px 14px;
}

/* Списки и таблицы */
QListWidget, QTreeWidget, QTableWidget {
    background-color: #090C14;
    border: 1px solid #151D2B;
    border-radius: 8px;
    outline: none;
    color: #E2E8F0;
}
QListWidget::item, QTreeWidget::item, QTableWidget::item {
    border-bottom: 1px solid #0E1420;
    padding: 4px 6px;
    min-height: 28px;
}
QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: #121825;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #162033;
    color: #00E5FF;
}

/* Заголовки колонок QTreeWidget */
QHeaderView::section {
    background-color: #0B0F18;
    color: #64748B;
    border: none;
    border-bottom: 1px solid #162030;
    padding: 6px 8px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.8px;
}

QCheckBox {
    color: #CBD5E1;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator, QTreeWidget::indicator, QTableWidget::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #233045;
    background-color: #0F1420;
}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover, QTableWidget::indicator:hover {
    border-color: #00D2BE;
}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked, QTableWidget::indicator:checked {
    background-color: #00D2BE;
    border-color: #00D2BE;
    image: url("");
}

QProgressBar {
    background-color: #0C1018;
    border: 1px solid #162030;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #00D2BE;
    border-radius: 2px;
}

QTextEdit#logOutput {
    background-color: #06080D;
    border: 1px solid #141A26;
    border-radius: 6px;
    color: #00E5FF;
    font-family: 'Consolas', 'Cascadia Code', monospace;
    font-size: 10px;
    padding: 4px;
}

QScrollBar:vertical {
    border: none;
    background: #080A10;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #1C2433;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #2A364C;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* =========================================================================
   BENTO GRID STUDIO (Cyberpunk Workstation Palette)
   ========================================================================= */

/* Главные карточки Bento Grid */
QFrame#bentoCard {
    background-color: #0F141F;
    border: 1px solid #1E293B;
    border-radius: 10px;
}
QFrame#bentoCard:hover {
    border-color: #283952;
}

/* Карточки метрик внутри Bento Grid */
QFrame#bentoMetricCard {
    background-color: #131A29;
    border: 1px solid #1E293B;
    border-radius: 8px;
    padding: 8px 10px;
}
QFrame#bentoMetricCard:hover {
    border-color: #00D2BE;
}

/* Заголовки карточек Bento Grid */
QLabel#bentoTitle {
    color: #F8FAFC;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.8px;
}

/* Подзаголовки и второстепенный текст */
QLabel#bentoSubtitle {
    color: #64748B;
    font-size: 11px;
}

/* Бейджи и хоткеи */
QLabel#bentoHotkeysPill {
    background-color: #131A29;
    border: 1px solid #1E293B;
    border-radius: 12px;
    padding: 4px 12px;
    color: #00D2BE;
    font-size: 11px;
    font-weight: 700;
}

/* Кнопки-пилюли Camelot Wheel (обычное состояние) */
QPushButton#bentoKeyPill {
    background-color: #131A29;
    border: 1px solid #1E293B;
    border-radius: 12px;
    padding: 3px 8px;
    color: #94A3B8;
    font-size: 11px;
    font-weight: 600;
    min-width: 28px;
    min-height: 20px;
}
QPushButton#bentoKeyPill:hover {
    background-color: #1E293B;
    border-color: #00D2BE;
    color: #F8FAFC;
}
QPushButton#bentoKeyPill:pressed {
    background-color: #0F141F;
}

/* Активно выбранная тональность Camelot Wheel */
QPushButton#bentoKeyPillActive {
    background-color: #00D2BE;
    border: 1px solid #00D2BE;
    border-radius: 12px;
    padding: 3px 8px;
    color: #07090E;
    font-size: 11px;
    font-weight: 700;
    min-width: 28px;
    min-height: 20px;
}
QPushButton#bentoKeyPillActive:hover {
    background-color: #33EBFF;
    border-color: #33EBFF;
    color: #000000;
}

/* Гармонически совместимые переходы Camelot Wheel (+/-1, Rel Maj/Min) */
QPushButton#bentoKeyPillHarmonic {
    background-color: #162838;
    border: 1px solid #00D2BE;
    border-radius: 12px;
    padding: 3px 8px;
    color: #00D2BE;
    font-size: 11px;
    font-weight: 700;
    min-width: 28px;
    min-height: 20px;
}
QPushButton#bentoKeyPillHarmonic:hover {
    background-color: #00D2BE;
    color: #07090E;
}
"""

