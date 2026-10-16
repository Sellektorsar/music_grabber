"""Тесты на DownloadThread: подключение, ввод кода, отмена.

Непокрытым был весь блок разбора ошибок подключения. Он важен: без него
пользователь при запущенном дважды приложении или с битым файлом сессии
видит молчание вместо объяснения. Каждая ветка проверяется по тексту
сообщения, а не по факту вызова.

Асинхронные сценарии прогоняются через asyncio.run в обычных тестах:
реальное ожидание ввода занимает USER_INPUT_TIMEOUT секунд, а такие
тесты идут сотни раз.
"""

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

import downloader as dl


class _Stop(Exception):
    """Служебный маркер: довести исполнение до нужной точки и выйти."""


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY",
                "all_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Ни один тест не должен реально ждать ввода: по умолчанию это
    # USER_INPUT_TIMEOUT секунд на каждый заход. Здесь достаточно запаса,
    # чтобы ответ, заложенный сразу после запроса, успел дойти.
    monkeypatch.setattr(dl, "USER_INPUT_TIMEOUT", 5)


@pytest.fixture
def thread():
    return dl.DownloadThread(1, "hash", "@chan", "direct", None, None,
                             proxy_config={})


def _thread_with_proxy(proxy_config):
    return dl.DownloadThread(1, "hash", "@chan", "direct", None, None,
                             proxy_config=proxy_config)


def _client(**kw):
    client = AsyncMock()
    for name, value in kw.items():
        setattr(client, name, value)
    return client


def _capture_logs(thread):
    """Подписывается на сигнал лога и возвращает список сообщений."""
    collected = []
    thread.log_signal.connect(lambda text: collected.append(text))
    return collected


def _run(thread, client):
    """Подменяет создание клиента и прогоняет async_run до конца.

    Ветка завершается либо возвратом, либо служебным _Stop -- оба варианта
    нормальны, важно лишь дойти до нужного сообщения в логе.
    """
    thread._create_client = MagicMock(return_value=client)
    try:
        asyncio.run(thread.async_run())
    except _Stop:
        pass


class TestConnectionErrors:
    """Разбор ошибок подключения к Telegram."""

    def test_locked_session_is_retried(self, thread, monkeypatch):
        """Занятый файл сессии -- повод подождать и пробовать снова."""
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = [
            sqlite3.OperationalError("database is locked"),
            None,
        ]
        client.is_user_authorized.side_effect = _Stop()

        _run(thread, client)

        assert client.connect.await_count == 2
        assert any("заблокирована другим процессом" in m for m in logs)

    def test_locked_session_retry_failure_explains_two_instances(
            self, thread, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = [
            sqlite3.OperationalError("database is locked"),
            sqlite3.OperationalError("database is locked"),
        ]

        _run(thread, client)

        assert any("запущено дважды" in m for m in logs), \
            "нужно прямо сказать про второй экземпляр приложения"

    def test_other_database_error_is_reported(self, thread):
        """Ошибка БД, не связанная с блокировкой, -- другой совет."""
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = sqlite3.OperationalError("disk I/O error")

        _run(thread, client)

        assert any("Ошибка базы данных сессии" in m for m in logs)
        assert not any("запущено дважды" in m for m in logs)

    def test_connection_error_without_proxy(self, thread):
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = ConnectionError("сеть недоступна")

        _run(thread, client)

        assert any("Ошибка подключения к Telegram:" in m for m in logs)

    def test_connection_error_with_proxy_mentions_proxy(self):
        """При включённом прокси совет должен быть про прокси."""
        thread = _thread_with_proxy({"enabled": True})
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = ConnectionError("прокси недоступен")

        _run(thread, client)

        assert any("через прокси" in m for m in logs)

    def test_legacy_proxy_flag_is_respected(self):
        """Старое имя ключа тоже должно давать правильный совет."""
        thread = _thread_with_proxy({"proxy_enabled": True})
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = ConnectionError("прокси недоступен")

        _run(thread, client)

        assert any("через прокси" in m for m in logs)

    def test_timeout_is_a_connection_error(self, thread):
        logs = _capture_logs(thread)
        client = _client()
        client.connect.side_effect = TimeoutError("долго")

        _run(thread, client)

        assert any("Ошибка подключения к Telegram:" in m for m in logs)


class TestCodeResponse:
    """Ответ на запрос кода авторизации попадает в очередь ввода."""

    def test_response_is_queued(self, thread):
        thread._on_code_response("12345")
        assert thread._input_queue.get_nowait() == "12345"

    def test_signal_is_wired_to_handler(self, thread):
        """Сигнал от GUI обязан доходить до наполнения очереди."""
        thread.code_response_signal.emit("98765")
        assert thread._input_queue.get_nowait() == "98765"


class TestGetUserInput:
    """Ожидание кода от пользователя."""

    def test_returns_answer(self, thread):
        """Ответ, пришедший после запроса, возвращается пользователю."""

        async def scenario():
            task = asyncio.ensure_future(thread.get_user_input("Код"))
            await asyncio.sleep(0)
            thread._input_queue.put("54321")
            return await task

        assert asyncio.run(scenario()) == "54321"

    def test_answer_queued_before_request_is_ignored(self, thread):
        """Старый ответ не должен подхватываться новым запросом.

        Очередь затирается намеренно -- иначе код от прошлой попытки
        авторизации молча ушёл бы в новую.
        """
        thread._input_queue.put("старый")
        assert asyncio.run(thread.get_user_input("Код")) is None

    def test_stale_answers_are_dropped(self, thread):
        """Ответ от прошлого запроса не должен уйти в новый."""

        async def scenario():
            thread._input_queue.put("старый")
            thread._input_queue.put("тоже старый")
            task = asyncio.ensure_future(thread.get_user_input("Код"))
            await asyncio.sleep(0)
            thread._input_queue.put("новый")
            return await task

        assert asyncio.run(scenario()) == "новый"

    def test_cancel_returns_none(self, thread):
        thread._cancel_requested = True
        assert asyncio.run(thread.get_user_input("Код")) is None

    def test_timeout_is_reported(self, thread, monkeypatch):
        """Истечение ожидания должно быть видно в логе, а не молчать."""
        monkeypatch.setattr(dl, "USER_INPUT_TIMEOUT", 0)
        logs = _capture_logs(thread)
        assert asyncio.run(thread.get_user_input("Код")) is None
        assert any("Истекло время ожидания" in m for m in logs)


class TestCancel:
    """Отмена загрузки."""

    def test_sets_flag(self, thread):
        thread._cancel_requested = False
        thread.cancel()
        assert thread._cancel_requested is True

    def test_propagates_to_recorder(self, thread):
        """Остановка потока должна дойти до рекордера."""
        thread.recorder = MagicMock()
        thread.cancel()
        thread.recorder.cancel.assert_called_once()

    def test_without_recorder_is_safe(self, thread):
        thread.recorder = None
        thread.cancel()
        assert thread._cancel_requested is True