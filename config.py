import json
import os

CONFIG_DIR = "telegram_audio"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DB_FILE = os.path.join(CONFIG_DIR, "downloads.db")

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
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        result = dict(DEFAULT_CONFIG)
        result.update(cfg)
        return result
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(**kwargs):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        cfg = dict(DEFAULT_CONFIG)
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
        except Exception:
            pass
        cfg.update(kwargs)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Не удалось сохранить конфиг: {e}")
