"""Тесты управления каналами (`ui/controllers/channels_controller.py`).

Модуль держался на 66 %: добавление каналов из трёх точек входа, выбор
канала в сайдбаре и фильтрация дерева по каналу не проверялись. Именно
здесь живёт правка DEFECT-011, поэтому поведение закреплено отдельно.
"""

from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox


@pytest.fixture
def win(qtbot, monkeypatch, tmp_path):
    """Окно приложения с полностью изолированными сохранёнными каналами."""
    config_dir = tmp_path / "telegram_audio"
    config_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("config.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(config_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok))

    from gui import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)

    # Сохранение каналов не должно трогать данные пользователя.
    monkeypatch.setattr(
        "ui.controllers.channels_controller.save_saved_channels",
        lambda chans: None, raising=False)
    return window


class TestAddChannelFromManager:

    def test_empty_input_is_ignored(self, win):
        """Пустое поле не должно добавлять канал."""
        win.chan_view_input.setText("   ")
        before = list(getattr(win, "_saved_channels", []))
        win._add_channel_from_manager()
        assert list(getattr(win, "_saved_channels", [])) == before

    def test_bare_name_gets_at_sign(self, win, monkeypatch):
        """Имя без @ должно нормализоваться."""
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "_refresh_channels_view", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = []

        win.chan_view_input.setText("akmpool")
        win._add_channel_from_manager()

        assert win._saved_channels == ["@akmpool"]
        assert win.chan_view_input.text() == "", "поле обязано очищаться"

    def test_url_is_kept_as_is(self, win, monkeypatch):
        """Ссылка https://t.me/x не должна превращаться в @https://…"""
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "_refresh_channels_view", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = []

        win.chan_view_input.setText("https://t.me/akmpool")
        win._add_channel_from_manager()

        assert win._saved_channels == ["https://t.me/akmpool"]

    def test_duplicate_is_not_added_twice(self, win, monkeypatch):
        """Повторное добавление не должно плодить дубликаты."""
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "_refresh_channels_view", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = ["@akmpool"]

        win.chan_view_input.setText("@akmpool")
        win._add_channel_from_manager()

        assert win._saved_channels == ["@akmpool"]

    def test_added_channel_becomes_active(self, win, monkeypatch):
        """Добавленный канал становится активным в поле Library."""
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "_refresh_channels_view", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = []

        win.chan_view_input.setText("@newchan")
        win._add_channel_from_manager()

        assert win.channel_input.text() == "@newchan"


class TestAddChannelFromHome:

    """`_add_channel_from_home` удалён как мёртвый код (шаг 4 рефакторинга).

    Метод остался от прежнего экрана Home, который заменён Bento Studio.
    Виджет `home_add_chan_input` не создавался, к сигналам метод не был
    подключён, вызова из кода не было. Тесты фиксируют новое состояние,
    чтобы метод не вернулся незаметно.
    """

    def test_method_is_gone(self):
        import inspect

        from ui.controllers.channels_controller import ChannelsMixin

        assert not hasattr(ChannelsMixin, "_add_channel_from_home")
        assert "_add_channel_from_home" not in inspect.getsource(ChannelsMixin)

    def test_widget_does_not_exist_on_window(self, win):
        assert not hasattr(win, "home_add_chan_input")

    def test_missing_method_raises(self, win):
        """Обращение к удалённому методу должно быть заметным."""
        assert not hasattr(win, "_add_channel_from_home")
        with pytest.raises(AttributeError):
            win._add_channel_from_home()


class TestRemoveSelectedChannel:

    def test_without_selection_nothing_happens(self, win, monkeypatch):
        """Без выделения удаление не должно ничего трогать."""
        win.saved_channels_list.clearSelection()
        win._saved_channels = ["@akmpool"]
        monkeypatch.setattr(win, "_remove_saved_channel",
                            lambda ch: pytest.fail("удаление не должно вызываться"))
        win._remove_selected_channel()

    def test_selected_channel_is_removed(self, win, monkeypatch):
        """Выбранный канал обязан быть удалён из списка."""
        removed = []
        monkeypatch.setattr(win, "_remove_saved_channel", removed.append)

        item = QListWidgetItem("@akmpool")
        item.setData(Qt.ItemDataRole.UserRole, "@akmpool")
        win.saved_channels_list.addItem(item)
        win.saved_channels_list.setCurrentItem(item)

        win._remove_selected_channel()

        assert removed == ["@akmpool"]


