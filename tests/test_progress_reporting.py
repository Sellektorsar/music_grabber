"""Тесты на отчёт о прогрессе загрузки.

``update_progress`` -- единственное место, где собирается весь прогресс:
полоса, счётчики, бейджи статусов у треков, панель активных загрузок,
индикатор потоков и скорость. Каждая ветка здесь соответствует тому,
что пользователь видит на экране, поэтому проверяется содержимое, а
не факт вызова.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def w(monkeypatch, tmp_path, qtbot):
    cfg_dir = tmp_path / "telegram_audio"
    cfg_dir.mkdir()
    monkeypatch.setattr("config.CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(cfg_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    from gui import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.log = MagicMock()
    win.download_thread = None
    win._track_status_badges = {}
    win._track_waveforms = {}
    win._track_row_by_id = {}
    win._scan_results = []
    win._update_storage_stats = MagicMock()
    return win


def _progress(w, **kw):
    base = {
        "total_scanned": 0, "audio_found": 0, "downloaded": 0,
        "skipped": 0, "already_exists": 0, "total_tasks": 0,
        "eta_seconds": 0, "current_file": "", "active_downloads": [],
    }
    base.update(kw)
    w.update_progress(base)


class TestProgressBar:
    """Полоса показывается только когда есть чем мерить."""

    def test_shown_with_percent(self, w):
        _progress(w, total_tasks=10, downloaded=3, audio_found=10)
        assert w.progress_bar.value() == 30
        assert w.progress_bar.isVisibleTo(w.progress_bar.parentWidget())

    def test_zero_tasks_keeps_bar_hidden(self, w):
        w.progress_bar.setVisible(False)
        _progress(w, total_tasks=0, downloaded=0)
        assert w.progress_bar.isVisibleTo(w.progress_bar.parentWidget()) is False

    def test_progress_survives_zero_download(self, w):
        """total_tasks > 0, но ничего ещё не скачано -- полоса есть."""
        _progress(w, total_tasks=5, downloaded=0, audio_found=5)
        assert w.progress_bar.value() == 0


class TestProgressLabel:
    """Подпись собирается из счётчиков сканирования и загрузки."""

    def _text(self, w):
        return w.progress_label.text()

    def test_counters_present(self, w):
        _progress(w, total_scanned=120, audio_found=40, downloaded=7,
                  skipped=3, already_exists=2, total_tasks=35)
        text = self._text(w)
        assert "Просмотрено: 120" in text
        assert "Аудио: 40" in text
        assert "Загружено: 7/35" in text
        assert "Пропущено: 3" in text
        assert "Уже есть: 2" in text

    def test_eta_formatted(self, w):
        _progress(w, eta_seconds=125)
        assert "ETA: 2 мин 5 сек" in self._text(w)

    def test_eta_dash_when_unknown(self, w):
        _progress(w, eta_seconds=0)
        assert "ETA: —" in self._text(w)

    def test_current_file_shown(self, w):
        _progress(w, current_file="Zivert - GAZ.mp3")
        assert "Файл: Zivert - GAZ.mp3" in self._text(w)

    def test_no_file_suffix_when_empty(self, w):
        _progress(w, current_file="")
        assert "Файл:" not in self._text(w)

    def test_counter_total_never_negative(self, w):
        """Пропущенные и имеющиеся не могут сделать итог отрицательным."""
        _progress(w, audio_found=1, already_exists=5, skipped=5, total_tasks=0)
        assert "Загружено: 0/0" in self._text(w)
        assert "-9" not in self._text(w)


class TestTrackStatusBadges:
    """Бейджи статусов у строк треков."""

    def test_downloading_badge_with_percent(self, w):
        badge = MagicMock()
        w._track_status_badges[555] = badge
        _progress(w, active_downloads=[{"id": 555, "percent": 42}])
        badge.setText.assert_called_once_with("DOWNLOADING 42%")
        assert "активно скачивается" in badge.setToolTip.call_args[0][0]

    def test_downloading_badge_without_percent(self, w):
        badge = MagicMock()
        w._track_status_badges[555] = badge
        _progress(w, active_downloads=[{"id": 555, "percent": 0}])
        badge.setText.assert_called_once_with("DOWNLOADING")

    def test_unknown_id_is_ignored(self, w):
        _progress(w, active_downloads=[{"id": 999, "percent": 10}])

    def test_entry_without_id_is_ignored(self, w):
        _progress(w, active_downloads=[{"percent": 10}])

    def test_completed_badge_marks_row_as_existing(self, w):
        """Скачанный трек помечается в данных, а не только в бейдже."""
        badge = MagicMock()
        wave = MagicMock()
        w._track_status_badges[7] = badge
        w._track_waveforms[7] = wave
        w._track_row_by_id[7] = 1
        w._scan_results = [{"title": "A"}, {"title": "B"}]

        _progress(w, last_completed_id=7)

        badge.setText.assert_called_once_with("SAVED")
        assert "успешно скачан" in badge.setToolTip.call_args[0][0]
        assert w._scan_results[1]["already_exists"] is True
        wave.setToolTip.assert_called_once_with("Файл сохранен на диске")

    def test_completed_row_index_out_of_range_is_safe(self, w):
        """Индекс из прошлой выборки не должен ронять обновление."""
        w._track_status_badges[7] = MagicMock()
        w._track_row_by_id[7] = 99
        w._scan_results = [{"title": "A"}]
        _progress(w, last_completed_id=7)

    def test_completed_without_waveform_is_safe(self, w):
        w._track_status_badges[7] = MagicMock()
        _progress(w, last_completed_id=7)

    def test_failed_ids_list_marks_badges(self, w):
        first = MagicMock()
        second = MagicMock()
        w._track_status_badges.update({1: first, 2: second})
        _progress(w, failed_ids=[1, 2])
        first.setText.assert_called_once_with("FAILED")
        second.setText.assert_called_once_with("FAILED")
        assert "Не удалось скачать" in first.setToolTip.call_args[0][0]

    def test_last_failed_id_used_as_fallback(self, w):
        """Поток шлёт последний id по одному -- он тоже должен учитываться."""
        badge = MagicMock()
        w._track_status_badges[3] = badge
        _progress(w, last_failed_id=3)
        badge.setText.assert_called_once_with("FAILED")

    def test_explicit_failed_list_wins_over_last(self, w):
        badge = MagicMock()
        w._track_status_badges[3] = badge
        _progress(w, failed_ids=[], last_failed_id=3)
        badge.setText.assert_called_once_with("FAILED")


class TestActiveDownloadsPanel:
    """Правая панель ACTIVE DOWNLOADS."""

    def _streams(self, w, count):
        """Заглушки виджетов панели: код вызывает только эти четыре метода."""
        widgets = []
        for _ in range(count):
            widgets.append((MagicMock(), MagicMock(), MagicMock(), MagicMock()))
        w.stream_widgets = widgets
        return widgets

    def _empty_label(self, w):
        """Метки Qt -- не mock, поэтому подменяем сам виджет."""
        label = MagicMock()
        w.stream_empty_lbl = label
        return label

    def test_idle_shows_placeholder(self, w):
        self._streams(w, 2)
        _progress(w, active_downloads=[])
        assert w.stream_empty_lbl.text() == "Нет активных загрузок"

    def test_waiting_for_threads_message(self, w):
        """Поток запущен, но загрузок нет -- это другое сообщение."""
        self._streams(w, 2)
        w.download_thread = MagicMock()
        _progress(w, active_downloads=[])
        assert w.stream_empty_lbl.text() == "Ожидание потоков..."

    def test_widgets_filled(self, w):
        widgets = self._streams(w, 1)
        container, lbl, spd, pbar = widgets[0]
        _progress(w, active_downloads=[{
            "filename": "Zivert - GAZ.mp3", "speed": 1.25, "percent": 60,
        }])
        container.setVisible.assert_called_with(True)
        lbl.setText.assert_called_once_with("Zivert - GAZ.mp3")
        lbl.setToolTip.assert_called_once_with("Zivert - GAZ.mp3")
        spd.setText.assert_called_once_with("1.2 MB/s")
        pbar.setValue.assert_called_once_with(60)

    def test_long_filename_is_shortened(self, w):
        """Длинное имя не должно ломать вёрстку панели."""
        widgets = self._streams(w, 1)
        long_name = "Very Long Artist Name - Extremely Long Track Title.mp3"
        _progress(w, active_downloads=[{"filename": long_name, "speed": 0.0}])
        shown = widgets[0][1].setText.call_args[0][0]
        assert shown.endswith("…")
        assert len(shown) <= 21

    def test_short_filename_is_untouched(self, w):
        widgets = self._streams(w, 1)
        _progress(w, active_downloads=[{"filename": "Short.mp3"}])
        widgets[0][1].setText.assert_called_once_with("Short.mp3")

    def test_spare_widgets_are_hidden(self, w):
        widgets = self._streams(w, 3)
        _progress(w, active_downloads=[{"filename": "a.mp3"}])
        widgets[2][0].setVisible.assert_called_with(False)

    def test_placeholder_hidden_while_loading(self, w):
        label = self._empty_label(w)
        self._streams(w, 1)
        _progress(w, active_downloads=[{"filename": "a.mp3"}])
        label.setVisible.assert_called_with(False)


class TestThreadAndSpeedIndicators:
    """Индикатор потоков и счётчики скорости."""

    def _max_threads(self, w, value):
        w.threads_spin.setValue(value)

    def test_idle_when_no_downloads(self, w):
        self._max_threads(w, 3)
        _progress(w, active_downloads=[])
        assert w.thread_val.text() == "IDLE"
        assert w.thread_bar.value() == 0

    def test_active_count_and_load(self, w):
        self._max_threads(w, 4)
        _progress(w, active_downloads=[{"id": 1}, {"id": 2}])
        assert w.thread_val.text() == "2/4"
        assert w.thread_bar.value() == 50

    def test_full_load(self, w):
        self._max_threads(w, 2)
        _progress(w, active_downloads=[{"id": 1}, {"id": 2}])
        assert w.thread_bar.value() == 100

    def test_speed_summed_across_downloads(self, w):
        _progress(w, active_downloads=[{"speed": 1.5}, {"speed": 2.25}])
        assert w.spd_current.text() == "Current:   3.8 MB/s"

    def test_speed_meter_receives_point(self, w):
        w.speed_meter = MagicMock()
        _progress(w, active_downloads=[{"speed": 3.0}])
        w.speed_meter.add_speed_point.assert_called_once_with(3.0)

    def test_total_downloads_counter(self, w):
        _progress(w, downloaded=17)
        assert w.spd_total.text() == "Total DL:  17 треков"

    def test_storage_stats_refreshed(self, w):
        _progress(w)
        w._update_storage_stats.assert_called()