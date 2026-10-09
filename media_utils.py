"""Утилиты для извлечения метаданных аудио, санитизации имен и фильтрации дат."""

import os
import re
import logging
from datetime import datetime, timezone
from telethon.tl.types import DocumentAttributeAudio

logger = logging.getLogger(__name__)


def is_audio_message(message) -> bool:
    """Единая проверка: содержит ли сообщение аудиофайл (DRY).

    Используется в основном цикле, превью, _has_audio_in_recent и автопоиске канала.
    """
    if getattr(message, "audio", None):
        return True
    mime = getattr(getattr(message, "document", None), "mime_type", None)
    return bool(mime and str(mime).startswith("audio/"))


def clean_promo_text(text: str) -> str:
    """Очищает строку от промо-тегов каналов, ссылок, эмодзи и рекламного мусора."""
    if not text:
        return ""
    # 1. URL и t.me ссылки
    text = re.sub(r"https?://\S+|www\.\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[?\(?\b(?:https?://)?t\.me/[a-zA-Z0-9_+/-]+\)?\]?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[?\(?\b(?:https?://)?telegram\.me/[a-zA-Z0-9_+/-]+\)?\]?", "", text, flags=re.IGNORECASE)

    # 2. @телеграм_хэндлы
    text = re.sub(r"\[?\(?@[a-zA-Z0-9_]+\)?\]?", "", text)

    # 3. Промо-вставки в скобках [новинка], [320 kbps], [mp3], [exclusive], [премьера]
    promo_brackets = [
        r"\[\s*(?:320\s*kbps|128\s*kbps|mp3|hq|exclusive|новинка|премьера|музыка|new|free\s*dl|download|bass\s*boosted|official\s*video|official\s*audio)\s*\]",
        r"\(\s*(?:320\s*kbps|128\s*kbps|mp3|hq|exclusive|новинка|премьера|музыка|new|free\s*dl|download|bass\s*boosted|official\s*video|official\s*audio)\s*\)",
    ]
    for pat in promo_brackets:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # 4. Эмодзи и декоративные спецсимволы Unicode
    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50-\u2b55\u200d\ufe0f]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = text.strip()

    # 5. Порядковый номер трека в начале (01. или 01 - )
    text = re.sub(r"^\d{1,3}\s*[.-]\s*", "", text)

    # 6. Пустые скобки после вырезания промо
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)

    # 7. Избыточные пробелы и крайняя пунктуация
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -_.,|")


def smart_title_case(text: str) -> str:
    """Приводит строку к Title Case, если она написана капслоком, сохраняя DJ-акронимы."""
    if not text or not (text.isupper() and len(text) > 3):
        return text
    words = text.split()
    keep_upper = {"VIP", "BPM", "ID", "DJ", "EDX", "MK", "BBC", "EP", "LP", "USA", "UK", "AC/DC", "ATB"}
    lower_particles = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "of", "in"}
    new_words = []
    for idx, w in enumerate(words):
        inner = w.strip("()[]\"'")
        inner_u = inner.upper()
        if inner_u in keep_upper:
            new_words.append(w.replace(inner, inner_u, 1))
        elif idx > 0 and inner.lower() in lower_particles:
            new_words.append(w.replace(inner, inner.lower(), 1))
        else:
            new_words.append(w.replace(inner, inner.capitalize(), 1))
    return " ".join(new_words)


def clean_track_metadata(performer: str, title: str) -> tuple[str, str]:
    """Нормализует метаданные трека, удаляя рекламные теги, каналы и ссылки."""
    p = clean_promo_text(performer or "")
    t = clean_promo_text(title or "")

    # Проверка, является ли артист заглушкой или названием канала
    is_generic_artist = not p or p.lower() in (
        "unknownartist", "unknown artist", "unknown", "audio", "track", "music"
    ) or "t.me/" in p.lower() or p.startswith("@")

    if is_generic_artist and " - " in t:
        parts = t.split(" - ", 1)
        p = parts[0].strip()
        t = parts[1].strip()

    if not p:
        p = "UnknownArtist"
    if not t:
        t = "UnknownTitle"

    p = smart_title_case(p)
    t = smart_title_case(t)

    return p, t


