"""
Interactive Bento Grid Studio Widgets for BEATSTORM Workstation:
1. CamelotWheelWidget: Camelot harmonic key selector for DJs.
2. TrackInspectorCard: Bento Card for inspecting track metadata, cover artwork, and ID3 tags.
"""

import os
import re
import logging
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QSizePolicy,
)

import audio_converter
from media_utils import extract_key_meta, get_camelot_color
from ui.widgets import extract_bpm_meta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Camelot Keys and Constants
# ---------------------------------------------------------------------------
MINOR_CAMELOT_KEYS = [f"{i}A" for i in range(1, 13)]
MAJOR_CAMELOT_KEYS = [f"{i}B" for i in range(1, 13)]
ALL_CAMELOT_KEYS = MINOR_CAMELOT_KEYS + MAJOR_CAMELOT_KEYS

# CSS Styles for Camelot Wheel
STYLE_RESET_BTN = """
QPushButton {
    background-color: #121824;
    border: 1px solid #1E293B;
    border-radius: 4px;
    color: #94A3B8;
    font-weight: 700;
    font-size: 10px;
    padding: 3px 8px;
}
QPushButton:hover {
    background-color: #1E293B;
    color: #FFFFFF;
    border-color: #475569;
}
QPushButton:pressed {
    background-color: #0F172A;
}
"""

STYLE_MINOR_DEFAULT = """
QPushButton {
    background-color: #0E1624;
    border: 1px solid #162E44;
    border-radius: 4px;
    color: #00E5FF;
    font-weight: 700;
    font-size: 11px;
    padding: 3px 2px;
}
QPushButton:hover {
    background-color: #14253B;
    border-color: #00E5FF;
}
"""

STYLE_MAJOR_DEFAULT = """
QPushButton {
    background-color: #0C1E17;
    border: 1px solid #143D2A;
    border-radius: 4px;
    color: #00E676;
    font-weight: 700;
    font-size: 11px;
    padding: 3px 2px;
}
QPushButton:hover {
    background-color: #123325;
    border-color: #00E676;
}
"""

STYLE_MINOR_SELECTED = """
QPushButton {
    background-color: #00E5FF;
    border: 2px solid #FFFFFF;
    border-radius: 4px;
    color: #050B14;
    font-weight: 900;
    font-size: 11px;
    padding: 3px 2px;
}
"""

STYLE_MAJOR_SELECTED = """
QPushButton {
    background-color: #00E676;
    border: 2px solid #FFFFFF;
    border-radius: 4px;
    color: #050B14;
    font-weight: 900;
    font-size: 11px;
    padding: 3px 2px;
}
"""

STYLE_MINOR_COMPATIBLE = """
QPushButton {
    background-color: #003644;
    border: 2px solid #00E5FF;
    border-radius: 4px;
    color: #00E5FF;
    font-weight: 800;
    font-size: 11px;
    padding: 3px 2px;
}
QPushButton:hover {
    background-color: #004D61;
}
"""

STYLE_MAJOR_COMPATIBLE = """
QPushButton {
    background-color: #083822;
    border: 2px solid #00E676;
    border-radius: 4px;
    color: #00E676;
    font-weight: 800;
    font-size: 11px;
    padding: 3px 2px;
}
QPushButton:hover {
    background-color: #0D4E30;
}
"""

STYLE_DIMMED = """
QPushButton {
    background-color: #080C12;
    border: 1px solid #121822;
    border-radius: 4px;
    color: #334155;
    font-weight: 600;
    font-size: 11px;
    padding: 3px 2px;
}
QPushButton:hover {
    background-color: #0F1722;
    color: #64748B;
}
"""


