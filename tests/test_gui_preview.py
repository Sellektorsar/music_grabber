"""Тесты на потоковое превью в главном окне.

Клик по треку без файла на диске поднимает отдельный поток, который
докачивает начало аудио и отдаёт его плееру. Здесь важны три вещи:
пользователь слышит именно тот трек, который нажал; превью помечено в
логе как превью; поток не остаётся висеть после завершения.
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
    win.play_audio_file = MagicMock()
    win._scan_results = []
    win.download_thread = None
    return win


class TestPreviewReady:
    """Превью пришло из потока."""

    def test_empty_path_is_ignored(self, w):
        w._on_preview_ready(42, None)
        w.play_audio_file.assert_not_called()

    def test_known_track_is_announced_by_name(self, w):
        """Пользователь должен слышать название, а не номер id."""
        w._scan_results = [{"id": 42, "performer": "Zivert", "title": "GAZ"}]
        w._on_preview_ready(42, "C:/cache/preview_42.mp3")
        w.play_audio_file.assert_called_once()
        assert "Zivert - GAZ" in w.play_audio_file.call_args.kwargs["title"]
        assert "PREVIEW" in w.play_audio_file.call_args.kwargs["title"]

    def test_unknown_track_is_announced_by_id(self, w):
        """Трека нет в результатах скана -- подойдёт его номер."""
        w._on_preview_ready(77, "C:/cache/preview_77.mp3")
        assert "77" in w.play_audio_file.call_args.kwargs["title"]

    def test_play_is_logged(self, w):
        w._scan_results = [{"id": 42, "performer": "Zivert", "title": "GAZ"}]
        w._on_preview_ready(42, "C:/cache/preview_42.mp3")
        assert any("потокового превью" in c[0][0] for c in w.log.call_args_list)

    def test_missing_artist_does_not_leave_dashes(self, w):
        """Без артиста строка не должна выглядеть как « - GAZ»."""
        w._scan_results = [{"id": 42, "performer": "", "title": "GAZ"}]
        w._on_preview_ready(42, "C:/cache/preview_42.mp3")
        title = w.play_audio_file.call_args.kwargs["title"]
        assert " - " not in title


class TestPreviewFinished:
    """Поток превью завершён и должен быть убран."""

    def _thread(self, w, track_id=42):
        thread = MagicMock()
        thread.preview_track_id = track_id
        w.download_thread = thread
        return thread

    def test_thread_is_kept_alive_until_destroyed(self, w):
        """Поток нельзя терять: Qt уничтожит QThread на лету."""
        import gui

        thread = self._thread(w)
        w._on_preview_finished()

        assert thread in gui._LINGERING_THREADS
        assert w.download_thread is None
        thread.finished.connect.assert_called()

    def test_thread_is_released_on_finish(self, w):
        import gui

        thread = self._thread(w)
        w._on_preview_finished()
        handler = thread.finished.connect.call_args[0][0]
        handler()
        assert thread not in gui._LINGERING_THREADS

    def test_scan_thread_is_left_alone(self, w):
        """Без preview_track_id поток обычный -- его не трогаем."""
        thread = self._thread(w, track_id=None)
        w._on_preview_finished()
        assert w.download_thread is thread

    def test_no_thread_is_safe(self, w):
        w.download_thread = None
        w._on_preview_finished()   # не должно поднять исключение

    def test_odd_finished_signal_does_not_break_cleanup(self, w):
        """Поток без нормального finished не должен мешать уборке."""

        class _Odd:
            preview_track_id = 5
            finished = None

        w.download_thread = _Odd()
        w._on_preview_finished()
        assert w.download_thread is None