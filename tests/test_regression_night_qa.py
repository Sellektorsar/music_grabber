"""
Regression & Robustness Test Suite for Autonomous Overnight QA.

Tests cover:
1. System tunnel proxy detection (Xray/v2ray/Windows Registry).
2. Deep nested directory creation in try_direct_download.
3. Clean .part file removal on cancellation in download_track_preview.
4. Player errorOccurred signal handling.
5. QThread lifecycle safety and cancel-on-restart guards.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import QMessageBox, QListWidgetItem
from PyQt6.QtCore import Qt

from downloader import get_system_tunnel_proxy
from recorder import TelegramAudioRecorder
from ui.player import AudioPlayerBar


class MockRunningThread(QThread):
    def __init__(self):
        super().__init__()
        self.cancel_called = False
        self.wait_called = False

    def isRunning(self):
        return True

    def cancel(self):
        self.cancel_called = True

    def wait(self, ms=None):
        self.wait_called = True
        return True


class TestSystemTunnelProxyDetection:
    def test_proxy_explicitly_configured_used_in_client(self):
        """1. Пользовательский прокси явно настроен -> используется в клиенте."""
        from downloader import DownloadThread
        dt = DownloadThread(
            api_id=12345,
            api_hash="hash",
            channel="@ch",
            mode="direct",
            date_from=None,
            date_to=None,
            proxy_config={"enabled": True, "type": "socks5", "host": "1.2.3.4", "port": 9050},
        )
        with patch("downloader.TelegramClient") as mock_tc:
            dt._create_client()
            assert mock_tc.called
            call_kwargs = mock_tc.call_args[1]
            assert "proxy" in call_kwargs
            proxy_tuple = call_kwargs["proxy"]
            assert proxy_tuple[1] == "1.2.3.4"
            assert proxy_tuple[2] == 9050

    def test_proxy_not_configured_falls_back_to_tunnel(self, monkeypatch):
        """2. Прокси не настроен -> fallback на активный системный туннель."""
        from downloader import DownloadThread
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        dt = DownloadThread(
            api_id=12345,
            api_hash="hash",
            channel="@ch",
            mode="direct",
            date_from=None,
            date_to=None,
            proxy_config={},
        )
        with patch("downloader.get_system_tunnel_proxy", return_value={"type": "socks5", "host": "127.0.0.1", "port": 10808}), \
             patch("downloader.TelegramClient") as mock_tc:
            dt._create_client()
            assert mock_tc.called
            call_kwargs = mock_tc.call_args[1]
            assert "proxy" in call_kwargs
            assert call_kwargs["proxy"][1] == "127.0.0.1"
            assert call_kwargs["proxy"][2] == 10808

    def test_proxy_explicitly_disabled_by_user(self, monkeypatch):
        """3. Прокси явно отключён пользователем -> прямое подключение без туннеля."""
        from downloader import DownloadThread
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        dt = DownloadThread(
            api_id=12345,
            api_hash="hash",
            channel="@ch",
            mode="direct",
            date_from=None,
            date_to=None,
            proxy_config={"force_direct": True, "enabled": False},
        )
        with patch("downloader.get_system_tunnel_proxy", return_value={"type": "socks5", "host": "127.0.0.1", "port": 10808}), \
             patch("downloader.TelegramClient") as mock_tc:
            dt._create_client()
            assert mock_tc.called
            call_kwargs = mock_tc.call_args[1]
            assert "proxy" not in call_kwargs

    def test_tunnel_proxy_port_closed(self, monkeypatch):
        """4. Порт закрыт -> возвращается None."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            sock_inst.connect_ex.return_value = 1  # connection refused
            mock_sock.return_value.__enter__.return_value = sock_inst
            proxy = get_system_tunnel_proxy()
            assert proxy is None

    def test_tunnel_proxy_port_occupied_by_non_socks(self, monkeypatch):
        """5. Порт занят другим TCP-сервисом (не-SOCKS) -> отклоняется."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            mock_sock.return_value.__enter__.return_value = sock_inst
            sock_inst.connect_ex.side_effect = [0, 1]  # 10808 open, 10809 closed
            sock_inst.recv.return_value = b"HTTP/1.1 400 Bad Request\r\n"
            proxy = get_system_tunnel_proxy()
            assert proxy is None

    def test_tunnel_proxy_socks5_handshake_timeout(self, monkeypatch):
        """6. SOCKS5 не отвечает на handshake (таймаут) -> не зависает, возвращает None."""
        import socket
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            mock_sock.return_value.__enter__.return_value = sock_inst
            sock_inst.connect_ex.return_value = 0
            sock_inst.recv.side_effect = socket.timeout("Timed out")
            proxy = get_system_tunnel_proxy()
            assert proxy is None

    def test_tunnel_proxy_socks5_handshake_refusal(self, monkeypatch):
        """7. SOCKS5 возвращает отказ (0x05 0xFF) -> отклоняется."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            mock_sock.return_value.__enter__.return_value = sock_inst
            sock_inst.connect_ex.side_effect = [0, 1]
            sock_inst.recv.return_value = b"\x05\xFF"  # 0xFF = no acceptable methods
            proxy = get_system_tunnel_proxy()
            assert proxy is None

    def test_tunnel_proxy_http_10809_connect_supported(self, monkeypatch):
        """8. HTTP-прокси на 10809 поддерживает CONNECT -> корректно определяется."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            mock_sock.return_value.__enter__.return_value = sock_inst
            # 10808 closed (1), 10809 open (0)
            sock_inst.connect_ex.side_effect = [1, 0]
            sock_inst.recv.return_value = b"HTTP/1.1 200 Connection established\r\n\r\n"
            proxy = get_system_tunnel_proxy()
            assert proxy is not None
            assert proxy.get("type") == "http"
            assert proxy.get("host") == "127.0.0.1"
            assert proxy.get("port") == 10809

    def test_tunnel_proxy_registry_malformed_values(self, monkeypatch):
        """9. Системные настройки Windows содержат некорректные значения -> безопасно игнорируются."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        # Malformed entries: no port, invalid port number, extra colons
        mock_winreg.QueryValueEx.side_effect = [
            (1, 4), ("corrupted_proxy_without_port;http=bad:notnum:extra", 1)
        ]
        monkeypatch.setitem(sys.modules, "winreg", mock_winreg)

        with patch("socket.socket") as mock_sock:
            sock_inst = MagicMock()
            mock_sock.return_value.__enter__.return_value = sock_inst
            sock_inst.connect_ex.return_value = 1
            proxy = get_system_tunnel_proxy()
            assert proxy is None