class TestChannelFiltering:

    def test_all_sentinel_clears_filter(self, win):
        """Служебный пункт «Все каналы» обязан сбрасывать фильтр."""
        win._filter_tree_by_channel("@akmpool")
        assert win._selected_channel_filter == "@akmpool"

        win._filter_tree_by_channel("__ALL__")
        assert win._selected_channel_filter is None

    def test_empty_value_clears_filter(self, win):
        win._filter_tree_by_channel("@akmpool")
        win._filter_tree_by_channel("")
        assert win._selected_channel_filter is None

    def test_filter_preserves_search_text(self, win):
        """Смена канала не должна затирать текст поиска."""
        win.search_filter_input.setText("zivert")
        win._filter_tree_by_channel("@other")
        assert win.search_filter_input.text() == "zivert"

    def test_select_all_resets_filter(self, win):
        win._filter_tree_by_channel("@akmpool")
        monkey_log = []
        win.log = lambda t: monkey_log.append(t)
        win._select_all_channels_view()
        assert win._selected_channel_filter is None
        assert any("все каналы" in m.lower() for m in monkey_log)


class TestSidebarChannelClick:

    def _item(self, win, text, data):
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, data)
        win.saved_channels_list.addItem(item)
        return item

    def test_all_channels_item_clears_input(self, win):
        """Пункт «Все каналы» должен очистить поле активного канала."""
        win._saved_channels = ["@akmpool"]
        win.channel_input.setText("@akmpool")
        win.log = lambda *a, **kw: None

        item = self._item(win, "🌟 Все каналы (1)", "__ALL__")
        win._on_saved_channel_clicked(item)

        assert win.channel_input.text() == ""
        assert win._selected_channel_filter is None

    def test_channel_item_sets_filter(self, win):
        """Выбор канала обязан поставить его в поле и включить фильтр."""
        win.channel_input.setText("")
        win.log = lambda *a, **kw: None

        item = self._item(win, "✈ @akmpool", "@akmpool")
        win._on_saved_channel_clicked(item)

        assert win.channel_input.text() == "@akmpool"
        assert win._selected_channel_filter == "@akmpool"

    def test_item_without_data_falls_back_to_text(self, win):
        """Если данных нет, канал берётся из текста подписи."""
        win.channel_input.setText("")
        win.log = lambda *a, **kw: None

        item = self._item(win, "✈ @akmpool", None)
        win._on_saved_channel_clicked(item)

        assert "@akmpool" in win.channel_input.text()

    def test_single_word_label_is_used_as_is(self, win):
        """Подпись из одного слова не должна ломать разбор."""
        win.channel_input.setText("")
        win.log = lambda *a, **kw: None

        item = self._item(win, "@solo", None)
        win._on_saved_channel_clicked(item)

        assert win.channel_input.text() == "@solo"


class TestActiveChannelConsistency:

    """Регрессия на DEFECT-011: удаление активного канала не должно оставлять
    его имя в поле, иначе статус в таблице становится «В пуле» у всех."""

    def test_full_add_then_delete_cycle(self, win, monkeypatch):
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "_refresh_channels_view", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = []

        # Добавили канал — он стал активным.
        win.chan_view_input.setText("@tmp_cycle")
        win._add_channel_from_manager()
        assert win.channel_input.text() == "@tmp_cycle"

        # Удалили его — поле обязано очиститься.
        win._remove_saved_channel("@tmp_cycle")
        assert win.channel_input.text() == "", "поле активного канала должно очиститься"

    def test_deleting_other_channel_keeps_active(self, win, monkeypatch):
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win.channel_input.setText("@akmpool")
        win._saved_channels = ["@akmpool", "@other"]

        win._remove_saved_channel("@other")

        assert win.channel_input.text() == "@akmpool"

    def test_case_does_not_matter(self, win, monkeypatch):
        """Регистр не должен влиять на очистку поля."""
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win.channel_input.setText("@AKMPOOL")
        win._saved_channels = ["@akmpool"]

        win._remove_saved_channel("@akmpool")

        assert win.channel_input.text() == ""