def create_track_artwork_placeholder(size: int = 100) -> QPixmap:
    """Генерирует аккуратный неоновый плейсхолдер обложки трека в стиле BEATSTORM."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Фоновый градиент с закруглением
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#121927"))
    grad.setColorAt(1.0, QColor("#090D14"))
    painter.setBrush(grad)
    painter.setPen(QPen(QColor("#1D293D"), 1.5))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 8, 8)

    center = size / 2.0
    # Внешняя дуга винила
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(0, 229, 255, 60), 1.5))
    painter.drawEllipse(int(center - 32), int(center - 32), 64, 64)

    # Внутренняя канавка
    painter.setPen(QPen(QColor(0, 229, 255, 120), 1.0, Qt.PenStyle.DashLine))
    painter.drawEllipse(int(center - 22), int(center - 22), 44, 44)

    # Сердцевина винила
    painter.setBrush(QColor("#00E5FF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(int(center - 8), int(center - 8), 16, 16)
    painter.setBrush(QColor("#090D14"))
    painter.drawEllipse(int(center - 3), int(center - 3), 6, 6)

    painter.end()
    return pix


# ---------------------------------------------------------------------------
# 1. CamelotWheelWidget
# ---------------------------------------------------------------------------
class CamelotWheelWidget(QWidget):
    """Интерактивный селектор гармонических тональностей Camelot Wheel для диджеев."""

    key_selected = pyqtSignal(str)
    key_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("camelotWheelWidget")
        self._selected_key: str | None = None
        self._compatible_keys: set[str] = set()
        self._buttons: dict[str, QPushButton] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Верхняя строка: заголовок и кнопка ALL / RESET
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        lbl_title = QLabel("CAMELOT HARMONIC WHEEL")
        lbl_title.setObjectName("bentoTitle")
        lbl_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.8px;")

        self.btn_reset = QPushButton("ALL / RESET")
        self.btn_reset.setObjectName("btnCamelotReset")
        self.btn_reset.setStyleSheet(STYLE_RESET_BTN)
        self.btn_reset.setToolTip("Сбросить фильтр тональностей / показать все треки")
        self.btn_reset.clicked.connect(self.clear_selection)

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_reset)
        layout.addLayout(header_layout)

        # Сетка 24 тональностей:
        # Строка 1: 1A..12A Minor (Cyan #00E5FF)
        # Строка 2: 1B..12B Major (Emerald #00E676)
        keys_grid = QGridLayout()
        keys_grid.setContentsMargins(0, 2, 0, 2)
        keys_grid.setSpacing(4)

        # Строка 1: Minor (A)
        lbl_minor = QLabel("MIN")
        lbl_minor.setStyleSheet("font-size: 9px; font-weight: 800; color: #00E5FF; padding-right: 2px;")
        keys_grid.addWidget(lbl_minor, 0, 0, Qt.AlignmentFlag.AlignCenter)

        for col, k in enumerate(MINOR_CAMELOT_KEYS, start=1):
            btn = QPushButton(k)
            btn.setObjectName("bentoKeyPill")
            btn.setFixedSize(30, 26)
            btn.setStyleSheet(STYLE_MINOR_DEFAULT)
            btn.setToolTip(f"Тональность {k} (Minor)")
            btn.clicked.connect(lambda checked=False, key_str=k: self._on_key_clicked(key_str))
            self._buttons[k] = btn
            keys_grid.addWidget(btn, 0, col)

        # Строка 2: Major (B)
        lbl_major = QLabel("MAJ")
        lbl_major.setStyleSheet("font-size: 9px; font-weight: 800; color: #00E676; padding-right: 2px;")
        keys_grid.addWidget(lbl_major, 1, 0, Qt.AlignmentFlag.AlignCenter)

        for col, k in enumerate(MAJOR_CAMELOT_KEYS, start=1):
            btn = QPushButton(k)
            btn.setObjectName("bentoKeyPill")
            btn.setFixedSize(30, 26)
            btn.setStyleSheet(STYLE_MAJOR_DEFAULT)
            btn.setToolTip(f"Тональность {k} (Major)")
            btn.clicked.connect(lambda checked=False, key_str=k: self._on_key_clicked(key_str))
            self._buttons[k] = btn
            keys_grid.addWidget(btn, 1, col)

        layout.addLayout(keys_grid)

    @staticmethod
    def get_compatible_keys(key: str) -> list[str]:
        """Вычисляет гармонически совместимые тональности по правилу Camelot:

        - Same number opposite letter (например 8B для 8A)
        - +1 number same letter (например 9A для 8A, с циклом 12->1)
        - -1 number same letter (например 7A для 8A, с циклом 1->12)
        """
        if not key:
            return []
        clean = str(key).strip().upper()
        m = re.match(r"^(\d{1,2})([AB])$", clean)
        if not m:
            return []
        num = int(m.group(1))
        letter = m.group(2)
        if not (1 <= num <= 12):
            return []

        opp_letter = "B" if letter == "A" else "A"
        next_num = 1 if num == 12 else num + 1
        prev_num = 12 if num == 1 else num - 1

        return [
            f"{num}{opp_letter}",
            f"{next_num}{letter}",
            f"{prev_num}{letter}",
        ]

    def _on_key_clicked(self, key: str) -> None:
        """Обработчик нажатия на кнопку тональности."""
        self.highlight_compatible(key)
        self.key_selected.emit(key)

    def highlight_compatible(self, selected_key: str) -> list[str]:
        """Рассчитывает гармонические матчи и визуально подсвечивает кнопки."""
        if not selected_key:
            self.clear_selection()
            return []

        clean = str(selected_key).strip().upper()
        if clean not in ALL_CAMELOT_KEYS:
            self.clear_selection()
            return []

        self._selected_key = clean
        matches = self.get_compatible_keys(clean)
        self._compatible_keys = set(matches)
        self._apply_button_styles()
        return matches

    def _apply_button_styles(self) -> None:
        """Обновляет стили всех 24 кнопок в зависимости от выбранной тональности."""
        if self._selected_key is None:
            # Все кнопки в исходном состоянии
            for k in MINOR_CAMELOT_KEYS:
                btn = self._buttons[k]
                btn.setObjectName("bentoKeyPill")
                btn.setStyleSheet(STYLE_MINOR_DEFAULT)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            for k in MAJOR_CAMELOT_KEYS:
                btn = self._buttons[k]
                btn.setObjectName("bentoKeyPill")
                btn.setStyleSheet(STYLE_MAJOR_DEFAULT)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            return

        for k, btn in self._buttons.items():
            is_minor = k.endswith("A")
            if k == self._selected_key:
                btn.setObjectName("bentoKeyPillActive")
                btn.setStyleSheet(STYLE_MINOR_SELECTED if is_minor else STYLE_MAJOR_SELECTED)
            elif k in self._compatible_keys:
                btn.setObjectName("bentoKeyPillHarmonic")
                btn.setStyleSheet(STYLE_MINOR_COMPATIBLE if is_minor else STYLE_MAJOR_COMPATIBLE)
            else:
                btn.setObjectName("bentoKeyPill")
                btn.setStyleSheet(STYLE_DIMMED)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def selected_key(self) -> str | None:
        """Возвращает текущую выбранную тональность или None."""
        return self._selected_key

    def clear_selection(self) -> None:
        """Сбрасывает выбор тональности и подсветку."""
        self._selected_key = None
        self._compatible_keys.clear()
        self._apply_button_styles()
        self.key_cleared.emit()


# ---------------------------------------------------------------------------
# 2. TrackInspectorCard
# ---------------------------------------------------------------------------
class TrackInspectorCard(QFrame):
    """Bento-карточка для инспектирования метаданных трека, обложки и редактирования ID3 тегов."""

    tags_saved = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bentoCard")
        self._current_track: dict = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Заголовок карточки
        card_header = QHBoxLayout()
        card_header.setContentsMargins(0, 0, 0, 0)
        lbl_head = QLabel("TRACK INSPECTOR")
        lbl_head.setObjectName("bentoTitle")
        lbl_head.setStyleSheet("font-size: 12px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.8px;")
        card_header.addWidget(lbl_head)
        card_header.addStretch()
        layout.addLayout(card_header)

        # Верхняя секция: обложка (100x100) + название, исполнитель и бейджи
        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 0, 0, 0)
        preview_row.setSpacing(12)

        # Квадратный thumbnail QLabel для обложки (100x100)
        self.artwork_preview = QLabel()
        self.artwork_preview.setFixedSize(100, 100)
        self.artwork_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork_preview.setScaledContents(True)
        self.artwork_preview.setStyleSheet(
            "border: 1px solid #1E293B; border-radius: 8px; background-color: #0E131E;"
        )
        self.artwork_preview.setPixmap(create_track_artwork_placeholder(100))
        self.lbl_artwork = self.artwork_preview  # alias

        # Информация о треке и бейджи
        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(4)

        self.lbl_title = QLabel("Трек не выбран")
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #FFFFFF;")
        self.lbl_title.setWordWrap(True)
        self.title_label = self.lbl_title  # alias

        self.lbl_artist = QLabel("—")
        self.lbl_artist.setStyleSheet("font-size: 12px; font-weight: 600; color: #94A3B8;")
        self.artist_label = self.lbl_artist  # alias

        # Бейджи (Camelot key, BPM, Bitrate)
        badges_layout = QHBoxLayout()
        badges_layout.setContentsMargins(0, 4, 0, 0)
        badges_layout.setSpacing(6)

        self.badge_key = QLabel("—")
        self.key_badge = self.badge_key
        self.badge_bpm = QLabel("— BPM")
        self.bpm_badge = self.badge_bpm
        self.badge_bitrate = QLabel("—")
        self.bitrate_badge = self.badge_bitrate

        self._update_badges(key="—", bpm="—", bitrate="—")

        badges_layout.addWidget(self.badge_key)
        badges_layout.addWidget(self.badge_bpm)
        badges_layout.addWidget(self.badge_bitrate)
        badges_layout.addStretch()

        meta_col.addWidget(self.lbl_title)
        meta_col.addWidget(self.lbl_artist)
        meta_col.addLayout(badges_layout)
        meta_col.addStretch()

        preview_row.addWidget(self.artwork_preview)
        preview_row.addLayout(meta_col, 1)
        layout.addLayout(preview_row)

        # Редактируемые ID3 поля
        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 4, 0, 4)
        form_layout.setSpacing(6)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def make_field_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #64748B;")
            return lbl

        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Название трека (TIT2)")
        self.input_title = self.edit_title
        self.edit_title.textChanged.connect(self._update_export_preview)

        self.edit_artist = QLineEdit()
        self.edit_artist.setPlaceholderText("Исполнитель (TPE1)")
        self.input_artist = self.edit_artist
        self.edit_artist.textChanged.connect(self._update_export_preview)

        self.edit_album = QLineEdit()
        self.edit_album.setPlaceholderText("Альбом (TALB)")
        self.input_album = self.edit_album

        self.edit_genre = QLineEdit()
        self.edit_genre.setPlaceholderText("Жанр (TCON)")
        self.input_genre = self.edit_genre

        self.edit_year = QLineEdit()
        self.edit_year.setPlaceholderText("Год (TDRC)")
        self.input_year = self.edit_year

        form_layout.addRow(make_field_label("Title:"), self.edit_title)
        form_layout.addRow(make_field_label("Artist:"), self.edit_artist)
        form_layout.addRow(make_field_label("Album:"), self.edit_album)
        form_layout.addRow(make_field_label("Genre:"), self.edit_genre)
        form_layout.addRow(make_field_label("Year:"), self.edit_year)
        layout.addLayout(form_layout)

        # Превью шаблона экспорта {channel}/{artist} - {title}.mp3
        export_box = QVBoxLayout()
        export_box.setContentsMargins(0, 2, 0, 2)
        export_box.setSpacing(2)

        lbl_exp_header = QLabel("EXPORT TEMPLATE PREVIEW:")
        lbl_exp_header.setStyleSheet("font-size: 10px; font-weight: 800; color: #64748B; letter-spacing: 0.5px;")

        self.lbl_export_preview = QLabel("{channel}/{artist} - {title}.mp3")
        self.lbl_export_preview.setStyleSheet(
            "background-color: #080D15; border: 1px dashed #1B293C; border-radius: 5px; "
            "padding: 5px 8px; color: #00D2BE; font-family: 'Consolas', 'Cascadia Code', monospace; "
            "font-size: 11px;"
        )
        self.lbl_export_preview.setWordWrap(True)
        self.export_preview_label = self.lbl_export_preview

        export_box.addWidget(lbl_exp_header)
        export_box.addWidget(self.lbl_export_preview)
        layout.addLayout(export_box)

        # Кнопки действий: Сохранить ID3 и Очистить промо
        btn_box = QHBoxLayout()
        btn_box.setSpacing(6)
        self.btn_save_tags = QPushButton("💾 Сохранить теги ID3")
        self.btn_save_tags.setObjectName("primaryButton")
        self.btn_save_tags.setToolTip("Записать ID3 теги в файл и обновить базу данных")
        self.btn_save_tags.clicked.connect(self.save_tags)

        self.btn_clean_promo = QPushButton("✨ Очистить промо")
        self.btn_clean_promo.setObjectName("chipButton")
        self.btn_clean_promo.setToolTip("Очистить промо-теги и скобки из названия и исполнителя")
        self.btn_clean_promo.clicked.connect(self.clean_promo)

        btn_box.addWidget(self.btn_save_tags, 1)
        btn_box.addWidget(self.btn_clean_promo)
        layout.addLayout(btn_box)

    def _update_badges(self, key: str, bpm: str, bitrate: str) -> None:
        """Обновляет визуальное отображение бейджей."""
        k_text = key if key and key != "—" else "—"
        k_color = get_camelot_color(k_text)
        self.badge_key.setText(k_text)
        self.badge_key.setStyleSheet(
            f"background-color: {k_color}22; color: {k_color}; border: 1px solid {k_color}66; "
            f"border-radius: 4px; padding: 2px 7px; font-weight: 800; font-size: 11px;"
        )

        b_text = f"{bpm} BPM" if bpm and bpm != "—" else "— BPM"
        self.badge_bpm.setText(b_text)
        self.badge_bpm.setStyleSheet(
            "background-color: #00E5FF18; color: #00E5FF; border: 1px solid #00E5FF44; "
            "border-radius: 4px; padding: 2px 7px; font-weight: 700; font-size: 11px;"
        )

        br_text = bitrate if bitrate and bitrate != "—" else "—"
        self.badge_bitrate.setText(br_text)
        self.badge_bitrate.setStyleSheet(
            "background-color: #00E67618; color: #00E676; border: 1px solid #00E67644; "
            "border-radius: 4px; padding: 2px 7px; font-weight: 700; font-size: 11px;"
        )

    def _update_export_preview(self) -> None:
        """Динамически формирует путь по шаблону экспорта {channel}/{artist} - {title}.mp3."""
        channel = (
            self._current_track.get("channel")
            or self._current_track.get("channel_title")
            or self._current_track.get("channel_id")
            or "{channel}"
        )
        artist = self.edit_artist.text().strip() or "{artist}"
        title = self.edit_title.text().strip() or "{title}"
        self.lbl_export_preview.setText(f"{channel}/{artist} - {title}.mp3")

    def _update_artwork(self, artwork_bytes: bytes | None) -> None:
        """Отображает изображение обложки либо плейсхолдер."""
        if artwork_bytes:
            pix = QPixmap()
            if pix.loadFromData(artwork_bytes) and not pix.isNull():
                scaled = pix.scaled(
                    100,
                    100,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.artwork_preview.setPixmap(scaled)
                return
        self.artwork_preview.setPixmap(create_track_artwork_placeholder(100))

    def display_track(self, track_data: dict | None) -> None:
        """Заполняет поля инспектора данными выбранного трека."""
        if not track_data:
            track_data = {}
        self._current_track = dict(track_data)

        title = str(self._current_track.get("title") or self._current_track.get("track_title") or "").strip()
        artist = str(self._current_track.get("artist") or self._current_track.get("performer") or "").strip()
        album = str(self._current_track.get("album") or "").strip()
        genre = str(self._current_track.get("genre") or "").strip()
        year = str(self._current_track.get("year") or "").strip()

        file_path = self._current_track.get("file_path") or self._current_track.get("path") or ""

        # Если файл существует локально, читаем существующие ID3 теги при отсутствии данных
        if file_path and os.path.exists(file_path):
            try:
                id3 = audio_converter.read_id3_tags(file_path)
                if not title and id3.get("title"):
                    title = id3["title"]
                if not artist and id3.get("artist"):
                    artist = id3["artist"]
                if not album and id3.get("album"):
                    album = id3["album"]
                if not genre and id3.get("genre"):
                    genre = id3["genre"]
                if not year and id3.get("year"):
                    year = id3["year"]
                if "artwork_bytes" in id3 and not self._current_track.get("artwork_bytes"):
                    self._current_track["artwork_bytes"] = id3["artwork_bytes"]
            except Exception as e:
                logger.debug(f"Ошибка чтения ID3 тегов: {e}")

        # Автоматическое определение BPM и Camelot Key если они еще не проставлены
        bpm = str(self._current_track.get("bpm") or "").strip()
        if not bpm or bpm == "—":
            bpm = extract_bpm_meta(title, artist)
        self._current_track["bpm"] = bpm

        key = str(self._current_track.get("key") or "").strip()
        if not key or key == "—":
            key = extract_key_meta(title, artist)
        self._current_track["key"] = key

        bitrate = str(self._current_track.get("bitrate") or "").strip()
        if not bitrate or bitrate == "—":
            dur = self._current_track.get("duration", 0)
            size = self._current_track.get("file_size", 0)
            if dur and size and dur > 0:
                calc_br = int((size * 8) / (dur * 1000))
                bitrate = f"{calc_br} kbps"
            else:
                bitrate = "320 kbps"
        self._current_track["bitrate"] = bitrate

        # Обновление полей ввода
        self.edit_title.setText(title)
        self.edit_artist.setText(artist)
        self.edit_album.setText(album)
        self.edit_genre.setText(genre)
        self.edit_year.setText(year)

        # Обновление заголовков и бейджей
        self.lbl_title.setText(title or "Unknown Title")
        self.lbl_artist.setText(artist or "Unknown Artist")
        self._update_badges(key=key, bpm=bpm, bitrate=bitrate)

        # Обложка
        artwork_bytes = self._current_track.get("artwork_bytes")
        self._update_artwork(artwork_bytes)

        # Превью шаблона экспорта
        self._update_export_preview()

    def save_tags(self) -> dict:
        """Записывает ID3 теги в файл (если он существует), обновляет словарь/БД и испускает сигнал tags_saved."""
        title = self.edit_title.text().strip()
        artist = self.edit_artist.text().strip()
        album = self.edit_album.text().strip()
        genre = self.edit_genre.text().strip()
        year = self.edit_year.text().strip()

        self._current_track["title"] = title
        self._current_track["artist"] = artist
        self._current_track["album"] = album
        self._current_track["genre"] = genre
        self._current_track["year"] = year

        file_path = self._current_track.get("file_path") or self._current_track.get("path")
        if file_path and os.path.exists(file_path):
            write_fn = getattr(audio_converter, "write_id3_metadata", None) or getattr(audio_converter, "write_id3_tags", None)
            if callable(write_fn):
                try:
                    write_fn(
                        filepath=file_path,
                        title=title,
                        artist=artist,
                        album=album,
                        year=year,
                        genre=genre,
                        bpm=self._current_track.get("bpm", ""),
                        key=self._current_track.get("key", ""),
                        artwork_bytes=self._current_track.get("artwork_bytes"),
                    )
                except Exception as e:
                    logger.warning(f"Ошибка сохранения ID3 тегов в {file_path}: {e}")

        # Обновляем БД если трек привязан к каналу и сообщению
        c_id = self._current_track.get("channel_id")
        m_id = self._current_track.get("message_id")
        if c_id and m_id:
            try:
                import database
                database.record_download(
                    channel_id=str(c_id),
                    message_id=int(m_id),
                    artist=artist,
                    title=title,
                    filename=self._current_track.get("filename", ""),
                    file_path=str(file_path or ""),
                    file_size=self._current_track.get("file_size", 0),
                    duration=self._current_track.get("duration", 0),
                )
            except Exception as e:
                logger.debug(f"Ошибка сохранения метаданных в БД: {e}")

        self.lbl_title.setText(title or "Unknown Title")
        self.lbl_artist.setText(artist or "Unknown Artist")
        self._update_export_preview()

        self.tags_saved.emit(self._current_track)
        return self._current_track

    def clean_promo(self) -> None:
        """Очищает промо-теги и скобки из полей названия и артиста."""
        from media_utils import clean_promo_text, smart_title_case
        cur_t = self.edit_title.text()
        cur_a = self.edit_artist.text()
        self.edit_title.setText(smart_title_case(clean_promo_text(cur_t)))
        self.edit_artist.setText(smart_title_case(clean_promo_text(cur_a)))
        self._update_export_preview()

    def inspect_track(self, track_data: dict | None) -> None:
        """Алиас для display_track для совместимости с Bento Grid Studio."""
        self.display_track(track_data)

    def save_id3(self) -> dict:
        """Алиас для save_tags для совместимости с Bento Grid Studio."""
        return self.save_tags()