class TestRecorderEdgeCases:
    @pytest.mark.asyncio
    async def test_try_direct_download_creates_nested_directories(self, tmp_path):
        client = AsyncMock()
        rec = TelegramAudioRecorder(client, channel="@testchannel", mode="direct")
        rec.base_folder = str(tmp_path)
        
        # Deep nested path that does not yet exist
        deep_target = tmp_path / "channels" / "electronic" / "subgenre" / "track.mp3"
        assert not os.path.exists(os.path.dirname(deep_target))

        msg = MagicMock()
        msg.id = 999
        msg.media = MagicMock()
        msg.document = MagicMock()
        msg.document.size = 100
        msg.document.mime_type = "audio/mpeg"

        # Mock _download_with_retry to simulate successful download writing file
        async def mock_dl(m, temp_path, progress_callback=None, total_size=0):
            with open(temp_path, "wb") as f:
                f.write(b"fake mp3 data")
            return True

        rec._download_with_retry = mock_dl
        rec._get_audio_extension = MagicMock(return_value=".mp3")

        res = await rec.try_direct_download(msg, str(deep_target))
        assert res is True
        assert os.path.exists(os.path.dirname(deep_target))
        assert os.path.exists(str(deep_target))

    @pytest.mark.asyncio
    async def test_download_track_preview_cancel_cleans_part(self, tmp_path):
        client = AsyncMock()
        rec = TelegramAudioRecorder(client, channel="@testchannel")
        rec.base_folder = str(tmp_path)

        msg = MagicMock()
        msg.id = 42
        msg.media = MagicMock()
        msg.document = MagicMock()
        msg.document.mime_type = "audio/mpeg"

        preview_dir = os.path.join(str(tmp_path), "previews")
        os.makedirs(preview_dir, exist_ok=True)
        part_path = os.path.join(preview_dir, "preview_42.mp3.part")

        # Mock iter_download to create part file then cancel
        async def fake_iter_download(media, offset=0, request_size=128*1024):
            with open(part_path, "wb") as f:
                f.write(b"part data")
            rec._cancelled = True
            yield b"chunk"

        client.iter_download = fake_iter_download
        rec.client = client
        rec._get_audio_extension = MagicMock(return_value=".mp3")

        # Mock get_messages to return msg
        client.get_messages = AsyncMock(return_value=[msg])

        res = await rec.download_track_preview("test_channel", 42)
        assert res is None
        # Verify .part was deleted
        assert not os.path.exists(part_path)


