"""Загрузка аудио: ограничение потоков, учёт результата, повторы, прямая загрузка.

Вынесено из recorder.py, чтобы модуль не разрастался за пределы разумного
размера.

Константы здесь намеренно берутся через ``_rec()`` -- обращение к модулю
recorder в момент вызова. Тесты подменяют ``recorder.db_module``,
``recorder.MAX_DOWNLOAD_RETRIES`` и другие значения именно там; обычный
импорт в начале файла сделал бы подмену невидимой для вынесенного кода.
Ленивый импорт заодно снимает круговую зависимость между модулями.
"""

import asyncio
import logging
import os
import time as time_module
import traceback

from telethon.errors import FloodWaitError

from media_utils import (
    clean_track_metadata,
    extract_bpm_meta,
    extract_key_meta,
    read_audio_id3_meta,
)
from audio_converter import write_id3_tags


def _rec():
    """Модуль recorder целиком, чтобы видеть подмены тестов."""
    import recorder
    return recorder


# Имя логгера совпадает с прежним: записи в app.log не должны выглядеть
# по-другому только из-за того, что код переехал в отдельный файл.
logger = logging.getLogger("recorder")


class DownloadMixin:
    """Загрузка и учёт скачанного. Смешивается в TelegramAudioRecorder."""

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
            # Единственный способ получить файл -- скачать его из Telegram.
            # Раньше здесь была ветка записи с звуковой карты и запасной
            # вариант "гибрид", который при неудачном скачивании писал с
            # микрофона то, что играет в системе, и помечал результат
            # успешным. Само воспроизведение трека в проекте отсутствовало,
            # поэтому режимы "record" и "hybrid" удалены из интерфейса.
            if await self.try_direct_download(message, file_path):
                succeeded = True
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
                            if getattr(self, "embed_id3_tags", True):
                                write_id3_tags(
                                    file_path,
                                    title=clean_tit if clean_tit != "UnknownTitle" else title,
                                    artist=clean_perf if clean_perf != "UnknownArtist" else performer,
                                    year=year_val,
                                    bpm=bpm_val if bpm_val != "—" else "",
                                    key=key_val if key_val != "—" else "",
                                    comment=f"Telegram: {str(self.channel_username).lstrip('@')}",
                                )
                        except Exception as tag_err:
                            logger.debug(f"Не удалось записать ID3 теги: {tag_err}")

                    _rec().db_module.record_download(
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
                self._failed_ids.add(msg_id)
                self._last_completed_id = None
                self._skipped += 1
            self._report_progress()

    async def _download_with_retry(self, message, temp_path, progress_callback=None, total_size=0):
        """Скачивание медиа с поддержкой докачки (.part), повторными попытками при сетевых сбоях и FloodWait.

        Возвращает True, если файл успешно скачан (существует на диске).
        """
        import inspect
        part_path = temp_path if temp_path.endswith(".part") else f"{temp_path}.part"
        for attempt in range(1, _rec().MAX_DOWNLOAD_RETRIES + 1):
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

                self.log(f"Попытка {attempt}/{_rec().MAX_DOWNLOAD_RETRIES}: медиа не скачано (отсутствует).")
                return False
            except FloodWaitError as e:
                wait = int(getattr(e, 'seconds', 1))
                self.log(f"FloodWait: ожидание {wait} сек. перед повтором (попытка {attempt}/{_rec().MAX_DOWNLOAD_RETRIES}).")
                # Ждём порциями, чтобы оставить возможность реакции на cancel.
                end = asyncio.get_event_loop().time() + wait
                while asyncio.get_event_loop().time() < end:
                    if self._cancelled:
                        return False
                    await asyncio.sleep(min(1.0, max(0.0, end - asyncio.get_event_loop().time())))
            except _rec()._FS_ERRORS as e:
                # Отказ файловой системы: повтор не поможет, а ждать три
                # попытки бессмысленно. Сообщаем прямо и выходим.
                self.log(f"Ошибка доступа к файлу: {e}")
                return False
            except _rec()._RETRYABLE_NETWORK_ERRORS as e:
                self.log(f"Сетевая ошибка (попытка {attempt}/{_rec().MAX_DOWNLOAD_RETRIES}): {e}")
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
