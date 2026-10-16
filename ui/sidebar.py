"""
Channels Sidebar and Telegram API configuration drawer for Beatstorm.
"""

from PyQt6.QtCore import Qt
from config import DEFAULT_CONFIG
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QListWidget,
    QGridLayout,
)


def setup_api_drawer(window) -> QGroupBox:
    """Создает выпадающую панель настроек Telegram API и прокси."""
    window.api_id_label = QLabel("API ID:")
    window.api_id_input = QLineEdit()
    window.api_id_input.setPlaceholderText("ID приложения")
    window.api_id_input.setToolTip("ID приложения из my.telegram.org/apps")

    window.api_hash_label = QLabel("API Hash:")
    window.api_hash_input = QLineEdit()
    window.api_hash_input.setEchoMode(QLineEdit.EchoMode.Password)
    window.api_hash_input.setPlaceholderText("Hash приложения")
    window.api_hash_input.setToolTip("Hash приложения из my.telegram.org/apps")

    window.proxy_button = QPushButton("Настройки прокси...")
    window.proxy_button.setObjectName("chipButton")

    window.threads_spin = QSpinBox()
    window.threads_spin.setRange(1, 10)
    window.threads_spin.setValue(5)
    window.threads_spin.setToolTip("Количество параллельных потоков скачивания (1–10)")

    window.bitrate_combo = QComboBox()
    window.bitrate_combo.addItems(["320k", "256k", "192k", "128k"])
    window.bitrate_combo.setCurrentText("192k")
    # Подсказка обязана прямо говорить про пропуск конвертации: трек, уже
    # лежащий в MP3, сохраняется как есть и с исходным битрейтом, поэтому
    # на MP3-каналах выбор битрейта не меняет ничего. Без этой оговорки
    # пользователь выбирает 256k и молча получает 320k.
    window.bitrate_combo.setToolTip(
        "Битрейт аудио при конвертации в MP3.\n"
        "Треки, уже в MP3, сохраняются без конвертации — с исходным "
        "битрейтом, без потери качества."
    )

    window.export_pattern_input = QLineEdit(DEFAULT_CONFIG["export_pattern"])
    window.export_pattern_input.setToolTip("Шаблон имени и папок сохранения: {channel}, {artist}, {title}, {year}, {bpm}")

    window.auto_m3u8_check = QCheckBox("Генерировать .M3U8 плейлисты")
    window.auto_m3u8_check.setChecked(True)
    window.auto_m3u8_check.setToolTip("Автоматически создавать M3U8 файл в папке канала при завершении скачивания")

    window.embed_id3_check = QCheckBox("Встраивать ID3v2 теги и обложки")
    window.embed_id3_check.setChecked(True)
    window.embed_id3_check.setToolTip("Автоматически записывать ID3v2 теги (TIT2, TPE1, TALB, APIC) в скачанные MP3 файлы")

    window.watcher_interval_spin = QSpinBox()
    window.watcher_interval_spin.setRange(1, 120)
    window.watcher_interval_spin.setValue(15)
    window.watcher_interval_spin.setSuffix(" мин")
    window.watcher_interval_spin.setToolTip("Интервал периодической проверки новых треков в каналах")

    window.api_group = QGroupBox("Параметры подключения и загрузки")
    api_form = QFormLayout()
    api_form.addRow(window.api_id_label, window.api_id_input)
    api_form.addRow(window.api_hash_label, window.api_hash_input)
    api_form.addRow("Прокси-сервер:", window.proxy_button)
    api_form.addRow("Потоков загрузки:", window.threads_spin)
    api_form.addRow("Качество MP3:", window.bitrate_combo)
    api_form.addRow("Шаблон экспорта:", window.export_pattern_input)
    api_form.addRow("Опции экспорта:", window.auto_m3u8_check)
    api_form.addRow("Тегирование аудио:", window.embed_id3_check)
    api_form.addRow("Интервал мониторинга:", window.watcher_interval_spin)

    window.btn_save_settings = QPushButton("💾 Сохранить настройки")
    window.btn_save_settings.setObjectName("primaryButton")
    window.btn_save_settings.setToolTip("Сохранить параметры API, битрейта и прокси в конфигурационный файл")
    window.btn_save_settings.clicked.connect(window._save_settings_with_feedback)

    window.save_feedback_lbl = QLabel("")
    window.save_feedback_lbl.setStyleSheet("color: #00E5FF; font-weight: 700; font-size: 11px;")

    save_row = QHBoxLayout()
    save_row.addWidget(window.btn_save_settings)
    save_row.addWidget(window.save_feedback_lbl)
    save_row.addStretch()
    api_form.addRow("", save_row)
    window.api_group.setLayout(api_form)

    window.bitrate_combo.currentTextChanged.connect(window._on_setting_changed)
    window.threads_spin.valueChanged.connect(window._on_setting_changed)

    window.toggle_api_btn = QPushButton("⚙️ Настройки Telegram API")
    window.toggle_api_btn.setObjectName("chipButton")
    window.toggle_api_btn.clicked.connect(window._toggle_api_settings)

    return window.api_group


