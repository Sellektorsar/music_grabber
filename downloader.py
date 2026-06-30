import asyncio
import queue
import traceback
from PyQt6.QtCore import QThread, pyqtSignal
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from recorder import TelegramAudioRecorder
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Таймаут ожидания ответа пользователя в окне ввода (телефон/код/2FA).
# Защищает от вечного зависания, если диалог по какой-то причине не отобразился.
USER_INPUT_TIMEOUT = 300  # секунд (5 минут)

class DownloadThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    request_code_signal = pyqtSignal(str)
    code_response_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(object)

    def __init__(self, api_id, api_hash, channel, mode, date_from, date_to, proxy_config=None):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.proxy_config = proxy_config or {}
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
            await self.client.connect()
            if not await self.client.is_user_authorized():
                phone = None
                while not phone:
                    if self._cancel_requested:
                        return
                    phone = await self.get_user_input("Введите номер телефона (с кодом страны, например +7...):")
                    if self._cancel_requested:
                        return
                    if not phone:
                        self.log_signal.emit("Номер телефона не может быть пустым. Попробуйте снова.")
                await self.client.send_code_request(phone)
                code = None
                while not code:
                    if self._cancel_requested:
                        return
                    code = await self.get_user_input("Введите код подтверждения, который вы получили:")
                    if self._cancel_requested:
                        return
                    if not code:
                        self.log_signal.emit("Код подтверждения не может быть пустым. Попробуйте снова.")
                try:
                    await self.client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = None
                    while not password:
                        if self._cancel_requested:
                            return
                        password = await self.get_user_input("Введите пароль двухфакторной аутентификации:")
                        if self._cancel_requested:
                            return
                        if not password:
                            self.log_signal.emit("Пароль не может быть пустым. Попробуйте снова.")
                    if self._cancel_requested:
                        return
                    await self.client.sign_in(password=password)
                except Exception as auth_err:
                    self.log_signal.emit(f"Ошибка аутентификации: {auth_err}")
                    return

            me = await self.client.get_me()
            self.log_signal.emit(f"Авторизован как: {me.first_name} {me.last_name or ''}")

            try:
                date_from_dt = datetime.strptime(self.date_from, "%Y-%m-%d") if self.date_from else None
                date_to_dt = datetime.strptime(self.date_to, "%Y-%m-%d") if self.date_to else None
            except ValueError as e:
                self.log_signal.emit(f"Неверный формат даты. Используйте YYYY-MM-DD: {e}")
                return
            if date_from_dt:
                date_from_dt = date_from_dt.replace(tzinfo=None)
            if date_to_dt:
                # Диапазон до конца указанного дня (локальное время)
                date_to_dt = date_to_dt + timedelta(days=1) - timedelta(seconds=1)

            if self._cancel_requested:
                self.log_signal.emit("Загрузка отменена до старта.")
                return

            self.recorder = TelegramAudioRecorder(self.client, self.channel, self.mode, date_from_dt, date_to_dt, self.log_signal.emit, self.progress_signal.emit)
            await self.recorder.start()

            if self._cancel_requested:
                self.log_signal.emit("Загрузка прервана пользователем.")
            else:
                self.log_signal.emit("Загрузка завершена.")
        except Exception as e:
            self.log_signal.emit(f"Ошибка: {e}")
            self.log_signal.emit(traceback.format_exc())
        finally:
            # Гарантированно закрываем соединение и сессию Telethon при любых сценариях,
            # чтобы не оставлять открытый сокет и незавершённую сессию.
            try:
                if hasattr(self, 'client') and self.client.is_connected():
                    await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Ошибка при закрытии соединения: {e}")

    def _create_client(self):
        proxy_enabled = self.proxy_config.get("enabled", False)
        if proxy_enabled:
            proxy_type = self.proxy_config.get("type", "socks5")
            proxy_host = self.proxy_config.get("host", "")
            proxy_port = self.proxy_config.get("port", 0)
            proxy_username = self.proxy_config.get("username") or None
            proxy_password = self.proxy_config.get("password") or None
            try:
                if proxy_type == "socks5":
                    import socks
                    proxy = (socks.SOCKS5, proxy_host, int(proxy_port))
                    self.log_signal.emit(f"Прокси SOCKS5://{proxy_host}:{proxy_port}")
                    return TelegramClient('session', self.api_id, self.api_hash, proxy=proxy)
                elif proxy_type == "http":
                    import socks
                    proxy = (socks.HTTP, proxy_host, int(proxy_port))
                    self.log_signal.emit(f"Прокси HTTP://{proxy_host}:{proxy_port}")
                    return TelegramClient('session', self.api_id, self.api_hash, proxy=proxy)
                elif proxy_type == "mtproto":
                    from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
                    secret = proxy_password or ""
                    self.log_signal.emit(f"Прокси MTProto://{proxy_host}:{proxy_port}")
                    return TelegramClient(
                        'session', self.api_id, self.api_hash,
                        connection=ConnectionTcpMTProxyRandomizedIntermediate,
                        proxy=(proxy_host, int(proxy_port), secret)
                    )
            except Exception as e:
                self.log_signal.emit(f"Ошибка создания прокси: {e}")
        return TelegramClient('session', self.api_id, self.api_hash)

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
        if hasattr(self, 'recorder'):
            self.recorder.cancel()
