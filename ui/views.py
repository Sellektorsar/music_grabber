import os
import shutil
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QProgressBar,
    QScrollArea,
)

from ui.widgets import SpeedMeterWidget
from ui.bento_widgets import CamelotWheelWidget, TrackInspectorCard
from media_utils import extract_key_meta

logger = logging.getLogger(__name__)


def create_home_view(window) -> QWidget:
    """Создает экран Bento Grid Studio с интерактивными карточками, аналитикой и ID3-редактором."""
    home_widget = QWidget()
    main_vbox = QVBoxLayout(home_widget)
    main_vbox.setContentsMargins(14, 14, 14, 14)
    main_vbox.setSpacing(10)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("background: transparent; border: none;")
    window.home_scroll = scroll

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 4, 0)
    layout.setSpacing(12)

    # ---------------------------------------------------------------------
    # HEADER & DJ HOTKEYS CHEATSHEET PILL
    # ---------------------------------------------------------------------
    header_frame = QFrame()
    header_frame.setObjectName("bentoCard")
    header_layout = QHBoxLayout(header_frame)
    header_layout.setContentsMargins(16, 10, 16, 10)
    header_layout.setSpacing(12)

    title_box = QVBoxLayout()
    title_box.setSpacing(2)
    hero_title = QLabel("🎧 BEATSTORM BENTO STUDIO")
    hero_title.setStyleSheet("font-size: 15px; font-weight: 900; color: #00D2BE; letter-spacing: 1px;")
    hero_subtitle = QLabel("DJ Pool Workstation • Автоматизированный поиск, гармоническое сведение и ID3-студия")
    hero_subtitle.setObjectName("bentoSubtitle")
    title_box.addWidget(hero_title)
    title_box.addWidget(hero_subtitle)
    header_layout.addLayout(title_box)

    header_layout.addStretch()

    # DJ Hotkeys cheatsheet pill
    hotkeys_pill = QLabel("[Space: Play | X: Select | ← →: Seek | Shift+D: DL | Shift+C: Clear]")
    hotkeys_pill.setObjectName("bentoHotkeysPill")
    header_layout.addWidget(hotkeys_pill)

    layout.addWidget(header_frame)

    # ---------------------------------------------------------------------
    # BENTO STUDIO CONTROL & SCANNING TOOLBAR
    # ---------------------------------------------------------------------
    actions_grid = QHBoxLayout()
    actions_grid.setSpacing(8)

    window.bento_channel_input = QLineEdit()
    window.bento_channel_input.setPlaceholderText("✈ Канал: @channel_name или t.me/...")
    window.bento_channel_input.setMinimumWidth(220)
    window.bento_channel_input.setMaximumWidth(320)
    window.bento_channel_input.setMinimumHeight(32)
    window.bento_channel_input.setStyleSheet("""
        QLineEdit {
            background-color: #131A29;
            border: 1px solid #1E293B;
            border-radius: 6px;
            padding: 5px 12px;
            color: #00E5FF;
            font-size: 12px;
            font-weight: 600;
        }
        QLineEdit:focus {
            border-color: #00D2BE;
        }
    """)
    if hasattr(window, "channel_input"):
        window.bento_channel_input.setText(window.channel_input.text())
        window.bento_channel_input.textChanged.connect(window.channel_input.setText)
        window.channel_input.textChanged.connect(window.bento_channel_input.setText)

    btn_scan_now = QPushButton("⚡ Сканировать")
    btn_scan_now.setObjectName("primaryButton")
    btn_scan_now.setMinimumHeight(32)
    btn_scan_now.setStyleSheet("""
        QPushButton {
            background-color: #00E5FF;
            border: 1px solid #00E5FF;
            color: #050B14;
            font-weight: 800;
            border-radius: 6px;
            padding: 4px 14px;
        }
        QPushButton:hover {
            background-color: #33EBFF;
            border-color: #33EBFF;
            color: #000000;
        }
        QPushButton:disabled {
            background-color: #0E2833;
            border-color: #0E2833;
            color: #1E4E63;
        }
    """)
    btn_scan_now.clicked.connect(lambda: window.start_scan() if hasattr(window, "start_scan") else None)

    btn_download_now = QPushButton("📥 Скачать")
    btn_download_now.setObjectName("chipButton")
    btn_download_now.setMinimumHeight(32)
    btn_download_now.setStyleSheet("""
        QPushButton {
            background-color: #0E2B18;
            border: 1px solid #2ECC71;
            color: #2ECC71;
            font-weight: 700;
            border-radius: 6px;
            padding: 4px 12px;
        }
        QPushButton:hover {
            background-color: #2ECC71;
            color: #0A0D15;
        }
        QPushButton:disabled {
            background-color: #0D1714;
            border-color: #163322;
            color: #205A38;
        }
    """)
    btn_download_now.setEnabled(False)
    btn_download_now.clicked.connect(lambda: window.start_download() if hasattr(window, "start_download") else None)

    btn_stop_now = QPushButton("⏹ Стоп")
    btn_stop_now.setObjectName("chipButton")
    btn_stop_now.setMinimumHeight(32)
    btn_stop_now.setStyleSheet("""
        QPushButton {
            background-color: #261214;
            border: 1px solid #5C1D24;
            color: #EF4444;
            font-weight: 700;
            border-radius: 6px;
            padding: 4px 12px;
        }
        QPushButton:hover {
            background-color: #EF4444;
            color: #FFFFFF;
        }
        QPushButton:disabled {
            background-color: #14161F;
            border-color: #1E2433;
            color: #475569;
        }
    """)
    btn_stop_now.setEnabled(False)
    btn_stop_now.clicked.connect(lambda: window.stop_download() if hasattr(window, "stop_download") else None)

    window.bento_btn_scan = btn_scan_now
    window.bento_btn_download = btn_download_now
    window.bento_btn_stop = btn_stop_now

    btn_proxy_now = QPushButton("⚙️ Прокси")
    btn_proxy_now.setObjectName("chipButton")
    btn_proxy_now.setMinimumHeight(32)
    btn_proxy_now.clicked.connect(lambda: window.open_proxy_settings() if hasattr(window, "open_proxy_settings") else None)
    window.bento_btn_proxy = btn_proxy_now

    btn_open_music = QPushButton("📂 Музыка")
    btn_open_music.setObjectName("chipButton")
    btn_open_music.setMinimumHeight(32)
    btn_open_music.clicked.connect(lambda: window.open_download_folder() if hasattr(window, "open_download_folder") else None)
    window.bento_btn_music = btn_open_music

    btn_go_lib = QPushButton("📚 Classic View")
    btn_go_lib.setObjectName("chipButton")
    btn_go_lib.setMinimumHeight(32)
    btn_go_lib.setToolTip("Переключиться в классический 3-колоночный режим")
    btn_go_lib.clicked.connect(lambda: window.switch_tab("library") if hasattr(window, "switch_tab") else None)
    window.bento_btn_classic = btn_go_lib

    actions_grid.addWidget(window.bento_channel_input)
    actions_grid.addWidget(btn_scan_now)
    actions_grid.addWidget(btn_download_now)
    actions_grid.addWidget(btn_stop_now)
    actions_grid.addWidget(btn_proxy_now)
    actions_grid.addWidget(btn_open_music)
    actions_grid.addStretch()
    actions_grid.addWidget(btn_go_lib)
    layout.addLayout(actions_grid)

    # ---------------------------------------------------------------------
    # ROW 1: BENTO CARD 1 & BENTO CARD 2
    # ---------------------------------------------------------------------
    row1_layout = QHBoxLayout()
    row1_layout.setSpacing(12)

    # Bento Card 1: Channel & Analytics Metrics
    card1 = QFrame()
    card1.setObjectName("bentoCard")
    c1_layout = QVBoxLayout(card1)
    c1_layout.setContentsMargins(14, 12, 14, 12)
    c1_layout.setSpacing(8)

    c1_header = QLabel("📊 CHANNEL & ANALYTICS METRICS")
    c1_header.setObjectName("bentoTitle")
    c1_sub = QLabel("Статистика базы данных, хранилища и сессии Telegram")
    c1_sub.setObjectName("bentoSubtitle")
    c1_layout.addWidget(c1_header)
    c1_layout.addWidget(c1_sub)

    # Grid of metric cards (2 columns x 3 rows)
    metrics_grid = QGridLayout()
    metrics_grid.setSpacing(8)

    # 1. Tracks indexed
    m_tracks = QFrame()
    m_tracks.setObjectName("bentoMetricCard")
    mt_layout = QVBoxLayout(m_tracks)
    mt_layout.setContentsMargins(8, 6, 8, 6)
    mt_layout.setSpacing(2)
    mt_lbl = QLabel("ТРЕКИ В ИНДЕКСЕ")
    mt_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_tracks_val = QLabel("0 треков")
    window.home_tracks_val.setStyleSheet("font-size: 17px; font-weight: 800; color: #00E5FF;")
    mt_sub = QLabel("Локальный SQLite")
    mt_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    mt_layout.addWidget(mt_lbl)
    mt_layout.addWidget(window.home_tracks_val)
    mt_layout.addWidget(mt_sub)
    metrics_grid.addWidget(m_tracks, 0, 0)

    # 2. Duplicates count (DUP)
    m_dup = QFrame()
    m_dup.setObjectName("bentoMetricCard")
    md_layout = QVBoxLayout(m_dup)
    md_layout.setContentsMargins(8, 6, 8, 6)
    md_layout.setSpacing(2)
    md_lbl = QLabel("ДУБЛИКАТЫ (DUP)")
    md_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_dup_val = QLabel("0 DUP")
    window.home_dup_val.setStyleSheet("font-size: 17px; font-weight: 800; color: #F59E0B;")
    md_sub = QLabel("Отфильтровано")
    md_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    md_layout.addWidget(md_lbl)
    md_layout.addWidget(window.home_dup_val)
    md_layout.addWidget(md_sub)
    metrics_grid.addWidget(m_dup, 0, 1)

    # 3. HQ 320k count
    m_hq = QFrame()
    m_hq.setObjectName("bentoMetricCard")
    mh_layout = QVBoxLayout(m_hq)
    mh_layout.setContentsMargins(8, 6, 8, 6)
    mh_layout.setSpacing(2)
    mh_lbl = QLabel("HQ 320K АУДИО")
    mh_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_hq_val = QLabel("0 HQ")
    window.home_hq_val.setStyleSheet("font-size: 17px; font-weight: 800; color: #10B981;")
    mh_sub = QLabel("High Bitrate")
    mh_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    mh_layout.addWidget(mh_lbl)
    mh_layout.addWidget(window.home_hq_val)
    mh_layout.addWidget(mh_sub)
    metrics_grid.addWidget(m_hq, 1, 0)

    # 4. Storage disk bar
    m_disk = QFrame()
    m_disk.setObjectName("bentoMetricCard")
    mdisk_layout = QVBoxLayout(m_disk)
    mdisk_layout.setContentsMargins(8, 6, 8, 6)
    mdisk_layout.setSpacing(2)
    mdisk_lbl = QLabel("ХРАНИЛИЩЕ ДИСКА")
    mdisk_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_disk_val = QLabel("— GB свободно")
    window.home_disk_val.setStyleSheet("font-size: 14px; font-weight: 800; color: #38BDF8;")
    window.home_disk_bar = QProgressBar()
    window.home_disk_bar.setFixedHeight(5)
    window.home_disk_bar.setRange(0, 100)
    window.home_disk_bar.setValue(25)
    mdisk_sub = QLabel("Папка: telegram_audio")
    mdisk_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    mdisk_layout.addWidget(mdisk_lbl)
    mdisk_layout.addWidget(window.home_disk_val)
    mdisk_layout.addWidget(window.home_disk_bar)
    mdisk_layout.addWidget(mdisk_sub)
    metrics_grid.addWidget(m_disk, 1, 1)

    # 5. Active channel
    m_chan = QFrame()
    m_chan.setObjectName("bentoMetricCard")
    mc_layout = QVBoxLayout(m_chan)
    mc_layout.setContentsMargins(8, 6, 8, 6)
    mc_layout.setSpacing(2)
    mc_lbl = QLabel("АКТИВНЫЙ КАНАЛ")
    mc_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_chan_val = QLabel("Не выбран")
    window.home_chan_val.setStyleSheet("font-size: 13px; font-weight: 800; color: #00D2BE;")
    mc_sub = QLabel("Готов к сканированию")
    mc_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    mc_layout.addWidget(mc_lbl)
    mc_layout.addWidget(window.home_chan_val)
    mc_layout.addWidget(mc_sub)
    metrics_grid.addWidget(m_chan, 2, 0)

    # 6. Telegram API status
    m_api = QFrame()
    m_api.setObjectName("bentoMetricCard")
    ma_layout = QVBoxLayout(m_api)
    ma_layout.setContentsMargins(8, 6, 8, 6)
    ma_layout.setSpacing(2)
    ma_lbl = QLabel("TELEGRAM СТАТУС")
    ma_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    window.home_api_val = QLabel("● Настроен")
    window.home_api_val.setStyleSheet("font-size: 13px; font-weight: 800; color: #2ECC71;")
    ma_sub = QLabel("MTProto сессия")
    ma_sub.setStyleSheet("font-size: 10px; color: #64748B;")
    ma_layout.addWidget(ma_lbl)
    ma_layout.addWidget(window.home_api_val)
    ma_layout.addWidget(ma_sub)
    metrics_grid.addWidget(m_api, 2, 1)

    c1_layout.addLayout(metrics_grid)
    row1_layout.addWidget(card1, 3)

    # Bento Card 2: Camelot Harmonic Wheel Card
    card2 = QFrame()
    card2.setObjectName("bentoCard")
    c2_layout = QVBoxLayout(card2)
    c2_layout.setContentsMargins(14, 12, 14, 12)
    c2_layout.setSpacing(8)

    c2_header = QLabel("🎵 CAMELOT HARMONIC WHEEL")
    c2_header.setObjectName("bentoTitle")
    c2_sub = QLabel("Интерактивный выбор тональностей и гармоническое сведение")
    c2_sub.setObjectName("bentoSubtitle")
    c2_layout.addWidget(c2_header)
    c2_layout.addWidget(c2_sub)

    window.camelot_wheel = CamelotWheelWidget()
    c2_layout.addWidget(window.camelot_wheel)

    # Label for harmonic mixing status / transition guidance
    window.camelot_status_lbl = QLabel("Нажмите ключ для фильтрации гармонических переходов (±1, Rel Maj/Min)")
    window.camelot_status_lbl.setStyleSheet("font-size: 10px; color: #64748B; font-style: italic;")
    c2_layout.addWidget(window.camelot_status_lbl)

    row1_layout.addWidget(card2, 2)
    layout.addLayout(row1_layout)

    # ---------------------------------------------------------------------
    # ROW 2: BENTO CARD 3 (Live Queue & Streams Card)
    # ---------------------------------------------------------------------
    card3 = QFrame()
    card3.setObjectName("bentoCard")
    c3_layout = QVBoxLayout(card3)
    c3_layout.setContentsMargins(14, 12, 14, 12)
    c3_layout.setSpacing(8)

    c3_top = QHBoxLayout()
    c3_title_box = QVBoxLayout()
    c3_title_box.setSpacing(2)
    c3_header = QLabel("⚡ LIVE QUEUE & STREAMS")
    c3_header.setObjectName("bentoTitle")
    c3_sub = QLabel("Параллельные MTProto потоки и динамический график скорости")
    c3_sub.setObjectName("bentoSubtitle")
    c3_title_box.addWidget(c3_header)
    c3_title_box.addWidget(c3_sub)
    c3_top.addLayout(c3_title_box)
    c3_top.addStretch()

    window.home_speed_lbl = QLabel("0.0 MB/s")
    window.home_speed_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #00D2BE;")
    c3_top.addWidget(window.home_speed_lbl)
    c3_layout.addLayout(c3_top)

    streams_box = QHBoxLayout()
    streams_box.setSpacing(14)

    # Mini graph
    window.home_speed_meter = SpeedMeterWidget()
    window.home_speed_meter.setFixedHeight(48)
    for sp in [0.0, 0.4, 1.2, 2.5, 3.8, 3.2, 4.5, 5.1, 4.8, 3.9, 4.2]:
        window.home_speed_meter.add_speed_point(sp)
    streams_box.addWidget(window.home_speed_meter, 2)

    # Multi-stream progress indicators
    streams_col = QVBoxLayout()
    streams_col.setSpacing(4)

    s1_box = QHBoxLayout()
    s1_lbl = QLabel("● Stream 1:")
    s1_lbl.setStyleSheet("font-size: 10px; color: #94A3B8; font-weight: 600; min-width: 65px;")
    window.home_stream1_bar = QProgressBar()
    window.home_stream1_bar.setFixedHeight(5)
    window.home_stream1_bar.setRange(0, 100)
    window.home_stream1_bar.setValue(100)
    s1_box.addWidget(s1_lbl)
    s1_box.addWidget(window.home_stream1_bar)
    streams_col.addLayout(s1_box)

    s2_box = QHBoxLayout()
    s2_lbl = QLabel("○ Stream 2:")
    s2_lbl.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 600; min-width: 65px;")
    window.home_stream2_bar = QProgressBar()
    window.home_stream2_bar.setFixedHeight(5)
    window.home_stream2_bar.setRange(0, 100)
    window.home_stream2_bar.setValue(0)
    s2_box.addWidget(s2_lbl)
    s2_box.addWidget(window.home_stream2_bar)
    streams_col.addLayout(s2_box)

    s3_box = QHBoxLayout()
    s3_lbl = QLabel("○ Stream 3:")
    s3_lbl.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 600; min-width: 65px;")
    window.home_stream3_bar = QProgressBar()
    window.home_stream3_bar.setFixedHeight(5)
    window.home_stream3_bar.setRange(0, 100)
    window.home_stream3_bar.setValue(0)
    s3_box.addWidget(s3_lbl)
    s3_box.addWidget(window.home_stream3_bar)
    streams_col.addLayout(s3_box)

    streams_box.addLayout(streams_col, 3)
    c3_layout.addLayout(streams_box)

    # Overall queue progress bar
    window.home_queue_progress = QProgressBar()
    window.home_queue_progress.setFixedHeight(4)
    window.home_queue_progress.setRange(0, 100)
    window.home_queue_progress.setValue(0)
    c3_layout.addWidget(window.home_queue_progress)

    layout.addWidget(card3)

    # ---------------------------------------------------------------------
    # ROW 3: BENTO CARD 4 & BENTO CARD 5
    # ---------------------------------------------------------------------
    row3_layout = QHBoxLayout()
    row3_layout.setSpacing(12)

    # Bento Card 4: Main Track Pool / Library Grid
    card4 = QFrame()
    card4.setObjectName("bentoCard")
    c4_layout = QVBoxLayout(card4)
    c4_layout.setContentsMargins(14, 12, 14, 12)
    c4_layout.setSpacing(8)

    c4_header = QLabel("🎼 MAIN TRACK POOL & RECENT RELEASES")
    c4_header.setObjectName("bentoTitle")
    c4_sub = QLabel("Недавно скачанные треки • Быстрый поиск и предпрослушивание")
    c4_sub.setObjectName("bentoSubtitle")
    c4_layout.addWidget(c4_header)
    c4_layout.addWidget(c4_sub)

    # Controls: Search bar + Inline Play button
    search_row = QHBoxLayout()
    search_row.setSpacing(8)

    window.home_search_input = QLineEdit()
    window.home_search_input.setPlaceholderText("🔍 Поиск трека, артиста (Enter — искать в канале)...")
    window.home_search_input.setClearButtonEnabled(True)
    window.home_search_input.setStyleSheet("""
        QLineEdit {
            background-color: #131A29;
            border: 1px solid #1E293B;
            border-radius: 6px;
            padding: 5px 10px;
            color: #F8FAFC;
            font-size: 12px;
        }
        QLineEdit:focus {
            border-color: #00D2BE;
        }
    """)
    if hasattr(window, "_search_channel_history"):
        window.home_search_input.returnPressed.connect(window._search_channel_history)

    window.home_btn_search_channel = QPushButton("🔍 В канале")
    window.home_btn_search_channel.setObjectName("secondaryButton")
    window.home_btn_search_channel.setToolTip("Глобальный поиск по всей истории Telegram-канала")
    window.home_btn_search_channel.setFixedHeight(28)
    if hasattr(window, "_search_channel_history"):
        window.home_btn_search_channel.clicked.connect(window._search_channel_history)

    window.home_btn_play_selected = QPushButton("▶ Play / Preview")
    window.home_btn_play_selected.setObjectName("primaryButton")
    window.home_btn_play_selected.setFixedHeight(28)
    search_row.addWidget(window.home_search_input, 1)
    search_row.addWidget(window.home_btn_search_channel)
    search_row.addWidget(window.home_btn_play_selected)
    c4_layout.addLayout(search_row)

    # Main Recent Table
    window.home_recent_table = QTableWidget()
    window.home_recent_table.setColumnCount(4)
    window.home_recent_table.setHorizontalHeaderLabels(["ТРЕК", "АРТИСТ", "КАНАЛ", "ФАЙЛ"])
    window.home_recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    window.home_recent_table.setColumnWidth(0, 200)
    window.home_recent_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
    window.home_recent_table.setColumnWidth(1, 140)
    window.home_recent_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
    window.home_recent_table.setColumnWidth(2, 120)
    window.home_recent_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    window.home_recent_table.verticalHeader().setVisible(False)
    window.home_recent_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.home_recent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    window.home_recent_table.setMinimumHeight(260)
    if hasattr(window, "_on_recent_table_double_clicked"):
        window.home_recent_table.itemDoubleClicked.connect(window._on_recent_table_double_clicked)
    if hasattr(window, "_on_recent_table_item_clicked"):
        window.home_recent_table.itemClicked.connect(window._on_recent_table_item_clicked)
    if hasattr(window, "_on_recent_table_item_changed"):
        window.home_recent_table.itemChanged.connect(window._on_recent_table_item_changed)
    c4_layout.addWidget(window.home_recent_table, 1)

    row3_layout.addWidget(card4, 3)

    # Bento Card 5: Track Inspector & ID3 Tag Editor
    window.track_inspector = TrackInspectorCard()
    window.track_inspector.setMinimumWidth(320)
    row3_layout.addWidget(window.track_inspector, 2)

    layout.addLayout(row3_layout)

    # ---------------------------------------------------------------------
    # INTERACTIVITY & FILTER CONNECTIONS
    # ---------------------------------------------------------------------
    # 1. Text Search Filter in Recent Table
    def _on_search_text_changed(text: str):
        query = text.strip().lower()
        table = window.home_recent_table
        for row in range(table.rowCount()):
            t_item = table.item(row, 0)
            a_item = table.item(row, 1)
            c_item = table.item(row, 2)
            f_item = table.item(row, 3)
            row_txt = " ".join([
                t_item.text() if t_item else "",
                a_item.text() if a_item else "",
                c_item.text() if c_item else "",
                f_item.text() if f_item else "",
            ]).lower()
            table.setRowHidden(row, query not in row_txt)

    window.home_search_input.textChanged.connect(_on_search_text_changed)

    # 2. Inline Play / Preview Button
    def _play_selected_track():
        table = window.home_recent_table
        selected = table.selectedItems()
        if not selected and table.rowCount() > 0:
            table.selectRow(0)
            selected = table.selectedItems()
        if selected:
            row = selected[0].row()
            t_item = table.item(row, 0)
            if t_item and hasattr(window, "_on_recent_table_double_clicked"):
                window._on_recent_table_double_clicked(t_item)

    window.home_btn_play_selected.clicked.connect(_play_selected_track)

    # 3. Camelot Harmonic Filtering Connection
    def _on_camelot_key_selected(key: str):
        compatible = window.camelot_wheel.get_compatible_keys(key)
        all_matches = set([key.upper()] + [k.upper() for k in compatible])
        window.camelot_status_lbl.setText(
            f"Ключ: {key} • Гармонические переходы: {', '.join(compatible)}"
        )
        table = window.home_recent_table
        for row in range(table.rowCount()):
            t_item = table.item(row, 0)
            a_item = table.item(row, 1)
            title = t_item.text() if t_item else ""
            artist = a_item.text() if a_item else ""
            t_key = extract_key_meta(title, artist)
            if t_key and t_key != "—":
                table.setRowHidden(row, t_key.upper() not in all_matches)
            else:
                combined = f"{artist} {title}".upper()
                matched = any(k in combined for k in all_matches)
                table.setRowHidden(row, not matched)
        if hasattr(window, "_apply_harmonic_filter") and callable(window._apply_harmonic_filter):
            window._apply_harmonic_filter(key)
        if hasattr(window, "log") and callable(window.log):
            window.log(f"Фильтр Camelot: {key} (совместимы: {', '.join(compatible)})")

    def _on_camelot_key_cleared():
        window.camelot_status_lbl.setText(
            "Нажмите ключ для фильтрации гармонических переходов (±1, Rel Maj/Min)"
        )
        table = window.home_recent_table
        for row in range(table.rowCount()):
            table.setRowHidden(row, False)
        if hasattr(window, "_apply_harmonic_filter") and callable(window._apply_harmonic_filter):
            window._apply_harmonic_filter(None)

    window.camelot_wheel.key_selected.connect(_on_camelot_key_selected)
    window.camelot_wheel.key_cleared.connect(_on_camelot_key_cleared)

    # 4. Connecting Table Selection to Track Inspector
    def _on_recent_row_selected():
        table = window.home_recent_table
        selected = table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        t_item = table.item(row, 0)
        a_item = table.item(row, 1)
        c_item = table.item(row, 2)
        f_item = table.item(row, 3)
        fpath = t_item.data(Qt.ItemDataRole.UserRole) if t_item else ""
        track_dict = {
            "title": t_item.text() if t_item else "",
            "artist": a_item.text() if a_item else "",
            "performer": a_item.text() if a_item else "",
            "channel": c_item.text() if c_item else "",
            "channel_id": c_item.text() if c_item else "",
            "filename": f_item.text() if f_item else "",
            "file_path": fpath,
        }
        window.track_inspector.display_track(track_dict)

    window.home_recent_table.itemSelectionChanged.connect(_on_recent_row_selected)

    def _on_inspector_tags_saved(saved_dict: dict):
        table = window.home_recent_table
        selected = table.selectedItems()
        if selected:
            row = selected[0].row()
            if table.item(row, 0):
                table.item(row, 0).setText(saved_dict.get("title", ""))
            if table.item(row, 1):
                table.item(row, 1).setText(saved_dict.get("artist", ""))
        artist = saved_dict.get("artist", "")
        title = saved_dict.get("title", "")
        if hasattr(window, "log"):
            window.log(f"💾 ID3 теги успешно сохранены: {artist} - {title}")

    window.track_inspector.tags_saved.connect(_on_inspector_tags_saved)

    # ---------------------------------------------------------------------
    # INITIAL DATA REFRESH (Graceful DB Load)
    # ---------------------------------------------------------------------
    try:
        import database
        cnt = database.get_download_count()
        window.home_tracks_val.setText(f"{cnt} треков")

        window.home_recent_table.blockSignals(True)
        records = database.get_downloads(limit=15)
        window.home_recent_table.setRowCount(len(records))
        for row_idx, r in enumerate(records):
            t_item = QTableWidgetItem(r.get("title") or "—")
            t_item.setData(Qt.ItemDataRole.UserRole, r)
            t_item.setCheckState(Qt.CheckState.Unchecked)
            a_item = QTableWidgetItem(r.get("performer") or r.get("artist") or "—")
            c_item = QTableWidgetItem(r.get("channel_id") or "—")
            f_item = QTableWidgetItem(r.get("filename") or "—")
            for it in (t_item, a_item, c_item, f_item):
                it.setForeground(QColor("#CBD5E1"))
            window.home_recent_table.setItem(row_idx, 0, t_item)
            window.home_recent_table.setItem(row_idx, 1, a_item)
            window.home_recent_table.setItem(row_idx, 2, c_item)
            window.home_recent_table.setItem(row_idx, 3, f_item)

        if len(records) > 0:
            window.home_recent_table.selectRow(0)
        window.home_recent_table.blockSignals(False)

        all_recs = database.get_downloads(limit=100)
        dups = sum(1 for r in all_recs if r.get("status") == "duplicate" or r.get("is_duplicate"))
        window.home_dup_val.setText(f"{dups} DUP")

        hq_cnt = 0
        for r in all_recs:
            dur = r.get("duration") or 0
            sz = r.get("file_size") or 0
            if dur > 0 and (sz * 8 / dur) >= 280000:
                hq_cnt += 1
            elif "320" in (r.get("filename") or "") or "320" in (r.get("title") or ""):
                hq_cnt += 1
        window.home_hq_val.setText(f"{hq_cnt} HQ")
    except Exception as e:
        logger.debug(f"Начальная загрузка метрик Bento: {e}")

    try:
        # Путь берётся от BASE_PATH: относительный "telegram_audio" при
        # запуске из ярлыка не существует, и метрики диска молча остались
        # бы незаполненными.
        from config import BASE_PATH
        total, used, free = shutil.disk_usage(BASE_PATH)
        free_gb = free / (1024 ** 3)
        window.home_disk_val.setText(f"{free_gb:.1f} GB свободно")
        pct = int((used / total) * 100) if total > 0 else 0
        window.home_disk_bar.setValue(pct)
    except Exception:
        pass

    scroll.setWidget(container)
    main_vbox.addWidget(scroll)
    return home_widget