# ---------------------------------------------------------------------------
# DEFECT-020. Статистика места считалась по пути от текущего каталога
# ---------------------------------------------------------------------------

class TestStorageStatsPath:
    """``_update_storage_stats`` обязан смотреть на BASE_PATH.

    Относительный ``telegram_audio`` при запуске из чужого рабочего
    каталога создавал лишнюю папку и показывал свободное место не на том
    диске — тот же класс, что был DEFECT-013.
    """

    def _host(self):
        from ui.controllers.channels_controller import ChannelsMixin

        class _Host(ChannelsMixin):
            def __init__(self):
                self.storage_usage_lbl = MagicMock()
                self.storage_bar = MagicMock()
                self.storage_info_lbl = MagicMock()

        return _Host()

    def test_uses_base_path(self, tmp_path, monkeypatch):
        import ui.controllers.channels_controller as cc

        base = tmp_path / "telegram_audio"
        monkeypatch.setattr(cc, "BASE_PATH", str(base))

        host = self._host()
        host._update_storage_stats()

        assert base.exists(), "папка должна соответствовать BASE_PATH"
        host.storage_usage_lbl.setText.assert_called()
        assert host.storage_bar.setValue.called

    def test_no_stray_folder_in_cwd(self, tmp_path, monkeypatch):
        import ui.controllers.channels_controller as cc

        base = tmp_path / "elsewhere" / "telegram_audio"
        monkeypatch.setattr(cc, "BASE_PATH", str(base))
        workdir = tmp_path / "cwd"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        self._host()._update_storage_stats()

        assert not (workdir / "telegram_audio").exists(), \
            "в рабочем каталоге не должно появляться лишней папки"

    def test_failure_does_not_raise(self, tmp_path, monkeypatch):
        import ui.controllers.channels_controller as cc

        blocked = tmp_path / "blocked"
        blocked.write_text("не папка", encoding="utf-8")
        monkeypatch.setattr(cc, "BASE_PATH", str(blocked / "data"))

        self._host()._update_storage_stats()   # без исключения


# ---------------------------------------------------------------------------
# DEFECT-023. Числовой api_id в конфиге ронял приложение при запуске
# ---------------------------------------------------------------------------

class TestLoadSettingsTypes:
    """QLineEdit.setText принимает только строку.

    Если ``api_id`` в config.json оказался числом -- правка руками или
    перенос из чужого конфига -- падение происходило в конструкторе
    MainWindow, то есть приложение не запускалось вовсе.
    """

    def _run_load(self, win, monkeypatch, tmp_path, cfg):
        import ui.controllers.channels_controller as cc
        monkeypatch.setattr(cc, "load_config", lambda: cfg)
        win._load_settings()

    def test_numeric_api_id_does_not_crash(self, win, monkeypatch, tmp_path):
        self._run_load(win, monkeypatch, tmp_path, {
            "api_id": 26222233, "api_hash": "abc", "channel": "@akmpool",
            "mode": "direct", "date_from": "2026-09-09", "date_to": "2026-10-09",
            "mp3_bitrate": "256k", "max_concurrent_downloads": 1,
        })
        assert win.api_id_input.text() == "26222233"

    def test_numeric_channel_does_not_crash(self, win, monkeypatch, tmp_path):
        self._run_load(win, monkeypatch, tmp_path, {
            "api_id": "1", "api_hash": "abc", "channel": 12345,
            "mode": "direct", "date_from": "", "date_to": "",
            "mp3_bitrate": "256k", "max_concurrent_downloads": 1,
        })
        assert win.channel_input.text() == "12345"

    def test_unknown_bitrate_is_ignored(self, win, monkeypatch, tmp_path):
        """Значения не из списка не должны ломать загрузку."""
        self._run_load(win, monkeypatch, tmp_path, {
            "api_id": "1", "api_hash": "abc", "channel": "@a",
            "mode": "direct", "date_from": "", "date_to": "",
            "mp3_bitrate": "999k", "max_concurrent_downloads": 1,
        })
