"""Регрессия шага 2 рефакторинга: рабочая папка -- одна на всех.

До правки путь до рабочей папки считался в трёх местах. ``config.BASE_PATH``
настройку ``base_folder`` игнорировал, а ``recorder.BASE_FOLDER`` её
учитывал. Если пользователь задавал свою папку, файлы уезжали туда, а
``config.json``, ``downloads.db``, ``session.session`` и список каналов
оставались в папке по умолчанию -- то есть приложение работало сразу с
двумя разными каталогами.

Проверяется главное свойство: все модули берут путь из одного места.
"""

import json
import os

import pytest

import config
import recorder as rec

# Настоящая реализация захватывается при импорте модуля: автофикстура
# conftest подменяет config.get_session_path на заглушку ради остальных
# тестов, а здесь проверяется именно поведение оригинала.
_REAL_GET_SESSION_PATH = config.get_session_path


@pytest.fixture
def base_dir(tmp_path, monkeypatch):
    """Подменяет каталог программы на временный."""
    app_dir = tmp_path / "Программа"
    app_dir.mkdir()
    monkeypatch.setattr(config, "get_base_dir", lambda: str(app_dir))
    return app_dir


def _write_config(app_dir, **settings):
    folder = app_dir / "telegram_audio"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"base_folder": "telegram_audio"}
    payload.update(settings)
    (folder / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


class TestConfiguredBaseFolder:
    """Настройка base_folder действительно применяется."""

    def test_default_when_no_config(self, base_dir):
        assert config.get_base_path() == str(base_dir / "telegram_audio")

    def test_default_folder_is_kept(self, base_dir):
        _write_config(base_dir)
        assert config.get_base_path() == str(base_dir / "telegram_audio")

    def test_absolute_setting_is_honoured(self, base_dir, tmp_path):
        """Своя папка на другом диске -- должно работать как настроено."""
        custom = tmp_path / "МояМузыка"
        custom.mkdir()
        _write_config(base_dir, base_folder=str(custom))
        assert config.get_base_path() == str(custom)

    def test_relative_setting_is_resolved_from_program_dir(self, base_dir):
        """Относительное имя отсчитывается от каталога программы."""
        _write_config(base_dir, base_folder="music")
        assert config.get_base_path() == str(base_dir / "music")

    def test_broken_config_does_not_break_startup(self, base_dir):
        """Битый config.json не должен мешать запуску приложения."""
        folder = base_dir / "telegram_audio"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text("{ это не json", encoding="utf-8")
        assert config.get_base_path() == str(folder)

    def test_empty_setting_is_ignored(self, base_dir):
        _write_config(base_dir, base_folder="")
        assert config.get_base_path() == str(base_dir / "telegram_audio")

    def test_result_is_always_absolute(self, base_dir):
        path = config.get_base_path()
        assert os.path.isabs(path), "относительный путь ломал бы запуск из ярлыка"


class TestSingleSourceOfTruth:
    """Модули обязаны смотреть в один источник."""

    def test_recorder_uses_config_path(self, base_dir):
        """recorder больше не вычисляет папку сам."""
        assert rec.BASE_FOLDER == config.BASE_PATH

    def test_session_path_is_independent_of_working_directory(self, base_dir,
                                                            monkeypatch):
        """Файл сессии не должен зависеть от того, откуда запущено.

        Он лежит рядом с программой, а не в рабочей папке, -- это осознанное
        решение: сессия переживает пересоздание папки с музыкой.
        """
        monkeypatch.setattr(config, "BASE_PATH", str(base_dir / "telegram_audio"))
        resolved = _REAL_GET_SESSION_PATH()
        assert os.path.isabs(resolved)
        assert resolved.startswith(str(base_dir)), \
            f"сессия ушла за пределы каталога программы: {resolved}"

    def test_session_never_lands_in_another_drive(self, base_dir, tmp_path,
                                                   monkeypatch):
        """Смена рабочего каталога не должна увести сессию в System32."""
        monkeypatch.setattr(config, "BASE_PATH", str(base_dir / "telegram_audio"))
        elsewhere = tmp_path / "другой"
        elsewhere.mkdir()
        previous = os.getcwd()
        os.chdir(elsewhere)
        try:
            resolved = _REAL_GET_SESSION_PATH()
        finally:
            os.chdir(previous)
        assert resolved.startswith(str(base_dir))

    def test_session_falls_back_to_program_folder_when_exists(self, base_dir,
                                                               monkeypatch):
        """Файл рядом с программой имеет приоритет перед рабочей папкой."""
        monkeypatch.setattr(config, "BASE_PATH", str(base_dir / "telegram_audio"))
        (base_dir / "telegram_audio").mkdir(exist_ok=True)
        (base_dir / "session.session").write_bytes(b"\x00")
        assert _REAL_GET_SESSION_PATH() == str(base_dir / "session")

    def test_config_files_live_in_base_path(self):
        assert config.CONFIG_FILE.startswith(config.BASE_PATH)
        assert config.DB_FILE.startswith(config.BASE_PATH)

    def test_no_hardcoded_folder_outside_config(self):
        """Контроль регрессии: литерал папки остался только в config.py.

        Именно такие литералы породили DEFECT-020 и DEFECT-025.
        Комментарии не проверяются: в них литерал допустим, он
        объясняет, от чего код ушёл.
        """
        checked = (
            "recorder.py", "main.py", "gui.py", "database.py",
            os.path.join("ui", "views.py"),
            os.path.join("ui", "controllers", "channels_controller.py"),
            os.path.join("ui", "controllers", "download_controller.py"),
            os.path.join("ui", "controllers", "tree_controller.py"),
        )
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in checked:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                code = [line for line in f if not line.lstrip().startswith("#")]
            joined = "".join(code)
            if '"telegram_audio"' in joined or "'telegram_audio'" in joined:
                offenders.append(name)
        assert not offenders, (
            f"литерал рабочей папки остался в: {offenders}")