class TestPlayerErrorHandling:
    def test_on_player_error_logs_and_resets(self):
        logs = []
        player = AudioPlayerBar(log_callback=lambda m: logs.append(m))
        player.btn_play_pause.setText("⏸")

        player._on_player_error(1, "ResourceError: Unrecognized codec")
        assert len(logs) == 1
        assert "Ошибка воспроизведения" in logs[0]
        assert "ResourceError" in logs[0]
        assert player.btn_play_pause.text() == "▶"


@pytest.fixture
def test_window(qtbot, monkeypatch, tmp_path):
    config_dir = tmp_path / "telegram_audio"
    config_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("config.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(config_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok))

    from gui import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    return win


class TestThreadLifecycleRobustness:

    def test_start_scan_blocks_when_thread_running(self, test_window):
        mock_th = MockRunningThread()
        test_window.download_thread = mock_th
        test_window.api_id_input.setText("12345")
        test_window.api_hash_input.setText("hash123")
        test_window.channel_input.setText("@testchan")

        logs = []
        test_window.log = lambda m: logs.append(m)
        test_window.start_scan()
        assert any("Предыдущая операция" in m for m in logs)
        assert test_window.download_thread is mock_th

    def test_start_download_blocks_when_thread_running(self, test_window):
        mock_th = MockRunningThread()
        test_window.download_thread = mock_th
        test_window.api_id_input.setText("12345")
        test_window.api_hash_input.setText("hash123")
        test_window.channel_input.setText("@testchan")

        it = QListWidgetItem("Track 1")
        it.setCheckState(Qt.CheckState.Checked)
        it.setData(Qt.ItemDataRole.UserRole, 101)
        test_window.track_list.addItem(it)

        logs = []
        test_window.log = lambda m: logs.append(m)
        test_window.start_download()
        assert any("Предыдущая операция" in m for m in logs)
        assert test_window.download_thread is mock_th

    def test_cleanup_on_exit_waits_for_active_thread(self, test_window):
        mock_th = MockRunningThread()
        test_window.download_thread = mock_th

        test_window._cleanup_on_exit()
        assert mock_th.wait_called is True

    def test_cleanup_on_exit_lingers_unstopped_thread(self, test_window):
        from gui import _LINGERING_THREADS
        mock_th = MockRunningThread()
        mock_th.wait = MagicMock(return_value=False)
        test_window.download_thread = mock_th

        test_window._cleanup_on_exit()
        assert mock_th in _LINGERING_THREADS
        mock_th.finished.emit()
        assert mock_th not in _LINGERING_THREADS

    def test_tree_render_flushes_deferred_widgets(self, test_window):
        tracks = [{"id": i, "title": f"T{i}", "performer": f"A{i}", "date": "2026-10-09"} for i in range(1, 11)]
        test_window._on_scan_results(tracks)
        assert len(test_window._track_status_badges) == 10
        assert len(test_window._track_waveforms) == 10

        # Re-render with a new batch: old badges are replaced and cleared
        tracks_2 = [{"id": i + 100, "title": f"NewT{i}", "performer": f"NewA{i}", "date": "2026-10-09"} for i in range(1, 11)]
        test_window._on_scan_results(tracks_2)
        assert len(test_window._track_status_badges) == 10
        assert len(test_window._track_waveforms) == 10
        assert 1 not in test_window._track_status_badges
        assert 101 in test_window._track_status_badges


class TestQtLifecycleAndTreeSafety:
    def test_unrelated_deferred_delete_objects_preserved_during_tree_render(self, test_window):
        """Гарантирует, что адресная очистка дерева НЕ удаляет посторонние объекты с deleteLater()."""
        from PyQt6.QtWidgets import QLabel, QApplication

        # Создаем сторонний объект (например, закрывающийся диалог или меню)
        unrelated_dialog = QLabel("unrelated_external_dialog")
        unrelated_dialog.deleteLater()
        assert unrelated_dialog in QApplication.allWidgets()

        # Выполняем рендеринг дерева (который очищает свои бейджи)
        tracks = [{"id": 501, "title": "Track 501", "performer": "Artist", "date": "2026-10-09"}]
        test_window._on_scan_results(tracks)

        # Сторонний объект ОБЯЗАН остаться живым и не уничтоженным преждевременно
        assert unrelated_dialog in QApplication.allWidgets()
        assert unrelated_dialog.text() == "unrelated_external_dialog"

    def test_statuses_and_waveforms_rendered_correctly(self, test_window):
        """Проверяет корректность рендеринга бейджей статусов и вейвформов."""
        tracks = [
            {"id": 1, "title": "T1", "performer": "A1", "date": "2026-10-09", "already_exists": True},
            {"id": 2, "title": "T2", "performer": "A2", "date": "2026-10-09", "is_duplicate": True, "duplicate_channel": "pool"},
            {"id": 3, "title": "T3", "performer": "A3", "date": "2026-10-09"},
        ]
        test_window._on_scan_results(tracks)

        badge1 = test_window._track_status_badges[1]
        badge2 = test_window._track_status_badges[2]
        badge3 = test_window._track_status_badges[3]

        assert badge1.text() == "SAVED"
        assert badge2.text() == "DUP"
        assert badge3.text() == "READY"

        wf1 = test_window._track_waveforms[1]
        assert wf1.pixmap() is not None
        assert not wf1.pixmap().isNull()

    def test_window_close_during_tree_rendering(self, test_window):
        """Проверяет отсутствие сбоев при закрытии окна во время рендеринга."""
        tracks = [{"id": i, "title": f"Track {i}", "performer": "Artist", "date": "2026-10-09"} for i in range(1, 20)]
        test_window._on_scan_results(tracks)
        test_window._cleanup_on_exit()
        test_window.close()

    def test_repeated_300_tree_updates_widget_stability(self, test_window):
        """Проверяет 300 последовательных обновлений дерева на стабильность числа виджетов."""
        for cycle in range(1, 301):
            tracks = [
                {"id": idx + (cycle * 20), "title": f"T{idx}", "performer": f"A{idx}", "date": "2026-10-09"}
                for idx in range(1, 16)
            ]
            test_window._on_scan_results(tracks)
            # Количество активных бейджей в дереве всегда строго равно размеру пачки (15)
            assert len(test_window._track_status_badges) == 15
            assert len(test_window._track_waveforms) == 15
