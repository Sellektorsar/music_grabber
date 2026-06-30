# Тестирование

## Быстрый запуск

```powershell
.venv\Scripts\python -m pytest
```

## Запуск с покрытием

```powershell
.venv\Scripts\python -m pytest --cov=. --cov-report=term-missing --cov-report=html
```

Отчёт: `htmlcov/index.html`

## Параллельный запуск

```powershell
.venv\Scripts\python -m pytest -n auto
```

(требуется `pytest-xdist`)

---

## Установка зависимостей

```powershell
pip install pytest pytest-cov pytest-asyncio pytest-qt
```

---

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py              # Моки Telethon, общие фикстуры
├── test_config.py           # 9 тестов — config.py
├── test_recorder.py         # 49 тестов — recorder.py
├── test_downloader.py       # 20 тестов — downloader.py
├── test_gui.py              # 53 теста — gui.py (pytest-qt)
└── test_integration.py      # 18 тестов — интеграционные
```

### `conftest.py`

- **Моки Telethon** на уровне модуля (все `telethon.*` подменены до импорта проекта)
- **Фикстуры:**
  - `isolate_base_folder(autouse)` — перенаправляет `BASE_FOLDER` во временную директорию
  - `mock_client` — AsyncMock с замокаными методами Telethon
  - `recorder` — `TelegramAudioRecorder(mock_client, '@testchannel')` (по умолчанию `progress_callback=None`, тесты не ломаются)
- **Хелперы:**
  - `make_message()` — фабрика мок-сообщений
  - `make_audio()` — фабрика мок-аудио
  - `make_document()` — фабрика мок-документов
  - `_get_doc_attr()` — фабрика DocumentAttributeAudio

---

## Покрытие (текущее)

| Файл | Покрытие | Пропущенные строки |
|------|----------|-------------------|
| `config.py` | 84% | error handler в save_config |
| `recorder.py` | 55% | `record_audio()`, `_maybe_follow_redirect()`, `save_recording()` |
| `downloader.py` | 67% | Часть auth-циклов (phone/code/2FA), QThread.run() |
| `gui.py` | 0%* | GUI-тесты используют MockDownloadThread, coverage не замеряет |
| `main.py` | — | Точка входа |
| **Total** | **~45%** | |

\* `test_gui.py` (53 теста) запускает код `gui.py` через MockDownloadThread. Coverage-замер возможен при запуске с `--cov=gui`.
`test_integration.py` (18 тестов) покрывает `downloader.py` и `recorder.py` в связке, но coverage-замер может не учитывать asyncio-контекст.

### Почему не 100%

1. **Telethon-зависимые методы** (`start()`, `_maybe_follow_redirect()`): требуют работающего экземпляра Telethon с реальной сессией.
2. **Интеграционные сценарии** (`downloader.py` auth-циклы с реальным Telethon): замоканы на уровне `MockDownloadThread`.
3. **Аппаратно-зависимые операции** (`record_audio()`, `save_recording()`): требуют sounddevice и ffmpeg.
4. **Обработчики ошибок** (повреждённый JSON, права на запись): сложно воспроизвести в тестовом окружении.
5. **`main.py`**: точка входа, требует реального окружения PyInstaller или ручного тестирования.

---

## Группы тестов

### `test_config.py` — 9 тестов

- `test_load_defaults_when_file_missing` — отсутствие файла → дефолты
- `test_load_merges_with_defaults` — частичный конфиг → слияние
- `test_load_returns_defaults_on_corrupt_json` — битый JSON → дефолты
- `test_load_unknown_fields_preserved` — незнакомые поля сохраняются
- `test_save_creates_file` — сохранение создаёт файл
- `test_save_merges_existing` — сохранение сливается с существующим
- `test_save_latest_overrides` — последнее сохранение перезаписывает
- `test_save_handles_permission_error` — ошибка записи не падает
- `test_default_config_structure` — структура DEFAULT_CONFIG

### `test_recorder.py` — 49 тестов

**Статические и независимые методы:**
- `_mime_to_ext` — 4 теста (известные MIME, регистр, неизвестные, None)
- `is_audio_message` — 4 теста
- `_to_utc` — 4 теста (None, naive, aware, корректность)
- `_get_date_folder` — 2 теста
- `generate_filename` — 6 тестов (артист/тайтл, отсутствие, санитизация, фолбэк, document-атрибуты)
- `_message_in_date_range` — 7 тестов (границы, NULL, naive date)
- `_is_older_than_from` — 3 теста
- `get_audio_duration` — 4 теста (audio, document, отсутствие)
- `_extract_tme_urls` — 5 тестов
- `_clean_temp_files` — 2 теста
- `cancel` — 2 теста

**Методы с моками:**
- `_download_with_retry` — 5 тестов (успех, FloodWait, NetworkError, cancel, все попытки)
- `try_direct_download` — 3 теста (файл существует, успех MP3, фолбэк)
- `process_message` — 2 теста (direct, hybrid)
- `_has_audio_in_recent` — 2 теста
- `_get_audio_extension` — 4 теста

### `test_downloader.py` — 20 тестов

- `USER_INPUT_TIMEOUT` — константа
- `cancel` — 3 теста (флаг, без recorder, с recorder)
- `get_user_input` — 3 теста (очередь, cancel, очистка очереди)
- `async_run` — 3 теста (неверный формат даты, cancel до старта, cancel во время auth)
- Auth-тесты с замоканным TelethonClient

### `test_integration.py` — 18 тестов

**Инфраструктура:** используется реальный `DownloadThread` с замоканным Telethon-клиентом (`monkeypatch`). `iter_messages` подменяется на async-генератор, возвращающий мок-сообщения, `download_media` пишет файл на диск. Сигналы `log_signal`, `progress_signal`, `request_code_signal` собираются напрямую.

**Группы тестов:**
- `TestFullFlow` (5) — 3 аудио скачиваются, файлы `.mp3` на диске, нет аудио → лог, hybrid-mode, сводка
- `TestAlreadyExists` (1) — pre-created file → skipped + counted
- `TestCancel` (3) — cancel во время загрузки, до старта, двойной cancel
- `TestErrors` (2) — частичный сбой, полный сбой
- `TestProgress` (2) — все поля присутствуют, счётчики растут
- `TestAuth` (3) — телефон + код, 2FA пароль, cancel во время ввода
- `TestDates` (2) — неверный формат даты, валидный диапазон

### `test_gui.py` — 53 теста

**Инфраструктура:**
- `MockDownloadThread(QObject)` — заглушка `DownloadThread` с совместимыми `pyqtSignal`
- `gui` fixture — изолирует конфиг, мокает `is_ffmpeg_available`, `QMessageBox`, `DownloadThread`
- Все тесты выполняются с `qtbot` (pytest-qt), без реального QThread/asyncio

**Группы тестов:**

- `TestInitialState` (11) — заголовок, кнопки, виджеты, маскировка, read-only, mode_combo
- `TestLoadSettings` (3) — пустой конфиг, загрузка из файла, невалидный mode
- `TestValidation` (4) — пустые поля api_id/hash/channel, нечисловой api_id → QMessageBox
- `TestFFmpegHandling` (2) — record без ffmpeg → critical, direct без ffmpeg → warning
- `TestStartDownload` (5) — создание/старт треда, параметры, очистка лога, кнопки, сигналы
- `TestStopDownload` (4) — cancel, сброс кнопок, без треда, лог-сообщение
- `TestCloseEvent` (2) — остановка при закрытии, без треда
- `TestDownloadFinished` (2) — сброс состояния, лог-сообщение
- `TestLogging` (2) — append, автоскролл
- `TestProgress` (4) — stats, current_file, ETA=0, форматирование
- `TestInputCodeDialog` (5) — создание, accept с текстом, accept пустой, reject, modal
- `TestShowInputDialog` (3) — создание, переиспользование, сброс _input_answered
- `TestOnCodeEntered` (3) — отправка в thread, игнорирование повторного, без треда
- `TestOnDialogClosed` (3) — отправка пустой строки, already_answered, без треда

---

## Написание тестов

### Добавление нового теста

```python
# tests/test_recorder.py

