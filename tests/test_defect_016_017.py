"""Регрессионные тесты на DEFECT-016 и DEFECT-017.

Найдены 15.10.2026 при разборе загрузки из t.me/kutsuevpool.

DEFECT-016. Канал и даты не сохранялись. Поля ``channel_input``,
``date_from_input``, ``date_to_input`` не имели ни одного сигнала: значения
читались из config при старте (channels_controller._load_settings), но
никогда не писались обратно. Пользователь вписывал канал, закрывал
приложение — на следующем запуске там снова был старый канал. Ровно тот же
класс, что был DEFECT-006 с режимом.

DEFECT-017. Настройка «Качество MP3» молча не работала для MP3-источников.
recorder.try_direct_download при расширении .mp3 сохраняет файл как есть и
не конвертирует, поэтому выбор 256k на MP3-канале давал 320k без единого
сообщения. Само поведение верное — перекодирование 320k в 256k было бы
чистой потерей качества, — но интерфейс о нём молчал.

Тесты проверяют и сигналы, и реальную запись в config, и то, что
поведение «не перекодировать MP3» зафиксировано и не будет сломано.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

import config as cfg_module
from ui.sidebar import setup_api_drawer, setup_channels_sidebar


# --------------------------------------------------------------------------
# Подготовка окна
# --------------------------------------------------------------------------

def _make_window():
    """Окно с записанными вызовами вместо методов контроллера.

    ``_on_setting_changed`` принимает ``*args``: сигнал ``clicked`` передаёт
    флаг ``checked``, а ``editingFinished`` не передаёт ничего.
    """
    win = QWidget()
    win.calls = []
    win._on_setting_changed = lambda *a: win.calls.append("setting_changed")
    win._save_settings_with_feedback = lambda *a: None
    win._toggle_api_settings = lambda *a: None
    win._preset_dates_all = lambda: win.date_from_input.clear() or win.date_to_input.clear()
    win._preset_dates_30d = lambda: None
    for name in ("_init_saved_channels", "_on_saved_channel_clicked",
                 "_prompt_add_channel", "_remove_selected_channel",
                 "_select_all_channels_view", "_show_channel_context_menu"):
        setattr(win, name, lambda *a: None)
    return win


# --------------------------------------------------------------------------
# DEFECT-016. Канал и даты не сохранялись
# --------------------------------------------------------------------------

class TestDefect016ChannelAndDatesNotSaved:

    def test_channel_field_saves_on_edit_finish(self, qtbot):
        win = _make_window()
        sidebar = setup_channels_sidebar(win)
        qtbot.addWidget(sidebar)

        win.channel_input.setText("@kutsuevpool")
        win.channel_input.editingFinished.emit()

        assert win.calls == ["setting_changed"], \
            "поле канала не сохраняет значение при потере фокуса"

    def test_date_fields_save_on_edit_finish(self, qtbot):
        win = _make_window()
        sidebar = setup_channels_sidebar(win)
        qtbot.addWidget(sidebar)

        win.date_from_input.setText("2024-04-01")
        win.date_from_input.editingFinished.emit()
        win.date_to_input.setText("2024-04-10")
        win.date_to_input.editingFinished.emit()

        assert len(win.calls) == 2, \
            "поля диапазона дат не сохраняют значения при потере фокуса"

    def test_preset_buttons_also_save(self, qtbot):
        """Пресеты меняют даты программно, editingFinished не сработает."""
        win = _make_window()
        sidebar = setup_channels_sidebar(win)
        qtbot.addWidget(sidebar)

        win.btn_preset_all.click()
        assert "setting_changed" in win.calls, \
            "предустановка «Все» не сохраняет очищенный диапазон"

        win.calls.clear()
        win.btn_preset_30d.click()
        assert "setting_changed" in win.calls, \
            "предустановка «30 дн» не сохраняет новый диапазон"

    def test_edited_channel_reaches_config_file(self, qtbot, tmp_path):
        """Сквозная проверка: правка поля действительно попадает в файл."""
        from ui.controllers.channels_controller import ChannelsMixin

        class _Host(ChannelsMixin):
            def __init__(self):
                self._proxy_config = {}
                self.api_id_input = QLineEdit(); self.api_id_input.setText("26222233")
                self.api_hash_input = QLineEdit(); self.api_hash_input.setText("hash")
                self.channel_input = QLineEdit()
                self.mode_combo = QComboBox(); self.mode_combo.addItem("Прямое", "direct")
                self.date_from_input = QLineEdit()
                self.date_to_input = QLineEdit()
                self.threads_spin = QSpinBox(); self.threads_spin.setValue(1)
                self.bitrate_combo = QComboBox()
                self.bitrate_combo.addItems(["320k", "256k", "192k", "128k"])
                self.export_pattern_input = QLineEdit()
                self.export_pattern_input.setText("{date}/{artist} - {title}.mp3")

        win = _make_window()
        sidebar = setup_channels_sidebar(win)
        qtbot.addWidget(sidebar)

        host = _Host()
        cfg_file = tmp_path / "config.json"

        win.channel_input.setText("@kutsuevpool")
        win.date_from_input.setText("2024-04-01")
        win.date_to_input.setText("2024-04-10")
        host.channel_input.setText(win.channel_input.text())
        host.date_from_input.setText(win.date_from_input.text())
        host.date_to_input.setText(win.date_to_input.text())

        with patch.object(cfg_module, "CONFIG_FILE", str(cfg_file)), \
             patch.object(cfg_module, "CONFIG_DIR", str(tmp_path)):
            host._save_settings()
            saved = json.loads(cfg_file.read_text(encoding="utf-8"))

        assert saved["channel"] == "@kutsuevpool"
        assert saved["date_from"] == "2024-04-01"
        assert saved["date_to"] == "2024-04-10"


# --------------------------------------------------------------------------
# DEFECT-017. Настройка качества молча не действует на MP3-источниках
# --------------------------------------------------------------------------

class TestDefect017BitrateSettingIsHonest:

    def _combo(self, qtbot):
        win = _make_window()
        drawer = setup_api_drawer(win)
        qtbot.addWidget(drawer)
        return win.bitrate_combo

    def test_tooltip_warns_about_mp3_passthrough(self, qtbot):
        """Пользователь обязан понимать, почему 256k даёт 320k."""
        tip = self._combo(qtbot).toolTip().lower()
        assert "без конвертации" in tip, \
            "подсказка обязана говорить, что MP3 сохраняется без конвертации"

    def test_tooltip_still_mentions_conversion_bitrate(self, qtbot):
        """Прежнее назначение подсказки не должно пропасть."""
        assert "битрейт" in self._combo(qtbot).toolTip().lower()

    def test_mp3_source_is_not_reencoded(self, qtbot, tmp_path):
        """Поведение «не перекодировать MP3» должно быть зафиксировано.

        Пользователь выбрал всегда максимальный битрейт, поэтому
        перекодирование исходного MP3 недопустимо: оно строго ухудшает файл.
        """
        import asyncio
        import os

        from recorder import TelegramAudioRecorder

        src = tmp_path / "track.mp3"
        src.write_bytes(b"ID3-fake-mp3-payload")
        dest = tmp_path / "out" / "track.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)

        th = TelegramAudioRecorder.__new__(TelegramAudioRecorder)
        th.log = MagicMock()
        th._cancelled = False
        th.client = MagicMock()

        async def _download(message, path, progress_callback=None, **kw):
            with open(path, "wb") as fh:
                fh.write(b"ID3-fake-mp3-payload")
            return True

        th._download_with_retry = _download
        th._get_audio_extension = lambda message: ".mp3"

        # convert_to_mp3 не должен вызываться вообще
        th.convert_to_mp3 = MagicMock(
            side_effect=AssertionError("MP3 нельзя перекодировать повторно")
        )

        ok = asyncio.run(th.try_direct_download(MagicMock(id=1), str(dest)))

        assert ok is True
        assert dest.exists(), "файл должен сохраниться как есть"
        assert dest.read_bytes() == src.read_bytes(), \
            "содержимое MP3 не должно изменяться при переносе"
        th.convert_to_mp3.assert_not_called()