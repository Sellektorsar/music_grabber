# Архитектура TelegramAudioDownloader

## Обзор

Desktop-приложение для скачивания голосовых сообщений и аудиофайлов из Telegram-каналов.  
Стек: Python 3.13, PyQt6, Telethon, sounddevice, pydub.  
Интерфейс: русский. Точка входа — `main.py`.

---

## Структура проекта

```
music_grabber/
├── main.py                   # Точка входа, настройка логгирования, запуск GUI
├── gui.py                    # PyQt6-виджеты: MainWindow, InputCodeDialog
├── downloader.py             # QThread-воркер: аутентификация, запуск рекордера
├── recorder.py               # Ядро: скачивание, запись, конвертация, фильтрация
├── config.py                 # JSON-конфиг: загрузка/сохранение настроек
├── tests/                    # Тесты pytest (149 тестов)
│   ├── conftest.py           # Моки Telethon, общие фикстуры
│   ├── test_config.py        # 9 тестов
│   ├── test_recorder.py      # 49 тестов
│   ├── test_downloader.py    # 20 тестов
│   ├── test_gui.py           # 53 теста (pytest-qt)
│   └── test_integration.py   # 18 тестов (полный цикл)
├── docs/                     # Документация
│   ├── ARCHITECTURE.md
│   ├── BUILD.md
│   ├── DEVELOPMENT.md
│   ├── TESTING.md
│   └── CHANGELOG.md
├── requirements.txt
├── pyproject.toml
├── .coveragerc
├── .gitignore
├── TelegramAudioDownloader.spec  # PyInstaller spec
└── telegram_audio/               # Директория загрузок и конфига
    ├── config.json               # Сохранённые настройки
    ├── logs/
    │   └── app.log               # Лог-файл (RotatingFileHandler, 5 MB, 3 бэкапа)
    └── YYYY-MM-DD/               # Папки по датам сообщений
        └── Artist - Title.mp3
```

---

## Схема зависимостей модулей

```
main.py
  └── gui.py
        ├── downloader.py ──────────────────────┐
        │     ├── recorder.py ←─── config.py    │
        │     └── telethon (TelegramClient)      │
        ├── config.py                           │
        └── shutil (is_ffmpeg_available)         │
                                                 │
recorder.py ←── config.py (константы на уровне   │
                модуля при импорте)              │
                                                 │
downloader.py ←── recorder.py, telethon, PyQt6  │
                                                 │
gui.py ←── downloader.py, config.py, PyQt6      │
```

**Правила зависимостей:**
- `main.py` → импортирует только `gui.py`
- `gui.py` → импортирует `downloader.py` и `config.py`
- `downloader.py` → импортирует `recorder.py` и `telethon`
- `recorder.py` → импортирует `config.py` при импорте модуля (загружает константы)
- `config.py` → не импортирует другие модули проекта

---

## Компоненты

### 1. `config.py` — Конфигурация (32 строки)

- **load_config()**: читает `telegram_audio/config.json`, сливает с `DEFAULT_CONFIG`
- **save_config(**kwargs)**: сохраняет настройки в JSON
- **DEFAULT_CONFIG**: 12 ключей (api_id, api_hash, channel, mode, date_from, date_to, base_folder, max_concurrent_downloads, max_download_retries, download_delay, mp3_bitrate, sample_rate)
- Контейнерный файл без состояния и классов

### 2. `recorder.py` — Ядро (God Object)

**Класс `TelegramAudioRecorder`** — основной исполнитель:
- `progress_callback` — опциональный callable для отчёта прогресса (счётчики, ETA)

| Метод | Назначение |
|-------|-----------|
| `start()` | Главный цикл: получает сущность канала, итерирует сообщения, фильтрует по датам, запускает скачивание |
| `process_message(message, path)` | Выбирает режим (direct/record/hybrid) и выполняет скачивание или запись |
| `try_direct_download(message, path)` | Скачивает медиа через Telethon, конвертирует в MP3, фолбэк при ошибке |
| `_download_with_retry(message, path)` | Скачивание с повторами при FloodWait и сетевых ошибках |
| `record_audio(duration, filename)` | Запись звука через sounddevice (InputStream + callback) |
| `save_recording(data, fs, filename)` | Сохраняет WAV → конвертирует в MP3 → удаляет WAV |
| `convert_to_mp3(src, dst)` | Конвертация через pydub |
| `generate_filename(message)` | Генерация имени `Artist - Title.mp3` с санитизацией символов |
| `is_audio_message(message)` | Статическая проверка: есть ли аудио в сообщении |
| `_message_in_date_range(message)` | Фильтр по диапазону дат |
| `_has_audio_in_recent(channel)` | Проверка: есть ли аудио в последних 50 сообщениях |
| `_maybe_follow_redirect(channel)` | Автопоиск основного канала по ссылкам в первых 10 сообщениях |
| `_extract_tme_urls(text)` | Извлечение ссылок t.me из текста |
| `_clean_temp_files()` | Очистка `.temp.*` и `.wav` файлов при старте |

