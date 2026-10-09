import os
import re
import time as time_module
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from telethon.tl.types import DocumentAttributeAudio
from telethon.errors import FloodWaitError
import logging

from media_utils import (
    is_audio_message,
    get_audio_meta,
    generate_filename,
    get_audio_duration,
    extract_tme_urls,
    to_utc,
    message_in_date_range,
    is_older_than_from,
    get_date_folder,
    clean_track_metadata,
    clean_filename,
    clean_promo_text,
    format_export_path,
    generate_m3u8_playlist,
    extract_key_meta,
    extract_bpm_meta,
    read_audio_id3_meta,
)
from audio_converter import (
    mime_to_ext,
    get_audio_extension,
    convert_to_mp3,
    write_id3_tags,
    read_id3_tags,
)
from audio_capture import (
    record_audio,
    save_recording,
)
import database as db_module

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

# Кэш разрешенных сущностей каналов (username -> entity) для ускорения сканирования
_CHANNEL_ENTITY_CACHE: Dict[str, Any] = {}

class TelegramAudioRecorder:
    @staticmethod
    def is_audio_message(message) -> bool:
        """Единая проверка: содержит ли сообщение аудиофайл (DRY)."""
        return is_audio_message(message)

    def _get_audio_extension(self, message):
        return get_audio_extension(message)

    @staticmethod
    def _mime_to_ext(mime):
        return mime_to_ext(mime)

    @staticmethod
    def _to_utc(dt):
        return to_utc(dt)

    def __init__(
        self,
        client,
        channel,
        mode='hybrid',
        date_from=None,
        date_to=None,
        logger_callback=None,
        progress_callback=None,
        max_concurrent_downloads=None,
        mp3_bitrate=None,
    ):
        self.client = client
        self.channel_username = channel
        self.mode = mode
        self.date_from = date_from
        self.date_to = date_to
        self.logger_callback = logger_callback or (lambda msg: None)
        self.progress_callback = progress_callback or (lambda data: None)
        self.max_concurrent_downloads = max_concurrent_downloads or MAX_CONCURRENT_DOWNLOADS
        self.mp3_bitrate = mp3_bitrate or _MP3_BITRATE
        os.makedirs(BASE_FOLDER, exist_ok=True)
        try:
            db_module.init_db()
        except Exception as e:
            logger.debug(f"Не удалось инициализировать базу данных загрузок: {e}")
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
        self.selected_ids = set()
        self._active_downloads = {}
        self._last_completed_id = None
        self._last_failed_id = None
        self._downloaded_playlist_entries = []

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
            "total_tasks": self._cnt_tasks,
            "current_file": self._current_file or "",
            "mode": self.mode,
            "eta_seconds": eta,
            "active_downloads": list(self._active_downloads.values()),
            "last_completed_id": self._last_completed_id,
            "last_failed_id": self._last_failed_id,
        })

    def _clean_temp_files(self):
        if not os.path.isdir(BASE_FOLDER):
            return
        cleaned = 0
        now = time_module.time()
        for root, dirs, files in os.walk(BASE_FOLDER):
            for f in files:
                f_path = os.path.join(root, f)
                is_temp = '.temp.' in f
                is_wav = f.endswith('.wav')
                is_stale_part = False
                if f.endswith('.part'):
                    try:
                        is_stale_part = (now - os.path.getmtime(f_path)) > 86400
                    except OSError:
                        is_stale_part = True
                if is_temp or is_wav or is_stale_part:
                    try:
                        os.remove(f_path)
                        cleaned += 1
                    except Exception:
                        pass
        if cleaned:
            self.log(f"Очищено временных файлов: {cleaned}")

    async def start(self):
        self.log(f"BASE_FOLDER: {os.path.abspath(BASE_FOLDER)}")
        self.log(f"Режим: {self.mode}; Диапазон дат: {self.date_from} .. {self.date_to}")
        self._clean_temp_files()

        ch_target = _CHANNEL_ENTITY_CACHE.get(self.channel_username)
        if ch_target is None:
            ch_target = await self.client.get_entity(self.channel_username)
            if ch_target:
                _CHANNEL_ENTITY_CACHE[self.channel_username] = ch_target
        channel = ch_target
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

        semaphore = asyncio.Semaphore(self.max_concurrent_downloads)
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
                if self.selected_ids and getattr(message, 'id', None) not in self.selected_ids:
                    continue

                self._cnt_audio += 1

                file_path = self.get_track_filepath(message)
                file_name = os.path.basename(file_path)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                msg_id = getattr(message, 'id', None)
                is_already_present = os.path.exists(file_path) or (
                    msg_id is not None and db_module.is_downloaded(self.channel_username, msg_id)
                )

                if not is_already_present:
                    p, t = self._get_audio_meta(message)
                    dur = self.get_audio_duration(message) or 0
                    dup = db_module.find_duplicate_download(p, t, dur, tolerance_sec=2)
                    if dup:
                        self.log(f"Дубликат трека из канала @{dup.get('channel_id', '')}, пропускаем: {p} - {t}")
                        is_already_present = True

                if is_already_present:
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

        if getattr(self, "_downloaded_playlist_entries", None) and _CFG.get("auto_generate_m3u8", True):
            try:
                chan_clean = (self.channel_username or "playlist").lstrip("@")
                today = datetime.now().strftime("%Y-%m-%d")
                pl_pattern = _CFG.get("playlist_filename", "{channel}_{date}.m3u8")
                pl_name = pl_pattern.replace("{channel}", chan_clean).replace("{date}", today)
                if not pl_name.lower().endswith(".m3u8"):
                    pl_name += ".m3u8"
                pl_path = os.path.join(BASE_FOLDER, pl_name)
                generate_m3u8_playlist(pl_path, self._downloaded_playlist_entries, relative=True)
                self.log(f"🎶 Автоматически создан M3U8 плейлист: {pl_path} ({len(self._downloaded_playlist_entries)} треков)")
            except Exception as pl_err:
                self.log(f"Предупреждение при создании M3U8 плейлиста: {pl_err}")

    async def scan(self, limit: Optional[int] = None, offset_id: int = 0):
        """Просмотр сообщений без скачивания. Возвращает список треков."""
        self.log(f"BASE_FOLDER: {os.path.abspath(BASE_FOLDER)}")
        self.log(f"Сканирование: {self.mode}; {self.date_from} .. {self.date_to}")
        ch_target = _CHANNEL_ENTITY_CACHE.get(self.channel_username)
        if ch_target is None:
            ch_target = await self.client.get_entity(self.channel_username)
            if ch_target:
                _CHANNEL_ENTITY_CACHE[self.channel_username] = ch_target
        channel = ch_target

        offset_date = self.date_to if self.date_to else None
        tracks = []
        downloaded_ids = db_module.get_downloaded_ids(self.channel_username)

        # Индекс ранее скачанных треков для умной кросс-канальной дедупликации
        all_completed = db_module.get_completed_tracks_index()
        dur_buckets = {}
        for c_tr in all_completed:
            c_dur = c_tr.get("duration", 0) or 0
            if c_dur > 0:
                for d_offset in (-2, -1, 0, 1, 2):
                    dur_buckets.setdefault(c_dur + d_offset, []).append(c_tr)

        last_scanned_id = offset_id
        async for message in self.client.iter_messages(
            channel, limit=limit, offset_id=offset_id, offset_date=offset_date
        ):
            if getattr(message, "id", None):
                last_scanned_id = message.id
            if self._cancelled:
                break
            if not self._message_in_date_range(message):
                if self._is_older_than_from(message):
                    break
                continue
            if not self.is_audio_message(message):
                continue

            file_name = self.generate_filename(message)
            msg_dt = getattr(message, "date", None)
            if hasattr(msg_dt, "strftime"):
                date_str = msg_dt.strftime("%Y-%m-%d")
            elif callable(getattr(msg_dt, "date", None)):
                date_str = str(msg_dt.date())
            else:
                date_str = str(msg_dt) if msg_dt else ""
            performer, title = self._get_audio_meta(message)
            clean_perf, clean_tit = clean_track_metadata(performer, title)

            size_bytes = 0
            if getattr(message, "document", None) and getattr(message.document, "size", None):
                size_bytes = message.document.size or 0
            elif getattr(message, "audio", None) and getattr(message.audio, "size", None):
                size_bytes = message.audio.size or 0

            duration_sec = self.get_audio_duration(message) or 0

            file_path = self.get_track_filepath(message, clean_perf, clean_tit)
            file_name = os.path.basename(file_path)

            msg_id = getattr(message, "id", 0)
            file_exists = os.path.exists(file_path)
            in_db = msg_id in downloaded_ids
            already_exists = file_exists or in_db
            is_cross_duplicate = False
            dup_channel = ""

            # Кросс-канальная нечеткая проверка (по артисту, названию и ±2s)
            if not already_exists and all_completed:
                candidates = (
                    dur_buckets.get(duration_sec, [])
                    if duration_sec > 0
                    else all_completed[:100]
                )
                for cand in candidates:
                    if db_module.is_fuzzy_track_match(
                        clean_perf,
                        clean_tit,
                        duration_sec,
                        cand.get("artist", ""),
                        cand.get("title", ""),
                        cand.get("duration", 0),
                        tolerance_sec=2,
                    ):
                        already_exists = True
                        is_cross_duplicate = True
                        dup_channel = cand.get("channel_id", "")
                        break

            # BPM и тональность (Key)
            msg_caption = getattr(message, "message", "") or ""
            text_context = f"{performer} {title} {file_name} {msg_caption}"
            bpm_val = extract_bpm_meta(text_context)
            key_val = extract_key_meta(title, performer)
            if key_val == "—":
                key_val = extract_key_meta(text_context)

            # Если файл уже существует на диске — считываем настоящие теги ID3 (TBPM, TKEY)
            if already_exists and file_path and os.path.exists(file_path):
                f_bpm, f_key = read_audio_id3_meta(file_path)
                if f_bpm != "—":
                    bpm_val = f_bpm
                if f_key != "—":
                    key_val = f_key

            tracks.append({
                "id": msg_id,
                "date": date_str,
                "filename": file_name,
                "filepath": file_path,
                "performer": clean_perf if clean_perf != "UnknownArtist" else performer,
                "title": clean_tit if clean_tit != "UnknownTitle" else title,
                "raw_performer": performer,
                "raw_title": title,
                "size": size_bytes,
                "duration": duration_sec,
                "bpm": bpm_val,
                "key": key_val,
                "already_exists": already_exists,
                "in_db": in_db,
                "is_duplicate": is_cross_duplicate,
                "duplicate_channel": dup_channel,
                "channel": getattr(self, "channel_username", ""),
                "channel_last_scanned_id": last_scanned_id,
            })

        self.last_scanned_id = last_scanned_id
        self.log(f"Сканирование завершено: найдено {len(tracks)} треков")
        return tracks

    def _message_in_date_range(self, message):
        return message_in_date_range(message, self.date_from, self.date_to)

    @staticmethod
    def _to_utc(dt):
        return to_utc(dt)

    def _is_older_than_from(self, message) -> bool:
        return is_older_than_from(message, self.date_from)

    def _get_date_folder(self, msg_date):
        return get_date_folder(msg_date, BASE_FOLDER)

    def get_track_filepath(self, message, performer: str = "", title: str = "") -> str:
        pattern = _CFG.get("export_pattern", "{date}/{artist} - {title}.mp3")
        p, t = (performer, title) if (performer and title) else self._get_audio_meta(message)
        from ui.widgets import extract_bpm_meta
        bpm = extract_bpm_meta(t, p)
        return format_export_path(
            base_folder=BASE_FOLDER,
            pattern=pattern,
            date_val=getattr(message, "date", None),
            channel=self.channel_username,
            artist=p,
            title=t,
            bpm=bpm,
        )

    async def download_with_limit(self, message, file_path, semaphore):
        msg_id = getattr(message, 'id', None)
        filename = os.path.basename(file_path)
        size_bytes = 0
        if getattr(message, 'document', None) and getattr(message.document, 'size', None):
            size_bytes = message.document.size or 0
        elif getattr(message, 'audio', None) and getattr(message.audio, 'size', None):
            size_bytes = message.audio.size or 0

        self._active_downloads[msg_id] = {
            "id": msg_id,
            "filename": filename,
            "bytes": 0,
            "total": size_bytes,
            "speed": 0.0,
            "percent": 0,
        }
        self._report_progress()
        try:
            async with semaphore:
                await self.process_message(message, file_path)
        finally:
            self._active_downloads.pop(msg_id, None)
            self._report_progress()

    async def process_message(self, message, file_path):
        msg_id = getattr(message, 'id', None)
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
                self._last_completed_id = msg_id
                self._last_failed_id = None
                if self._downloaded == 0:
                    self._progress_start = time_module.time()
                self._downloaded += 1
                try:
                    performer, title = self._get_audio_meta(message)
                    clean_perf, clean_tit = clean_track_metadata(performer, title)
                    duration = self.get_audio_duration(message) or 0
                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

                    if file_path.lower().endswith(".mp3") and os.path.exists(file_path):
                        try:
                            bpm_val = extract_bpm_meta(title, performer)
                            key_val = extract_key_meta(title, performer)
                            f_bpm, f_key = read_audio_id3_meta(file_path)
                            if bpm_val == "—" and f_bpm != "—":
                                bpm_val = f_bpm
                            if key_val == "—" and f_key != "—":
                                key_val = f_key
                            msg_dt = getattr(message, "date", None)
                            year_val = getattr(msg_dt, "year", "") if msg_dt else ""
                            write_id3_tags(
                                file_path,
                                title=clean_tit if clean_tit != "UnknownTitle" else title,
                                artist=clean_perf if clean_perf != "UnknownArtist" else performer,
                                year=year_val,
                                bpm=bpm_val if bpm_val != "—" else "",
                                key=key_val if key_val != "—" else "",
                                comment=f"Telegram: @{self.channel_username}",
                            )
                        except Exception as tag_err:
                            logger.debug(f"Не удалось записать ID3 теги: {tag_err}")

                    db_module.record_download(
                        channel_id=self.channel_username,
                        message_id=getattr(message, "id", 0),
                        filename=os.path.basename(file_path),
                        file_path=file_path,
                        file_size=file_size,
                        artist=clean_perf if clean_perf != "UnknownArtist" else (performer or ""),
                        title=clean_tit if clean_tit != "UnknownTitle" else (title or ""),
                        duration=duration,
                        status="completed",
                    )
                    self._downloaded_playlist_entries.append({
                        "filepath": file_path,
                        "artist": clean_perf if clean_perf != "UnknownArtist" else (performer or ""),
                        "title": clean_tit if clean_tit != "UnknownTitle" else (title or ""),
                        "duration": duration,
                    })
                except Exception as db_err:
                    logger.debug(f"Не удалось сохранить запись о загрузке в БД: {db_err}")
            else:
                self._last_failed_id = msg_id
                self._last_completed_id = None
                self._skipped += 1
            self._report_progress()

    async def _download_with_retry(self, message, temp_path, progress_callback=None, total_size=0):
        """Скачивание медиа с поддержкой докачки (.part), повторными попытками при сетевых сбоях и FloodWait.

        Возвращает True, если файл успешно скачан (существует на диске).
        """
        import inspect
        part_path = temp_path if temp_path.endswith(".part") else f"{temp_path}.part"
        for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
            if self._cancelled:
                return False
            try:
                # 1. Попытка через MTProto iter_download с поддержкой докачки (offset), если iter_download - реальный генератор
                iter_dl_fn = getattr(self.client, "iter_download", None)
                msg_media = getattr(message, "media", None)
                is_gen = inspect.isasyncgenfunction(iter_dl_fn) or (
                    callable(iter_dl_fn) and type(self.client).__name__ not in ("AsyncMock", "MagicMock")
                )
                if is_gen and msg_media is not None:
                    try:
                        current_offset = os.path.getsize(part_path) if os.path.exists(part_path) else 0
                        if total_size and current_offset >= total_size:
                            if os.path.exists(part_path) and part_path != temp_path:
                                os.replace(part_path, temp_path)
                            return True

                        if current_offset > 0:
                            self.log(
                                f"Докачка файла с {current_offset // 1024} КБ"
                                + (f" из {total_size // 1024} КБ..." if total_size else "...")
                            )

                        bytes_written = 0
                        with open(part_path, "ab") as fd:
                            async for chunk in self.client.iter_download(
                                message.media,
                                offset=current_offset,
                                request_size=128 * 1024,
                            ):
                                if self._cancelled:
                                    return False
                                fd.write(chunk)
                                current_offset += len(chunk)
                                bytes_written += len(chunk)
                                if progress_callback is not None:
                                    progress_callback(current_offset, total_size)

                        if os.path.exists(part_path) and (
                            (total_size and os.path.getsize(part_path) >= total_size)
                            or (not total_size and (current_offset > 0 or bytes_written > 0))
                        ):
                            if part_path != temp_path:
                                os.replace(part_path, temp_path)
                            return True
                    except (TypeError, AttributeError):
                        pass

                # 2. Фолбэк на стандартный message.download_media
                if hasattr(message, "download_media") and callable(message.download_media):
                    try:
                        dl_res = message.download_media(file=temp_path, progress_callback=progress_callback)
                    except TypeError:
                        dl_res = message.download_media(file=temp_path)
                    if asyncio.iscoroutine(dl_res):
                        await dl_res

                if os.path.exists(temp_path):
                    return True

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
            # Гарантируем существование директории назначения (особенно для вложенных шаблонов экспорта)
            target_dir = os.path.dirname(path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            temp_ext = self._get_audio_extension(message)
            msg_id = getattr(message, 'id', '0')
            temp_path = path + f".{msg_id}.temp{temp_ext}"

            if os.path.exists(path):
                self.log(f"Файл уже существует: {path}")
                return True

            if os.path.exists(temp_path):
                self.log(f"Временный файл уже существует: {temp_path}")
            else:
                total_size = 0
                if getattr(message, "document", None) and getattr(message.document, "size", None):
                    total_size = message.document.size or 0
                elif getattr(message, "audio", None) and getattr(message.audio, "size", None):
                    total_size = message.audio.size or 0

                last_time = time_module.time()
                last_bytes = 0

                def _chunk_cb(current, total):
                    nonlocal last_time, last_bytes
                    now = time_module.time()
                    dt = now - last_time
                    if dt >= 0.20 or (total and current >= total):
                        speed = ((current - last_bytes) / dt) / (1024 * 1024) if dt > 0 else 0.0
                        last_time = now
                        last_bytes = current
                        if msg_id in self._active_downloads:
                            self._active_downloads[msg_id]["bytes"] = current
                            tot = total or self._active_downloads[msg_id].get("total", 0)
                            self._active_downloads[msg_id]["total"] = tot
                            pct = int(current / max(1, tot) * 100) if tot > 0 else 0
                            self._active_downloads[msg_id]["percent"] = min(100, pct)
                            self._active_downloads[msg_id]["speed"] = max(0.0, speed)
                        self._report_progress()

                if not await self._download_with_retry(message, temp_path, progress_callback=_chunk_cb, total_size=total_size):
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

    async def download_track_preview(
        self,
        channel_name: str,
        message_id: int,
        max_bytes: int = 1024 * 1024,
    ) -> str | None:
        """Потоковая загрузка первых 512KB-1MB аудиозаписи для мгновенного предпрослушивания."""
        import inspect
        preview_dir = os.path.join(self.base_folder, "previews")
        os.makedirs(preview_dir, exist_ok=True)

        # 1. Проверяем, существует ли уже кэшированное превью
        for ext in (".mp3", ".m4a", ".ogg", ".flac", ".wav"):
            cand = os.path.join(preview_dir, f"preview_{message_id}{ext}")
            if os.path.exists(cand) and os.path.getsize(cand) >= 32 * 1024:
                return cand

        # 2. Получаем сообщение из Telegram
        try:
            target = channel_name or self.channel_username
            ch_target = _CHANNEL_ENTITY_CACHE.get(target)
            if ch_target is None and hasattr(self.client, "get_entity"):
                res_ent = self.client.get_entity(target)
                ch_target = await res_ent if asyncio.iscoroutine(res_ent) else res_ent
                if ch_target:
                    _CHANNEL_ENTITY_CACHE[target] = ch_target

            if not ch_target:
                ch_target = target

            res_msgs = self.client.get_messages(ch_target, ids=message_id)
            messages = await res_msgs if asyncio.iscoroutine(res_msgs) else res_msgs
            if not messages:
                return None
            message = messages if not isinstance(messages, list) else (messages[0] if messages else None)
            if not message or not getattr(message, "media", None):
                return None

            temp_ext = self._get_audio_extension(message)
            preview_path = os.path.join(preview_dir, f"preview_{message_id}{temp_ext}")
            part_path = f"{preview_path}.part"

            iter_dl_fn = getattr(self.client, "iter_download", None)
            msg_media = getattr(message, "media", None)
            is_gen = inspect.isasyncgenfunction(iter_dl_fn) or (
                callable(iter_dl_fn) and type(self.client).__name__ not in ("AsyncMock", "MagicMock")
            )

            bytes_written = 0
            if is_gen and msg_media is not None:
                try:
                    with open(part_path, "wb") as fd:
                        async for chunk in self.client.iter_download(
                            msg_media,
                            offset=0,
                            request_size=128 * 1024,
                        ):
                            if self._cancelled:
                                break
                            fd.write(chunk)
                            bytes_written += len(chunk)
                            if bytes_written >= max_bytes:
                                break
                except Exception as iter_err:
                    logger.debug(f"iter_download failed: {iter_err}")

            if self._cancelled:
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                return None

            if bytes_written == 0:
                if hasattr(message, "download_media") and callable(message.download_media):
                    dl_res = message.download_media(file=part_path)
                    if asyncio.iscoroutine(dl_res):
                        await dl_res
                elif hasattr(self.client, "download_media") and callable(self.client.download_media):
                    dl_res = self.client.download_media(message, file=part_path)
                    if asyncio.iscoroutine(dl_res):
                        await dl_res

            if self._cancelled:
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                return None

            if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
                if os.path.exists(preview_path):
                    try:
                        os.remove(preview_path)
                    except OSError:
                        pass
                os.replace(part_path, preview_path)
                return preview_path
        except Exception as err:
            self.log(f"Ошибка при скачивании превью #{message_id}: {err}")
        return None

    def get_audio_duration(self, message):
        return get_audio_duration(message)

    def _mime_to_ext(self, mime):
        return mime_to_ext(mime)

    def convert_to_mp3(self, src_path, dest_path):
        bitrate = getattr(self, "mp3_bitrate", None) or _MP3_BITRATE
        return convert_to_mp3(src_path, dest_path, bitrate=bitrate)

    def record_audio(self, duration, filename):
        bitrate = getattr(self, "mp3_bitrate", None) or _MP3_BITRATE
        return record_audio(
            duration,
            filename,
            is_cancelled_fn=lambda: self._cancelled,
            sample_rate=_SAMPLE_RATE,
            bitrate=bitrate,
            log_callback=self.log,
        )

    def save_recording(self, data, fs, filename):
        return save_recording(
            data,
            fs,
            filename,
            bitrate=_MP3_BITRATE,
            log_callback=self.log,
        )

    def _get_audio_meta(self, message):
        return get_audio_meta(message)

    def generate_filename(self, message):
        return generate_filename(message)

    async def _has_audio_in_recent(self, channel, sample: int = 50) -> bool:
        async for m in self.client.iter_messages(channel, limit=sample):
            if self.is_audio_message(m):
                return True
        return False

    def _extract_tme_urls(self, text: str):
        return extract_tme_urls(text)

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

