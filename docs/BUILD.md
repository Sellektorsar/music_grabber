# Сборка проекта

## Требования

- Windows 10/11
- Python 3.13+
- [ffmpeg](https://ffmpeg.org/) в PATH (для конвертации в MP3)

---

## Установка зависимостей

```powershell
# Создание виртуального окружения
python -m venv .venv
.venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt

# Для запуска тестов дополнительно
pip install pytest pytest-cov pytest-asyncio
```

---

## Сборка исполняемого файла (PyInstaller)

### Версия для распространения (без консоли)

```powershell
.venv\Scripts\pyinstaller TelegramAudioDownloader.spec
```

Результат: `dist/TelegramAudioDownloader.exe`

### Версия для отладки (с консолью)

```powershell
pyinstaller --onedir --windowed --icon=music_grabber.ico main.py
```

### Примечания по spec-файлу

`TelegramAudioDownloader.spec` собирает все динамические импорты:

| Модуль | hiddenimports |
|--------|---------------|
| telethon | `collect_submodules('telethon')` |
| pydub | `collect_submodules('pydub')` |
| scipy | `collect_submodules('scipy')` |
| sounddevice | `collect_submodules('sounddevice')` |
| numpy | `collect_submodules('numpy')` |
| PyQt6 | Явно: `PyQt6`, `PyQt6.QtCore`, `PyQt6.QtWidgets`, `PyQt6.QtGui` |

Также собираются `collect_data_files('telethon')` для TL-схем.

---

## Структура дистрибутива

```
TelegramAudioDownloader.exe
└── _internal/  # или рядом с .exe при --onefile
    ├── main.py
    ├── gui.py
    ├── downloader.py
    ├── recorder.py
    ├── config.py
    ├── библиотеки (PyQt6, telethon, numpy, scipy, sounddevice, pydub)
    └── ...
```

При первом запуске создаётся `telegram_audio/config.json` и `telegram_audio/logs/`.