def create_channels_view(window) -> QWidget:
    """Создает экран Channels Manager для удобного управления сохраненными каналами."""
    chan_widget = QWidget()
    layout = QVBoxLayout(chan_widget)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    header_frame = QFrame()
    header_frame.setObjectName("panelCard")
    hf_layout = QVBoxLayout(header_frame)
    hf_layout.setContentsMargins(18, 14, 18, 14)
    hf_layout.setSpacing(4)

    ch_title = QLabel("📡 TELEGRAM CHANNELS MANAGER")
    ch_title.setStyleSheet("font-size: 16px; font-weight: 900; color: #00D2BE; letter-spacing: 1px;")
    ch_subtitle = QLabel("Управление пулом каналов Telegram: добавляйте новые источники, переключайтесь и сканируйте")
    ch_subtitle.setStyleSheet("font-size: 12px; color: #94A3B8;")
    hf_layout.addWidget(ch_title)
    hf_layout.addWidget(ch_subtitle)
    layout.addWidget(header_frame)

    add_frame = QFrame()
    add_frame.setObjectName("panelCard")
    af_layout = QHBoxLayout(add_frame)
    af_layout.setContentsMargins(14, 10, 14, 10)
    af_layout.setSpacing(10)

    add_lbl = QLabel("Новый канал:")
    add_lbl.setStyleSheet("font-weight: 700; color: #CBD5E1; font-size: 12px;")

    window.chan_view_input = QLineEdit()
    window.chan_view_input.setPlaceholderText("Введите @username канала или ссылку https://t.me/channel...")
    window.chan_view_input.setStyleSheet("""
        QLineEdit {
            background-color: #0F1420;
            border: 1px solid #1C2636;
            border-radius: 6px;
            padding: 6px 12px;
            color: #FFFFFF;
            font-size: 12px;
        }
        QLineEdit:focus {
            border-color: #00D2BE;
        }
    """)
    window.chan_view_input.returnPressed.connect(window._add_channel_from_manager)

    btn_add = QPushButton("+ Добавить канал")
    btn_add.setObjectName("primaryButton")
    btn_add.setFixedHeight(32)
    btn_add.clicked.connect(window._add_channel_from_manager)
    window.chan_btn_add = btn_add

    af_layout.addWidget(add_lbl)
    af_layout.addWidget(window.chan_view_input, 1)
    af_layout.addWidget(btn_add)
    layout.addWidget(add_frame)

    tbl_lbl = QLabel("СОХРАНЕННЫЕ КАНАЛЫ")
    tbl_lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #64748B; letter-spacing: 0.8px;")
    layout.addWidget(tbl_lbl)

    window.channels_mgr_table = QTableWidget()
    window.channels_mgr_table.setColumnCount(4)
    window.channels_mgr_table.setHorizontalHeaderLabels(["ИКОНКА", "КАНАЛ", "СТАТУС", "ДЕЙСТВИЯ"])
    window.channels_mgr_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    window.channels_mgr_table.setColumnWidth(0, 50)
    window.channels_mgr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
    window.channels_mgr_table.setColumnWidth(1, 240)
    window.channels_mgr_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
    window.channels_mgr_table.setColumnWidth(2, 140)
    window.channels_mgr_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    window.channels_mgr_table.verticalHeader().setVisible(False)
    window.channels_mgr_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.channels_mgr_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(window.channels_mgr_table, 1)

    return chan_widget
