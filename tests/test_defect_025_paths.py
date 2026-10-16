"""Регрессия DEFECT-025: список каналов и метрики диска -- от BASE_PATH.

Пути строились из литерала "telegram_audio", то есть от текущего рабочего
каталога процесса. При запуске из ярлыка рабочим каталогом становится
System32, и последствия были тихими:

* список каналов читался из несуществующего файла и молча возвращался
  к значениям по умолчанию -- добавленные пользователем каналы исчезали;
* запись сохранялась в постороннюю папку рядом с ярлыком;
* показатель свободного места на главном экране оставался пустым.

Тот же относительный путь использовали и тесты, из-за чего прогон
тестов переписывал настоящий файл пользователя. Поэтому проверяется
не содержимое, а сам факт использования каталога приложения.
"""

import os

import pytest

import ui.controllers.channels_controller as cc


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Изолированный BASE_PATH плюс запрет на запись в рабочий каталог."""
    base_dir = tmp_path / "telegram_audio"
    base_dir.mkdir()
    monkeypatch.setattr(cc, "BASE_PATH", str(base_dir))
    return base_dir


def test_channels_file_lives_in_base_path(base):
    assert cc._channels_file() == str(base / "channels.json")


def test_save_writes_into_base_path(base, monkeypatch, tmp_path):
    """Файл должен появиться в каталоге приложения, а не в рабочем."""
    work = tmp_path / "рабочий-каталог"
    work.mkdir()
    monkeypatch.chdir(work)

    cc.save_saved_channels(["@akmpool"])

    assert (base / "channels.json").exists()
    assert not (work / "telegram_audio").exists()


def test_load_reads_from_base_path(base, monkeypatch, tmp_path):
    """Список каналов не должен зависеть от того, откуда запущено."""
    (base / "channels.json").write_text('["@akmpool", "@primetimedj"]',
                                       encoding="utf-8")
    work = tmp_path / "другой-каталог"
    work.mkdir()
    monkeypatch.chdir(work)

    assert cc.load_saved_channels() == ["@akmpool", "@primetimedj"]


def test_load_falls_back_to_defaults_when_absent(base):
    assert cc.load_saved_channels() == list(cc.DEFAULT_CHANNELS)


def test_round_trip_keeps_custom_channels(base):
    """Добавленный канал обязан пережить перезапуск приложения."""
    cc.save_saved_channels(["@akmpool", "@primetimedj"])
    assert cc.load_saved_channels() == ["@akmpool", "@primetimedj"]


def test_storage_stats_use_base_path(monkeypatch, tmp_path):
    """Показатель диска тоже должен смотреть в каталог приложения."""
    import shutil

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    del app

    base_dir = tmp_path / "telegram_audio"
    base_dir.mkdir()
    monkeypatch.setattr(cc, "BASE_PATH", str(base_dir))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)
    monkeypatch.setattr("config.CONFIG_DIR", str(base_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(base_dir / "config.json"))

    import gui
    window = gui.MainWindow()

    seen = {}

    def _fake_usage(path):
        seen["path"] = path
        return (1000, 400, 600)

    monkeypatch.setattr(shutil, "disk_usage", _fake_usage)
    window._refresh_home_view()

    assert seen["path"] == str(base_dir), \
        "метрики диска должны считаться по каталогу приложения"


def test_no_relative_telegram_audio_left_behind():
    """Контроль регрессии: в модуле не должно остаться относительных путей."""
    source = open(cc.__file__, encoding="utf-8").read()
    assert 'disk_usage("telegram_audio")' not in source
    assert 'os.path.join("telegram_audio"' not in source
    assert 'os.makedirs("telegram_audio"' not in source