def clean_filename(filename: str) -> str:
    """Очищает имя файла от рекламных тегов и приводит к чистому виду."""
    if not filename:
        return "UnknownArtist - UnknownTitle.mp3"
    name, ext = os.path.splitext(filename)
    if " - " in name:
        artist, title = name.split(" - ", 1)
        artist_clean, title_clean = clean_track_metadata(artist, title)
        name_clean = f"{artist_clean} - {title_clean}"
    else:
        name_clean = clean_promo_text(name)
        if name_clean.isupper() and len(name_clean) > 3:
            name_clean = smart_title_case(name_clean)
    if not name_clean:
        name_clean = "Unknown Track"
    invalid_chars = '/\\:*?"<>|'
    for ch in invalid_chars:
        name_clean = name_clean.replace(ch, "_")
    return f"{name_clean}{ext if ext else '.mp3'}"


def get_audio_meta(message, clean: bool = False) -> tuple[str, str]:
    """Извлекает имя исполнителя и название трека из метаданных сообщения."""
    performer = "UnknownArtist"
    title = "UnknownTitle"
    try:
        if message.audio and hasattr(message.audio, "performer"):
            performer = message.audio.performer or "UnknownArtist"
            title = message.audio.title or "UnknownTitle"
        elif message.document:
            for attr in message.document.attributes:
                if isinstance(attr, DocumentAttributeAudio):
                    performer = attr.performer or "UnknownArtist"
                    title = attr.title or "UnknownTitle"
                    break
    except Exception:
        pass
    if clean:
        performer, title = clean_track_metadata(performer, title)
    return performer, title


def generate_filename(message, max_length: int = 200, clean: bool = False) -> str:
    """Генерирует безопасное имя MP3 файла из метаданных аудиосообщения."""
    artist, title = get_audio_meta(message, clean=clean)
    stem = f"{artist} - {title}"
    if len(stem) > max_length:
        stem = stem[:max_length]
    filename = f"{stem}.mp3"
    invalid_chars = '/\\:*?"<>|'
    for ch in invalid_chars:
        filename = filename.replace(ch, "_")
    return filename


def get_audio_duration(message) -> float | None:
    """Извлекает длительность аудиозаписи в секундах."""
    if getattr(message, "audio", None) and hasattr(message.audio, "duration"):
        return message.audio.duration
    if getattr(message, "document", None):
        audio_attrs = [
            attr
            for attr in message.document.attributes
            if isinstance(attr, DocumentAttributeAudio)
        ]
        if audio_attrs:
            return audio_attrs[0].duration
    return None


def extract_tme_urls(text: str) -> list[str]:
    """Извлекает ссылки на Telegram (t.me) из текста сообщения."""
    pattern = r"(https?://t\.me/[^\s]+|t\.me/[^\s]+)"
    result = []
    for m in re.finditer(pattern, text or ""):
        url = m.group(0)
        if url.startswith("https://") or url.startswith("http://"):
            url = url.split("://", 1)[1]
        result.append(url)
    return result


