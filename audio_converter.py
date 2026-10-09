"""Модуль конвертации аудиоформатов и работы с расширениями файлов."""

import os
import logging
from pydub import AudioSegment

logger = logging.getLogger(__name__)

MIME_TO_EXT_MAP = {
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


def mime_to_ext(mime: str | None) -> str:
    """Определяет расширение файла по MIME-типу."""
    if not mime:
        return ".ogg"
    return MIME_TO_EXT_MAP.get(mime.lower(), ".ogg")


def get_audio_extension(message) -> str:
    """Извлекает расширение аудиофайла из сообщения Telegram."""
    if getattr(message, "audio", None):
        if getattr(message.audio, "mime_type", None):
            return mime_to_ext(message.audio.mime_type)
    if getattr(message, "document", None):
        if getattr(message.document, "mime_type", None):
            return mime_to_ext(message.document.mime_type)
        if getattr(message, "file", None) and getattr(message.file, "name", None):
            _, ext = os.path.splitext(message.file.name)
            if ext:
                return ext
    return ".ogg"


def convert_to_mp3(src_path: str, dest_path: str, bitrate: str = "192k") -> None:
    """Конвертирует аудиофайл любого поддерживаемого формата в MP3 через pydub."""
    audio = AudioSegment.from_file(src_path)
    audio.export(dest_path, format="mp3", bitrate=bitrate)
    logger.debug(f"Файл {src_path} сконвертирован в {dest_path} с битрейтом {bitrate}")


def write_id3_tags(
    filepath: str,
    title: str = "",
    artist: str = "",
    album: str = "",
    year: str | int = "",
    genre: str = "",
    bpm: str | int = "",
    key: str = "",
    comment: str = "",
    artwork_bytes: bytes | None = None,
    artwork_mime: str = "image/jpeg",
) -> bool:
    """Записывает теги ID3v2 в MP3 файл (Title, Artist, Album, Year, Genre, BPM, Key, Comment, Artwork)."""
    if not filepath or not os.path.exists(filepath):
        return False
    try:
        from mutagen.id3 import (
            ID3,
            TIT2,
            TPE1,
            TALB,
            TDRC,
            TCON,
            TBPM,
            TKEY,
            COMM,
            APIC,
            ID3NoHeaderError,
        )
    except ImportError:
        logger.debug("Библиотека mutagen не установлена, теги ID3 пропущены")
        return False

    try:
        try:
            audio = ID3(filepath)
        except ID3NoHeaderError:
            audio = ID3()

        if title:
            audio.delall("TIT2")
            audio.add(TIT2(encoding=3, text=[str(title)]))

        if artist:
            audio.delall("TPE1")
            audio.add(TPE1(encoding=3, text=[str(artist)]))

        if album:
            audio.delall("TALB")
            audio.add(TALB(encoding=3, text=[str(album)]))

        if year:
            y_str = str(year).strip()
            audio.delall("TDRC")
            audio.add(TDRC(encoding=3, text=[y_str]))

        if genre:
            audio.delall("TCON")
            audio.add(TCON(encoding=3, text=[str(genre)]))

        if bpm:
            b_str = str(bpm).replace("—", "").strip()
            if b_str and b_str.isdigit():
                audio.delall("TBPM")
                audio.add(TBPM(encoding=3, text=[b_str]))

        if key:
            k_str = str(key).replace("—", "").strip()
            if k_str:
                audio.delall("TKEY")
                audio.add(TKEY(encoding=3, text=[k_str]))

        if comment:
            audio.delall("COMM")
            audio.add(COMM(encoding=3, lang="eng", desc="", text=[str(comment)]))

        if artwork_bytes:
            audio.delall("APIC")
            audio.add(
                APIC(
                    encoding=3,
                    mime=artwork_mime or "image/jpeg",
                    type=3,  # Cover front
                    desc="Cover",
                    data=artwork_bytes,
                )
            )

        audio.save(filepath, v2_version=3)
        return True
    except Exception as e:
        logger.warning(f"Ошибка записи ID3 тегов в {filepath}: {e}")
        return False


# Алиас для единообразия в UI и Bento модулях
write_id3_metadata = write_id3_tags


def read_id3_tags(filepath: str) -> dict:
    """Считывает теги ID3 из MP3 файла."""
    res = {}
    if not filepath or not os.path.exists(filepath):
        return res
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError

        try:
            audio = ID3(filepath)
        except ID3NoHeaderError:
            return res

        if "TIT2" in audio:
            res["title"] = str(audio["TIT2"])
        if "TPE1" in audio:
            res["artist"] = str(audio["TPE1"])
        if "TALB" in audio:
            res["album"] = str(audio["TALB"])
        if "TCON" in audio:
            res["genre"] = str(audio["TCON"])
        if "TBPM" in audio:
            res["bpm"] = str(audio["TBPM"])
        if "TKEY" in audio:
            res["key"] = str(audio["TKEY"])
        if "TDRC" in audio:
            res["year"] = str(audio["TDRC"])
        comments = audio.getall("COMM")
        if comments:
            res["comment"] = str(comments[0])
        apics = audio.getall("APIC")
        if apics:
            res["has_artwork"] = True
            res["artwork_bytes"] = apics[0].data
            res["artwork_mime"] = apics[0].mime
    except Exception as e:
        logger.debug(f"Ошибка чтения ID3 тегов из {filepath}: {e}")
    return res


# Алиас для чтения ID3 тегов
read_id3_metadata = read_id3_tags
