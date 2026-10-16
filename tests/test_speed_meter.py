"""Тесты на график скорости SpeedMeterWidget.

Отрисовка проверяется не вызовом, а результатом: виджет рендерится в
QPixmap, и по пикселям видно, что при ненулевой скорости появляется
светящаяся линия, а в простое её нет. Так ловятся и ошибки геометрии
(деление на ноль на пустой истории), и молчаливый пустой виджет.
"""

from PyQt6.QtGui import QImage

from ui.widgets import SpeedMeterWidget

HISTORY_LEN = 16


def _render(widget, width=160, height=50):
    """Рисует виджет и возвращает яркость пикселей."""
    widget.resize(width, height)
    pixmap = widget.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    total = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            color = image.pixelColor(x, y)
            total += color.red() + color.green() + color.blue()
    return total


class TestHistory:
    """Буфер измерений: фиксированная длина и сдвиг окна."""

    def test_starts_flat_at_zero(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        assert meter._history == [0.0] * HISTORY_LEN

    def test_height_is_fixed(self, qtbot):
        """Виджет не должен прыгать по высоте при обновлениях."""
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        assert meter.height() == 50

    def test_new_point_shifts_window(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        meter.add_speed_point(2.5)
        assert meter._history[-1] == 2.5
        assert meter._history[:-1] == [0.0] * (HISTORY_LEN - 1)

    def test_old_values_scroll_out(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        for speed in (1.0, 2.0, 3.0):
            meter.add_speed_point(speed)
        assert meter._history[-3:] == [1.0, 2.0, 3.0]
        assert len(meter._history) == HISTORY_LEN

    def test_negative_speed_is_clamped(self, qtbot):
        """Отрицательное значение не должно рисоваться вверх от нуля."""
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        meter.add_speed_point(-5.0)
        assert meter._history[-1] == 0.0

    def test_idle_clears_buffer(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        for speed in (1.0, 2.0, 3.0):
            meter.add_speed_point(speed)
        meter.set_idle()
        assert meter._history == [0.0] * HISTORY_LEN


class TestPainting:
    """Отрисовка должна давать картинку и не падать на вырожденных размерах."""

    def test_idle_renders_background(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        assert _render(meter) > 0, "фон графика должен быть отрисован"

    def test_active_line_is_brighter_than_idle(self, qtbot):
        """При скорости появляется неоновая линия -- это и есть смысл."""
        idle = SpeedMeterWidget()
        qtbot.addWidget(idle)

        active = SpeedMeterWidget()
        qtbot.addWidget(active)
        for _ in range(HISTORY_LEN):
            active.add_speed_point(4.0)

        assert _render(active) > _render(idle)

    def test_flat_nonzero_history_does_not_divide_by_zero(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        for _ in range(HISTORY_LEN):
            meter.add_speed_point(1.0)
        assert _render(meter) > 0

    def test_tiny_widget_does_not_crash(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        meter.add_speed_point(3.0)
        assert _render(meter, width=1, height=1) >= 0

    def test_narrow_widget_does_not_crash(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        for speed in (0.0, 1.0, 5.0):
            meter.add_speed_point(speed)
        assert _render(meter, width=8, height=50) >= 0

    def test_render_does_not_crash_after_idle(self, qtbot):
        meter = SpeedMeterWidget()
        qtbot.addWidget(meter)
        for speed in (2.0, 4.0):
            meter.add_speed_point(speed)
        meter.set_idle()
        assert _render(meter) > 0