"""Тесты на config.py — выбор базовой директории, путь сессии, отказоустойчивость.

Закрывает ветки, которые не покрывались: все режимы ``get_base_dir``
(в том числе frozen и dist/), запасные пути ``get_session_path`` и обе
ветки ``except`` в ``save_config`` -- чтение испорченного конфига и
невозможность записи.

Все проверки идут через подмену атрибутов модуля и временный каталог:
рабочие config.json и session.session не затрагиваются.
"""

import json
import os
import sys

import pytest

import config as cfg_module

# Фикстура isolate_session_file в conftest подменяет get_session_path на весь
# прогон, поэтому здесь нужна именно исходная функция: она захватывается
# при импорте модуля, до применения подмены.
_real_get_session_path = cfg_module.get_session_path


def _mk(path):
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class TestGetBaseDir:

    def test_not_frozen_uses_cwd_with_work_folder(self, tmp_path, monkeypatch):
        _mk(tmp_path / "telegram_audio")
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.chdir(tmp_path)
        assert cfg_module.get_base_dir() == os.path.abspath(str(tmp_path))

    def test_not_frozen_without_work_folder_uses_module_dir(self, tmp_path, monkeypatch):
        """Нет telegram_audio в cwd -- берётся каталог самого модуля."""
        empty = _mk(tmp_path / "empty")
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.chdir(empty)
        expected = os.path.dirname(os.path.abspath(cfg_module.__file__))
        assert cfg_module.get_base_dir() == expected

    def test_frozen_dist_with_work_folder_returns_parent(self, tmp_path, monkeypatch):
        """Запуск из dist/ внутри проекта: настройки остаются общими."""
        dist = _mk(tmp_path / "dist")
        _mk(tmp_path / "telegram_audio")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "app.exe"))
        assert cfg_module.get_base_dir() == os.path.abspath(str(tmp_path))

    def test_frozen_dist_with_config_py_returns_parent(self, tmp_path, monkeypatch):
        dist = _mk(tmp_path / "dist")
        (tmp_path / "config.py").write_text("#", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "app.exe"))
        assert cfg_module.get_base_dir() == os.path.abspath(str(tmp_path))

    def test_frozen_dist_without_markers_stays_in_dist(self, tmp_path, monkeypatch):
        """Нет ни папки данных, ни config.py -- остаёмся рядом с exe."""
        dist = _mk(tmp_path / "dist")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "app.exe"))
        assert cfg_module.get_base_dir() == os.path.abspath(str(dist))

    def test_frozen_outside_dist_uses_exe_dir(self, tmp_path, monkeypatch):
        exe_dir = tmp_path / "installed"
        exe_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "app.exe"))
        assert cfg_module.get_base_dir() == os.path.abspath(str(exe_dir))


class TestGetSessionPath:

    def test_prefers_session_in_base_dir(self, tmp_path, monkeypatch):
        (tmp_path / "session.session").write_bytes(b"")
        monkeypatch.setattr(cfg_module, "get_base_dir", lambda: str(tmp_path))
        assert _real_get_session_path() == os.path.join(str(tmp_path), "session")

    def test_falls_back_to_session_in_work_folder(self, tmp_path, monkeypatch):
        work = _mk(tmp_path / "telegram_audio")
        (tmp_path / "telegram_audio" / "session.session").write_bytes(b"")
        monkeypatch.setattr(cfg_module, "get_base_dir", lambda: str(tmp_path))
        assert _real_get_session_path() == os.path.join(work, "session")

    def test_returns_base_path_when_nothing_found(self, tmp_path, monkeypatch):
        """Файла ещё нет -- возвращается путь по умолчанию."""
        empty = _mk(tmp_path / "empty")
        monkeypatch.setattr(cfg_module, "get_base_dir", lambda: empty)
        assert _real_get_session_path() == os.path.join(empty, "session")


