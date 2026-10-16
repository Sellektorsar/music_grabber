"""Тесты на downloader.py: определение туннеля, все ветки прокси, отмена.

Закрывает блок 457-665, который планом B2 назван приоритетным: ветки
SOCKS5 / HTTP / MTProxy, авторизация на прокси, системный туннель и отказ
создания клиента.

Системный туннель намеренно не проверяется во время обычного прогона
pytest -- условие ``not os.environ.get("PYTEST_CURRENT_TEST")`` в коде
исключает его, поэтому переменная удаляется точечно в нужных тестах.
"""

import asyncio
import queue
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import downloader as dl


class _FakeSocket:
    """Заглушка сокета: connect_ex всегда отказывает, если не задан ответ."""

    reply = b""
    connect_result = 1

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def settimeout(self, v):
        pass

    def connect_ex(self, addr):
        return self.connect_result

    def sendall(self, data):
        pass

    def recv(self, n):
        return self.reply


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY",
                "all_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


class TestGetSystemTunnelProxy:

    def test_detects_local_socks5(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        _FakeSocket.connect_result = 0
        _FakeSocket.reply = b"\x05\x00"
        try:
            assert dl.get_system_tunnel_proxy() == {
                "type": "socks5", "host": "127.0.0.1", "port": 10808}
        finally:
            _FakeSocket.connect_result = 1

    def test_skips_socks_when_auth_required(self, monkeypatch):
        """SOCKS отвечает требованием пароля -- это не наш туннель."""
        monkeypatch.setattr("socket.socket", _FakeSocket)
        _FakeSocket.connect_result = 0
        _FakeSocket.reply = b"\x05\x02"
        try:
            with patch("winreg.OpenKey", side_effect=OSError):
                assert dl.get_system_tunnel_proxy() is None
        finally:
            _FakeSocket.connect_result = 1

    def test_socket_failure_is_not_fatal(self, monkeypatch):
        monkeypatch.setattr("socket.socket",
                            MagicMock(side_effect=OSError("нет сокета")))
        with patch("winreg.OpenKey", side_effect=OSError):
            assert dl.get_system_tunnel_proxy() is None

    def test_env_socks5_url(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        monkeypatch.setenv("ALL_PROXY", "socks5://10.0.0.5:9050")
        with patch("winreg.OpenKey", side_effect=OSError):
            got = dl.get_system_tunnel_proxy()
        assert got["type"] == "socks5"
        assert got["host"] == "10.0.0.5"
        assert got["port"] == 9050

    def test_env_http_without_scheme(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        monkeypatch.setenv("HTTPS_PROXY", "proxy.local:3128")
        with patch("winreg.OpenKey", side_effect=OSError):
            got = dl.get_system_tunnel_proxy()
        assert got["type"] == "http"
        assert got["host"] == "proxy.local"
        assert got["port"] == 3128

    def test_registry_socks_entry(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        key = MagicMock()
        key.__enter__ = lambda s: s
        key.__exit__ = lambda s, *a: False
        with patch("winreg.OpenKey", return_value=key), \
             patch("winreg.QueryValueEx", side_effect=[
                 (1, ""), ("socks=127.0.0.1:10808", "")]):
            got = dl.get_system_tunnel_proxy()
        assert got["type"] == "socks5"
        assert got["port"] == 10808

    def test_registry_plain_host_port(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        key = MagicMock()
        key.__enter__ = lambda s: s
        key.__exit__ = lambda s, *a: False
        with patch("winreg.OpenKey", return_value=key), \
             patch("winreg.QueryValueEx", side_effect=[
                 (1, ""), ("http=192.168.1.10:8080", "")]):
            got = dl.get_system_tunnel_proxy()
        assert got["type"] == "http"
        assert got["host"] == "192.168.1.10"
        assert got["port"] == 8080

    def test_nothing_found_returns_none(self, monkeypatch):
        monkeypatch.setattr("socket.socket", _FakeSocket)
        with patch("winreg.OpenKey", side_effect=OSError):
            assert dl.get_system_tunnel_proxy() is None


def _thread(**proxy):
    t = dl.DownloadThread(1, "hash", "@chan", "direct", None, None,
                          proxy_config=proxy or {})
    return t


class TestCreateClientProxyBranches:

    def test_direct_when_tunnel_explicitly_disabled(self):
        t = _thread(enabled=False, force_direct=True)
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert "proxy" not in TC.call_args.kwargs, \
            "явный запрет туннеля обязан дать прямое подключение"

    def test_socks5_without_auth(self):
        t = _thread(enabled=True, type="socks5", host="1.2.3.4", port=1080)
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        proxy = TC.call_args.kwargs["proxy"]
        assert proxy[1] == "1.2.3.4" and proxy[2] == 1080
        assert len(proxy) == 3, "без логина пароль не передаётся"

    def test_socks5_with_auth(self):
        t = _thread(enabled=True, type="socks5", host="1.2.3.4", port=1080,
                    username="u", password="p")
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        proxy = TC.call_args.kwargs["proxy"]
        assert proxy[3] is True and proxy[4] == "u" and proxy[5] == "p"

    def test_http_without_auth(self):
        t = _thread(enabled=True, type="http", host="8.8.8.8", port=8080)
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert TC.call_args.kwargs["proxy"][1] == "8.8.8.8"

    def test_http_with_auth(self):
        t = _thread(enabled=True, type="http", host="8.8.8.8", port=8080,
                    username="u", password="p")
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert TC.call_args.kwargs["proxy"][4] == "u"

    def test_mtproto_uses_connection_class(self):
        """MTProxy требует особого класса соединения.

        conftest подменяет ``telethon`` заглушкой без вложенных модулей,
        поэтому ветка импортирует ``telethon.network.connection`` -- его
        приходится зарегистрировать, иначе проверка падает на заглушке,
        а не на коде приложения.
        """
        sentinel = type("FakeMtProxyConnection", (), {})
        net = MagicMock()
        net.ConnectionTcpMTProxyRandomizedIntermediate = sentinel
        with patch.dict(sys.modules, {
            "telethon.network": MagicMock(),
            "telethon.network.connection": net,
        }):
            t = _thread(enabled=True, type="mtproto", host="proxy.tg",
                        port=443, password="secret")
            with patch.object(dl, "TelegramClient") as TC:
                t._create_client()

        kwargs = TC.call_args.kwargs
        assert kwargs.get("connection") is sentinel, \
            "MTProxy обязан использовать ConnectionTcpMTProxyRandomizedIntermediate"
        assert kwargs["proxy"] == ("proxy.tg", 443, "secret")

    def test_mtproto_without_secret_passes_empty(self):
        net = MagicMock()
        with patch.dict(sys.modules, {
            "telethon.network": MagicMock(),
            "telethon.network.connection": net,
        }):
            t = _thread(enabled=True, type="mtproto", host="proxy.tg", port=443)
            with patch.object(dl, "TelegramClient") as TC:
                t._create_client()
        assert TC.call_args.kwargs["proxy"][2] == ""

    def test_flat_proxy_keys_are_honoured(self):
        """Старые плоские ключи proxy_* тоже должны работать."""
        t = _thread(proxy_enabled=True, proxy_type="socks5",
                    proxy_host="5.5.5.5", proxy_port=7777)
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert TC.call_args.kwargs["proxy"][1] == "5.5.5.5"

    def test_proxy_error_falls_back_to_plain_client(self):
        """Нечисловой порт роняет int(port) -- клиент создаётся без прокси."""
        t = _thread(enabled=True, type="socks5", host="1.2.3.4", port="не порт")
        with patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert "proxy" not in TC.call_args.kwargs

    def test_system_tunnel_used_when_proxy_disabled(self, monkeypatch):
        t = _thread(enabled=False)
        tunnel = {"type": "socks5", "host": "127.0.0.1", "port": 10808}
        # Переменная выставляется pytest'ом на время вызова теста, поэтому
        # убирать её нужно непосредственно перед синхронным вызовом.
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(dl, "get_system_tunnel_proxy", return_value=tunnel), \
             patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert TC.call_args.kwargs["proxy"][2] == 10808

    def test_system_tunnel_http_variant(self, monkeypatch):
        t = _thread(enabled=False)
        tunnel = {"type": "http", "host": "127.0.0.1", "port": 10809}
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(dl, "get_system_tunnel_proxy", return_value=tunnel), \
             patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert TC.call_args.kwargs["proxy"][2] == 10809

    def test_no_tunnel_and_no_proxy_gives_plain_client(self, monkeypatch):
        t = _thread(enabled=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with patch.object(dl, "get_system_tunnel_proxy", return_value=None), \
             patch.object(dl, "TelegramClient") as TC:
            t._create_client()
        assert "proxy" not in TC.call_args.kwargs

    def test_broken_session_db_does_not_break_client(self, tmp_path):
        """Битая сессия не должна мешать создать клиента."""
        bad = tmp_path / "session.session"
        bad.write_bytes("не база данных".encode("utf-8"))
        t = _thread(enabled=False, force_direct=True)
        with patch("config.get_session_path", return_value=str(tmp_path / "session")), \
             patch.object(dl, "TelegramClient"):
            t._create_client()


class TestQrAuth:
    """``_qr_auth`` ждёт до USER_INPUT_TIMEOUT секунд.

    Заглушка ``wait`` обязана сразу завершаться успехом: если она всегда
    бросает ``TimeoutError``, цикл ``while time < end`` честно отработает
    все 120 секунд и прогон тестов растянется на минуты.
    """

    def _qr(self, thread):
        qr = MagicMock()
        qr.url = "https://t.me/qr/abc"
        qr.wait = AsyncMock(return_value=None)
        thread.client = MagicMock()
        thread.client.qr_login = AsyncMock(return_value=qr)
        return qr

    def test_successful_qr_login(self):
        t = _thread()
        self._qr(t)
        t.client.get_me = AsyncMock(return_value=MagicMock())

        assert asyncio.run(t._qr_auth()) is True

    def test_get_me_none_returns_false(self):
        t = _thread()
        self._qr(t)
        t.client.get_me = AsyncMock(return_value=None)

        assert asyncio.run(t._qr_auth()) is False

    def test_cancelled_before_wait_returns_false(self):
        t = _thread()
        self._qr(t)
        t._cancel_requested = True
        t.client.get_me = AsyncMock(return_value=None)

        assert asyncio.run(t._qr_auth()) is False

    def test_cancel_during_wait_stops_immediately(self):
        """Отмена во время ожидания завершает авторизацию, а не ждёт 120 с."""
        t = _thread()
        qr = self._qr(t)

        def _cancel_then_timeout(*a, **kw):
            t._cancel_requested = True
            raise asyncio.TimeoutError

        qr.wait = AsyncMock(side_effect=_cancel_then_timeout)
        t.client.get_me = AsyncMock(return_value=MagicMock())

        assert asyncio.run(t._qr_auth()) is False
        t.client.get_me.assert_not_called()

    def test_qr_url_is_emitted(self):
        t = _thread()
        qr = self._qr(t)
        t.client.get_me = AsyncMock(return_value=MagicMock())
        seen = []
        t.qr_login_signal.connect(seen.append)

        asyncio.run(t._qr_auth())
        assert seen == ["https://t.me/qr/abc"]

    def test_exception_is_logged_and_swallowed(self):
        t = _thread()
        t.client = MagicMock()
        t.client.qr_login = AsyncMock(side_effect=RuntimeError("сеть упала"))
        assert asyncio.run(t._qr_auth()) is False


class TestGetUserInput:

    def test_returns_queued_value(self):
        t = _thread()
        t._input_queue = MagicMock()
        t._input_queue.empty.return_value = False
        t._input_queue.get_nowait.side_effect = [queue.Empty(), "12345"]
        assert asyncio.run(t.get_user_input("Введите код")) == "12345"

    def test_returns_none_when_cancelled(self):
        t = _thread()
        t._cancel_requested = True
        t._input_queue = MagicMock()
        t._input_queue.empty.return_value = True
        assert asyncio.run(t.get_user_input("Введите код")) is None


class TestCancel:

    def test_cancel_sets_flag_and_stops_recorder(self):
        t = _thread()
        rec = MagicMock()
        t.recorder = rec
        t._active_recorders = []
        t.cancel()
        assert t._cancel_requested is True
        rec.cancel.assert_called_once()

    def test_recorder_error_is_swallowed(self):
        t = _thread()
        rec = MagicMock()
        rec.cancel.side_effect = RuntimeError("уже остановлен")
        t.recorder = rec
        t._active_recorders = []
        t.cancel()
        assert t._cancel_requested is True

    def test_active_recorders_are_cancelled(self):
        t = _thread()
        t.recorder = None
        r1, r2 = MagicMock(), MagicMock()
        t._active_recorders = [r1, r2]
        t.cancel()
        r1.cancel.assert_called_once()
        r2.cancel.assert_called_once()

    def test_active_recorder_error_does_not_stop_others(self):
        t = _thread()
        t.recorder = None
        bad = MagicMock()
        bad.cancel.side_effect = RuntimeError("ошибка")
        good = MagicMock()
        t._active_recorders = [bad, good]
        t.cancel()
        good.cancel.assert_called_once()