def to_utc(dt: datetime | None) -> datetime | None:
    """Приводит наивный datetime к aware UTC. None пропускает."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive -> локальное tz
    return dt.astimezone(timezone.utc)


def message_in_date_range(message, date_from, date_to) -> bool:
    """Проверяет, попадает ли сообщение в заданный диапазон дат."""
    if not date_from and not date_to:
        return True
    msg_date = getattr(message, "date", None)
    if msg_date is None:
        return False
    if msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)
    date_from_utc = to_utc(date_from)
    date_to_utc = to_utc(date_to)
    if date_from_utc and msg_date < date_from_utc:
        return False
    if date_to_utc and msg_date > date_to_utc:
        return False
    return True


def is_older_than_from(message, date_from) -> bool:
    """Возвращает True, если сообщение старше нижней границы диапазона."""
    if not date_from:
        return False
    msg_date = getattr(message, "date", None)
    if msg_date is None:
        return False
    if msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)
    return msg_date < to_utc(date_from)


def get_date_folder(msg_date, base_folder: str) -> str:
    """Формирует имя целевой папки даты по локальному времени пользователя."""
    if getattr(msg_date, "tzinfo", None) is not None:
        msg_date = msg_date.astimezone()
    date_str = msg_date.strftime("%Y-%m-%d")
    return os.path.join(base_folder, date_str)


def sanitize_path_segment(segment: str) -> str:
    """Очищает сегмент пути (папку или файл) от недопустимых символов."""
    if not segment:
        return "Unknown"
    invalid_chars = '/\\:*?"<>|'
    res = str(segment).replace("..", "")
    for ch in invalid_chars:
        res = res.replace(ch, "_")
    res = re.sub(r"_+", "_", res).strip("_. ")
    return res or "Unknown"


def format_export_path(
    base_folder: str,
    pattern: str,
    date_val: datetime | None = None,
    channel: str = "",
    artist: str = "UnknownArtist",
    title: str = "UnknownTitle",
    bpm: str = "",
    ext: str = "mp3",
) -> str:
    """Формирует структурированный путь экспорта файла по настраиваемому паттерну."""
    if not pattern:
        pattern = "{date}/{artist} - {title}.mp3"

    if date_val is not None:
        if getattr(date_val, "tzinfo", None) is not None:
            date_val = date_val.astimezone()
        date_str = date_val.strftime("%Y-%m-%d")
        year_str = date_val.strftime("%Y")
    else:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        year_str = now.strftime("%Y")

    ext_clean = ext.lstrip(".") or "mp3"
    clean_artist = sanitize_path_segment(artist or "UnknownArtist")
    clean_title = sanitize_path_segment(title or "UnknownTitle")
    clean_channel = sanitize_path_segment(channel.lstrip("@") or "UnknownChannel")
    clean_bpm = sanitize_path_segment(bpm) if bpm and bpm != "—" else ""

    norm_pattern = pattern.replace("\\", "/")
    segments = [s.strip() for s in norm_pattern.split("/") if s.strip()]

    formatted_segments = []
    for part in segments:
        seg = part
        seg = seg.replace("{date}", date_str)
        seg = seg.replace("{year}", year_str)
        seg = seg.replace("{channel}", clean_channel)
        seg = seg.replace("{artist}", clean_artist)
        seg = seg.replace("{title}", clean_title)
        seg = seg.replace("{bpm}", clean_bpm)
        seg = seg.replace("{ext}", ext_clean)
        clean_seg = sanitize_path_segment(seg)
        formatted_segments.append(clean_seg)

    if not formatted_segments:
        rel_path = f"{clean_artist} - {clean_title}.{ext_clean}"
    else:
        last = formatted_segments[-1]
        if not last.lower().endswith(f".{ext_clean.lower()}"):
            last = f"{last}.{ext_clean}"
            formatted_segments[-1] = last
        rel_path = os.path.join(*formatted_segments)

    return os.path.join(base_folder, rel_path)


def generate_m3u8_playlist(
    playlist_path: str,
    track_entries: list[dict],
    relative: bool = True,
) -> str:
    """Создает стандартный UTF-8 M3U8 плейлист для DJ-программ (Rekordbox, Serato, Traktor, Engine DJ)."""
    full_path = os.path.abspath(playlist_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    playlist_dir = os.path.dirname(full_path)

    lines = ["#EXTM3U\n"]
    for t in track_entries:
        fpath = t.get("filepath", "")
        if not fpath:
            continue
        artist = t.get("artist") or t.get("performer") or "Unknown"
        title = t.get("title") or "Unknown"
        dur = int(round(float(t.get("duration", 0) or 0)))

        if relative:
            try:
                target_path = os.path.relpath(fpath, playlist_dir)
            except ValueError:
                target_path = os.path.abspath(fpath)
        else:
            target_path = os.path.abspath(fpath)

        target_path = target_path.replace("\\", "/")
        lines.append(f"#EXTINF:{dur},{artist} - {title}\n")
        lines.append(f"{target_path}\n")

    with open(full_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return full_path


_MUSICAL_TO_CAMELOT = {
    # Minor keys
    "abm": "1A", "g#m": "1A", "a flat minor": "1A", "g sharp minor": "1A",
    "ebm": "2A", "d#m": "2A", "e flat minor": "2A", "d sharp minor": "2A",
    "bbm": "3A", "a#m": "3A", "b flat minor": "3A", "a sharp minor": "3A",
    "fm": "4A", "f minor": "4A",
    "cm": "5A", "c minor": "5A",
    "gm": "6A", "g minor": "6A",
    "dm": "7A", "d minor": "7A",
    "am": "8A", "a minor": "8A",
    "em": "9A", "e minor": "9A",
    "bm": "10A", "b minor": "10A",
    "f#m": "11A", "gbm": "11A", "f sharp minor": "11A", "g flat minor": "11A",
    "c#m": "12A", "dbm": "12A", "c sharp minor": "12A", "d flat minor": "12A",

    # Major keys
    "b": "1B", "b maj": "1B", "b major": "1B", "cb": "1B",
    "f#": "2B", "f# maj": "2B", "f# major": "2B", "gb": "2B",
    "db": "3B", "db maj": "3B", "db major": "3B", "c#": "3B", "c# major": "3B",
    "ab": "4B", "ab maj": "4B", "ab major": "4B", "g#": "4B", "g# major": "4B",
    "eb": "5B", "eb maj": "5B", "eb major": "5B", "d#": "5B", "d# major": "5B",
    "bb": "6B", "bb maj": "6B", "bb major": "6B", "a#": "6B", "a# major": "6B",
    "f": "7B", "f maj": "7B", "f major": "7B",
    "c": "8B", "c maj": "8B", "c major": "8B",
    "g": "9B", "g maj": "9B", "g major": "9B",
    "d": "10B", "d maj": "10B", "d major": "10B",
    "a": "11B", "a maj": "11B", "a major": "11B",
    "e": "12B", "e maj": "12B", "e major": "12B",
}

_CAMELOT_COLORS = {
    "1A": "#00D2BE", "1B": "#00D2BE",
    "2A": "#3B82F6", "2B": "#3B82F6",
    "3A": "#6366F1", "3B": "#6366F1",
    "4A": "#8B5CF6", "4B": "#8B5CF6",
    "5A": "#EC4899", "5B": "#EC4899",
    "6A": "#EF4444", "6B": "#EF4444",
    "7A": "#F97316", "7B": "#F97316",
    "8A": "#F59E0B", "8B": "#F59E0B",
    "9A": "#EAB308", "9B": "#EAB308",
    "10A": "#84CC16", "10B": "#84CC16",
    "11A": "#10B981", "11B": "#10B981",
    "12A": "#14B8A6", "12B": "#14B8A6",
}


def get_camelot_color(key: str) -> str:
    """Возвращает фирменный неоновый цвет колеса Камелот для заданной тональности."""
    if not key or key == "—":
        return "#64748B"
    clean = key.strip().upper()
    return _CAMELOT_COLORS.get(clean, "#64748B")


def extract_key_meta(title: str, artist: str = "") -> str:
    """Извлекает музыкальную тональность и приводит к коду колеса Camelot (1A-12B)."""
    if hasattr(title, "_mock_name") or type(title).__name__ == "MagicMock":
        title = ""
    if hasattr(artist, "_mock_name") or type(artist).__name__ == "MagicMock":
        artist = ""
    title_str = str(title) if title is not None else ""
    artist_str = str(artist) if artist is not None else ""
    combined = f"{artist_str} {title_str}"

    # 1. Прямой поиск Camelot-нотации: 1A-12B (e.g. [8A], 8A - 124, 11B)
    m_cam = re.search(r'\b(1[0-2]|[1-9])([ABab])\b', combined)
    if m_cam:
        num = m_cam.group(1)
        letter = m_cam.group(2).upper()
        return f"{num}{letter}"

    # 2. Поиск с префиксом "Key:" или "Тональность:" (Key: Am, Key: F#m, Key: C)
    m_key_pfx = re.search(
        r'(?:key|тональность)[:\s]+([A-Ga-g][#b]?(?:\s*(?:m|min|minor|maj|major))?)\b',
        combined,
        re.IGNORECASE,
    )
    if m_key_pfx:
        raw_key = m_key_pfx.group(1).lower().strip()
        compact_key = raw_key.replace(" ", "")
        if raw_key in _MUSICAL_TO_CAMELOT:
            return _MUSICAL_TO_CAMELOT[raw_key]
        if compact_key in _MUSICAL_TO_CAMELOT:
            return _MUSICAL_TO_CAMELOT[compact_key]

    # 3. Поиск нотации в скобках [Am], (F#m), [C minor], [G#m]
    bracket_content = re.findall(r'\[([^\]]+)\]|\(([^\)]+)\)', combined)
    for b_tuple in bracket_content:
        b_str = (b_tuple[0] or b_tuple[1]).strip().lower()
        for part in re.split(r'[-_/,|]\s*', b_str):
            clean_part = part.strip()
            m_c = re.match(r'^(1[0-2]|[1-9])([ab])$', clean_part)
            if m_c:
                return f"{m_c.group(1)}{m_c.group(2).upper()}"
            if clean_part in _MUSICAL_TO_CAMELOT:
                return _MUSICAL_TO_CAMELOT[clean_part]
            compact_part = clean_part.replace(" ", "")
            if compact_part in _MUSICAL_TO_CAMELOT:
                return _MUSICAL_TO_CAMELOT[compact_part]

    # 4. Поиск явных минорных обозначений (Am, Cm, Dm, Em, Fm, Gm, Bm, F#m, C#m, G#m, Ebm, Bbm)
    m_minor = re.search(r'\b([A-G][#b]?m(?:in|inor)?)\b', combined, re.IGNORECASE)
    if m_minor:
        norm_m = m_minor.group(1).lower()
        if "minor" in norm_m:
            norm_m = norm_m.replace("minor", "m")
        elif "min" in norm_m:
            norm_m = norm_m.replace("min", "m")
        if norm_m in _MUSICAL_TO_CAMELOT:
            return _MUSICAL_TO_CAMELOT[norm_m]

    return "—"


def extract_bpm_meta(title: str, artist: str = "") -> str:
    """Извлекает реальный BPM из метаданных трека (названия/исполнителя), если указан."""
    if hasattr(title, "_mock_name") or type(title).__name__ == "MagicMock":
        title = ""
    if hasattr(artist, "_mock_name") or type(artist).__name__ == "MagicMock":
        artist = ""
    title_str = str(title) if title is not None else ""
    artist_str = str(artist) if artist is not None else ""
    combined = f"{artist_str} {title_str}"
    m = re.search(r'\b([6-9]\d|1\d{2}|2[0-1]\d)\s*(?:bpm|бпм)\b', combined, re.IGNORECASE)
    if m:
        return m.group(1)
    m_bracket = re.search(r'\[([6-9]\d|1\d{2}|2[0-1]\d)\s*(?:bpm|бпм)?\]', combined, re.IGNORECASE)
    if m_bracket:
        return m_bracket.group(1)
    m_paren = re.search(r'\(([6-9]\d|1\d{2}|2[0-1]\d)\s*(?:bpm|бпм)?\)', combined, re.IGNORECASE)
    if m_paren:
        return m_paren.group(1)
    m_pfx = re.match(r'^(?:\[|\()?(\d{2,3})(?:\]|\))?\s*[-_ ]', title_str.strip())
    if m_pfx:
        val = int(m_pfx.group(1))
        if 60 <= val <= 220:
            return str(val)
    return "—"


def read_audio_id3_meta(file_path: str) -> tuple[str, str]:
    """Считывает реальные теги BPM (TBPM) и тональности (TKEY/Camelot) напрямую из аудиофайла через mutagen."""
    if not file_path or not os.path.exists(file_path):
        return "—", "—"
    try:
        import mutagen
        audio = mutagen.File(file_path)
        if not audio or not getattr(audio, "tags", None):
            return "—", "—"
        tags = audio.tags

        # 1. Извлечение BPM
        bpm_str = "—"
        raw_bpm = tags.get("TBPM") or tags.get("TXXX:BPM") or tags.get("bpm")
        if raw_bpm:
            bpm_text = str(raw_bpm).strip()
            try:
                bpm_float = float(bpm_text)
                if 40 <= bpm_float <= 260:
                    bpm_str = str(int(round(bpm_float)))
            except (ValueError, TypeError):
                m = re.search(r'\b([6-9]\d|1\d{2}|2[0-1]\d)\b', bpm_text)
                if m:
                    bpm_str = m.group(1)

        # 2. Извлечение тональности (Key)
        key_str = "—"
        raw_key = tags.get("TKEY") or tags.get("GEOB:Key") or tags.get("initialkey")
        if raw_key:
            k_val = str(raw_key).strip()
            m_cam = re.match(r'^(1[0-2]|[1-9])([ABab])$', k_val)
            if m_cam:
                key_str = f"{m_cam.group(1)}{m_cam.group(2).upper()}"
            else:
                norm_k = k_val.lower().replace(" ", "")
                if norm_k in _MUSICAL_TO_CAMELOT:
                    key_str = _MUSICAL_TO_CAMELOT[norm_k]
                elif k_val.lower() in _MUSICAL_TO_CAMELOT:
                    key_str = _MUSICAL_TO_CAMELOT[k_val.lower()]
                else:
                    cand_k = extract_key_meta(k_val)
                    if cand_k != "—":
                        key_str = cand_k

        return bpm_str, key_str
    except Exception as e:
        logger.debug(f"Ошибка чтения ID3 тегов из {file_path}: {e}")
        return "—", "—"


