"""Регрессия шага 1 рефакторинга: разделение recorder.py.

Загрузка вынесена в recorder_download.DownloadMixin. При этом сломаться
могло ровно одно -- подмена значений на уровне модуля. Тесты и conftest
подменяют ``recorder.BASE_FOLDER``, ``recorder.MAX_DOWNLOAD_RETRIES``,
``recorder._DOWNLOAD_DELAY`` и ``recorder.db_module``, а вынесенные
методы обязаны видеть подмену. Обычный импорт в начале файла сделал бы
её невидимой: пришлось бы искать константы по месту определения.

Поэтому проверяется и структура (код действительно вынесен), и то, что
подмена действительно доходит до вынесенного кода.
"""

import asyncio
import inspect
import os
from unittest.mock import MagicMock

import pytest

import recorder as rec
import recorder_download


def _run(coro):
    return asyncio.run(coro)


def _message(msg_id=7):
    """Сообщение с настоящим числовым id.

    id попадает в имя временного файла, поэтому заглушка MagicMock
    дала бы недопустимое для Windows имя и обрыв вместо загрузки.
    """
    message = MagicMock()
    message.id = msg_id
    message.media = object()
    message.audio = None
    message.document = None
    return message


@pytest.fixture
def r(tmp_path):
    recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan", mode="direct")
    recorder.log = MagicMock()
    recorder._cancelled = False
    recorder.base_folder = str(tmp_path)
    # Расширение задано явно: иначе заглушка сообщения даёт .ogg, и файл
    # сохраняется под другим именем, а ещё и уходит в конвертацию ffmpeg.
    recorder._get_audio_extension = MagicMock(return_value=".mp3")
    return recorder


def _logs(recorder):
    return [c[0][0] for c in recorder.log.call_args_list]


class TestCodeWasActuallyMoved:
    """Контроль регрессии: разделение не откатилось обратно."""

    METHODS = ("download_with_limit", "process_message",
               "_download_with_retry", "try_direct_download")

    @pytest.mark.parametrize("name", METHODS)
    def test_method_lives_in_download_module(self, name):
        func = getattr(rec.TelegramAudioRecorder, name)
        assert func.__module__ == "recorder_download"

    @pytest.mark.parametrize("name", METHODS)
    def test_method_is_inherited_from_mixin(self, name):
        assert issubclass(rec.TelegramAudioRecorder, recorder_download.DownloadMixin)
        assert hasattr(recorder_download.DownloadMixin, name)

    def test_mixin_is_small_enough_to_read(self):
        """Смысл разделения -- файл должен оставаться обозримым."""
        source = inspect.getsource(recorder_download)
        assert len(source.splitlines()) < 400

    def test_recorder_shrank(self):
        source = inspect.getsource(rec)
        assert len(source.splitlines()) < 1000, \
            "загрузка вернулась в recorder.py"


class TestLateBindingIsVisible:
    """Подмена на уровне recorder должна доходить до вынесенных методов."""

    def test_base_folder_patch_is_visible(self, r, monkeypatch, tmp_path):
        target = tmp_path / "папка-подмены"
        target.mkdir()
        monkeypatch.setattr(rec, "BASE_FOLDER", str(target))

        recorder = rec.TelegramAudioRecorder(MagicMock(), "@chan")
        assert recorder.base_folder == str(target)

    def test_retries_patch_is_visible(self, r, monkeypatch, tmp_path):
        """Число попыток читается из recorder в момент вызова."""
        monkeypatch.setattr(rec, "MAX_DOWNLOAD_RETRIES", 7)
        r.client.iter_download = None
        message = _message()
        message.download_media = None

        assert _run(r._download_with_retry(
            message, str(tmp_path / "нет-файла.mp3"))) is False

        assert any("Попытка 1/7" in line for line in _logs(r)), \
            f"подмена числа попыток не видна: {_logs(r)}"

    def test_default_retries_value_is_three(self, r, tmp_path):
        r.client.iter_download = None
        message = _message()
        message.download_media = None

        _run(r._download_with_retry(message, str(tmp_path / "нет-файла.mp3")))

        assert any(f"Попытка 1/{rec.MAX_DOWNLOAD_RETRIES}" in line
                   for line in _logs(r))

    def test_database_patch_is_visible(self, r, monkeypatch, tmp_path):
        """Запись о загрузке должна попадать в подменённый db_module."""
        import database as real_db
        monkeypatch.setattr(rec, "db_module", MagicMock())
        monkeypatch.setattr(recorder_download, "write_id3_tags",
                            MagicMock(), raising=False)

        path = tmp_path / "track.mp3"

        async def _ok(message, file_path):
            with open(file_path, "wb") as fh:
                fh.write(b"\x00" * 4096)
            return True

        r.try_direct_download = _ok
        r._get_audio_meta = MagicMock(return_value=("Zivert", "GAZ"))
        r.get_audio_duration = MagicMock(return_value=180.0)

        _run(r.process_message(_message(), str(path)))

        rec.db_module.record_download.assert_called_once()
        assert rec.db_module is not real_db


class TestBehaviourPreserved:
    """Перенос не должен был изменить поведение."""

    def test_direct_download_still_works(self, r, tmp_path):
        path = tmp_path / "track.mp3"

        async def iter_download(_media, offset=0, request_size=0):
            yield b"\x00" * 4096

        r.client.iter_download = iter_download
        assert _run(r.try_direct_download(_message(), str(path))) is True
        assert path.exists()

    def test_preview_still_in_recorder(self, r, tmp_path):
        """Превью осталось в recorder.py -- оно не про загрузку файла."""
        assert rec.TelegramAudioRecorder.download_track_preview.__module__ \
            == "recorder"

    def test_no_temp_leftovers_after_move(self, r, tmp_path):
        """Перенос не должен оставлять огрызков в рабочей папке."""
        _run(r.try_direct_download(_message(), str(tmp_path / "a.mp3")))
        leftovers = [n for n in os.listdir(tmp_path)
                     if ".temp" in n or n.endswith(".part")]
        assert leftovers == [], f"остались временные файлы: {leftovers}"