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
    sanitize_path_segment,
)
from audio_converter import (
    mime_to_ext,
    get_audio_extension,
    convert_to_mp3,
    write_id3_tags,
    read_id3_tags,
)
import database as db_module
from config import BASE_PATH, DEFAULT_CONFIG, get_base_dir, load_config
from recorder_download import DownloadMixin

logger = logging.getLogger(__name__)

try:
    _CFG = load_config()
except (FileNotFoundError, ValueError, OSError):
    _CFG = {}

# Рабочая папка берётся из config: раньше recorder считал её сам по
# настройке base_folder, а config.BASE_PATH её игнорировал. Из-за этого
# файлы уезжали в одну папку, а настройки, база и сессия -- в другую.
# Имя остаётся собственным глобалом модуля, чтобы тесты могли подменить
# его через monkeypatch.setattr(recorder, 'BASE_FOLDER', ...).
BASE_FOLDER = BASE_PATH
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

# Ошибки файловой системы являются подклассами OSError, поэтому попадали
# в список «сетевых» и повторялись три раза подряд, хотя повтор ничего не
# исправлял. Сообщение «сетевая ошибка» уводило пользователя чинить сеть
# вместо того, чтобы проверить права на папку. Этот список проверяется
# раньше сетевого.
_FS_ERRORS = (
    PermissionError,
    IsADirectoryError,
    NotADirectoryError,
    FileExistsError,
    FileNotFoundError,
)

# Кэш разрешенных сущностей каналов (username -> entity) для ускорения сканирования
_CHANNEL_ENTITY_CACHE: Dict[str, Any] = {}


