"""
UI Widgets and drawing helpers for Beatstorm.
"""

import math
import random
import re
from PyQt6.QtCore import Qt, QRect, QPointF
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


def create_beatstorm_logo_pixmap() -> QPixmap:
    """Создает аутентичный логотип BEATSTORM с неоновым импульсом."""
    pix = QPixmap(28, 28)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Внешняя бирюзовая дуга импульса
    pen = QPen(QColor("#00D2BE"), 2.5)
    painter.setPen(pen)
    painter.drawArc(QRect(3, 3, 22, 22), 45 * 16, 270 * 16)
    # Внутренняя дуга
    pen2 = QPen(QColor(0, 210, 190, 180), 2.0)
    painter.setPen(pen2)
    painter.drawArc(QRect(7, 7, 14, 14), 135 * 16, 200 * 16)
    # Центральный квант
    painter.setBrush(QColor("#00D2BE"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(11, 11, 6, 6)
    painter.end()
    return pix


def create_user_avatar_pixmap() -> QPixmap:
    """Создает мини-аватар профиля DJ KAiros."""
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 24, 24)
    grad.setColorAt(0.0, QColor("#00D2BE"))
    grad.setColorAt(1.0, QColor("#6366F1"))
    painter.setBrush(grad)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, 24, 24)
    painter.setPen(QPen(QColor("#FFFFFF")))
    painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    painter.drawText(QRect(0, 0, 24, 24), Qt.AlignmentFlag.AlignCenter, "K")
    painter.end()
    return pix


_WAVEFORM_CACHE = {}


def create_waveform_pixmap(width=140, height=22, color_hex="#00D2BE", seed=42) -> QPixmap:
    """Генерирует высокодетализированный музыкальный вейвформ в стиле DJ Workstation (Rekordbox / Serato)."""
    cache_seed = (int(seed) % 32) if isinstance(seed, (int, float)) else 42
    cache_key = (width, height, color_hex, cache_seed)
    if cache_key in _WAVEFORM_CACHE:
        return _WAVEFORM_CACHE[cache_key]

    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rng = random.Random(cache_seed)
    bar_width = 1.5
    gap = 1.0
    num_bars = int(width / (bar_width + gap))

    pen = QPen(QColor(color_hex))
    pen.setWidthF(bar_width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    mid_y = height / 2.0
    for i in range(num_bars):
        t = i / float(max(1, num_bars))
        # Музыкальный энергетический профиль (интро, дропы, брейкдауны)
        beat_pulse = 0.45 + 0.55 * abs(math.sin(t * 3.14159 * 3.2))
        envelope = 0.35 + 0.65 * (0.5 + 0.5 * math.cos((t - 0.5) * 2.8))
        raw_h = rng.uniform(4, height * 0.92) * envelope * beat_pulse
        h = max(3.0, min(height - 2, raw_h))
        x = i * (bar_width + gap) + 1.0
        painter.drawLine(QPointF(x, mid_y - h / 2.0), QPointF(x, mid_y + h / 2.0))

    painter.end()
    _WAVEFORM_CACHE[cache_key] = pix
    return pix



def create_waveform_placeholder(width=140, height=22) -> QPixmap:
    """Генерирует аккуратную линию-плейсхолдер для еще не скачанных треков."""
    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#243142"))
    pen.setWidthF(1.5)
    pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)

    mid_y = height / 2.0
    painter.drawLine(QPointF(6.0, mid_y), QPointF(width - 6.0, mid_y))
    painter.end()
    return pix


_PLACEHOLDER_CACHE = {}


def get_cached_waveform_placeholder(width=150, height=22) -> QPixmap:
    """Кэширует и возвращает статический плейсхолдер вейвформа без повторной перерисовки."""
    key = (width, height)
    if key not in _PLACEHOLDER_CACHE:
        _PLACEHOLDER_CACHE[key] = create_waveform_placeholder(width, height)
    return _PLACEHOLDER_CACHE[key]


from media_utils import extract_bpm_meta


class SpeedMeterWidget(QWidget):
    """Мини-график скорости скачивания с динамической отрисовкой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self._history = [0.0] * 16

    def add_speed_point(self, speed_mb: float):
        self._history.pop(0)
        self._history.append(max(0.0, float(speed_mb)))
        self.update()

    def set_idle(self):
        self._history = [0.0] * 16
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # Фоновый контейнер
        painter.setBrush(QColor("#080D15"))
        painter.setPen(QPen(QColor("#151D2A"), 1))
        painter.drawRoundedRect(0, 0, int(w), int(h), 6, 6)

        max_val = max(max(self._history), 1.0)
        n = len(self._history)
        step_x = (w - 12.0) / max(1, n - 1)

        points = []
        for i, val in enumerate(self._history):
            x = 6.0 + i * step_x
            normalized_y = (val / max_val) * (h - 16.0)
            y = (h - 8.0) - normalized_y
            points.append(QPointF(x, y))

        path = QPainterPath()
        path.moveTo(points[0])
        for p in points[1:]:
            path.lineTo(p)

        # Градиентная неоновая заливка под кривой
        grad_path = QPainterPath(path)
        grad_path.lineTo(w - 6.0, h - 4.0)
        grad_path.lineTo(6.0, h - 4.0)
        grad_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, int(h))
        grad.setColorAt(0.0, QColor(0, 210, 190, 85))
        grad.setColorAt(0.6, QColor(0, 210, 190, 25))
        grad.setColorAt(1.0, QColor(0, 210, 190, 0))
        painter.fillPath(grad_path, grad)

        # Неоновая линия графика
        curve_pen = QPen(QColor("#00D2BE"), 2)
        painter.strokePath(path, curve_pen)

        # Точка на последнем значении
        last_pt = points[-1]
        if self._history[-1] > 0.05:
            painter.setBrush(QColor(0, 210, 190, 70))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(last_pt, 6.0, 6.0)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#00D2BE"), 1.5))
            painter.drawEllipse(last_pt, 2.5, 2.5)

        painter.end()


# Реэкспорт компонентов Bento Grid Studio для централизованного доступа
from ui.bento_widgets import (
    CamelotWheelWidget,
    TrackInspectorCard,
    create_track_artwork_placeholder,
)