def setup_channels_sidebar(window) -> QFrame:
    """Создает левую панель управления каналами Telegram (Channels Sidebar)."""
    window.left_panel = QFrame()
    window.left_panel.setObjectName("panelCard")
    window.left_panel.setFixedWidth(230)
    left_layout = QVBoxLayout(window.left_panel)
    left_layout.setContentsMargins(12, 12, 12, 12)
    left_layout.setSpacing(10)

    # Заголовок левой панели
    chan_header = QHBoxLayout()
    chan_title = QLabel("TELEGRAM CHANNELS")
    chan_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")
    chan_title.setToolTip("Управление источниками и каналами Telegram")
    chan_header.addWidget(chan_title)
    chan_header.addStretch()
    left_layout.addLayout(chan_header)

    # Подзаголовок: SAVED CHANNELS + кнопки добавления и удаления
    saved_header = QHBoxLayout()
    saved_lbl = QLabel("SAVED CHANNELS")
    saved_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    saved_lbl.setToolTip("Список сохраненных каналов для быстрого переключения")

    window.btn_add_chan = QPushButton("+")
    window.btn_add_chan.setObjectName("chipButton")
    window.btn_add_chan.setFixedSize(22, 20)
    window.btn_add_chan.setToolTip("Добавить канал в список сохраненных")
    window.btn_add_chan.clicked.connect(window._prompt_add_channel)

    window.btn_remove_chan = QPushButton("—")
    window.btn_remove_chan.setObjectName("chipButton")
    window.btn_remove_chan.setFixedSize(22, 20)
    window.btn_remove_chan.setToolTip("Удалить выбранный канал из списка сохраненных")
    window.btn_remove_chan.clicked.connect(window._remove_selected_channel)

    saved_header.addWidget(saved_lbl)
    saved_header.addStretch()
    saved_header.addWidget(window.btn_add_chan)
    saved_header.addWidget(window.btn_remove_chan)
    left_layout.addLayout(saved_header)

    window.btn_all_channels = QPushButton("🌟 Все каналы")
    window.btn_all_channels.setObjectName("chipButton")
    window.btn_all_channels.setFixedHeight(26)
    window.btn_all_channels.setStyleSheet("""
        QPushButton {
            background-color: #0E1E38;
            border: 1px solid #1E3A5F;
            border-radius: 6px;
            color: #00E5FF;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            text-align: left;
        }
        QPushButton:hover {
            background-color: #142A4E;
            border: 1px solid #00E5FF;
        }
    """)
    window.btn_all_channels.setToolTip("Отобразить треки со всех сохраненных каналов")
    window.btn_all_channels.clicked.connect(window._select_all_channels_view)
    left_layout.addWidget(window.btn_all_channels)

    # Список сохраненных каналов
    window.saved_channels_list = QListWidget()
    window.saved_channels_list.setObjectName("channelList")
    window.saved_channels_list.setFixedHeight(180)
    window.saved_channels_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    window.saved_channels_list.customContextMenuRequested.connect(window._show_channel_context_menu)
    window.saved_channels_list.itemClicked.connect(window._on_saved_channel_clicked)
    left_layout.addWidget(window.saved_channels_list)

    window._init_saved_channels()

    # Блок выбора канала и параметров сканирования
    window.channel_group = QGroupBox("Поиск канала")
    chan_form = QVBoxLayout()
    chan_form.setSpacing(6)

    window.channel_label = QLabel("Канал (@channelname):")
    window.channel_input = QLineEdit()
    window.channel_input.setPlaceholderText("@channelname или ссылка")
    window.channel_input.setToolTip("Username канала или ссылка вида https://t.me/channel")

    window.mode_label = QLabel("Режим:")
    window.mode_combo = QComboBox()
    window.mode_combo.addItem("Прямое скачивание", "direct")
    window.mode_combo.addItem("Запись звука", "record")
    window.mode_combo.addItem("Гибрид (прямое, затем запись)", "hybrid")
    # Режим должен сохраняться сразу, как битрейт и число потоков: в сайдбаре
    # нет кнопки сохранения, поэтому выбор режима молча терялся при закрытии.
    window.mode_combo.currentIndexChanged.connect(window._on_setting_changed)

    date_grid = QGridLayout()
    date_grid.setContentsMargins(0, 0, 0, 0)
    date_grid.setSpacing(4)
    window.date_from_label = QLabel("От:")
    window.date_from_label.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold;")
    window.date_from_input = QLineEdit()
    window.date_from_input.setPlaceholderText("ГГГГ-ММ-ДД")
    window.date_to_label = QLabel("До:")
    window.date_to_label.setStyleSheet("color: #64748B; font-size: 10px; font-weight: bold;")
    window.date_to_input = QLineEdit()
    window.date_to_input.setPlaceholderText("ГГГГ-ММ-ДД")
    date_grid.addWidget(window.date_from_label, 0, 0)
    date_grid.addWidget(window.date_from_input, 0, 1)
    date_grid.addWidget(window.date_to_label, 1, 0)
    date_grid.addWidget(window.date_to_input, 1, 1)

    # Канал и даты тоже должны сохраняться сразу, как режим, битрейт и
    # число потоков. Раньше у этих трёх полей не было ни одного сигнала:
    # значения читались из config при старте, но никогда не писались
    # обратно, поэтому введённый канал молча терялся при закрытии.
    window.channel_input.editingFinished.connect(window._on_setting_changed)
    window.date_from_input.editingFinished.connect(window._on_setting_changed)
    window.date_to_input.editingFinished.connect(window._on_setting_changed)

    preset_row = QHBoxLayout()
    window.btn_preset_all = QPushButton("Все")
    window.btn_preset_all.setObjectName("chipButton")
    window.btn_preset_all.clicked.connect(window._preset_dates_all)
    window.btn_preset_all.clicked.connect(window._on_setting_changed)
    window.btn_preset_30d = QPushButton("30 дн")
    window.btn_preset_30d.setObjectName("chipButton")
    window.btn_preset_30d.clicked.connect(window._preset_dates_30d)
    window.btn_preset_30d.clicked.connect(window._on_setting_changed)
    preset_row.addWidget(window.btn_preset_all)
    preset_row.addWidget(window.btn_preset_30d)

    window.scan_button = QPushButton("⚡ ЗАГРУЗИТЬ ТРЕКИ")
    window.scan_button.setObjectName("primaryButton")

    chan_form.addWidget(window.channel_label)
    chan_form.addWidget(window.channel_input)
    chan_form.addWidget(window.mode_label)
    chan_form.addWidget(window.mode_combo)
    chan_form.addLayout(date_grid)
    chan_form.addLayout(preset_row)
    chan_form.addWidget(window.scan_button)
    window.channel_group.setLayout(chan_form)
    left_layout.addWidget(window.channel_group)
    if hasattr(window, "toggle_api_btn"):
        left_layout.addWidget(window.toggle_api_btn)
    left_layout.addStretch()

    return window.left_panel
