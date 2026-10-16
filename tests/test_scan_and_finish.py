"""Тесты на завершение сканирования и загрузки.

Обе функции закрывают рабочий цикл: гасят кнопки, возвращают статус,
чистят панель загрузок и -- важное -- регистрируют поток в
``_LINGERING_THREADS``, иначе Qt успевает уничтожить QThread на лету.
Именно поэтому ветки с ``sender()`` и оставшимися бейджами проверяются
отдельно.
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

    import gui
    from gui import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    gui._LINGERING_THREADS.clear()
    win.log = MagicMock()
    win.qr_dialog = None
    win._scan_results = []
    win.download_thread = None
    win._is_paginating = False
    win._track_status_badges = {}
    return win


def _badge(text):
    """Заглушка бейджа статуса: код читает text() и меняет оформление."""
    badge = MagicMock()
    badge.text.return_value = text
    return badge


def _qr():
    dialog = MagicMock()
    return dialog


class TestScanFinished:
    """Сканирование завершено: кнопки и статус приходят в порядок."""

    def test_buttons_return_to_idle(self, w):
        w._is_paginating = True
        w._scan_finished()
        assert w._is_paginating is False
        assert w.scan_button.isEnabled() is True
        assert w.stop_button.isEnabled() is False

    def test_status_is_pool_ready_when_results(self, w):
        w._scan_results = [{"id": 1}]
        w._scan_finished()
        assert w.status_badge.text() == "● POOL READY"

    def test_status_is_standby_when_empty(self, w):
        w._scan_results = []
        w._scan_finished()
        assert w.status_badge.text() == "● STANDBY"

    def test_thread_is_kept_alive_until_destroyed(self, w):
        """Поток обязан пережить выход из слота, иначе он умрёт на лету."""
        import gui

        thread = MagicMock()
        w.download_thread = thread
        w._scan_finished()

        assert thread in gui._LINGERING_THREADS
        assert w.download_thread is None

        finished_sig = thread.finished
        assert finished_sig.connect.called, \
            "поток должен сниматься с учёта по своему finished"

        handler = finished_sig.connect.call_args[0][0]
        handler()
        assert thread not in gui._LINGERING_THREADS

    def test_no_thread_leaves_nothing_behind(self, w):
        import gui

        w.download_thread = None
        w._scan_finished()
        assert gui._LINGERING_THREADS == set()

    def test_qr_dialog_is_closed(self, w):
        w.qr_dialog = _qr()
        dialog = w.qr_dialog
        w._scan_finished()
        dialog.close.assert_called_once()
        assert w.qr_dialog is None

    def test_bad_finished_signal_does_not_break_completion(self, w):
        """Поток без нормального сигнала finished не должен ломать слот."""

        class _OddThread:
            finished = None

        w.download_thread = _OddThread()
        w._scan_finished()
        assert w.scan_button.isEnabled() is True


class TestDownloadFinished:
    """Загрузка завершена: интерфейс возвращается в исходное состояние."""

    def test_logs_completion(self, w):
        w.download_finished()
        assert "Загрузка завершена" in w.log.call_args_list[0][0][0]

    def test_stale_badges_marked_failed(self, w):
        """Несохранённые треки не должны навсегда оставаться оранжевыми."""
        queued = _badge("QUEUED")
        downloading = _badge("DOWNLOADING 40%")
        w._track_status_badges = {1: queued, 2: downloading, 3: _badge("SAVED")}

        w.download_finished()

        queued.setText.assert_called_once_with("FAILED")
        downloading.setText.assert_called_once_with("FAILED")
        assert "Не сохранено треков: 2" in " ".join(
            c[0][0] for c in w.log.call_args_list)

    def test_no_stale_badges_no_warning(self, w):
        w._track_status_badges = {1: _badge("SAVED"), 2: _badge("FAILED")}
        w.download_finished()
        assert not any(
            "Не сохранено" in c[0][0] for c in w.log.call_args_list)

    def test_buttons_restored(self, w):
        w.download_finished()
        assert w.scan_button.isEnabled() is True
        assert w.stop_button.isEnabled() is False
        assert w.download_button.isEnabled() is False

    def test_download_enabled_when_results_present(self, w):
        w._scan_results = [{"id": 1}]
        w.download_finished()
        assert w.download_button.isEnabled() is True

    def test_thread_reference_cleared(self, w):
        w.download_thread = MagicMock()
        w.download_finished()
        assert w.download_thread is None

    def test_status_badge_completed(self, w):
        w.download_finished()
        assert w.status_badge.text() == "● COMPLETED"

    def test_qr_dialog_is_closed(self, w):
        w.qr_dialog = _qr()
        dialog = w.qr_dialog
        w.download_finished()
        dialog.close.assert_called_once()
        assert w.qr_dialog is None

    def test_stream_panel_is_cleared(self, w):
        label = MagicMock()
        w.stream_empty_lbl = label
        w.stream_widgets = [(MagicMock(), MagicMock(), MagicMock(), MagicMock())]
        w.speed_meter = MagicMock()

        w.download_finished()

        label.setText.assert_called_once_with("Все загрузки завершены")
        label.setVisible.assert_called_with(True)
        w.stream_widgets[0][0].setVisible.assert_called_with(False)
        w.speed_meter.set_idle.assert_called_once()
        assert w.spd_current.text() == "Current:   0.0 MB/s"
        assert w.thread_val.text() == "IDLE"
        assert w.thread_bar.value() == 0