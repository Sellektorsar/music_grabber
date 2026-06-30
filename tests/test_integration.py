"""
Интеграционные тесты TelegramAudioDownloader.

Тестируют полный цикл: DownloadThread → TelegramAudioRecorder → файловая система.
Telethon замокан на уровне модуля (conftest.py), но QThread/asyncio/Qt Signals — реальные.
"""

import os
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from downloader import DownloadThread
import recorder as rec_module


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_config(monkeypatch):
    """Убирает задержки для быстрых тестов."""
    monkeypatch.setattr(rec_module, '_DOWNLOAD_DELAY', 0.005)
    monkeypatch.setattr(rec_module, 'MAX_CONCURRENT_DOWNLOADS', 10)


def _make_message(file_id=0, has_audio=True, mime="audio/mpeg",
                  performer="Artist", title="Song"):
    """Создаёт мок-сообщение, download_media пишет файл на диск."""
    msg = MagicMock()
    if has_audio:
        msg.audio = MagicMock(
            mime_type=mime, duration=30,
            performer=f"{performer}{file_id}",
            title=f"{title}{file_id}",
        )
    else:
        msg.audio = None
    msg.document = None
    msg.date = datetime.now(timezone.utc) - timedelta(days=file_id)
    msg.id = file_id
    msg.raw_text = ""
    msg.file = None
    msg.buttons = None

    async def _download(**kw):
        file_path = kw.get("file")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"x" * 1024)
        return file_path

    msg.download_media = AsyncMock(side_effect=_download)
    return msg


def _make_thread(**kw):
    """Создаёт DownloadThread с умолчаниями."""
    params = dict(
        api_id=12345, api_hash="hash",
        channel="@chan", mode="direct",
        date_from=None, date_to=None,
    )
    params.update(kw)
    return DownloadThread(**params)


@pytest.fixture
def client(monkeypatch):
    """Настраивает mock TelegramClient для DownloadThread."""
    cl = AsyncMock()
    cl.is_user_authorized = AsyncMock(return_value=True)
    cl.get_me = AsyncMock(return_value=MagicMock(first_name="T", last_name="U"))
    cl.get_entity = AsyncMock(return_value=MagicMock(id=1))
    cl.is_connected = MagicMock(return_value=False)
    cl.disconnect = AsyncMock()
    cl.send_code_request = AsyncMock()
    cl.sign_in = AsyncMock()
    monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: cl)
    return cl


def _configure_messages(client, count=3, fail_at=None, slow=False):
    """Настраивает iter_messages на выдачу мок-сообщений."""
    fail_at = fail_at or set()
    msgs = [_make_message(file_id=i) for i in range(count)]
    for i in fail_at:
        msgs[i].download_media = AsyncMock(
            side_effect=Exception(f"Error {i}")
        )

    async def _iter(*args, **kwargs):
        for m in msgs:
            if slow:
                await asyncio.sleep(0.003)
            yield m

    client.iter_messages = _iter
    return msgs


# ---------------------------------------------------------------------------
# Полный цикл скачивания
# ---------------------------------------------------------------------------