**Константы модуля** (из `config.py`):
- `BASE_FOLDER`, `MAX_CONCURRENT_DOWNLOADS`, `MAX_DOWNLOAD_RETRIES`, `_DOWNLOAD_DELAY`, `_MP3_BITRATE`, `_SAMPLE_RATE`

### 3. `downloader.py` — Воркер (154 строки)

**Класс `DownloadThread(QThread)`** — асинхронный загрузчик:

| Сигнал | Тип | Назначение |
|--------|-----|-----------|
| `log_signal` | `str` | Логирование в GUI |
| `finished_signal` | `()` | Сигнал о завершении потока |
| `request_code_signal` | `str` | Запрос ввода от пользователя |
| `code_response_signal` | `str` | Ответ пользователя |
| `progress_signal` | `object` | Данные прогресса (dict) |

**Поток выполнения `async_run()`:**
1. Подключение к Telegram (`TelegramClient.connect()`)
2. Аутентификация (phone → code → 2FA), проверка cancel на каждом шаге
3. Получение информации о пользователе (`get_me()`)
4. Парсинг и валидация дат из строк `YYYY-MM-DD`
5. Создание `TelegramAudioRecorder` и вызов `start()`
6. Обработка отмены и ошибок
7. Закрытие соединения в `finally`

**Межпоточное взаимодействие:**
- `queue.Queue` для передачи ввода от GUI к воркеру
- `pyqtSignal` для обратной связи (логи, диалоги ввода)
- Флаг `_cancel_requested` для остановки

### 4. `gui.py` — Пользовательский интерфейс

**Класс `MainWindow(QWidget)`:**
- Поля: API ID, API Hash, канал, режим, даты
- Кнопки: Старт / Стоп
- Панель прогресса (QLabel)
- Лог-вывод (QTextEdit)
- `closeEvent` — остановка потока при закрытии окна
- `_load_settings()` / `start_download()` — загрузка и сохранение конфига
- `update_progress(data)` — обновление панели прогресса по сигналу `progress_signal`

**Класс `InputCodeDialog(QDialog)`:**
- Модальное окно для ввода телефона/кода/пароля
- Защита от двойной отправки ответа (флаг `_input_answered`)

**Функция `is_ffmpeg_available()`:**
- Проверка ffmpeg в PATH через `shutil.which()`

### 5. `main.py` — Точка входа (39 строк)

- `setup_logging()`: настройка RotatingFileHandler + StreamHandler
- `main()`: создание QApplication, показ MainWindow

---

## Потоки выполнения

```
Main Thread (Qt)
  └── QThread (DownloadThread)
        └── asyncio event loop (async_run)
              ├── Telethon Client (сеть)
              ├── queue.Queue (ввод пользователя)
              └── asyncio.to_thread (блокирующие операции)
                    ├── convert_to_mp3 (pydub → ffmpeg)
                    └── record_audio (sounddevice)
```

- Qt-поток обрабатывает GUI-события
- DownloadThread выполняет всю сетевую работу в отдельном потоке
- Блокирующие операции (конвертация, запись) вынесены через `asyncio.to_thread`
- Cancel реализован через флаг и `sd.CallbackAbort()`

---

## Обработка ошибок

| Сценарий | Защита |
|----------|--------|
| Cancel во время auth | `_cancel_requested` проверяется перед/после каждого ввода |
| Неверный код/пароль | `except Exception` с понятным сообщением, выход |
| FloodWait | Ретрай с ожиданием, пошаговая проверка cancel |
| Сетевая ошибка | Ретрай (3 попытки), затем фолбэк |
| Ошибка конвертации | Сохранение в исходном формате |
| Ошибка записи звука | Логирование, continue |
| Повреждённый JSON конфига | Возврат дефолтного конфига |
| Ошибка сохранения конфига | Логирование предупреждения |

---

## Отказоустойчивость

- `asyncio.gather(return_exceptions=True)` — сбой одной задачи не ломает остальные
- WAV-файл гарантированно удаляется в `finally` блоке `save_recording()`
- Temp-файлы очищаются при старте через `_clean_temp_files()`
- Соединение Telethon закрывается в `finally` блоке `async_run()`
- `QApplication` создаётся до любых QObject-виджетов
- `closeEvent` останавливает поток при закрытии окна
