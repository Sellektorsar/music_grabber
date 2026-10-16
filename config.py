import json
import os
import sys


def get_base_dir() -> str:
    """Определяет базовую директорию проекта или исполняемого файла.
    Если приложение запущено из подпапки dist/ внутри проекта, используется корневая папка проекта,
    чтобы настройки, база данных и сессия были едиными для exe и скриптов.
    В автономном режиме используется директория самого exe-файла.
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent_dir = os.path.dirname(exe_dir)
        if os.path.basename(exe_dir).lower() == "dist" and (
            os.path.exists(os.path.join(parent_dir, "telegram_audio"))
            or os.path.exists(os.path.join(parent_dir, "config.py"))
        ):
            return parent_dir
        return exe_dir
    else:
        cwd = os.path.abspath(os.getcwd())
        if os.path.exists(os.path.join(cwd, "telegram_audio")):
            return cwd
        return os.path.dirname(os.path.abspath(__file__))


BASE_FOLDER = "telegram_audio"


def _configured_base_folder() -> str:
    """Рабочая папка из настройки base_folder, всегда абсолютный путь.

    Единственное место, где заранее известный путь используется, чтобы
    найти другой: сам файл настроек лежит в папке по умолчанию, иначе
    его негде было бы искать.
    """
    default_dir = os.path.join(get_base_dir(), BASE_FOLDER)
    cfg_file = os.path.join(default_dir, "config.json")
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            raw = json.load(f).get("base_folder")
    except (OSError, ValueError, AttributeError):
        return default_dir
    if not raw or not isinstance(raw, str):
        return default_dir
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.join(get_base_dir(), raw)


def get_base_path() -> str:
    """Единый источник правды о рабочей папке приложения.

    Все рабочие данные приложения (config.json, downloads.db,
    session.session, аудиофайлы, плейлисты, превью, список каналов)
    обязаны находиться именно здесь. Путь считается от каталога программы,
    а не от текущего рабочего каталога: при запуске из ярлыка это
    System32, и данные молча разъезжались бы по разным папкам
    (DEFECT-020, DEFECT-025).
    """
    return _configured_base_folder()


# Единый абсолютный путь к рабочей папке. Остаётся константой, а не
# функцией: пять модулей импортируют его при загрузке, а тесты
# подменяют его через monkeypatch.
BASE_PATH = get_base_path()
CONFIG_DIR = BASE_PATH
CONFIG_FILE = os.path.join(BASE_PATH, "config.json")
DB_FILE = os.path.join(BASE_PATH, "downloads.db")


def get_session_path() -> str:
    """Возвращает путь к файлу сессии Telegram MTProto (без суффикса .session)."""
    base = get_base_dir()
    session_in_base = os.path.join(base, "session.session")
    session_in_cfg = os.path.join(BASE_PATH, "session.session")
    if os.path.exists(session_in_base):
        return os.path.join(base, "session")
    if os.path.exists(session_in_cfg):
        return os.path.join(BASE_PATH, "session")
    return os.path.join(base, "session")


DEFAULT_CONFIG = {
    "api_id": "",
    "api_hash": "",
    "channel": "",
    "mode": "direct",
    "date_from": "",
    "date_to": "",
    "base_folder": "telegram_audio",
    "max_concurrent_downloads": 5,
    "max_download_retries": 3,
    "download_delay": 1,
    "mp3_bitrate": "192k",
    "sample_rate": 44100,
    "proxy_enabled": False,
    "proxy_type": "socks5",
    "proxy_host": "127.0.0.1",
    "proxy_port": 10808,
    "proxy_username": "",
    "proxy_password": "",
    "export_pattern": "{date}/{artist} - {title}.mp3",
    "auto_generate_m3u8": True,
    "playlist_filename": "{channel}_{date}.m3u8",
    "minimize_to_tray": False,
    "tray_notifications": True,
    "auto_watcher_enabled": False,
    "auto_watcher_interval_minutes": 15,
    "embed_id3_tags": True,
}

DEFAULT_SEARCH_LIMIT = 200


class Settings:
    """Единая точка доступа к config.json.

    Настройки читаются и пишутся только через этот класс. Кэша внутри
    намеренно нет: приложение перезаписывает файл из памяти, и закешированная
    копия разошлась бы с тем, что показано в интерфейсе.
    """

    # Имена плоских ключей и их соответствие вложенному словарю "proxy".
    # Раньше это соответствие было продублировано в трёх местах.
    PROXY_FIELDS = {
        "proxy_enabled": "enabled",
        "proxy_type": "type",
        "proxy_host": "host",
        "proxy_port": "port",
        "proxy_username": "username",
        "proxy_password": "password",
    }

    def read(self) -> dict:
        """Все настройки: сохранённые поверх значений по умолчанию."""
        result = dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                result.update(stored)
        except (OSError, ValueError):
            pass
        return result

    def get(self, key: str, default=None):
        value = self.read().get(key, default)
        return DEFAULT_CONFIG.get(key) if value is None and key in DEFAULT_CONFIG else value

    def _merge_proxy(self, cfg: dict, updates: dict) -> dict:
        """Держит вложенный "proxy" и плоские proxy_* в согласованном виде.

        При наличии вложенного словаря загрузчик читает именно его и
        игнорирует плоские ключи, поэтому частичное обновление одного
        proxy_* молча расходилось с вложенным значением.
        """
        if "proxy" in updates or not any(
                key in updates for key in self.PROXY_FIELDS):
            return cfg
        nested = dict(cfg.get("proxy") or {})
        for flat_key, name in self.PROXY_FIELDS.items():
            if flat_key in updates:
                value = updates[flat_key]
                nested[name] = str(value) if name == "port" else value
        cfg["proxy"] = nested
        return cfg

    def write(self, updates: dict) -> bool:
        """Сохраняет изменения, не затирая остальные настройки.

        Возвращает False, если записать не удалось: вызывающий код решает,
        стоит ли сообщать об этом пользователю.
        """
        try:
            cfg = self.read()
            cfg.update(updates)
            cfg = self._merge_proxy(cfg, updates)
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Не удалось сохранить конфиг: {e}")
            return False


_settings = Settings()


def load_config():
    """Все настройки приложения. Совместимая обёртка над Settings."""
    return _settings.read()


def save_config(**kwargs):
    """Сохраняет переданные настройки. Совместимая обёртка над Settings."""
    _settings.write(kwargs)