class TestFullFlow:
    """Проверка, что файлы создаются, прогресс обновляется, нет регрессий."""

    @pytest.mark.asyncio
    async def test_3_audio_скачиваются_файлы_на_диске(self, client):
        _configure_messages(client, 3)
        t = _make_thread()
        logs, progress = [], []
        t.log_signal.connect(logs.append)
        t.progress_signal.connect(progress.append)

        await t.async_run()

        assert any("загрузка завершена" in l.lower() for l in logs), logs
        last = progress[-1]
        assert last["audio_found"] == 3
        assert last["downloaded"] == 3
        assert last["skipped"] == 0
        assert last["already_exists"] == 0

    @pytest.mark.asyncio
    async def test_нет_аудио_лог_сообщает(self, client):
        async def _iter(*a, **kw):
            for i in range(3):
                yield _make_message(file_id=i, has_audio=False)
        client.iter_messages = _iter
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        assert any("не найдено" in l.lower() for l in logs), logs
        last = progress[-1]
        assert last["audio_found"] == 0

    @pytest.mark.asyncio
    async def test_файлы_mp3_созданы_на_диске(self, client, tmp_path):
        _configure_messages(client, 2)
        t = _make_thread()
        t.log_signal.connect(print)

        await t.async_run()

        mp3 = list(tmp_path.rglob("*.mp3"))
        assert len(mp3) >= 2, [str(f) for f in mp3]

    @pytest.mark.asyncio
    async def test_гибрид_режим_direct_success(self, client):
        _configure_messages(client, 2)
        t = _make_thread(mode="hybrid")
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        last = progress[-1]
        assert last["downloaded"] == 2
        assert last["skipped"] == 0

    @pytest.mark.asyncio
    async def test_лог_содержит_сводку(self, client):
        _configure_messages(client, 1)
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)

        await t.async_run()

        assert any("сводка" in l.lower() for l in logs), logs


# ---------------------------------------------------------------------------
# already_exists
# ---------------------------------------------------------------------------

class TestAlreadyExists:
    """Файлы, уже существующие на диске, пропускаются."""

    @pytest.mark.asyncio
    async def test_существующий_файл_пропускается(self, client, tmp_path):
        _configure_messages(client, 3)
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)
        progress = []; t.progress_signal.connect(progress.append)

        today = datetime.now().strftime("%Y-%m-%d")
        folder = tmp_path / "telegram_audio" / today
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Artist0 - Song0.mp3").write_text("existing")

        await t.async_run()

        assert any("уже существует" in l.lower() for l in logs), logs
        last = progress[-1]
        assert last["already_exists"] >= 1
        assert last["audio_found"] == 3
        assert last["downloaded"] >= 2


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

class TestCancel:
    """Отмена во время скачивания прерывает процесс."""

    @pytest.mark.asyncio
    async def test_отмена_во_время_загрузки(self, client):
        async def _slow_iter(*a, **kw):
            for i in range(30):
                await asyncio.sleep(0.003)
                yield _make_message(file_id=i)
        client.iter_messages = _slow_iter
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)
        progress = []; t.progress_signal.connect(progress.append)

        cancelled = False
        def _cancel(data):
            nonlocal cancelled
            if data["total_scanned"] >= 3 and not cancelled:
                cancelled = True
                t.cancel()
        t.progress_signal.connect(_cancel)

        await t.async_run()

        assert cancelled, "Cancel не сработал — сообщения слишком быстрые"
        last = progress[-1] if progress else {}
        assert last.get("audio_found", 99) < 30, "Все 30 обработаны несмотря на cancel"

    @pytest.mark.asyncio
    async def test_отмена_до_старта(self, client):
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)
        t.cancel()

        await t.async_run()

        assert any("отменена" in l.lower() for l in logs), logs

    @pytest.mark.asyncio
    async def test_отмена_не_ломает_поток(self, client):
        _configure_messages(client, 1)
        t = _make_thread()
        t.cancel()
        t.cancel()  # повторный cancel без ошибки
        await t.async_run()


# ---------------------------------------------------------------------------
# Ошибки скачивания
# ---------------------------------------------------------------------------

class TestErrors:
    """Сбой скачивания отдельного сообщения не ломает остальные."""

    @pytest.mark.asyncio
    async def test_один_файл_не_скачался_остальные_ок(self, client):
        _configure_messages(client, 5, fail_at={1, 3})
        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        last = progress[-1]
        assert last["audio_found"] == 5
        assert last["downloaded"] == 3
        assert last["skipped"] == 2

    @pytest.mark.asyncio
    async def test_все_файлы_с_ошибкой(self, client):
        _configure_messages(client, 3, fail_at={0, 1, 2})
        t = _make_thread()
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        last = progress[-1]
        assert last["downloaded"] == 0
        assert last["skipped"] == 3


# ---------------------------------------------------------------------------
# Прогресс
# ---------------------------------------------------------------------------

