import pytest
import asyncio
import queue
from unittest.mock import MagicMock, AsyncMock, PropertyMock, patch
from downloader import DownloadThread, USER_INPUT_TIMEOUT


class TestConstants:

    def test_user_input_timeout(self):
        assert USER_INPUT_TIMEOUT == 300


class TestCancel:

    def test_sets_cancel_requested(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        assert dt._cancel_requested is False
        dt.cancel()
        assert dt._cancel_requested is True

    def test_cancel_without_recorder_no_error(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt.cancel()

    def test_cancel_calls_recorder_cancel(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt.recorder = MagicMock()
        dt.cancel()
        dt.recorder.cancel.assert_called_once()


class TestGetUserInput:

    @pytest.mark.asyncio
    async def test_returns_input_from_queue(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        task = asyncio.create_task(dt.get_user_input("Enter phone:"))
        await asyncio.sleep(0.01)
        dt._input_queue.put('777')
        result = await task
        assert result == '777'

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt.cancel()
        result = await dt.get_user_input("Enter phone:")
        assert result is None

    @pytest.mark.asyncio
    async def test_clears_previous_queue(self):
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt._input_queue.put('old_value')
        task = asyncio.create_task(dt.get_user_input("Enter:"))
        await asyncio.sleep(0.01)
        dt._input_queue.put('new_value')
        result = await task
        assert result == 'new_value'


class TestAsyncRunDateParsing:

    @pytest.mark.asyncio
    async def test_invalid_date_format_logs_error(self):
        logs = []
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', 'not-a-date', None)
        dt.log_signal.connect(logs.append)
        dt._cancel_requested = True
        await dt.async_run()
        assert any("Неверный формат даты" in log for log in logs)

    @pytest.mark.asyncio
    async def test_cancel_before_start_logs(self):
        logs = []
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt.log_signal.connect(logs.append)
        dt.client = AsyncMock()
        dt.client.is_user_authorized = AsyncMock(return_value=True)
        dt.client.get_me = AsyncMock()
        dt._cancel_requested = True
        await dt.async_run()
        assert any("отменена" in log for log in logs)


class TestAsyncRunAuth:
    @pytest.mark.asyncio
    async def test_cancel_during_phone_prompt(self):
        logs = []
        dt = DownloadThread(12345, 'hash', '@ch', 'direct', None, None)
        dt.log_signal.connect(logs.append)
        dt.client = AsyncMock()
        dt.client.is_user_authorized = AsyncMock(return_value=False)
        dt.client.send_code_request = AsyncMock()
        dt.client.sign_in = AsyncMock()
        dt.client.get_me = AsyncMock()
        dt._cancel_requested = True
        result = await dt.async_run()
        assert result is None


class TestProxyClientCreation:
    def test_socks5_with_auth(self, monkeypatch):
        import socks

        captured_proxy = []

        def mock_client(*args, **kwargs):
            captured_proxy.append(kwargs.get("proxy"))
            return MagicMock()

        monkeypatch.setattr("downloader.TelegramClient", mock_client)

        proxy_cfg = {
            "enabled": True,
            "type": "socks5",
            "host": "proxy.example.com",
            "port": 1080,
            "username": "myuser",
            "password": "mypassword",
        }
        dt = DownloadThread(12345, "hash", "@ch", "direct", None, None, proxy_config=proxy_cfg)
        dt._create_client()

        assert len(captured_proxy) == 1
        assert captured_proxy[0] == (
            socks.SOCKS5,
            "proxy.example.com",
            1080,
            True,
            "myuser",
            "mypassword",
        )

    def test_socks5_without_auth(self, monkeypatch):
        import socks

        captured_proxy = []

        def mock_client(*args, **kwargs):
            captured_proxy.append(kwargs.get("proxy"))
            return MagicMock()

        monkeypatch.setattr("downloader.TelegramClient", mock_client)

        proxy_cfg = {
            "enabled": True,
            "type": "socks5",
            "host": "127.0.0.1",
            "port": 9050,
        }
        dt = DownloadThread(12345, "hash", "@ch", "direct", None, None, proxy_config=proxy_cfg)
        dt._create_client()

        assert len(captured_proxy) == 1
        assert captured_proxy[0] == (socks.SOCKS5, "127.0.0.1", 9050)


class TestConnectionErrorHandling:
    @pytest.mark.asyncio
    async def test_connection_error_direct_tunnel_no_proxy_checks(self, monkeypatch):
        """Проверяет прямое подключение без проверок MTProto сокетов (через системный туннель)."""
        logs = []
        dt = DownloadThread(12345, "hash", "@ch", "direct", None, None, proxy_config={"enabled": False})
        dt.log_signal.connect(logs.append)

        bad_client = AsyncMock()
        bad_client.connect.side_effect = ConnectionError("Connection to Telegram failed")
        bad_client.is_connected = MagicMock(return_value=False)

        monkeypatch.setattr("downloader.TelegramClient", lambda *args, **kwargs: bad_client)

        await dt.async_run()

        assert any("Ошибка подключения к Telegram" in log for log in logs)
        assert not any("автоматическое переподключение" in log for log in logs)

    @pytest.mark.asyncio
    async def test_proxy_connection_error_logs_proxy_hint(self, monkeypatch):
        logs = []
        dt = DownloadThread(12345, "hash", "@ch", "direct", None, None, proxy_config={"enabled": True, "type": "socks5"})
        dt.log_signal.connect(logs.append)

        bad_client = AsyncMock()
        bad_client.connect.side_effect = ConnectionError("Proxy refused")
        bad_client.is_connected = MagicMock(return_value=False)

        monkeypatch.setattr("downloader.TelegramClient", lambda *args, **kwargs: bad_client)

        await dt.async_run()

        assert any("Ошибка подключения к Telegram через прокси" in log for log in logs)