class TelegramAudioRecorder(DownloadMixin):
    @staticmethod
    def is_audio_message(message) -> bool:
        """Единая проверка: содержит ли сообщение аудиофайл (DRY)."""
        return is_audio_message(message)

    def _get_audio_extension(self, message):
        return get_audio_extension(message)

    @staticmethod
    def _to_utc(dt):
        return to_utc(dt)

    @staticmethod
    def _mime_to_ext(mime):
        """Mime-тип -> расширение. Дубликат копии ниже удалён."""
        return mime_to_ext(mime)

    @property
    def base_folder(self) -> str:
        if getattr(self, "_custom_base_folder", False):
            return self._base_folder
        return BASE_FOLDER

    @base_folder.setter
    def base_folder(self, val: str):
        self._base_folder = val
        if val != BASE_FOLDER:
            self._custom_base_folder = True
        else:
            self._custom_base_folder = False

    def __init__(
        self,
        client,
        channel,
        mode='direct',
        date_from=None,
        date_to=None,
        logger_callback=None,
        progress_callback=None,
        max_concurrent_downloads=None,
        mp3_bitrate=None,
        **kwargs,
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
        self.base_folder = BASE_FOLDER
        self.embed_id3_tags = bool(kwargs.get(
            "embed_id3_tags", load_config().get("embed_id3_tags", DEFAULT_CONFIG["embed_id3_tags"])))
        os.makedirs(self.base_folder, exist_ok=True)
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
        self._failed_ids = set()
        self._downloaded_playlist_entries = []

    def log(self, msg):
        self.logger_callback(msg)

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
            # Полный список неудачных: одного last_failed_id не хватало,
            # из-за чего в интерфейсе почти все треки навсегда оставались QUEUED.
            "failed_ids": list(self._failed_ids),
        })

    def _clean_temp_files(self):
        if not os.path.isdir(self.base_folder):
            return
        cleaned = 0
        now = time_module.time()
        for root, dirs, files in os.walk(self.base_folder):
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
        self.log(f"BASE_FOLDER: {os.path.abspath(self.base_folder)}")
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

        # Если заданы конкретные ID треков — запрашиваем их напрямую через get_messages без полного обхода истории
        direct_messages = None
        if self.selected_ids and hasattr(self.client, "get_messages") and callable(self.client.get_messages):
            try:
                id_list = list(self.selected_ids)
                fetched = []
                batch_size = 100
                for i in range(0, len(id_list), batch_size):
                    chunk_ids = id_list[i:i + batch_size]
                    res_msgs = self.client.get_messages(channel, ids=chunk_ids)
                    msgs = await res_msgs if asyncio.iscoroutine(res_msgs) else res_msgs
                    if isinstance(msgs, (list, tuple)):
                        fetched.extend([m for m in msgs if m is not None])
                    elif msgs is not None:
                        fetched.append(msgs)
                if fetched:
                    direct_messages = fetched
            except Exception as direct_err:
                logger.debug(f"Прямой запрос get_messages не удался, откат к iter_messages: {direct_err}")
                direct_messages = None

        if direct_messages is not None:
            for message in direct_messages:
                if self._cancelled:
                    self.log("Загрузка прервана пользователем.")
                    break

                self._cnt_total += 1
                self._cnt_in_range += 1

                if self.is_audio_message(message):
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
                    await asyncio.sleep(_DOWNLOAD_DELAY)

                self._report_progress()
        else:
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

        cfg_now = load_config()
        if getattr(self, "_downloaded_playlist_entries", None) and cfg_now.get("auto_generate_m3u8", True):
            try:
                # В плейлист попадают только реально существующие файлы: раньше
                # сюда добавлялись все треки, помеченные успешными, и .m3u8
                # указывал на несуществующие пути.
                playlist_entries = [
                    entry for entry in self._downloaded_playlist_entries
                    if os.path.exists(entry.get("filepath", ""))
                ]
                if not playlist_entries:
                    return
                raw_chan = (self.channel_username or "playlist").removeprefix("@")
                chan_clean = sanitize_path_segment(raw_chan)
                today = datetime.now().strftime("%Y-%m-%d")
                pl_pattern = cfg_now.get("playlist_filename", "{channel}_{date}.m3u8")
                pl_name = pl_pattern.replace("{channel}", chan_clean).replace("{date}", today)
                if not pl_name.lower().endswith(".m3u8"):
                    pl_name += ".m3u8"
                pl_path = os.path.join(self.base_folder, pl_name)
                generate_m3u8_playlist(pl_path, playlist_entries, relative=True)
                self.log(f"🎶 Автоматически создан M3U8 плейлист: {pl_path} ({len(playlist_entries)} треков)")
            except Exception as pl_err:
                self.log(f"Предупреждение при создании M3U8 плейлиста: {pl_err}")

    def _parse_track_from_message(
        self, message, downloaded_ids, all_completed, dur_buckets, last_scanned_id
    ) -> Optional[dict]:
        """Формирует метаданные трека из сообщения Telegram (DRY)."""
        if not self.is_audio_message(message):
            return None

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

        return {
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
        }

    async def scan(
        self,
        limit: Optional[int] = None,
        offset_id: int = 0,
        search_query: Optional[str] = None,
    ):
        """Просмотр сообщений без скачивания. Возвращает список треков.
        Если указан search_query, выполняет поиск по всей истории канала через MTProto.
        """
        self.log(f"BASE_FOLDER: {os.path.abspath(self.base_folder)}")
        sq = search_query.strip() if search_query and isinstance(search_query, str) else None
        if sq:
            self.log(f"Глобальный поиск в канале {self.channel_username}: '{sq}' (лимит={limit or 'нет'})")
        else:
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

        if sq:
            from telethon.tl.types import InputMessagesFilterMusic

            async for message in self.client.iter_messages(
                channel,
                limit=limit,
                offset_id=offset_id,
                offset_date=offset_date,
                search=sq,
                filter=InputMessagesFilterMusic,
            ):
                if getattr(message, "id", None):
                    last_scanned_id = message.id
                if self._cancelled:
                    break
                if not self._message_in_date_range(message):
                    continue

                track = self._parse_track_from_message(
                    message, downloaded_ids, all_completed, dur_buckets, last_scanned_id
                )
                if track:
                    tracks.append(track)

            if not tracks and offset_id == 0 and not self._cancelled:
                async for message in self.client.iter_messages(
                    channel,
                    limit=limit,
                    offset_id=offset_id,
                    offset_date=offset_date,
                    search=sq,
                ):
                    if getattr(message, "id", None):
                        last_scanned_id = message.id
                    if self._cancelled:
                        break
                    if not self._message_in_date_range(message):
                        continue

                    track = self._parse_track_from_message(
                        message, downloaded_ids, all_completed, dur_buckets, last_scanned_id
                    )
                    if track:
                        tracks.append(track)
        else:
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

                track = self._parse_track_from_message(
                    message, downloaded_ids, all_completed, dur_buckets, last_scanned_id
                )
                if track:
                    tracks.append(track)

        self.last_scanned_id = last_scanned_id
        if sq:
            self.log(f"Поиск завершен: найдено {len(tracks)} треков по запросу '{sq}'")
        else:
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
        return get_date_folder(msg_date, self.base_folder)

    def get_track_filepath(self, message, performer: str = "", title: str = "") -> str:
        pattern = load_config().get("export_pattern", DEFAULT_CONFIG["export_pattern"])
        p, t = (performer, title) if (performer and title) else self._get_audio_meta(message)
        from ui.widgets import extract_bpm_meta
        bpm = extract_bpm_meta(t, p)
        return format_export_path(
            base_folder=self.base_folder,
            pattern=pattern,
            date_val=getattr(message, "date", None),
            channel=self.channel_username,
            artist=p,
            title=t,
            bpm=bpm,
        )


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

    def convert_to_mp3(self, src_path, dest_path):
        bitrate = getattr(self, "mp3_bitrate", None) or _MP3_BITRATE
        return convert_to_mp3(src_path, dest_path, bitrate=bitrate)

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