class TestProgress:
    """Сигнал progress_signal содержит корректные данные."""

    @pytest.mark.asyncio
    async def test_все_поля_присутствуют(self, client):
        _configure_messages(client, 1)
        t = _make_thread()
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        p = progress[-1]
        for field in ("total_scanned", "audio_found", "downloaded",
                      "skipped", "already_exists", "current_file",
                      "mode", "eta_seconds"):
            assert field in p, f"Поле {field} отсутствует: {p}"

    @pytest.mark.asyncio
    async def test_счётчики_растут(self, client):
        _configure_messages(client, 3)
        t = _make_thread()
        progress = []; t.progress_signal.connect(progress.append)

        await t.async_run()

        audio_vals = [p["audio_found"] for p in progress if p["audio_found"] > 0]
        assert 1 in audio_vals
        assert 3 in audio_vals


# ---------------------------------------------------------------------------
# Аутентификация
# ---------------------------------------------------------------------------

class TestAuth:
    """Ввод телефона/кода/пароля через code_response_signal."""

    @pytest.mark.asyncio
    async def test_телефон_код(self, client, monkeypatch):
        client.is_user_authorized = AsyncMock(return_value=False)
        monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: client)

        t = _make_thread()
        logs = []; t.log_signal.connect(logs.append)

        values = iter(["+71234567890", "123456"])
        t.request_code_signal.connect(
            lambda p: t.code_response_signal.emit(next(values))
        )
        _configure_messages(client, 1)

        await t.async_run()

        assert client.send_code_request.called
        assert client.sign_in.called
        args, _ = client.sign_in.call_args
        assert args[0] == "+71234567890"
        assert args[1] == "123456"

    @pytest.mark.asyncio
    async def test_2fa_пароль(self, client, monkeypatch):
        client.is_user_authorized = AsyncMock(return_value=False)
        monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: client)

        call_n = [0]
        async def _sign_in(*a, **kw):
            call_n[0] += 1
            if call_n[0] == 1:
                from telethon.errors import SessionPasswordNeededError
                raise SessionPasswordNeededError()
            return MagicMock()
        client.sign_in = AsyncMock(side_effect=_sign_in)

        t = _make_thread()
        values = iter(["+71234567890", "123456", "pa$$word"])
        t.request_code_signal.connect(
            lambda p: t.code_response_signal.emit(next(values))
        )
        _configure_messages(client, 1)

        await t.async_run()

        assert call_n[0] == 2
        assert client.sign_in.call_args[1].get("password") == "pa$$word"

    @pytest.mark.asyncio
    async def test_отмена_во_время_ввода_телефона(self, client, monkeypatch):
        client.is_user_authorized = AsyncMock(return_value=False)
        monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: client)

        t = _make_thread()
        finished = []
        t.finished_signal.connect(lambda: finished.append(True))

        t.request_code_signal.connect(lambda p: t.cancel())

        await t.async_run()

        assert t._cancel_requested
        assert len(finished) == 0  # finished_signal эмитится только в run(), не в async_run()


# ---------------------------------------------------------------------------
# Неверные даты
# ---------------------------------------------------------------------------

class TestDates:
    """Обработка неверного формата дат."""

    @pytest.mark.asyncio
    async def test_неверный_формат_даты(self, client, monkeypatch):
        monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: client)
        t = _make_thread(date_from="not-a-date")
        logs = []; t.log_signal.connect(logs.append)

        await t.async_run()

        assert any("формат" in l.lower() for l in logs), logs

    @pytest.mark.asyncio
    async def test_даты_валидные(self, client, monkeypatch):
        monkeypatch.setattr("downloader.TelegramClient", lambda *a, **kw: client)
        _configure_messages(client, 1)
        t = _make_thread(date_from="2025-01-01", date_to="2025-12-31")
        logs = []; t.log_signal.connect(logs.append)

        await t.async_run()

        assert any("загрузка завершена" in l.lower() for l in logs), logs
