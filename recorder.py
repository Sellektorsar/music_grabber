import os
import re
import time as time_module
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from telethon.tl.types import DocumentAttributeAudio
from telethon.errors import FloodWaitError
from pydub import AudioSegment
from scipy.io.wavfile import write as scipy_write
import numpy as np
import sounddevice as sd
import logging

logger = logging.getLogger(__name__)

try:
    from config import load_config
    _CFG = load_config()
except (ImportError, FileNotFoundError, ValueError, OSError):
    _CFG = {}

BASE_FOLDER = _CFG.get("base_folder", "telegram_audio")
MAX_CONCURRENT_DOWNLOADS = _CFG.get("max_concurrent_downloads", 5)
MAX_DOWNLOAD_RETRIES = _CFG.get("max_download_retries", 3)
_DOWNLOAD_DELAY = _CFG.get("download_delay", 1)
_MP3_BITRATE = _CFG.get("mp3_bitrate", "192k")
_SAMPLE_RATE = _CFG.get("sample_rate", 44100)

# Ошибки Telethon, при которых оправдан повтор с задержкой
_RETRYABLE_NETWORK_ERRORS = (
    ConnectionError,
    asyncio.TimeoutError,
    OSError,
)

class TelegramAudioRecorder:
    @staticmethod
    def is_audio_message(message) -> bool:
        """Единая проверка: содержит ли сообщение аудиофайл (DRY).

        Используется в основном цикле, превью, _has_audio_in_recent и автопоиске канала.
        """
        if getattr(message, 'audio', None):
            return True
        mime = getattr(getattr(message, 'document', None), 'mime_type', None)
        return bool(mime and str(mime).startswith('audio/'))

    def _get_audio_extension(self, message):
        if message.audio:
            if message.audio.mime_type:
                return self._mime_to_ext(message.audio.mime_type)
        if message.document:
            if message.document.mime_type:
                return self._mime_to_ext(message.document.mime_type)
            if message.file and message.file.name:
                _, ext = os.path.splitext(message.file.name)
                if ext:
                    return ext
        return ".ogg"

    def __init__(self, client, channel, mode='hybrid', date_from=None, date_to=None, logger_callback=None, progress_callback=None):
        self.client = client
        self.channel_username = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.logger_callback = logger_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda data: None)
        os.makedirs(BASE_FOLDER, exist_ok=True)
        self._cancelled = False

        # Счетчики для диагностики
        self._cnt_total = 0
        self._cnt_in_range = 0
        self._cnt_audio = 0
        self._cnt_tasks = 0

        # Счетчики прогресса
        self._downloaded = 0
        self._skipped = 0
        self._already_exists = 0
        self._current_file = ""
        self._progress_start = 0.0

    def log(self, msg):
        self.logger_callback(msg)
        logger.info(msg)

    def cancel(self):
        self._cancelled = True

    def _report_progress(self):
        if not self.progress_callback:
            return
        eta = 0.0
        if self._downloaded > 0 and self._progress_start > 0:
            elapsed = time_module.time() - self._progress_start
            avg = elapsed / self._downloaded
            remaining = max(0, self._cnt_audio - self._already_exists - self._downloaded - self._skipped)
            eta = avg * remaining
        self.progress_callback({
            "total_scanned": self._cnt_total,
            "audio_found": self._cnt_audio,
            "downloaded": self._downloaded,
            "skipped": self._skipped,
            "already_exists": self._already_exists,
            "current_file": self._current_file or "",
            "mode": self.mode,
            "eta_seconds": eta,
        })

    def _clean_temp_files(self):
        if not os.path.isdir(BASE_FOLDER):
            return
        cleaned = 0
        for root, dirs, files in os.walk(BASE_FOLDER):
            for f in files:
                is_temp = '.temp.' in f
                is_wav = f.endswith('.wav')
                if is_temp or is_wav:
                    try:
                        os.remove(os.path.join(root, f))
                        cleaned += 1
                    except Exception:
                        pass
        if cleaned:
            self.log(f"Очищено временных файлов: {cleaned}")

    async def start(self):
        self.log(f"BASE_FOLDER: {os.path.abspath(BASE_FOLDER)}")
        self.log(f"Режим: {self.mode}; Диапазон дат: {self.date_from} .. {self.date_to}")
        self._clean_temp_files()

        channel = await self.client.get_entity(self.channel_username)
        # Расширенная диагностика по сущности канала
        try:
            ch_username = getattr(channel, 'username', None)
            ch_id = getattr(channel, 'id', None)
            ch_title = getattr(channel, 'title', None)
            ch_flags = {
                'broadcast': getattr(channel, 'broadcast', None),
                'megagroup': getattr(channel, 'megagroup', None),
                'gigagroup': getattr(channel, 'gigagroup', None),
                'forum': getattr(channel, 'forum', None),
            }
            self.log(f"Подключение к каналу: {ch_title} (@{ch_username}) id={ch_id} flags={ch_flags}")
        except Exception:
            self.log(f"Подключение к каналу: {getattr(channel, 'title', 'unknown')}")

        # Консервативный автопереход: только если в последних 50 сообщениях нет аудио
        try:
            has_audio_here = await self._has_audio_in_recent(channel, sample=50)
            if not has_audio_here:
                maybe = await self._maybe_follow_redirect(channel)
                if maybe and getattr(maybe, 'id', None) != getattr(channel, 'id', None):
                    new_flags = {
                        'broadcast': getattr(maybe, 'broadcast', None),
                        'megagroup': getattr(maybe, 'megagroup', None),
                        'gigagroup': getattr(maybe, 'gigagroup', None),
                        'forum': getattr(maybe, 'forum', None),
                    }
                    self.log(f"Обнаружена ссылка на основной канал, переключаемся: {getattr(maybe,'title',None)} (@{getattr(maybe,'username',None)}) id={getattr(maybe,'id',None)} flags={new_flags}")
                    channel = maybe
        except Exception as e:
            self.log(f"Автопоиск основного канала не удался: {e}")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        tasks = []
        preview_count = 0

        # Стартуем итерацию с сообщения старше верхней границы диапазона
        # (offset_date = эксклюзивная граница «старше чем»), чтобы не сканировать
        # лишние сообщения новее date_to.
        offset_date = self.date_to if self.date_to else None

        # Итерируем сообщения канала (Telethon отдаёт от новых к старым)
        async for message in self.client.iter_messages(channel, limit=None, offset_date=offset_date):
            if self._cancelled:
                self.log("Загрузка прервана пользователем.")
                break

            self._cnt_total += 1

            # Превью первых 5 сообщений
            if preview_count < 5:
                try:
                    msg_date = getattr(message, 'date', None)
                    mime = None
                    if getattr(message, 'document', None) and getattr(message.document, 'mime_type', None):
                        mime = message.document.mime_type
                    self.log(f"[preview] msg_id={getattr(message, 'id', None)} date={msg_date} has_audio={self.is_audio_message(message)} mime={mime}")
                except Exception:
                    self.log(f"[preview] msg_id={getattr(message, 'id', None)} — ошибка извлечения сведений")
                finally:
                    preview_count += 1

            # Фильтр по диапазону дат. Сообщения идут от новых к старым.
            if not self._message_in_date_range(message):
                # Если сообщение уже старше нижней границы — дальше пойдут только
                # более старые, весь остаток истории вне диапазона: завершаем обход.
                if self._is_older_than_from(message):
                    break
                continue

            self._cnt_in_range += 1

            if self.is_audio_message(message):
                self._cnt_audio += 1

                date_folder = self._get_date_folder(message.date)
                os.makedirs(date_folder, exist_ok=True)

                file_name = self.generate_filename(message)
                file_path = os.path.join(date_folder, file_name)

                if os.path.exists(file_path):
                    self.log(f"Файл уже существует, пропускаем: {file_path}")
                    self._already_exists += 1
                    self._report_progress()
                    continue

                task = asyncio.create_task(self.download_with_limit(message, file_path, semaphore))
                tasks.append(task)
                self._cnt_tasks += 1
                await asyncio.sleep(_DOWNLOAD_DELAY)  # Небольшая задержка для безопасности

            self._report_progress()

        # Итоговая сводка
        self.log(
            f"Сводка: сообщений просмотрено={self._cnt_total}, в диапазоне={self._cnt_in_range}, аудио найдено={self._cnt_audio}, задач создано={self._cnt_tasks}"
        )

        if tasks:
            # return_exceptions=True: сбой одной задачи не должен обрывать остальные.
            # process_message уже оборачивает основную логику в try/except, поэтому
            # исключения здесь — это форс-мажорные случаи, логируем их и идём дальше.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    self.log(f"Ошибка фоновой задачи: {r}")
        else:
            if self._cnt_audio == 0:
                self.log("Аудиосообщений не найдено. Убедитесь, что указали @username канала (а не его отображаемое имя) и проверьте диапазон дат.")

    def _message_in_date_range(self, message):
        if not self.date_from and not self.date_to:
            return True
        # message.date приходит из Telethon как aware datetime (UTC).
        # date_from/date_to из GUI — наивные локальные даты/время пользователя.
        # Приводим их к aware (через astimezone, для naive трактуется как локальное),
        # затем к UTC для корректного сравнения.
        msg_date = message.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        date_from_utc = self._to_utc(self.date_from)
        date_to_utc = self._to_utc(self.date_to)
        if date_from_utc and msg_date < date_from_utc:
            return False
        if date_to_utc and msg_date > date_to_utc:
            return False
        return True

    @staticmethod
    def _to_utc(dt):
        """Границы диапазона из GUI — наивные локальные datetime.
        Приводим к aware-локальному, затем к UTC. None пропускаем.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.astimezone()  # naive -> локальное tz (соглашение)
        return dt.astimezone(timezone.utc)

    def _is_older_than_from(self, message) -> bool:
        """Сообщения итерируются от новых к старым.
        Возвращает True, если сообщение уже старше нижней границы диапазона,
        т.е. дальше идти нет смысла — можно прервать обход истории.
        """
        if not self.date_from:
            return False
        msg_date = message.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        return msg_date < self._to_utc(self.date_from)

    def _get_date_folder(self, msg_date):
        # Имя папки формируем по локальному времени пользователя,
        # чтобы файлы группировались по «человеческим» датам.
        if msg_date.tzinfo is not None:
            msg_date = msg_date.astimezone()
        date_str = msg_date.strftime("%Y-%m-%d")
        return os.path.join(BASE_FOLDER, date_str)

    async def download_with_limit(self, message, file_path, semaphore):
        async with semaphore:
            await self.process_message(message, file_path)

    async def process_message(self, message, file_path):
        self._current_file = os.path.basename(file_path)
        self._report_progress()
        succeeded = False
        try:
            if self.mode in ['direct', 'hybrid']:
                if await self.try_direct_download(message, file_path):
                    succeeded = True

            if not succeeded and self.mode in ['record', 'hybrid']:
                duration = self.get_audio_duration(message)
                if duration:
                    await asyncio.to_thread(self.record_audio, duration, file_path)
                    succeeded = True
                else:
                    self.log("Не удалось определить длительность аудио для записи")
        except Exception as e:
            self.log(f"Ошибка обработки сообщения: {e}")
            self.log(traceback.format_exc())
        finally:
            if succeeded:
                if self._downloaded == 0:
                    self._progress_start = time_module.time()
                self._downloaded += 1
            else:
                self._skipped += 1
            self._report_progress()

    async def _download_with_retry(self, message, temp_path):
        """Скачивание медиа с повторными попытками при сетевых сбоях и FloodWait.

        Возвращает True, если файл успешно скачан (существует на диске).
        """
        for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
            if self._cancelled:
                return False
            try:
                await message.download_media(file=temp_path)
                if os.path.exists(temp_path):
                    return True
                # Медиа может отсутствовать в сообщении (атрибут есть, файла нет).
                self.log(f"Попытка {attempt}/{MAX_DOWNLOAD_RETRIES}: медиа не скачано (отсутствует).")
                return False
            except FloodWaitError as e:
                wait = int(getattr(e, 'seconds', 1))
                self.log(f"FloodWait: ожидание {wait} сек. перед повтором (попытка {attempt}/{MAX_DOWNLOAD_RETRIES}).")
                # Ждём порциями, чтобы оставить возможность реакции на cancel.
                end = asyncio.get_event_loop().time() + wait
                while asyncio.get_event_loop().time() < end:
                    if self._cancelled:
                        return False
                    await asyncio.sleep(min(1.0, max(0.0, end - asyncio.get_event_loop().time())))
            except _RETRYABLE_NETWORK_ERRORS as e:
                self.log(f"Сетевая ошибка (попытка {attempt}/{MAX_DOWNLOAD_RETRIES}): {e}")
                await asyncio.sleep(2 * attempt)
            except Exception as e:
                # Непонятная/не сетевая ошибка — не ретраим, прокидываем наверх.
                raise
        return False

    async def try_direct_download(self, message, path):
        try:
            temp_ext = self._get_audio_extension(message)
            msg_id = getattr(message, 'id', '0')
            temp_path = path + f".{msg_id}.temp{temp_ext}"

            if os.path.exists(path):
                self.log(f"Файл уже существует: {path}")
                return True

            if os.path.exists(temp_path):
                self.log(f"Временный файл уже существует: {temp_path}")
            else:
                if not await self._download_with_retry(message, temp_path):
                    self.log(f"Не удалось скачать медиа для сообщения {getattr(message, 'id', '?')}.")
                    return False
                self.log(f"Скачан временный файл: {temp_path}")

            # Подстраховка: если файла всё-таки нет (медиа отсутствовало) — выходим без os.replace.
            if not os.path.exists(temp_path):
                self.log(f"Медиа отсутствует, пропуск (нет файла {temp_path}).")
                return False

            # Если уже MP3 — сохраняем без конвертации
            if temp_ext.lower() == ".mp3":
                os.replace(temp_path, path)
                self.log(f"Сохранён без конвертации: {path}")
                return True

            # Пытаемся конвертировать в MP3 (ffmpeg — блокирующий подпроцесс,
            # выносим из event-loop, чтобы не морозить цикл и(cancel оставался отзывчивым).
            try:
                await asyncio.to_thread(self.convert_to_mp3, temp_path, path)
                os.remove(temp_path)
                self.log(f"Конвертирован и сохранён: {path}")
                return True
            except Exception as conv_err:
                self.log(f"Конвертация не удалась: {conv_err}")
                # Фолбэк: сохраняем оригинал с исходным расширением
                fallback_path = os.path.splitext(path)[0] + temp_ext
                os.replace(temp_path, fallback_path)
                self.log(f"Сохранён оригинал без конвертации: {fallback_path}")
                return True
        except Exception as e:
            self.log(f"Не удалось скачать напрямую: {e}")
            self.log(traceback.format_exc())
            return False

    def get_audio_duration(self, message):
        if message.audio and hasattr(message.audio, 'duration'):
            return message.audio.duration
        if message.document:
            audio_attrs = [attr for attr in message.document.attributes if isinstance(attr, DocumentAttributeAudio)]
            if audio_attrs:
                return audio_attrs[0].duration
        return None

    def _mime_to_ext(self, mime):
        if not mime:
            return ".ogg"
        mapping = {
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/x-wav": ".wav",
            "audio/wav": ".wav",
            "audio/x-flac": ".flac",
            "audio/flac": ".flac",
            "audio/aac": ".aac",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
        }
        return mapping.get(mime.lower(), ".ogg")

    def convert_to_mp3(self, src_path, dest_path):
        audio = AudioSegment.from_file(src_path)
        audio.export(dest_path, format="mp3", bitrate=_MP3_BITRATE)

    def record_audio(self, duration, filename):
        try:
            fs = _SAMPLE_RATE
            frames = int(duration * fs)
            self.log(f"Запись аудио длительностью {duration} сек. в файл {filename}")

            recording = np.zeros((frames, 2), dtype=np.float32)
            current_frame = 0

            def callback(indata, frames_per_buffer, time_info, status):
                nonlocal current_frame
                if self._cancelled:
                    raise sd.CallbackAbort()
                remaining = frames - current_frame
                if remaining <= 0:
                    return
                to_copy = min(frames_per_buffer, remaining)
                recording[current_frame:current_frame + to_copy] = indata[:to_copy]
                current_frame += to_copy

            with sd.InputStream(samplerate=fs, channels=2, callback=callback, blocksize=4096):
                while current_frame < frames and not self._cancelled:
                    sd.sleep(0.1)

            if self._cancelled:
                recording = recording[:current_frame]
                self.log(f"Запись прервана, сохранено {current_frame / fs:.1f} сек.")
            elif current_frame < frames:
                recording = recording[:current_frame]

            if current_frame > 0:
                self.save_recording(recording, fs, filename)
            else:
                self.log("Запись не выполнена (нет данных).")
        except Exception as e:
            self.log(f"Ошибка записи аудио: {e}")

    def save_recording(self, data, fs, filename):
        if data.dtype != np.int16:
            max_abs = np.max(np.abs(data))
            if max_abs > 0:
                data = (data / max_abs * 32767).astype(np.int16)
            else:
                data = data.astype(np.int16)
        wav_temp = filename + ".wav"
        try:
            scipy_write(wav_temp, fs, data)
            self.convert_to_mp3(wav_temp, filename)
            self.log(f"Аудио записано и конвертировано: {filename}")
        finally:
            if os.path.exists(wav_temp):
                os.remove(wav_temp)

    def generate_filename(self, message):
        try:
            if message.audio:
                attrs = message.audio
                artist = attrs.performer or "UnknownArtist"
                title = attrs.title or "UnknownTitle"
            else:
                audio_attrs = [attr for attr in message.document.attributes if isinstance(attr, DocumentAttributeAudio)]
                if audio_attrs:
                    artist = audio_attrs[0].performer or "UnknownArtist"
                    title = audio_attrs[0].title or "UnknownTitle"
                else:
                    artist = "UnknownArtist"
                    title = "UnknownTitle"

            filename = f"{artist} - {title}.mp3"
            invalid_chars = '/\\:*?"<>|'
            for ch in invalid_chars:
                filename = filename.replace(ch, "_")
            return filename
        except Exception:
            msg_id = getattr(message, 'id', int(datetime.now().timestamp() * 1000))
            return f"track_{msg_id}.mp3"

    async def _has_audio_in_recent(self, channel, sample: int = 50) -> bool:
        async for m in self.client.iter_messages(channel, limit=sample):
            if self.is_audio_message(m):
                return True
        return False

    def _extract_tme_urls(self, text: str):
        pattern = r"(https?://t\.me/[^\s]+|t\.me/[^\s]+)"
        result = []
        for m in re.finditer(pattern, text or ''):
            url = m.group(0)
            if url.startswith('https://') or url.startswith('http://'):
                url = url.split('://', 1)[1]
            result.append(url)
        return result

    async def _maybe_follow_redirect(self, channel):
        candidate_urls = []
        async for msg in self.client.iter_messages(channel, limit=10):
            candidate_urls.extend(self._extract_tme_urls(getattr(msg, 'raw_text', '') or ''))
            try:
                if msg.buttons:
                    for row in msg.buttons:
                        for btn in row:
                            url = getattr(btn, 'url', None)
                            if url:
                                candidate_urls.extend(self._extract_tme_urls(url))
            except Exception:
                pass
        # фильтр ссылок на t.me без boost
        clean = []
        for u in candidate_urls:
            if 't.me/boost/' in u:
                continue
            if 't.me/' in u:
                clean.append(u)
        # уникализируем
        seen = set()
        uniq = []
        for u in clean:
            if u not in seen:
                uniq.append(u)
                seen.add(u)
        for url in uniq:
            try:
                ent = await self.client.get_entity(url)
                if getattr(ent, 'broadcast', False):
                    # есть ли аудио в первых 5 постах?
                    async for m in self.client.iter_messages(ent, limit=5):
                        if self.is_audio_message(m):
                            return ent
            except Exception:
                continue
        return None

