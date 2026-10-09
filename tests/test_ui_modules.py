"""
Unit tests for modular ui/ package (theme, dialogs, widgets, player, views).
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget
from ui.theme import DARK_STYLESHEET
from ui.widgets import (
    create_beatstorm_logo_pixmap,
    create_user_avatar_pixmap,
    create_waveform_pixmap,
    create_waveform_placeholder,
    get_cached_waveform_placeholder,
    extract_bpm_meta,
    SpeedMeterWidget,
    _WAVEFORM_CACHE,
    _PLACEHOLDER_CACHE,
)
from ui.dialogs import (
    is_ffmpeg_available,
    InputCodeDialog,
    QRCodeDialog,
    ProxySettingsDialog,
)
from ui.player import AudioPlayerBar
from ui.views import create_home_view, create_channels_view


class TestTheme:
    def test_stylesheet_content(self):
        assert isinstance(DARK_STYLESHEET, str)
        assert len(DARK_STYLESHEET) > 500
        assert "#panelCard" in DARK_STYLESHEET
        assert "#primaryButton" in DARK_STYLESHEET
        assert "QTreeWidget" in DARK_STYLESHEET
        assert "#bentoCard" in DARK_STYLESHEET
        assert "#bentoMetricCard" in DARK_STYLESHEET
        assert "#bentoTitle" in DARK_STYLESHEET
        assert "#bentoKeyPill" in DARK_STYLESHEET
        assert "#bentoKeyPillActive" in DARK_STYLESHEET
        assert "#bentoKeyPillHarmonic" in DARK_STYLESHEET


class TestWidgets:
    def test_logo_pixmap(self, qtbot):
        pix = create_beatstorm_logo_pixmap()
        assert not pix.isNull()
        assert pix.width() == 28
        assert pix.height() == 28

    def test_user_avatar_pixmap(self, qtbot):
        pix = create_user_avatar_pixmap()
        assert not pix.isNull()
        assert pix.width() == 24
        assert pix.height() == 24

    def test_waveform_pixmap_and_cache(self, qtbot):
        pix1 = create_waveform_pixmap(140, 22, "#00D2BE", seed=42)
        assert not pix1.isNull()
        assert pix1.width() == 140
        assert pix1.height() == 22
        # Caching returns the same object for same key
        pix2 = create_waveform_pixmap(140, 22, "#00D2BE", seed=42)
        assert pix1 is pix2

    def test_waveform_placeholder_and_cache(self, qtbot):
        pix1 = get_cached_waveform_placeholder(150, 22)
        assert not pix1.isNull()
        assert pix1.width() == 150
        pix2 = get_cached_waveform_placeholder(150, 22)
        assert pix1 is pix2

    def test_extract_bpm_meta(self):
        assert extract_bpm_meta("Dance Groove 126 bpm", "Artist") == "126"
        assert extract_bpm_meta("[128] Track Club Mix", "DJ") == "128"
        assert extract_bpm_meta("Regular Track Title", "Artist") == "—"

    def test_speed_meter_widget(self, qtbot):
        widget = SpeedMeterWidget()
        qtbot.addWidget(widget)
        assert widget.height() == 50
        widget.add_speed_point(2.5)
        assert widget._history[-1] == 2.5
        widget.set_idle()
        assert widget._history[-1] == 0.0


class TestDialogs:
    def test_ffmpeg_available(self):
        result = is_ffmpeg_available()
        assert isinstance(result, bool)

    def test_input_code_dialog(self, qtbot):
        dlg = InputCodeDialog("Введите код:")
        qtbot.addWidget(dlg)
        assert dlg.label.text() == "Введите код:"
        dlg.input.setText("12345")
        received = []
        dlg.code_entered.connect(received.append)
        dlg.on_accept()
        assert received == ["12345"]

    def test_qr_code_dialog(self, qtbot):
        dlg = QRCodeDialog("tg://login?token=abc123xyz")
        qtbot.addWidget(dlg)
        assert not dlg.image_label.pixmap().isNull()

    def test_proxy_settings_dialog(self, qtbot):
        dlg = ProxySettingsDialog()
        qtbot.addWidget(dlg)
        cfg = {
            "enabled": True,
            "type": "socks5",
            "host": "127.0.0.1",
            "port": 1080,
            "username": "user",
            "password": "pass",
        }
        dlg.set_proxy_config(cfg)
        saved = dlg.get_proxy_config()
        assert saved["enabled"] is True
        assert saved["host"] == "127.0.0.1"
        assert saved["port"] == "1080"


class TestAudioPlayerBar:
    def test_format_time_ms(self):
        assert AudioPlayerBar.format_time_ms(0) == "00:00"
        assert AudioPlayerBar.format_time_ms(61000) == "01:01"
        assert AudioPlayerBar.format_time_ms(360000) == "06:00"

    def test_player_bar_init_and_controls(self, qtbot):
        logs = []
        bar = AudioPlayerBar(log_callback=logs.append)
        qtbot.addWidget(bar)
        assert bar.isHidden() is True
        assert bar.btn_play_pause.text() == "▶"
        assert bar.volume_slider.value() == 80

        # Try to play nonexistent file
        bar.play_audio_file("nonexistent.mp3")
        assert any("Файл не найден" in msg for msg in logs)


class TestViews:
    def test_views_creation(self, qtbot):
        mock_window = QWidget()
        mock_window.switch_tab = lambda t: None
        mock_window.start_scan = lambda: None
        mock_window.open_download_folder = lambda: None
        mock_window._on_recent_table_double_clicked = lambda it: None
        mock_window._add_channel_from_manager = lambda: None

        home_widget = create_home_view(mock_window)
        qtbot.addWidget(home_widget)
        # Backward compatibility attributes
        assert hasattr(mock_window, "home_tracks_val")
        assert hasattr(mock_window, "home_chan_val")
        assert hasattr(mock_window, "home_disk_val")
        assert hasattr(mock_window, "home_api_val")
        assert hasattr(mock_window, "home_recent_table")

        # Bento Studio specific elements
        assert hasattr(mock_window, "home_dup_val")
        assert hasattr(mock_window, "home_hq_val")
        assert hasattr(mock_window, "home_disk_bar")
        assert hasattr(mock_window, "camelot_wheel")
        assert hasattr(mock_window, "track_inspector")
        assert hasattr(mock_window, "home_speed_meter")
        assert hasattr(mock_window, "home_search_input")
        assert hasattr(mock_window, "home_btn_play_selected")

        chans_widget = create_channels_view(mock_window)
        qtbot.addWidget(chans_widget)
        assert hasattr(mock_window, "chan_view_input")
        assert hasattr(mock_window, "channels_mgr_table")

    def test_bento_grid_studio_interactions(self, qtbot):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt

        clicked_tracks = []
        mock_window = QWidget()
        mock_window.switch_tab = lambda t: None
        mock_window.start_scan = lambda: None
        mock_window.open_download_folder = lambda: None
        mock_window._on_recent_table_double_clicked = lambda it: clicked_tracks.append(it.text())
        mock_window._add_channel_from_manager = lambda: None

        home_widget = create_home_view(mock_window)
        qtbot.addWidget(home_widget)

        # Populate test tracks in recent table
        table = mock_window.home_recent_table
        table.setRowCount(2)
        it1 = QTableWidgetItem("Techno Anthem [8A]")
        it1.setData(Qt.ItemDataRole.UserRole, "c:/music/track1.mp3")
        it2 = QTableWidgetItem("House Groove [5B]")
        it2.setData(Qt.ItemDataRole.UserRole, "c:/music/track2.mp3")
        table.setItem(0, 0, it1)
        table.setItem(0, 1, QTableWidgetItem("Producer A"))
        table.setItem(0, 2, QTableWidgetItem("kutsuevpool"))
        table.setItem(0, 3, QTableWidgetItem("track1.mp3"))

        table.setItem(1, 0, it2)
        table.setItem(1, 1, QTableWidgetItem("Producer B"))
        table.setItem(1, 2, QTableWidgetItem("kutsuevpool"))
        table.setItem(1, 3, QTableWidgetItem("track2.mp3"))

        # Test Search filtering
        mock_window.home_search_input.setText("Techno")
        assert table.isRowHidden(0) is False
        assert table.isRowHidden(1) is True

        mock_window.home_search_input.clear()
        assert table.isRowHidden(0) is False
        assert table.isRowHidden(1) is False

        # Test Camelot Harmonic Filtering (select 8A -> 8A, 7A, 9A, 8B compatible, 5B hidden)
        mock_window.camelot_wheel.highlight_compatible("8A")
        mock_window.camelot_wheel.key_selected.emit("8A")
        assert table.isRowHidden(0) is False
        assert table.isRowHidden(1) is True

        # Clear key filter -> all visible
        mock_window.camelot_wheel.clear_selection()
        assert table.isRowHidden(0) is False
        assert table.isRowHidden(1) is False

        # Test Inline Play / Preview button
        table.selectRow(0)
        mock_window.home_btn_play_selected.click()
        assert len(clicked_tracks) == 1
        assert clicked_tracks[0] == "Techno Anthem [8A]"

        # Test Track Inspector update on selection
        inspector = mock_window.track_inspector
        assert inspector.input_title.text() == "Techno Anthem [8A]"
        assert inspector.input_artist.text() == "Producer A"


class TestPanels:
    def test_deck_header_creation(self, qtbot):
        from ui.navbar import setup_deck_header

        mock = QWidget()
        mock.switch_tab = lambda t: None
        mock._filter_tracks_text = lambda txt: None
        mock._toggle_api_settings = lambda: None

        header = setup_deck_header(mock)
        qtbot.addWidget(header)
        assert hasattr(mock, "deck_header")
        assert hasattr(mock, "tab_home")
        assert hasattr(mock, "tab_channels")
        assert hasattr(mock, "tab_library")
        assert hasattr(mock, "top_search_input")

    def test_api_drawer_and_sidebar_creation(self, qtbot):
        from ui.sidebar import setup_api_drawer, setup_channels_sidebar

        mock = QWidget()
        mock._save_settings_with_feedback = lambda: None
        mock._on_setting_changed = lambda: None
        mock._toggle_api_settings = lambda: None
        mock._prompt_add_channel = lambda: None
        mock._remove_selected_channel = lambda: None
        mock._select_all_channels_view = lambda: None
        mock._show_channel_context_menu = lambda pos: None
        mock._on_saved_channel_clicked = lambda it: None
        mock._init_saved_channels = lambda: None
        mock._preset_dates_all = lambda: None
        mock._preset_dates_30d = lambda: None

        drawer = setup_api_drawer(mock)
        qtbot.addWidget(drawer)
        assert hasattr(mock, "api_group")
        assert hasattr(mock, "api_id_input")
        assert hasattr(mock, "api_hash_input")

        sidebar = setup_channels_sidebar(mock)
        qtbot.addWidget(sidebar)
        assert hasattr(mock, "left_panel")
        assert hasattr(mock, "saved_channels_list")
        assert hasattr(mock, "scan_button")

    def test_download_monitor_creation(self, qtbot):
        from ui.monitor import setup_download_monitor

        mock = QWidget()
        mock._toggle_log = lambda: None

        monitor = setup_download_monitor(mock)
        qtbot.addWidget(monitor)
        assert hasattr(mock, "right_panel")
        assert hasattr(mock, "speed_meter")
        assert hasattr(mock, "log_output")
        assert len(mock.stream_widgets) == 5

    def test_library_panel_creation(self, qtbot):
        from ui.library import setup_library_panel

        mock = QWidget()
        mock._toggle_filter_bar = lambda: None
        mock.start_scan = lambda: None
        mock._expand_all_groups = lambda: None
        mock._collapse_all_groups = lambda: None
        mock._select_only_new_tracks = lambda: None
        mock._select_all_tracks = lambda: None
        mock._clear_selection = lambda: None
        mock._filter_tracks_text = lambda txt: None
        mock._on_tree_item_double_clicked = lambda it, col: None
        mock._on_tree_item_changed = lambda it, col: None
        mock._on_tree_scroll = lambda val: None
        mock._load_more_tracks = lambda: None
        mock._update_download_button_counter = lambda: None
        mock._on_track_double_clicked = lambda it: None
        mock.open_download_folder = lambda: None

        panel = setup_library_panel(mock)
        qtbot.addWidget(panel)
        assert hasattr(mock, "center_panel")
        assert hasattr(mock, "library_tree")
        assert hasattr(mock, "library_table")
        assert hasattr(mock, "btn_lib_sync")
        assert hasattr(mock, "btn_load_more")
        assert hasattr(mock, "search_filter_input")
        assert mock.library_tree.columnCount() == 8


class TestControllers:
    def test_channels_controller_storage(self, tmp_path, monkeypatch):
        from ui.controllers.channels_controller import (
            DEFAULT_CHANNELS,
            load_saved_channels,
            save_saved_channels,
        )

        assert len(DEFAULT_CHANNELS) > 0
        monkeypatch.chdir(tmp_path)

        chans = ["@chan1", "@chan2"]
        save_saved_channels(chans)
        loaded = load_saved_channels()
        assert loaded == chans

    def test_tree_controller_mixin(self, qtbot):
        from ui.controllers.tree_controller import TreeControllerMixin
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
        from PyQt6.QtCore import Qt

        class DummyTree(QWidget, TreeControllerMixin):
            def __init__(self):
                super().__init__()
                self.library_tree = QTreeWidget()

        dt = DummyTree()
        qtbot.addWidget(dt)
        dt._expand_all_groups()
        dt._collapse_all_groups()
        assert dt.library_tree is not None

        item = QTreeWidgetItem(dt.library_tree)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        dt.toggle_item_check_state(item)
        assert item.checkState(0) == Qt.CheckState.Checked
        dt.toggle_item_check_state(item)
        assert item.checkState(0) == Qt.CheckState.Unchecked

    def test_player_bar_seek_relative(self, qtbot):
        from ui.player import AudioPlayerBar

        player_bar = AudioPlayerBar()
        qtbot.addWidget(player_bar)
        # Mock player position
        if player_bar._player:
            player_bar.seek_relative(5000)
            player_bar.seek_relative(-5000)
        else:
            # Safe call even if QtMultimedia isn't active
            player_bar.seek_relative(1000)

    def test_dj_hotkeys_handling(self, qtbot, monkeypatch):
        import gui
        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QLineEdit, QTreeWidgetItem

        win = gui.MainWindow()
        qtbot.addWidget(win)

        # 1. When text input is focused, typing Space / Shift+D / X should not trigger DJ hotkeys
        line_edit = QLineEdit(win)
        line_edit.setFocus()
        ev_space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ")
        win.keyPressEvent(ev_space)

        # 2. When not focused on input, Shift+C clears search
        win.setFocus()
        win.top_search_input.setText("electronic")
        ev_shift_c = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
        win.keyPressEvent(ev_shift_c)
        assert win.top_search_input.text() == ""

        # 3. Shift+D triggers start_download
        download_called = []
        win.start_download = lambda: download_called.append(True)
        ev_shift_d = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_D, Qt.KeyboardModifier.ShiftModifier)
        win.keyPressEvent(ev_shift_d)
        assert len(download_called) == 1

        # 4. Left / Right arrows trigger seek_relative
        seek_deltas = []
        win.player_bar.seek_relative = lambda d: seek_deltas.append(d)
        ev_left = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        win.keyPressEvent(ev_left)
        assert seek_deltas == [-10000]
        ev_right = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        win.keyPressEvent(ev_right)
        assert seek_deltas == [-10000, 10000]

        # 5. X / Enter toggles check state on current item
        top_item = QTreeWidgetItem(win.library_tree)
        top_item.setCheckState(0, Qt.CheckState.Unchecked)
        win.library_tree.setCurrentItem(top_item)
        ev_x = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier)
        win.keyPressEvent(ev_x)
        assert top_item.checkState(0) == Qt.CheckState.Checked
        ev_enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        win.keyPressEvent(ev_enter)
        assert top_item.checkState(0) == Qt.CheckState.Unchecked


    def test_download_controller_validation(self, qtbot, monkeypatch):
        from ui.controllers.download_controller import DownloadControllerMixin
        from PyQt6.QtWidgets import QLineEdit, QComboBox

        class DummyDownloader(QWidget, DownloadControllerMixin):
            def __init__(self):
                super().__init__()
                self.api_id_input = QLineEdit()
                self.api_hash_input = QLineEdit()
                self.channel_input = QLineEdit()
                self.mode_combo = QComboBox()
                self.date_from_input = QLineEdit()
                self.date_to_input = QLineEdit()

            def _save_settings(self):
                pass

        dd = DummyDownloader()
        qtbot.addWidget(dd)
        # Empty inputs should return None
        monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", lambda *a, **k: None)
        assert dd._validate_inputs() is None

    def test_dj_filters_toolbar(self, qtbot):
        import gui

        win = gui.MainWindow()
        qtbot.addWidget(win)

        assert hasattr(win, "combo_filter_status")
        assert hasattr(win, "combo_filter_duration")
        assert hasattr(win, "combo_filter_bpm")
        assert hasattr(win, "combo_filter_bitrate")
        assert hasattr(win, "btn_reset_filters")

        # 1. Duration filter check
        t_dj = {"title": "Hit", "performer": "DJ", "duration": 300}
        t_short = {"title": "Jingle", "performer": "DJ", "duration": 45}
        assert win._check_track_filter_match(t_dj, "", "", 0, 1, 0, 0) is True
        assert win._check_track_filter_match(t_short, "", "", 0, 1, 0, 0) is False

        # 2. Status filter check
        t_dup = {"title": "A", "performer": "B", "is_duplicate": True, "already_exists": True}
        t_new = {"title": "A", "performer": "B", "is_duplicate": False, "already_exists": False}
        assert win._check_track_filter_match(t_dup, "", "", 3, 0, 0, 0) is True
        assert win._check_track_filter_match(t_new, "", "", 3, 0, 0, 0) is False

        # 3. BPM filter check
        t_house = {"title": "Track [126 BPM]", "performer": "Producer"}
        t_dnb = {"title": "Track [174 BPM]", "performer": "Producer"}
        assert win._check_track_filter_match(t_house, "", "", 0, 0, 1, 0) is True
        assert win._check_track_filter_match(t_house, "", "", 0, 0, 4, 0) is False
        assert win._check_track_filter_match(t_dnb, "", "", 0, 0, 4, 0) is True

        # 4. Bitrate filter check
        t_hq = {"title": "Track", "filename": "Artist - Track [320 kbps].mp3", "size": 10000000}
        assert win._check_track_filter_match(t_hq, "", "", 0, 0, 0, 1) is True

        # 5. Reset filters
        win.combo_filter_status.setCurrentIndex(2)
        win.combo_filter_bpm.setCurrentIndex(3)
        win._reset_dj_filters()
        assert win.combo_filter_status.currentIndex() == 0
        assert win.combo_filter_bpm.currentIndex() == 0

    def test_export_m3u8_ui(self, qtbot, tmp_path):
        import gui

        win = gui.MainWindow()
        qtbot.addWidget(win)

        assert hasattr(win, "btn_export_m3u8")
        assert hasattr(win, "export_selected_to_m3u8")

        # Fake scanned tracks
        t1 = {"id": 1, "filepath": str(tmp_path / "a.mp3"), "performer": "DJ A", "title": "Track A", "duration": 180}
        t2 = {"id": 2, "filepath": str(tmp_path / "b.mp3"), "performer": "DJ B", "title": "Track B", "duration": 220}
        win._scan_results = [t1, t2]

        out_pl = tmp_path / "test_out.m3u8"
        result = win.export_selected_to_m3u8(target_filepath=str(out_pl))
        assert result == str(out_pl.resolve())
        assert out_pl.exists()
        content = out_pl.read_text(encoding="utf-8")
        assert "#EXTM3U" in content
        assert "DJ A - Track A" in content
        assert "DJ B - Track B" in content


class TestSystemTrayAndBackgroundWatcher:
    """Тестирование системного трея, всплывающих уведомлений и фонового наблюдателя каналов."""

    def test_system_tray_initialized(self, qtbot):
        import gui
        from PyQt6.QtWidgets import QSystemTrayIcon

        win = gui.MainWindow()
        qtbot.addWidget(win)

        assert hasattr(win, "tray_icon")
        assert isinstance(win.tray_icon, QSystemTrayIcon)
        assert "BEATSTORM" in win.tray_icon.toolTip()
        menu = win.tray_icon.contextMenu()
        assert menu is not None
        actions = [a.text() for a in menu.actions() if a.text()]
        assert any("Показать" in a for a in actions)
        assert any("Скрыть" in a for a in actions)
        assert any("Фоновый мониторинг" in a for a in actions)
        assert any("Проверить" in a for a in actions)
        assert any("Выход" in a for a in actions)

    def test_show_tray_notification(self, qtbot, monkeypatch):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)

        mock_show = MagicMock()
        monkeypatch.setattr(win.tray_icon, "showMessage", mock_show)

        win.show_tray_notification("BEATSTORM", "Test Notification")
        mock_show.assert_called_once()
        args, _ = mock_show.call_args
        assert args[0] == "BEATSTORM"
        assert args[1] == "Test Notification"

    def test_toggle_background_watcher(self, qtbot, monkeypatch):
        import gui

        win = gui.MainWindow()
        qtbot.addWidget(win)

        assert hasattr(win, "_watcher_timer")
        # Включаем мониторинг
        win.toggle_background_watcher(True)
        assert win._watcher_enabled is True
        assert win._watcher_timer.isActive()
        assert win.action_tray_watcher.isChecked() is True

        # Выключаем мониторинг
        win.toggle_background_watcher(False)
        assert win._watcher_enabled is False
        assert not win._watcher_timer.isActive()
        assert win.action_tray_watcher.isChecked() is False

    def test_close_event_minimizes_to_tray(self, qtbot, monkeypatch):
        import gui
        from PyQt6.QtGui import QCloseEvent

        win = gui.MainWindow()
        qtbot.addWidget(win)
        win.show()

        # Mock tray_icon.isVisible to True and minimize_to_tray to True
        monkeypatch.setattr(gui, "load_config", lambda: {"minimize_to_tray": True, "tray_notifications": True})
        monkeypatch.setattr(win.tray_icon, "isVisible", lambda: True)

        evt = QCloseEvent()
        win.closeEvent(evt)
        # Event should be ignored (window hidden instead of terminated)
        assert not evt.isAccepted()
        assert not win.isVisible()

        # Now force close (e.g. user selected 'Выход')
        win._force_close = True
        evt2 = QCloseEvent()
        win.closeEvent(evt2)
        assert evt2.isAccepted()

    def test_check_channel_updates_now(self, qtbot, monkeypatch):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)

        win._saved_channels = ["@TestChannel1", "@TestChannel2"]
        mock_scan = MagicMock()
        monkeypatch.setattr(win, "start_scan", mock_scan)

        win.check_channel_updates_now()
        mock_scan.assert_called_once_with(channels=["@TestChannel1", "@TestChannel2"], limit_per_channel=50)


class TestStreamingPreviewUI:
    """Тестирование UI потокового предпрослушивания (Feature 10)."""

    def test_play_or_preview_track_local_file(self, qtbot, monkeypatch, tmp_path):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"DATA")

        track = {"id": 1, "filepath": str(real_file), "performer": "Artist", "title": "Song"}
        mock_play = MagicMock()
        monkeypatch.setattr(win, "play_audio_file", mock_play)

        win.play_or_preview_track(track)
        mock_play.assert_called_once_with(str(real_file), title="Artist - Song")

    def test_play_or_preview_track_cached_preview(self, qtbot, monkeypatch, tmp_path):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)
        win.base_folder = str(tmp_path)

        preview_dir = tmp_path / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        cached_file = preview_dir / "preview_77.mp3"
        cached_file.write_bytes(b"PREVIEW_DATA" * 4000)

        track = {"id": 77, "filepath": str(tmp_path / "missing.mp3"), "performer": "DJ", "title": "Beat"}
        mock_play = MagicMock()
        monkeypatch.setattr(win, "play_audio_file", mock_play)

        win.play_or_preview_track(track)
        mock_play.assert_called_once_with(str(cached_file), title="⚡ [PREVIEW] DJ - Beat")

    def test_play_or_preview_track_starts_stream(self, qtbot, monkeypatch, tmp_path):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)
        win.base_folder = str(tmp_path)

        track = {"id": 88, "filepath": str(tmp_path / "missing.mp3"), "performer": "DJ", "title": "Banger", "channel": "@pool"}
        mock_stream = MagicMock()
        monkeypatch.setattr(win, "start_preview_stream", mock_stream)

        win.play_or_preview_track(track)
        mock_stream.assert_called_once_with("@pool", 88, "DJ - Banger")
        assert "Буферизация превью" in win.player_title_label.text()

    def test_on_preview_ready(self, qtbot, monkeypatch, tmp_path):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)

        win._scan_results = [{"id": 55, "performer": "Carl", "title": "Cox"}]
        mock_play = MagicMock()
        monkeypatch.setattr(win, "play_audio_file", mock_play)

        preview_file = str(tmp_path / "preview_55.mp3")
        win._on_preview_ready(55, preview_file)
        mock_play.assert_called_once_with(preview_file, title="⚡ [PREVIEW] Carl - Cox")

    def test_start_preview_stream_execution(self, qtbot, monkeypatch):
        import gui
        from unittest.mock import MagicMock

        win = gui.MainWindow()
        qtbot.addWidget(win)

        win.api_id_input.setText("12345")
        win.api_hash_input.setText("abcdef")
        win.channel_input.setText("@somechannel")
        win._proxy_config = {"enabled": False}

        mock_thread_start = MagicMock()
        monkeypatch.setattr("downloader.DownloadThread.start", mock_thread_start)

        win.start_preview_stream("@somechannel", 123, "Test - Track")
        assert win.download_thread is not None
        assert win.download_thread.preview_track_id == 123
        mock_thread_start.assert_called_once()