class TestSaveConfigRobustness:

    def test_broken_existing_config_is_replaced(self, tmp_path, monkeypatch):
        """Испорченный config.json не должен мешать сохранению."""
        cfg_dir = tmp_path / "data"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text("{ это не json", encoding="utf-8")

        monkeypatch.setattr(cfg_module, "CONFIG_DIR", str(cfg_dir))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(cfg_file))

        cfg_module.save_config(mp3_bitrate="320k")

        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved["mp3_bitrate"] == "320k"

    def test_unreadable_config_keeps_defaults(self, tmp_path, monkeypatch):
        """config.json не читается -- сохраняются значения по умолчанию."""
        cfg_dir = tmp_path / "data"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(json.dumps({"mp3_bitrate": "128k"}), encoding="utf-8")

        real_open = open

        def _open(path, *a, **kw):
            if str(path) == str(cfg_file) and "r" in (a[0] if a else kw.get("mode", "r")):
                raise PermissionError("нет доступа")
            return real_open(path, *a, **kw)

        monkeypatch.setattr(cfg_module, "CONFIG_DIR", str(cfg_dir))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(cfg_file))
        monkeypatch.setattr("builtins.open", _open)

        cfg_module.save_config(mode="direct")

        saved = json.loads(real_open(cfg_file, encoding="utf-8").read())
        assert saved["mode"] == "direct"
        # Файл не прочитан, поэтому mp3_bitrate берётся из значений по
        # умолчанию, а не из того, что лежало в файле.
        assert saved["mp3_bitrate"] == cfg_module.DEFAULT_CONFIG["mp3_bitrate"]

    def test_write_failure_does_not_raise(self, tmp_path, monkeypatch, caplog):
        """Отказ записи не должен ронять вызывающий код."""
        cfg_dir = tmp_path / "data"
        cfg_dir.mkdir()
        # Каталог вместо файла: open(..., "w") завершится ошибкой
        cfg_file = cfg_dir / "config.json"
        cfg_file.mkdir()

        monkeypatch.setattr(cfg_module, "CONFIG_DIR", str(cfg_dir))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(cfg_file))

        with caplog.at_level("WARNING"):
            cfg_module.save_config(mode="direct")

        assert any("Не удалось сохранить конфиг" in r.message for r in caplog.records), \
            "отказ записи должен попадать в лог с предупреждением"

    def test_makedirs_failure_does_not_raise(self, tmp_path, monkeypatch):
        """Не удаётся даже создать папку -- тоже не роняем."""
        blocked = tmp_path / "blocked"
        blocked.write_text("не папка", encoding="utf-8")

        monkeypatch.setattr(cfg_module, "CONFIG_DIR", str(blocked / "data"))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(blocked / "data" / "config.json"))

        cfg_module.save_config(mode="direct")  # не должно бросить исключение


class TestSessionIsolationGuard:
    """Страховка от повторения порчи рабочей сессии.

    Тесты, вызывающие downloader._create_client, открывают файл сессии и
    выставляют PRAGMA journal_mode=WAL. Без подмены пути они писали в
    настоящий session.session и портили авторизацию Telegram.
    """

    def test_session_path_points_inside_tmp(self, tmp_path):
        assert cfg_module.get_session_path().startswith(str(tmp_path)), \
            "во время тестов путь сессии обязан вести во временный каталог"

    def test_real_session_file_is_not_used(self):
        import config as real_config_mod
        import downloader

        # Подмена действует и для локального импорта внутри _create_client:
        # функция делает `from config import get_session_path` в момент вызова.
        assert real_config_mod.get_session_path is not _real_get_session_path
        assert "telegram_audio" not in real_config_mod.get_session_path()

    def test_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(tmp_path / "нет.json"))
        assert cfg_module.load_config() == dict(cfg_module.DEFAULT_CONFIG)

    def test_broken_file_returns_defaults(self, tmp_path, monkeypatch):
        broken = tmp_path / "config.json"
        broken.write_text("не json вовсе", encoding="utf-8")
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(broken))
        assert cfg_module.load_config() == dict(cfg_module.DEFAULT_CONFIG)

    def test_partial_file_is_merged_with_defaults(self, tmp_path, monkeypatch):
        partial = tmp_path / "config.json"
        partial.write_text(json.dumps({"channel": "@akmpool"}), encoding="utf-8")
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(partial))

        cfg = cfg_module.load_config()
        assert cfg["channel"] == "@akmpool"
        assert cfg["mp3_bitrate"] == cfg_module.DEFAULT_CONFIG["mp3_bitrate"]


class TestDefaultConfigShape:

    def test_defaults_have_no_unexpected_types(self):
        assert isinstance(cfg_module.DEFAULT_CONFIG["mp3_bitrate"], str)
        assert cfg_module.DEFAULT_CONFIG["mode"] in ("direct", "record", "hybrid")

    def test_save_merges_into_existing_file(self, tmp_path, monkeypatch):
        """Частичное обновление не должно затирать остальные ключи."""
        cfg_dir = tmp_path / "data"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(json.dumps({"channel": "@akmpool", "mode": "record"}),
                            encoding="utf-8")

        monkeypatch.setattr(cfg_module, "CONFIG_DIR", str(cfg_dir))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", str(cfg_file))

        cfg_module.save_config(mode="direct")

        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved["channel"] == "@akmpool"
        assert saved["mode"] == "direct"