# Разработка

## Окружение

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest pytest-cov pytest-asyncio pytest-qt
```

---

## Запуск

```powershell
.venv\Scripts\python main.py
```

---

## Конфигурация

Конфиг хранится в `telegram_audio/config.json`. Создаётся автоматически при первом сохранении.

| Поле | Тип | По умолчанию | Описание |
|------|-----|-------------|----------|
| `api_id` | `str` | `""` | ID приложения из my.telegram.org/apps |
| `api_hash` | `str` | `""` | Hash приложения |
| `channel` | `str` | `""` | @username канала |
| `mode` | `str` | `"direct"` | `direct`, `record`, `hybrid` |
| `date_from` | `str` | `""` | `YYYY-MM-DD` или пусто |
| `date_to` | `str` | `""` | `YYYY-MM-DD` или пусто |
| `base_folder` | `str` | `"telegram_audio"` | Корневая папка загрузок |
| `max_concurrent_downloads` | `int` | `5` | Максимум одновременных скачиваний |
| `max_download_retries` | `int` | `3` | Попыток скачивания при ошибках |
| `download_delay` | `float` | `1` | Секунд между сообщениями |
| `mp3_bitrate` | `str` | `"192k"` | Битрейт MP3 |
| `sample_rate` | `int` | `44100` | Частота дискретизации записи |

---

## Соглашения

### Код

- Комментарии на русском (пользовательские сообщения и логи)
- f-string для форматирования
- `logger.info()` для бизнес-логики, `logger.debug()` для отладки
- `logging.getLogger(__name__)` в каждом модуле

### Импорты

- Сначала стандартная библиотека
- Затем сторонние библиотеки
- Затем модули проекта
- Разделены пустой строкой

### Обработка ошибок

- Любой `cancel` проверяется флагом `_cancel_requested` / `_cancelled`
- Блокирующие операции выносятся через `asyncio.to_thread()`
- `try/except` на каждом уровне, общий `except` в `async_run()` и `process_message()`

### GUI

- Все значения полей ввода оборачиваются в `strip()`
- Сигналы Qt подключаются к слотам один раз
- Поток создаётся через `QThread` + `asyncio.run()`
- Межпоточное взаимодействие — `queue.Queue` + `pyqtSignal`

---

## Тестирование

См. [TESTING.md](TESTING.md).

---

## Сборка

См. [BUILD.md](BUILD.md).

---

## Модули проекта

### `config.py`

Контейнер для констант и функций работы с JSON-конфигом.  
Без классов, без состояния. Рекомендуется не расширять без необходимости.

### `recorder.py`

God Object. Содержит всю бизнес-логику, кроме GUI и Qt-специфичного кода.  
Основной класс `TelegramAudioRecorder`.  
Параметр `progress_callback` — опциональный callable(`dict`) для отчёта прогресса (счётчики + ETA).

**Почему не декомпозирован:** риск регрессии при 0% тестов на момент написания перевешивал выгоду от рефакторинга. Теперь, когда есть 78 тестов, декомпозиция возможна, но не является приоритетом.

### `downloader.py`

QThread-воркер, связывающий GUI и recorder.  
Отвечает за:
- Аутентификацию (phone → code → 2FA)
- Запуск/отмену загрузки
- Парсинг дат

### `gui.py`

PyQt6 интерфейс.  
Два класса: `MainWindow` (основное окно) и `InputCodeDialog` (диалог ввода).  
Сигналы:
- `MainWindow.log` → `DownloadThread.log_signal`
- `MainWindow.download_finished` → `DownloadThread.finished_signal`
- `MainWindow.show_input_dialog` → `DownloadThread.request_code_signal`
- `MainWindow.update_progress` → `DownloadThread.progress_signal`
- `InputCodeDialog.code_entered` → `DownloadThread.code_response_signal`

### `main.py`

Точка входа. Настройка логгирования и запуск Qt-приложения.

---

## Расширение: добавление нового режима

1. Добавить значение в `mode_combo` в `gui.py`
2. Реализовать метод в `TelegramAudioRecorder`
3. Добавить ветку в `process_message()`
4. Обновить `_report_progress()` если меняется логика счётчиков
5. Добавить тесты
6. Обновить документацию и CHANGELOG
