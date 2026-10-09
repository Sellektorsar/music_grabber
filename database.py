"""Модуль локального индекса метаданных загрузок (SQLite).

Обеспечивает отслеживание скачанных треков для мгновенной дедупликации,
даже если файлы на диске были перемещены или переименованы.
"""

from contextlib import contextmanager
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Set

import config

logger = logging.getLogger(__name__)


def normalize_channel_id(channel: str) -> str:
    """Приводит ссылку или юзернейм канала к единому каноническому идентификатору.

    Примеры:
        'https://t.me/kutsuevpool' -> 'kutsuevpool'
        '@kutsuevpool' -> 'kutsuevpool'
        'kutsuevpool' -> 'kutsuevpool'
    """
    if not channel:
        return ""
    c = str(channel).strip()
    c = re.sub(r"^https?://t\.me/", "", c, flags=re.IGNORECASE)
    c = re.sub(r"^t\.me/", "", c, flags=re.IGNORECASE)
    return c.lstrip("@").strip("/").lower()


def _safe_int(val: Any) -> Optional[int]:
    """Безопасно преобразует значение в int, возвращая None при невозможности."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def get_db_path(db_path: Optional[str] = None) -> str:
    """Возвращает путь к файлу БД."""
    if db_path:
        return db_path
    return getattr(config, "DB_FILE", os.path.join("telegram_audio", "downloads.db"))


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Открывает подключение к SQLite с поддержкой WAL и таймаутом."""
    path = get_db_path(db_path)
    dir_name = os.path.dirname(os.path.abspath(path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception as e:
        logger.debug(f"Не удалось применить PRAGMA для БД: {e}")
    return conn


@contextmanager
def db_session(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер для безопасного закрытия подключения к БД."""
    conn = get_db_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


_DB_INITIALIZED: Set[str] = set()


def init_db(db_path: Optional[str] = None) -> None:
    """Инициализирует структуру таблиц и индексов в SQLite."""
    path = os.path.abspath(get_db_path(db_path))
    if path in _DB_INITIALIZED and os.path.exists(path):
        return
    try:
        with db_session(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    filename TEXT,
                    file_path TEXT,
                    file_size INTEGER DEFAULT 0,
                    artist TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    duration INTEGER DEFAULT 0,
                    downloaded_at TEXT,
                    status TEXT DEFAULT 'completed',
                    UNIQUE(channel_id, message_id)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_downloads_channel_msg ON downloads (channel_id, message_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_downloads_channel ON downloads (channel_id);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads (status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_downloads_duration ON downloads (duration);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_downloads_artist_title ON downloads (artist, title);"
            )
            conn.commit()
        _DB_INITIALIZED.add(path)
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise


def record_download(
    channel_id: str,
    message_id: int,
    filename: str = "",
    file_path: str = "",
    file_size: int = 0,
    artist: str = "",
    title: str = "",
    duration: int = 0,
    status: str = "completed",
    downloaded_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Сохраняет запись о скачанном аудио треке в БД."""
    c_id = normalize_channel_id(channel_id)
    msg_id = _safe_int(message_id)
    if not c_id or msg_id is None:
        return False
    if downloaded_at is None:
        downloaded_at = datetime.now(timezone.utc).isoformat()
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            conn.execute(
                """
                INSERT INTO downloads (
                    channel_id, message_id, filename, file_path, file_size,
                    artist, title, duration, downloaded_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, message_id) DO UPDATE SET
                    filename=excluded.filename,
                    file_path=excluded.file_path,
                    file_size=excluded.file_size,
                    artist=excluded.artist,
                    title=excluded.title,
                    duration=excluded.duration,
                    downloaded_at=excluded.downloaded_at,
                    status=excluded.status;
                """,
                (
                    c_id,
                    msg_id,
                    str(filename or ""),
                    str(file_path or ""),
                    _safe_int(file_size) or 0,
                    str(artist or ""),
                    str(title or ""),
                    _safe_int(duration) or 0,
                    downloaded_at,
                    str(status or "completed"),
                ),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.warning(f"Ошибка записи в БД загрузок: {e}")
        return False


def is_downloaded(
    channel_id: str, message_id: int, db_path: Optional[str] = None
) -> bool:
    """Проверяет, был ли трек успешно скачан ранее."""
    c_id = normalize_channel_id(channel_id)
    msg_id = _safe_int(message_id)
    if not c_id or msg_id is None:
        return False
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM downloads WHERE channel_id = ? AND message_id = ? AND status = 'completed' LIMIT 1;",
                (c_id, msg_id),
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.debug(f"Ошибка проверки загрузки в БД: {e}")
        return False


def get_downloaded_ids(
    channel_id: str, db_path: Optional[str] = None
) -> Set[int]:
    """Возвращает множество (set) всех message_id, успешно скачанных для данного канала."""
    c_id = normalize_channel_id(channel_id)
    if not c_id:
        return set()
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "SELECT message_id FROM downloads WHERE channel_id = ? AND status = 'completed';",
                (c_id,),
            )
            return {row["message_id"] for row in cursor.fetchall()}
    except Exception as e:
        logger.debug(f"Ошибка получения списка скачанных ID: {e}")
        return set()


def get_download(
    channel_id: str, message_id: int, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Возвращает метаданные скачанного трека или None."""
    c_id = normalize_channel_id(channel_id)
    msg_id = _safe_int(message_id)
    if not c_id or msg_id is None:
        return None
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM downloads WHERE channel_id = ? AND message_id = ?;",
                (c_id, msg_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.debug(f"Ошибка чтения записи из БД: {e}")
        return None


def get_downloads(
    channel_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Возвращает список записей загрузок."""
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            if channel_id:
                c_id = normalize_channel_id(channel_id)
                cursor = conn.execute(
                    "SELECT * FROM downloads WHERE channel_id = ? ORDER BY id DESC LIMIT ? OFFSET ?;",
                    (c_id, limit, offset),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM downloads ORDER BY id DESC LIMIT ? OFFSET ?;",
                    (limit, offset),
                )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.debug(f"Ошибка выборки загрузок из БД: {e}")
        return []


def get_download_count(
    channel_id: Optional[str] = None,
    status: str = "completed",
    db_path: Optional[str] = None,
) -> int:
    """Возвращает количество загрузок."""
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            if channel_id:
                c_id = normalize_channel_id(channel_id)
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM downloads WHERE channel_id = ? AND status = ?;",
                    (c_id, status),
                )
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM downloads WHERE status = ?;",
                    (status,),
                )
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.debug(f"Ошибка подсчета загрузок из БД: {e}")
        return 0


def delete_download(
    channel_id: str, message_id: int, db_path: Optional[str] = None
) -> bool:
    """Удаляет запись о загрузке трека из БД."""
    c_id = normalize_channel_id(channel_id)
    msg_id = _safe_int(message_id)
    if not c_id or msg_id is None:
        return False
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM downloads WHERE channel_id = ? AND message_id = ?;",
                (c_id, msg_id),
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.warning(f"Ошибка удаления записи из БД: {e}")
        return False


def clear_channel_history(
    channel_id: str, db_path: Optional[str] = None
) -> int:
    """Очищает историю загрузок для канала."""
    c_id = normalize_channel_id(channel_id)
    if not c_id:
        return 0
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM downloads WHERE channel_id = ?;", (c_id,)
            )
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        logger.warning(f"Ошибка очистки истории канала в БД: {e}")
        return 0


def normalize_track_text(text: str) -> str:
    """Приводит название или артиста к очищенной строке для сравнения дубликатов."""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"https?://\S+|www\.\S+|t\.me/\S+|@[a-zA-Z0-9_]+", "", t)
    t = re.sub(
        r"\[\s*(?:320\s*kbps|128\s*kbps|mp3|hq|exclusive|новинка|премьера|new)\s*\]",
        "",
        t,
    )
    t = re.sub(r"\b(?:feat|ft|featuring|pres|presents|with)\b[^\-]+", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_fuzzy_track_match(
    artist1: str,
    title1: str,
    dur1: int,
    artist2: str,
    title2: str,
    dur2: int,
    tolerance_sec: int = 2,
    similarity_threshold: float = 0.80,
) -> bool:
    """Проверяет нечеткое соответствие треков по исполнителю, названию и длительности (±2s)."""
    import difflib

    dur1_int = _safe_int(dur1) or 0
    dur2_int = _safe_int(dur2) or 0

    if dur1_int > 0 and dur2_int > 0:
        if abs(dur1_int - dur2_int) > tolerance_sec:
            return False

    norm_a1 = normalize_track_text(artist1)
    norm_t1 = normalize_track_text(title1)
    norm_a2 = normalize_track_text(artist2)
    norm_t2 = normalize_track_text(title2)

    if not (norm_a1 or norm_t1) or not (norm_a2 or norm_t2):
        return False

    sig1 = f"{norm_a1} - {norm_t1}".strip(" -")
    sig2 = f"{norm_a2} - {norm_t2}".strip(" -")

    generic_sigs = {
        "unknownartist - unknowntitle",
        "unknown artist - unknown title",
        "unknown - unknown",
    }
    if sig1 in generic_sigs or sig2 in generic_sigs:
        return False

    if norm_a1 == norm_a2 and norm_t1 == norm_t2:
        return True

    ratio_a = difflib.SequenceMatcher(None, norm_a1, norm_a2).ratio()
    ratio_t = difflib.SequenceMatcher(None, norm_t1, norm_t2).ratio()

    # Точный артист и почти совпадающее название
    if norm_a1 == norm_a2 and ratio_t >= 0.85:
        return True
    # Точное название и почти совпадающий артист
    if norm_t1 == norm_t2 and ratio_a >= 0.85:
        return True
    # Оба компонента очень близки
    if ratio_a >= 0.88 and ratio_t >= 0.88:
        return True

    if sig1 == sig2:
        return True

    return difflib.SequenceMatcher(None, sig1, sig2).ratio() >= 0.92


def find_duplicate_download(
    artist: str,
    title: str,
    duration: int = 0,
    tolerance_sec: int = 2,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Ищет уже скачанный трек в БД среди всех каналов по нечеткому совпадению и длительности."""
    dur = _safe_int(duration) or 0
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            if dur > 0:
                min_dur = max(0, dur - tolerance_sec)
                max_dur = dur + tolerance_sec
                cursor = conn.execute(
                    "SELECT * FROM downloads WHERE status = 'completed' AND duration BETWEEN ? AND ?;",
                    (min_dur, max_dur),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM downloads WHERE status = 'completed' ORDER BY id DESC LIMIT 500;"
                )
            candidates = [dict(row) for row in cursor.fetchall()]

        for cand in candidates:
            if is_fuzzy_track_match(
                artist,
                title,
                dur,
                cand.get("artist", ""),
                cand.get("title", ""),
                cand.get("duration", 0),
                tolerance_sec=tolerance_sec,
            ):
                return cand
        return None
    except Exception as e:
        logger.debug(f"Ошибка поиска дубликата в БД: {e}")
        return None


def get_completed_tracks_index(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Возвращает компактный список всех успешно скачанных треков для быстрого пакетного дедупа."""
    try:
        init_db(db_path)
        with db_session(db_path) as conn:
            cursor = conn.execute(
                "SELECT id, channel_id, message_id, artist, title, duration, filename, file_path FROM downloads WHERE status = 'completed';"
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.debug(f"Ошибка получения индекса скачанных треков: {e}")
        return []

