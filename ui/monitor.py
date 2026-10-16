"""
Download Monitor panel builder for Beatstorm (Right Sidebar).
"""

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QProgressBar,
    QTextEdit,
    QSizePolicy,
    QScrollArea,
)
from PyQt6.QtCore import Qt
from ui.widgets import SpeedMeterWidget


def setup_download_monitor(window) -> QFrame:
    """Создает правую панель мониторинга многопоточных загрузок (Download Monitor)."""
    window.right_panel = QFrame()
    window.right_panel.setObjectName("panelCard")
    window.right_panel.setFixedWidth(235)
    outer_layout = QVBoxLayout(window.right_panel)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    # Контент панели помещается в прокручиваемую область: при малой высоте
    # окна (например, когда открыт drawer настроек) секции переставали
    # помещаться и Qt накладывал их друг на друга — график проходил по
    # тексту меток, «STORAGE STATS» печатался поверх подписей скорости.
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("background: transparent; border: none;")

    content = QWidget()
    content.setStyleSheet("background: transparent;")
    right_layout = QVBoxLayout(content)
    right_layout.setContentsMargins(12, 12, 12, 12)
    right_layout.setSpacing(10)
    scroll.setWidget(content)
    outer_layout.addWidget(scroll)

    # Заголовок правой панели
    mon_header = QHBoxLayout()
    mon_title = QLabel("DOWNLOAD MONITOR")
    mon_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")
    mon_title.setToolTip("Панель мониторинга многопоточных загрузок, скорости и дискового пространства")
    mon_header.addWidget(mon_title)
    mon_header.addStretch()
    right_layout.addLayout(mon_header)

    # MULTI-THREAD STATUS
    thread_hdr = QHBoxLayout()
    thread_lbl = QLabel("MULTI-THREAD STATUS")
    thread_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px;")
    thread_lbl.setToolTip("Статус и загрузка параллельных рабочих потоков")
    window.thread_val = QLabel("IDLE")
    window.thread_val.setStyleSheet("font-size: 10px; font-weight: 800; color: #00E5FF;")
    thread_hdr.addWidget(thread_lbl)
    thread_hdr.addStretch()
    thread_hdr.addWidget(window.thread_val)
    right_layout.addLayout(thread_hdr)

    window.thread_bar = QProgressBar()
    window.thread_bar.setValue(0)
    window.thread_bar.setTextVisible(False)
    window.thread_bar.setFixedHeight(4)
    right_layout.addWidget(window.thread_bar)

    # ACTIVE DOWNLOADS (Стримы активных потоков)
    active_lbl = QLabel("ACTIVE DOWNLOADS")
    active_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px; margin-top: 4px;")
    active_lbl.setToolTip("Файлы, скачиваемые в текущую секунду")
    right_layout.addWidget(active_lbl)

    window.stream_box = QVBoxLayout()
    window.stream_box.setSpacing(6)

    window.stream_empty_lbl = QLabel("Нет активных загрузок")
    window.stream_empty_lbl.setStyleSheet("font-size: 11px; color: #475569; font-style: italic; padding: 4px 0;")
    window.stream_box.addWidget(window.stream_empty_lbl)

    window.stream_widgets = []
    for i in range(5):
        s_container = QWidget()
        c_layout = QVBoxLayout(s_container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(2)

        s_row = QHBoxLayout()
        s_lbl = QLabel(f"Поток {i+1}")
        s_lbl.setStyleSheet("font-size: 11px; color: #CBD5E1; font-weight: 600;")
        s_spd = QLabel("0.0 MB/s")
        s_spd.setStyleSheet("font-size: 10px; color: #64748B; font-family: monospace;")
        s_row.addWidget(s_lbl)
        s_row.addStretch()
        s_row.addWidget(s_spd)

        s_pbar = QProgressBar()
        s_pbar.setValue(0)
        s_pbar.setTextVisible(False)
        s_pbar.setFixedHeight(4)

        c_layout.addLayout(s_row)
        c_layout.addWidget(s_pbar)
        s_container.setVisible(False)

        window.stream_box.addWidget(s_container)
        window.stream_widgets.append((s_container, s_lbl, s_spd, s_pbar))

    right_layout.addLayout(window.stream_box)

    # SPEED METERS (Интерактивный сплайн-график скорости)
    speed_hdr = QHBoxLayout()
    speed_title = QLabel("SPEED METERS")
    speed_title.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px; margin-top: 4px;")
    speed_title.setToolTip("График текущей скорости скачивания в реальном времени")
    speed_chev = QLabel("⌄")
    speed_chev.setStyleSheet("color: #64748B; font-weight: 700;")
    speed_hdr.addWidget(speed_title)
    speed_hdr.addStretch()
    speed_hdr.addWidget(speed_chev)
    right_layout.addLayout(speed_hdr)

    speed_block = QWidget()
    speed_block_layout = QVBoxLayout(speed_block)
    speed_block_layout.setContentsMargins(0, 0, 0, 0)
    speed_block_layout.setSpacing(3)

    window.speed_meter = SpeedMeterWidget()
    speed_block_layout.addWidget(window.speed_meter)

    window.spd_current = QLabel("Current:   0.0 MB/s")
    window.spd_average = QLabel("Average:   0.0 MB/s")
    window.spd_total = QLabel("Total DL:  0 треков")
    for slbl in (window.spd_current, window.spd_average, window.spd_total):
        slbl.setStyleSheet("font-size: 10px; color: #94A3B8; font-family: monospace;")
        slbl.setFixedHeight(15)
        speed_block_layout.addWidget(slbl)
    # Блок неразжимаем: при нехватке высоты правой панели (например, когда
    # открыт drawer настроек) QVBoxLayout переставал вмещать секции и виджеты
    # накладывались друг на друга — график проходил по тексту меток.
    speed_block.setMinimumHeight(50 + 3 * 15 + 3 * 3 + 6)
    speed_block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    right_layout.addWidget(speed_block)

    # STORAGE STATS (Память диска)
    storage_hdr = QHBoxLayout()
    storage_lbl = QLabel("STORAGE STATS")
    storage_lbl.setStyleSheet("font-size: 9px; font-weight: 700; color: #64748B; letter-spacing: 0.8px; margin-top: 4px;")
    storage_lbl.setToolTip("Реальное свободное место на локальном накопителе")
    storage_hdr.addWidget(storage_lbl)
    storage_hdr.addStretch()
    right_layout.addLayout(storage_hdr)

    window.storage_usage_lbl = QLabel("—% full")
    window.storage_usage_lbl.setStyleSheet("font-size: 10px; color: #00E5FF; font-weight: 700;")
    right_layout.addWidget(window.storage_usage_lbl)

    window.storage_bar = QProgressBar()
    window.storage_bar.setValue(0)
    window.storage_bar.setTextVisible(False)
    window.storage_bar.setFixedHeight(4)
    right_layout.addWidget(window.storage_bar)

    window.storage_info_lbl = QLabel("— GB available")
    window.storage_info_lbl.setStyleSheet("font-size: 10px; color: #64748B;")
    right_layout.addWidget(window.storage_info_lbl)

    # Консоль логов и кнопка монитора
    window.btn_toggle_log = QPushButton("🎛 Монитор консоли")
    window.btn_toggle_log.setObjectName("chipButton")
    window.btn_toggle_log.clicked.connect(window._toggle_log)
    right_layout.addWidget(window.btn_toggle_log)

    window.log_output = QTextEdit()
    window.log_output.setObjectName("logOutput")
    window.log_output.setReadOnly(True)
    window.log_output.setMaximumHeight(90)
    right_layout.addWidget(window.log_output)

    # Прогресс-бар и лейбл загрузки
    window.progress_bar = QProgressBar()
    window.progress_bar.setVisible(False)
    window.progress_bar.setMinimum(0)
    window.progress_bar.setMaximum(100)
    window.progress_bar.setValue(0)

    window.progress_label = QLabel("")
    window.progress_label.setStyleSheet("font-size: 11px; color: #94A3B8; font-family: monospace;")
    window.progress_label.setWordWrap(True)

    return window.right_panel