class TestMyFeature:
    def test_basic_case(self, recorder):
        result = recorder.my_method()
        assert result == expected
```

### Использование mock-сообщений

```python
from unittest.mock import MagicMock
from conftest import make_message, make_audio, make_document

msg = make_message(
    audio=make_audio(mime_type='audio/mpeg', duration=30),
    date=datetime(2025, 6, 15, tzinfo=timezone.utc),
)
```

### Async-тесты

```python
@pytest.mark.asyncio
async def test_async_method(self, recorder):
    result = await recorder._has_audio_in_recent(channel, sample=10)
    assert result is True
```

### Мок Telethon-клиента

```python
recorder.client.iter_messages = AsyncMock()

# Для async for нужна асинхронная итерация
async def _iter_mock(*args, **kwargs):
    for msg in [mock_msg1, mock_msg2]:
        yield msg

recorder.client.iter_messages = _iter_mock
```

### GUI-тесты

```python
# tests/test_gui.py

def test_start_creates_thread(gui):
    window, monkeypatch, tmp_path = gui
    window.api_id_input.setText("12345")
    window.api_hash_input.setText("hash")
    window.channel_input.setText("@chan")
    window.start_button.click()
    assert window.download_thread is not None
    assert window.download_thread.started is True


def test_update_progress(window):
    window.update_progress({
        "total_scanned": 10,
        "audio_found": 5,
        "downloaded": 3,
        "skipped": 1,
        "already_exists": 1,
        "current_file": "song.mp3",
        "mode": "hybrid",
        "eta_seconds": 60,
    })
    assert "Просмотрено: 10" in window.progress_label.text()
    assert "Файл: song.mp3" in window.progress_label.text()
```

**Важно:** GUI-тесты используют `MockDownloadThread` — заглушку, которая не запускает реальный `asyncio`. Для тестирования интеграции с Telethon используйте `test_downloader.py`. Для тестирования бизнес-логики — `test_recorder.py`.
