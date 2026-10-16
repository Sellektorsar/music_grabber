"""
Music Library panel builder for Beatstorm (Center Workspace).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QTreeWidget,
    QHeaderView,
    QAbstractItemView,
    QListWidget,
    QComboBox,
)


def setup_library_panel(window) -> QFrame:
    """Создает центральную панель библиотеки треков (MUSIC LIBRARY Panel)."""
    window.center_panel = QFrame()
    window.center_panel.setObjectName("panelCard")
    center_layout = QVBoxLayout(window.center_panel)
    center_layout.setContentsMargins(14, 12, 14, 12)
    center_layout.setSpacing(10)

    # Верхняя панель библиотеки: MUSIC LIBRARY + Filter + Sync
    lib_header = QHBoxLayout()
    lib_title = QLabel("MUSIC LIBRARY")
    lib_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")

    window.btn_lib_filter = QPushButton("⚲ Filter")
    window.btn_lib_filter.setObjectName("chipButton")
    window.btn_lib_filter.setToolTip("Показать или скрыть панель быстрого поиска и фильтров")
    window.btn_lib_filter.clicked.connect(window._toggle_filter_bar)
    window.filter_btn = window.btn_lib_filter

    window.btn_lib_sync = QPushButton("🔄 Sync")
    window.btn_lib_sync.setObjectName("chipButton")
    window.btn_lib_sync.setToolTip("Повторно просканировать канал и обновить список")
    window.btn_lib_sync.clicked.connect(window.start_scan)
    window.sync_btn = window.btn_lib_sync

    window.btn_lib_download = None  # Исключаем дублирующую кнопку

    lib_header.addWidget(lib_title)
    lib_header.addStretch()
    lib_header.addWidget(window.btn_lib_filter)
    lib_header.addWidget(window.btn_lib_sync)
    center_layout.addLayout(lib_header)

    # Batch Action & Filter Toolbar
    window.batch_bar = QWidget()
    window.batch_bar.setVisible(False)
    batch_container_layout = QVBoxLayout(window.batch_bar)
    batch_container_layout.setContentsMargins(0, 0, 0, 0)
    batch_container_layout.setSpacing(6)

    # Row 1: Batch Actions & Search Input
    row1_layout = QHBoxLayout()
    row1_layout.setContentsMargins(0, 0, 0, 0)
    row1_layout.setSpacing(8)

    window.btn_expand_all = QPushButton("⊞ Развернуть")
    window.btn_expand_all.setObjectName("chipButton")
    window.btn_expand_all.setToolTip("Развернуть все группы по датам и каналам")
    window.btn_expand_all.clicked.connect(window._expand_all_groups)

    window.btn_collapse_all = QPushButton("⊟ Свернуть")
    window.btn_collapse_all.setObjectName("chipButton")
    window.btn_collapse_all.setToolTip("Свернуть все группы для компактного просмотра")
    window.btn_collapse_all.clicked.connect(window._collapse_all_groups)

    window.btn_select_new = QPushButton("⚡ Только новые")
    window.btn_select_new.setObjectName("chipButton")
    window.btn_select_new.clicked.connect(window._select_only_new_tracks)

    window.btn_select_all = QPushButton("☑ Все")
    window.btn_select_all.setObjectName("chipButton")
    window.btn_select_all.clicked.connect(window._select_all_tracks)

    window.btn_select_none = QPushButton("☐ Снять")
    window.btn_select_none.setObjectName("chipButton")
    window.btn_select_none.clicked.connect(window._clear_selection)

    window.search_filter_input = QLineEdit()
    window.search_filter_input.setPlaceholderText("🔍 Поиск в списке (Enter — искать по всему каналу)...")
    window.search_filter_input.setClearButtonEnabled(True)
    window.search_filter_input.textChanged.connect(window._filter_tracks_text)
    if hasattr(window, "_search_channel_history"):
        window.search_filter_input.returnPressed.connect(window._search_channel_history)
    window.search_input = window.search_filter_input

    window.btn_search_channel = QPushButton("🔍 В канале")
    window.btn_search_channel.setObjectName("chipButton")
    window.btn_search_channel.setToolTip("Глобальный поиск по всей истории Telegram-канала через MTProto")
    if hasattr(window, "_search_channel_history"):
        window.btn_search_channel.clicked.connect(window._search_channel_history)

    window.stats_label = QLabel("")
    window.stats_label.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 11px;")

    row1_layout.addWidget(window.btn_expand_all)
    row1_layout.addWidget(window.btn_collapse_all)
    row1_layout.addWidget(window.btn_select_new)
    row1_layout.addWidget(window.btn_select_all)
    row1_layout.addWidget(window.btn_select_none)
    row1_layout.addWidget(window.search_filter_input, 1)
    row1_layout.addWidget(window.btn_search_channel)
    row1_layout.addWidget(window.stats_label)
    batch_container_layout.addLayout(row1_layout)

    # Row 2: Smart DJ Filters Bar (Status, Duration, BPM, Bitrate)
    row2_layout = QHBoxLayout()
    row2_layout.setContentsMargins(0, 0, 0, 0)
    row2_layout.setSpacing(6)

    lbl_dj_filter = QLabel("DJ FILTERS:")
    lbl_dj_filter.setStyleSheet("font-size: 10px; font-weight: 800; color: #64748B; letter-spacing: 0.5px;")

    window.combo_filter_status = QComboBox()
    window.combo_filter_status.addItems(["Все статусы", "⚡ Новые (READY)", "💾 На диске (SAVED)", "♻ Дубликаты (DUP)"])
    window.combo_filter_status.setToolTip("Фильтр по статусу готовности трека")
    if hasattr(window, "_apply_all_filters"):
        window.combo_filter_status.currentIndexChanged.connect(window._apply_all_filters)

    window.combo_filter_duration = QComboBox()
    window.combo_filter_duration.addItems([
        "Любая длительность",
        "DJ Tracks (3:00 - 8:00)",
        "Extended Mix (> 5:00)",
        "Radio Edit (< 3:30)",
        "DJ Set / Mix (> 20:00)",
    ])
    window.combo_filter_duration.setToolTip("Фильтр по хронометражу трека")
    if hasattr(window, "_apply_all_filters"):
        window.combo_filter_duration.currentIndexChanged.connect(window._apply_all_filters)

    window.combo_filter_bpm = QComboBox()
    window.combo_filter_bpm.addItems([
        "Любой BPM",
        "House / Dance (120-130)",
        "Afro / Deep (115-124)",
        "Trance / Hard (130-145)",
        "DnB / Jungle (160-180)",
        "Slow / Downtempo (< 115)",
    ])
    window.combo_filter_bpm.setToolTip("Фильтр по диапазону темпа (BPM)")
    if hasattr(window, "_apply_all_filters"):
        window.combo_filter_bpm.currentIndexChanged.connect(window._apply_all_filters)

    window.combo_filter_bitrate = QComboBox()
    window.combo_filter_bitrate.addItems([
        "Любое качество",
        "HQ / 320 kbps",
        "Lossless (FLAC/WAV)",
        "Standard (≥ 192k)",
    ])
    window.combo_filter_bitrate.setToolTip("Фильтр по качеству и битрейту")
    if hasattr(window, "_apply_all_filters"):
        window.combo_filter_bitrate.currentIndexChanged.connect(window._apply_all_filters)

    window.btn_reset_filters = QPushButton("↺ Сброс")
    window.btn_reset_filters.setObjectName("chipButton")
    window.btn_reset_filters.setToolTip("Сбросить все диджейские фильтры")
    if hasattr(window, "_reset_dj_filters"):
        window.btn_reset_filters.clicked.connect(window._reset_dj_filters)

    window.btn_export_m3u8 = QPushButton("🎶 Экспорт M3U8")
    window.btn_export_m3u8.setObjectName("chipButton")
    window.btn_export_m3u8.setToolTip("Создать M3U8 плейлист для Rekordbox/Serato/Traktor из выбранных треков")
    if hasattr(window, "export_selected_to_m3u8"):
        window.btn_export_m3u8.clicked.connect(window.export_selected_to_m3u8)

    row2_layout.addWidget(lbl_dj_filter)
    row2_layout.addWidget(window.combo_filter_status)
    row2_layout.addWidget(window.combo_filter_duration)
    row2_layout.addWidget(window.combo_filter_bpm)
    row2_layout.addWidget(window.combo_filter_bitrate)
    row2_layout.addWidget(window.btn_reset_filters)
    row2_layout.addWidget(window.btn_export_m3u8)
    row2_layout.addStretch()

    batch_container_layout.addLayout(row2_layout)
    center_layout.addWidget(window.batch_bar)

    # Мульти-колоночное групповое дерево (BEATSTORM Library Tree)
    window.library_tree = QTreeWidget()
    window.library_tree.setColumnCount(8)
    window.library_tree.setHeaderLabels(
        ["☑", "TITLE  ▲", "ARTIST", "BPM / KEY", "DUR.", "CHANNEL", "STATUS", "WAVEFORM"]
    )
    window.library_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    window.library_tree.setColumnWidth(0, 46)
    # TITLE, ARTIST, CHANNEL и WAVEFORM тянутся, а не держат заданную
    # ширину. Раньше они были Interactive, и при узком окне сумма колонок
    # превышала доступную ширину: CHANNEL, STATUS и WAVEFORM уезжали за
    # край, а STATUS -- основная обратная связь (READY/SAVED/FAILED) --
    # становился недоступен без горизонтальной прокрутки.
    window.library_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    window.library_tree.setColumnWidth(1, 180)
    window.library_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    window.library_tree.setColumnWidth(2, 120)
    window.library_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
    window.library_tree.setColumnWidth(3, 76)
    window.library_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
    window.library_tree.setColumnWidth(4, 50)
    window.library_tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
    window.library_tree.setColumnWidth(5, 120)
    window.library_tree.header().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
    window.library_tree.setColumnWidth(6, 92)
    window.library_tree.header().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
    window.library_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.library_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    window.library_tree.setAnimated(True)
    window.library_tree.setIndentation(12)
    window.library_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    if hasattr(window, "_show_tree_context_menu"):
        window.library_tree.customContextMenuRequested.connect(window._show_tree_context_menu)
    window.library_tree.itemDoubleClicked.connect(window._on_tree_item_double_clicked)
    window.library_tree.itemChanged.connect(window._on_tree_item_changed)
    window.library_tree.verticalScrollBar().valueChanged.connect(window._on_tree_scroll)
    if hasattr(window, "_on_tree_selection_changed"):
        window.library_tree.itemSelectionChanged.connect(window._on_tree_selection_changed)

    # Алиас для 100% обратной совместимости
    window.library_table = window.library_tree
    window.library_table.rowCount = lambda: len(getattr(window, "_scan_results", []))
    window.library_table.setRowCount = lambda n: None

    center_layout.addWidget(window.library_tree, 1)

    # Кнопка для ручной/прогрессивной подгрузки
    window.btn_load_more = QPushButton("⬇ Загрузить ещё треки...")
    window.btn_load_more.setObjectName("chipButton")
    window.btn_load_more.setToolTip("Прогрузить следующие треки из истории каналов")
    window.btn_load_more.setVisible(False)
    window.btn_load_more.clicked.connect(window._load_more_tracks)
    center_layout.addWidget(window.btn_load_more)

    # Скрытый список window.track_list (для 100% совместимости)
    window.track_list = QListWidget()
    window.track_list.setVisible(False)
    window.track_list.itemChanged.connect(window._update_download_button_counter)
    window.track_list.itemDoubleClicked.connect(window._on_track_double_clicked)
    center_layout.addWidget(window.track_list)

    # Нижняя панель действий библиотеки
    lib_footer = QHBoxLayout()
    window.download_button = QPushButton("⚡ Скачать выбранное")
    window.download_button.setObjectName("primaryButton")
    window.download_button.setEnabled(False)

    window.stop_button = QPushButton("⏹ Остановить")
    window.stop_button.setObjectName("stopButton")
    window.stop_button.setEnabled(False)

    window.btn_open_folder = QPushButton("📂 Папка загрузок")
    window.btn_open_folder.setObjectName("chipButton")
    window.btn_open_folder.clicked.connect(window.open_download_folder)

    lib_footer.addWidget(window.btn_open_folder)
    lib_footer.addStretch()
    lib_footer.addWidget(window.stop_button)
    lib_footer.addWidget(window.download_button)
    center_layout.addLayout(lib_footer)

    return window.center_panel
