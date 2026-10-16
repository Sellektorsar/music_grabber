"""Тесты на уборку временных файлов после прерванной загрузки.

При сбое сети или закрытии приложения в папке остаются ``.temp.``,
``.wav`` (черновик записи с карты) и ``.part`` (обрыв докачки). Если их
не убирать, папка разрастается мусором, а пользователь не понимает,
откуда взялись файлы без треков в имени.

Важная оговорка: свежий ``.part`` удалять нельзя -- он основа докачки,
и стирание обесценило бы уже скачанное.
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

import recorder as rec


@pytest.fixture
def r(tmp_path):
    recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan", mode="direct")
    recorder.log = MagicMock()
    recorder._cancelled = False
    recorder.base_folder = str(tmp_path / "music")
    return recorder


def _write(path, size=8, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


def _listdir(root):
    found = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            found.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(found)


class TestTempCleanup:
    """Что убирается, а что не должно."""

    def test_missing_base_folder_is_noop(self, r):
        assert not os.path.isdir(r.base_folder)
        r._clean_temp_files()          # не должно поднять исключение

    def test_temp_file_is_removed(self, r, tmp_path):
        _write(tmp_path / "music" / "Zivert - GAZ.temp.mp3")
        r._clean_temp_files()
        assert _listdir(r.base_folder) == []

    def test_wav_draft_is_removed(self, r, tmp_path):
        """Черновик записи с карты не нужен после обработки."""
        _write(tmp_path / "music" / "2026-01-01" / "raw.wav")
        r._clean_temp_files()
        assert _listdir(r.base_folder) == []

    def test_fresh_part_is_kept(self, r, tmp_path):
        """Свежий .part -- это основа докачки, стирать его нельзя."""
        _write(tmp_path / "music" / "track.mp3.part", size=4096)
        r._clean_temp_files()
        assert _listdir(r.base_folder) == ["track.mp3.part"]

    def test_stale_part_is_removed(self, r, tmp_path):
        """Двухдневный огрызок уже бесполезен."""
        _write(tmp_path / "music" / "track.mp3.part", age_days=2)
        r._clean_temp_files()
        assert _listdir(r.base_folder) == []

    def test_part_exactly_at_threshold_is_kept(self, r, tmp_path):
        """Граница в сутки не должна вычищать свежие файлы."""
        _write(tmp_path / "music" / "track.mp3.part", age_days=0.5)
        r._clean_temp_files()
        assert _listdir(r.base_folder) == ["track.mp3.part"]

    def test_finished_tracks_survive(self, r, tmp_path):
        path = _write(tmp_path / "music" / "2026-04-04" / "Zivert - GAZ.mp3")
        r._clean_temp_files()
        assert path.exists()

    def test_nested_folders_are_visited(self, r, tmp_path):
        _write(tmp_path / "music" / "a" / "b" / "c" / "deep.temp.mp3")
        r._clean_temp_files()
        assert _listdir(r.base_folder) == []

    def test_cleanup_count_is_logged(self, r, tmp_path):
        _write(tmp_path / "music" / "one.temp.mp3")
        _write(tmp_path / "music" / "two.wav")
        r._clean_temp_files()
        assert any("Очищено временных файлов: 2" in c[0][0]
                   for c in r.log.call_args_list)

    def test_nothing_to_clean_is_silent(self, r, tmp_path):
        _write(tmp_path / "music" / "Zivert - GAZ.mp3")
        r._clean_temp_files()
        assert not any("Очищено временных файлов" in c[0][0]
                       for c in r.log.call_args_list)

    def test_locked_file_does_not_stop_cleanup(self, r, tmp_path):
        """Занятый файл не должен мешать убрать остальные."""
        locked = _write(tmp_path / "music" / "locked.temp.mp3")
        _write(tmp_path / "music" / "free.temp.mp3")

        real_remove = os.remove

        def _remove(path):
            if os.path.abspath(path) == os.path.abspath(str(locked)):
                raise PermissionError("файл занят")
            return real_remove(path)

        with patch.object(rec.os, "remove", _remove):
            r._clean_temp_files()

        assert locked.exists()
        assert not (tmp_path / "music" / "free.temp.mp3").exists()


class TestMimeHelpers:
    """Определение расширения и времени -- используются при разборе.

    Метод ``_mime_to_ext`` был определён дважды; копия-дубликат удалена
    (шаг 4 рефакторинга), рабочая осталась на месте.
    """

    def _message(self, audio=None, document=None, file=None):
        message = MagicMock()
        message.audio = audio
        message.document = document
        message.file = file
        return message

    def test_audio_mime_is_used(self, r):
        audio = MagicMock()
        audio.mime_type = "audio/flac"
        assert r._get_audio_extension(self._message(audio=audio)) == ".flac"

    def test_document_mime_is_used(self, r):
        """Аудио без mime_type должно читаться как документ."""
        document = MagicMock()
        document.mime_type = "audio/mpeg"
        assert r._get_audio_extension(self._message(document=document)) == ".mp3"

    def test_extension_comes_from_file_name(self, r):
        """Без mime_type расширение берётся из имени файла."""
        document = MagicMock()
        document.mime_type = None
        attached = MagicMock()
        attached.name = "Zivert - GAZ.wav"
        assert r._get_audio_extension(
            self._message(document=document, file=attached)) == ".wav"

    def test_unknown_audio_falls_back_to_ogg(self, r):
        assert r._get_audio_extension(self._message()) == ".ogg"

    def test_mime_helper_exists_exactly_once(self):
        """Контроль регрессии: две копии одного метода больше не появятся."""
        import inspect

        source = inspect.getsource(rec)
        assert source.count("def _mime_to_ext") == 1

    def test_mime_helper_still_works(self, r):
        assert r._mime_to_ext("audio/flac") == ".flac"

    def test_to_utc_is_timezone_aware(self, r):
        import datetime

        converted = r._to_utc(datetime.datetime(2026, 4, 4, 12, 0))
        assert converted.tzinfo is not None