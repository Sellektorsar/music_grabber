import asyncio
import os
import queue
import sys
import traceback
import urllib.parse
from PyQt6.QtCore import QThread, pyqtSignal
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from recorder import TelegramAudioRecorder
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def get_system_tunnel_proxy():
    """Обнаруживает активный системный туннель (локальный SOCKS5 10808, HTTP 10809, Windows Registry proxy, env vars)."""
    # 1. Проверяем локальный SOCKS5 туннель (Xray/V2Ray/Sing-box/Clash на порту 10808)
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.20)
            if s.connect_ex(("127.0.0.1", 10808)) == 0:
                s.sendall(b"\x05\x01\x00")
                resp = s.recv(2)
                # 0x05 - SOCKSv5, 0x00 - NO AUTHENTICATION REQUIRED (успех)
                if resp and len(resp) >= 2 and resp[0] == 0x05 and resp[1] == 0x00:
                    return {"type": "socks5", "host": "127.0.0.1", "port": 10808}
    except Exception:
        pass

    # 1b. Проверяем локальный HTTP туннель (Xray/V2Ray на порту 10809) с проверкой CONNECT
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.20)
            if s.connect_ex(("127.0.0.1", 10809)) == 0:
                s.sendall(b"CONNECT 149.154.167.51:443 HTTP/1.1\r\nHost: 149.154.167.51:443\r\n\r\n")
                resp = s.recv(16)
                if resp and (b"200" in resp or b"HTTP/1" in resp):
                    return {"type": "http", "host": "127.0.0.1", "port": 10809}
    except Exception:
        pass

    # 2. Проверяем настройки системного прокси Windows (реестр)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if enabled:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if server:
                        entries = server.split(";")
                        target_entry = None
                        target_type = "http"
                        for entry in entries:
                            entry_clean = entry.strip()
                            if "socks=" in entry_clean.lower():
                                target_entry = entry_clean.lower().replace("socks=", "")
                                target_type = "socks5"
                                break
                            elif "http=" in entry_clean.lower() or ":" in entry_clean:
                                target_entry = entry_clean.lower().replace("http=", "").replace("https=", "")
                                target_type = "http"
                                break
                        if not target_entry and entries:
                            target_entry = entries[0]
                        clean = target_entry.replace("http://", "").replace("https://", "").replace("socks5://", "")
                        if ":" in clean:
                            host, port = clean.rsplit(":", 1)
                            if port.strip().isdigit():
                                return {"type": target_type, "host": host.strip(), "port": int(port.strip())}
        except Exception:
            pass

    # 3. Переменные окружения
    for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy"):
        val = os.environ.get(key)
        if val:
            try:
                parsed = urllib.parse.urlparse(val if "://" in val else f"http://{val}")
                ptype = "socks5" if "socks" in parsed.scheme.lower() else "http"
                return {
                    "type": ptype,
                    "host": parsed.hostname or "127.0.0.1",
                    "port": parsed.port or (10808 if ptype == "socks5" else 10809),
                }
            except Exception:
                pass

    return None

# Таймаут ожидания ответа пользователя в окне ввода (телефон/код/2FA).
# Защищает от вечного зависания, если диалог по какой-то причине не отобразился.
USER_INPUT_TIMEOUT = 300  # секунд (5 минут)

# Кэш авторизованного пользователя для избежания повторных запросов get_me()
_ME_CACHE = None


class DownloadThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    request_code_signal = pyqtSignal(str)
    code_response_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(object)
    scan_signal = pyqtSignal(object)
    qr_login_signal = pyqtSignal(str)
    preview_signal = pyqtSignal(int, str)

    def __init__(
        self,
        api_id,
        api_hash,
        channel,
        mode,
        date_from,
        date_to,
        proxy_config=None,
        scan_only=False,
        selected_ids=None,
        max_concurrent_downloads=None,
        mp3_bitrate=None,
        channels=None,
        limit_per_channel=None,
        channel_offsets=None,
        preview_track_id=None,
    ):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.proxy_config = proxy_config or {}
        self.scan_only = scan_only
        self.selected_ids = set(selected_ids or [])
        self.max_concurrent_downloads = max_concurrent_downloads
        self.mp3_bitrate = mp3_bitrate
        self.channels = channels
        self.limit_per_channel = limit_per_channel
        self.channel_offsets = channel_offsets or {}
        self.preview_track_id = preview_track_id
        self._cancel_requested = False

        self._input_queue = queue.Queue()
        self.code_response_signal.connect(self._on_code_response)

    def _on_code_response(self, text):
        self._input_queue.put(text)

    def run(self):
        try:
            asyncio.run(self.async_run())
        finally:
            # Сигнал о завершении эмитим строго один раз, независимо от того,
            # как завершился asyncio (нормально, исключением или отменой).
            self.finished_signal.emit()

    async def async_run(self):
        self.client = self._create_client()
        try:
            try:
                await self.client.connect()
            except (ConnectionError, TimeoutError, OSError) as conn_err:
                proxy_enabled = bool(
                    self.proxy_config.get("enabled", False)
                    or self.proxy_config.get("proxy_enabled", False)
                )
                if proxy_enabled:
                    self.log_signal.emit(
                        f"⚠️ Ошибка подключения к Telegram через прокси: {conn_err}. Проверьте работоспособность прокси."
                    )
                else:
                    self.log_signal.emit(f"⚠️ Ошибка подключения к Telegram: {conn_err}")
                return

            if not await self.client.is_user_authorized():
                self.log_signal.emit("Требуется авторизация. Попробуйте QR-код...")
                qr_ok = await self._qr_auth()
                if self._cancel_requested:
                    return
                if not qr_ok:
                    self.log_signal.emit(
                        "QR-код не был отсканирован. Пробуем вход по номеру телефона..."
                    )
                    phone = None
                    while not phone:
                        if self._cancel_requested:
                            return
                        phone = await self.get_user_input(
                            "Введите номер телефона (с кодом страны, например +7...):"
                        )
                        if self._cancel_requested:
                            return
                        if not phone:
                            self.log_signal.emit(
                                "Номер телефона не может быть пустым. Попробуйте снова."
                            )
                    await self.client.send_code_request(phone)
                    code = None
                    while not code:
                        if self._cancel_requested:
                            return
                        code = await self.get_user_input(
                            "Введите код подтверждения, который вы получили:"
                        )
                        if self._cancel_requested:
                            return
                        if not code:
                            self.log_signal.emit(
                                "Код подтверждения не может быть пустым. Попробуйте снова."
                            )
                    try:
                        await self.client.sign_in(phone, code)
                    except SessionPasswordNeededError:
                        password = None
                        while not password:
                            if self._cancel_requested:
                                return
                            password = await self.get_user_input(
                                "Введите пароль двухфакторной аутентификации:"
                            )
                            if self._cancel_requested:
                                return
                            if not password:
                                self.log_signal.emit(
                                    "Пароль не может быть пустым. Попробуйте снова."
                                )
                        if self._cancel_requested:
                            return
                        await self.client.sign_in(password=password)
                    except Exception as auth_err:
                        self.log_signal.emit(f"Ошибка аутентификации: {auth_err}")
                        return

            global _ME_CACHE
            if _ME_CACHE is None:
                me = await self.client.get_me()
                _ME_CACHE = me
                self.log_signal.emit(
                    f"Авторизован как: {me.first_name} {me.last_name or ''}"
                )

            try:
                date_from_dt = (
                    datetime.strptime(self.date_from, "%Y-%m-%d")
                    if self.date_from
                    else None
                )
                date_to_dt = (
                    datetime.strptime(self.date_to, "%Y-%m-%d")
                    if self.date_to
                    else None
                )
            except ValueError as e:
                self.log_signal.emit(
                    f"Неверный формат даты. Используйте YYYY-MM-DD: {e}"
                )
                return
            if date_from_dt:
                date_from_dt = date_from_dt.replace(tzinfo=None)
            if date_to_dt:
                date_to_dt = date_to_dt + timedelta(days=1) - timedelta(seconds=1)

            if self._cancel_requested:
                self.log_signal.emit("Загрузка отменена до старта.")
                return

            self.recorder = TelegramAudioRecorder(
                self.client,
                self.channel,
                self.mode,
                date_from_dt,
                date_to_dt,
                self.log_signal.emit,
                self.progress_signal.emit,
                max_concurrent_downloads=self.max_concurrent_downloads,
                mp3_bitrate=self.mp3_bitrate,
            )

            if getattr(self, "preview_track_id", None):
                ch_target = self.channel or (self.channels[0] if self.channels else "")
                self.log_signal.emit(f"⚡ Потоковая буферизация превью #{self.preview_track_id} ({ch_target})...")
                preview_path = await self.recorder.download_track_preview(
                    ch_target, self.preview_track_id
                )
                if preview_path and os.path.exists(preview_path):
                    self.preview_signal.emit(self.preview_track_id, preview_path)
                    self.log_signal.emit(f"🎧 Превью готово: {preview_path}")
                else:
                    self.log_signal.emit(f"Не удалось буферизовать превью для #{self.preview_track_id}")
                return

            if self.scan_only:
                channels_list = [
                    str(ch).strip()
                    for ch in (self.channels if self.channels else [self.channel])
                    if str(ch).strip()
                ]
                all_tracks = []
                self._active_recorders = []

                async def _scan_single_channel(ch_clean: str):
                    if self._cancel_requested:
                        return []
                    try:
                        rec = TelegramAudioRecorder(
                            self.client,
                            ch_clean,
                            self.mode,
                            date_from_dt,
                            date_to_dt,
                            self.log_signal.emit,
                            self.progress_signal.emit,
                            max_concurrent_downloads=self.max_concurrent_downloads,
                            mp3_bitrate=self.mp3_bitrate,
                        )
                        self._active_recorders.append(rec)
                        self.recorder = rec
                        offset_id = (
                            self.channel_offsets.get(ch_clean, 0)
                            if self.channel_offsets
                            else 0
                        )
                        tracks = await rec.scan(
                            limit=self.limit_per_channel, offset_id=offset_id
                        )
                        last_id = (
                            getattr(rec, "last_scanned_id", offset_id)
                            or offset_id
                        )
                        for t in tracks:
                            if not t.get("channel"):
                                t["channel"] = ch_clean
                            t["channel_last_scanned_id"] = last_id
                        return tracks
                    except Exception as ch_err:
                        self.log_signal.emit(
                            f"Ошибка сканирования {ch_clean}: {ch_err}"
                        )
                        return []

                scan_results = await asyncio.gather(
                    *(_scan_single_channel(c) for c in channels_list)
                )
                for res in scan_results:
                    all_tracks.extend(res)

                self.scan_signal.emit(all_tracks)
                self.log_signal.emit(f"Сканирование завершено: {len(all_tracks)} треков")
                return

            channels_list = self.channels if self.channels else [self.channel]
            for ch in channels_list:
                if self._cancel_requested:
                    break
                ch_clean = str(ch).strip()
                if not ch_clean:
                    continue
                self.recorder = TelegramAudioRecorder(
                    self.client,
                    ch_clean,
                    self.mode,
                    date_from_dt,
                    date_to_dt,
                    self.log_signal.emit,
                    self.progress_signal.emit,
                    max_concurrent_downloads=self.max_concurrent_downloads,
                    mp3_bitrate=self.mp3_bitrate,
                )
                self.recorder.selected_ids = self.selected_ids
                await self.recorder.start()

            if self._cancel_requested:
                self.log_signal.emit("Загрузка прервана пользователем.")
            else:
                self.log_signal.emit("Загрузка завершена.")
        except Exception as e:
            self.log_signal.emit(f"Ошибка: {e}")
            self.log_signal.emit(traceback.format_exc())
        finally:
            try:
                if hasattr(self, "client") and self.client.is_connected():
                    await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Ошибка при закрытии соединения: {e}")

    def _create_client(self):
        proxy_enabled = bool(
            self.proxy_config.get("enabled", False)
            or self.proxy_config.get("proxy_enabled", False)
        )
        if proxy_enabled:
            proxy_type = str(
                self.proxy_config.get("type")
                or self.proxy_config.get("proxy_type")
                or "socks5"
            ).lower()
            proxy_host = str(
                self.proxy_config.get("host")
                or self.proxy_config.get("proxy_host")
                or "127.0.0.1"
            )
            proxy_port = (
                self.proxy_config.get("port")
                or self.proxy_config.get("proxy_port")
                or 10808
            )
            proxy_username = (
                self.proxy_config.get("username")
                or self.proxy_config.get("proxy_username")
                or None
            )
            proxy_password = (
                self.proxy_config.get("password")
                or self.proxy_config.get("proxy_password")
                or None
            )
            try:
                if proxy_type == "socks5":
                    import socks

                    if proxy_username and proxy_password:
                        proxy = (
                            socks.SOCKS5,
                            proxy_host,
                            int(proxy_port),
                            True,
                            proxy_username,
                            proxy_password,
                        )
                    else:
                        proxy = (socks.SOCKS5, proxy_host, int(proxy_port))
                    self.log_signal.emit(f"Подключение через SOCKS5://{proxy_host}:{proxy_port}...")
                    return TelegramClient(
                        "session",
                        self.api_id,
                        self.api_hash,
                        proxy=proxy,
                        connection_retries=3,
                        timeout=10,
                    )
                elif proxy_type == "http":
                    import socks

                    if proxy_username and proxy_password:
                        proxy = (
                            socks.HTTP,
                            proxy_host,
                            int(proxy_port),
                            True,
                            proxy_username,
                            proxy_password,
                        )
                    else:
                        proxy = (socks.HTTP, proxy_host, int(proxy_port))
                    self.log_signal.emit(f"Подключение через HTTP://{proxy_host}:{proxy_port}...")
                    return TelegramClient(
                        "session",
                        self.api_id,
                        self.api_hash,
                        proxy=proxy,
                        connection_retries=3,
                        timeout=10,
                    )
                elif proxy_type == "mtproto":
                    from telethon.network.connection import (
                        ConnectionTcpMTProxyRandomizedIntermediate,
                    )

                    secret = proxy_password or ""
                    self.log_signal.emit(f"Подключение через MTProto://{proxy_host}:{proxy_port}...")
                    return TelegramClient(
                        "session",
                        self.api_id,
                        self.api_hash,
                        connection=ConnectionTcpMTProxyRandomizedIntermediate,
                        proxy=(proxy_host, int(proxy_port), secret),
                        connection_retries=3,
                        timeout=10,
                    )
            except Exception as e:
                self.log_signal.emit(f"Ошибка создания прокси: {e}")
        else:
            # Если прокси в настройках выключен, проверяем наличие активного системного туннеля (VPN/Xray),
            # кроме случаев, когда пользователь явно запросил прямое подключение (force_direct / disable_tunnel / direct)
            explicitly_disabled = bool(
                self.proxy_config.get("force_direct")
                or self.proxy_config.get("disable_tunnel")
                or str(self.proxy_config.get("type", "")).lower() in ("direct", "none")
            )
            if not explicitly_disabled and not os.environ.get("PYTEST_CURRENT_TEST"):
                sys_tunnel = get_system_tunnel_proxy()
                if sys_tunnel:
                    st_type = sys_tunnel.get("type", "socks5")
                    st_host = sys_tunnel.get("host", "127.0.0.1")
                    st_port = sys_tunnel.get("port", 10808)
                    try:
                        import socks

                        sock_type = socks.SOCKS5 if st_type == "socks5" else socks.HTTP
                        self.log_signal.emit(
                            f"Используется активный системный туннель ({st_type.upper()}://{st_host}:{st_port})..."
                        )
                        return TelegramClient(
                            "session",
                            self.api_id,
                            self.api_hash,
                            proxy=(sock_type, st_host, int(st_port)),
                            connection_retries=3,
                            timeout=10,
                        )
                    except Exception as te:
                        logger.debug(f"Не удалось применить системный туннель: {te}")

        return TelegramClient(
            "session",
            self.api_id,
            self.api_hash,
            connection_retries=3,
            timeout=10,
        )

    async def _qr_auth(self):
        try:
            qr_login = await self.client.qr_login()
            self.log_signal.emit(
                "Отсканируйте QR-код в Telegram (Настройки > Устройства > Сканировать QR-код)"
            )
            self.qr_login_signal.emit(qr_login.url)
            end = asyncio.get_running_loop().time() + 120
            while asyncio.get_running_loop().time() < end:
                if self._cancel_requested:
                    return False
                try:
                    await asyncio.wait_for(qr_login.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    continue
            if self._cancel_requested:
                return False
            me = await self.client.get_me()
            if me:
                self.log_signal.emit("QR-авторизация успешна!")
                return True
            return False
        except Exception as e:
            if not self._cancel_requested:
                self.log_signal.emit(f"QR-авторизация не удалась: {e}")
            return False

    async def get_user_input(self, prompt):
        # Очищаем очередь от старых ответов (если остались от предыдущего ввода)
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break

        self.request_code_signal.emit(prompt)

        deadline = asyncio.get_event_loop().time() + USER_INPUT_TIMEOUT
        while not self._cancel_requested:
            try:
                return self._input_queue.get_nowait()
            except queue.Empty:
                pass
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                self.log_signal.emit("Истекло время ожидания ввода данных.")
                return None
            await asyncio.sleep(min(0.2, remaining))
        return None

    def cancel(self):
        self._cancel_requested = True
        if hasattr(self, "recorder") and self.recorder:
            try:
                self.recorder.cancel()
            except Exception:
                pass
        if hasattr(self, "_active_recorders"):
            for r in self._active_recorders:
                try:
                    r.cancel()
                except Exception:
                    pass
