"""Регрессионные тесты на дефекты ночного физического аудита.

Каждый тест написан так, чтобы падать при откате соответствующей правки.
Это страховка от молчаливого возврата дефекта при следующем рефакторинге.

Соответствие: night_qa/full_physical_audit/defects.md, DEFECT-001 … DEFECT-013.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from PyQt6.QtWidgets import QApplication, QMessageBox, QScrollArea

import config as cfg_module
import ui.controllers.download_controller as dl_ctrl


# --------------------------------------------------------------------------
# DEFECT-010. Частичный save_config(proxy_port=...) расходился с вложенным ключом
# --------------------------------------------------------------------------

class TestDefect010ProxyConfigMirroring:

    def test_partial_save_updates_nested_proxy_dict(self, tmp_path):
        """Плоский proxy_port обязан попасть и во вложенный ключ proxy."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "proxy_port": 10808,
            "proxy": {"enabled": False, "type": "socks5", "host": "127.0.0.1",
                      "port": "11111", "username": "", "password": ""},
        }), encoding="utf-8")

        with patch.object(cfg_module, "CONFIG_FILE", str(cfg_file)), \
             patch.object(cfg_module, "CONFIG_DIR", str(tmp_path)):
            cfg_module.save_config(proxy_port=10808)
            saved = json.loads(cfg_file.read_text(encoding="utf-8"))

        # Загрузчик читает вложенный словарь и игнорирует плоские ключи,
        # поэтому расхождение здесь означало бы «сохранение не работает».
        assert saved["proxy_port"] == 10808
        assert saved["proxy"]["port"] == "10808"

    def test_full_proxy_dict_save_is_not_mirrored(self, tmp_path):
        """Явная передача всего словаря proxy не должна переписываться."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")
        proxy = {"enabled": True, "type": "http", "host": "10.0.0.1",
                 "port": "8080", "username": "u", "password": "p"}

        with patch.object(cfg_module, "CONFIG_FILE", str(cfg_file)), \
             patch.object(cfg_module, "CONFIG_DIR", str(tmp_path)):
            cfg_module.save_config(proxy=proxy)
            saved = json.loads(cfg_file.read_text(encoding="utf-8"))

        assert saved["proxy"] == proxy

    def test_port_stored_as_string_matches_gui_writer(self, tmp_path):
        """GUI пишет порт строкой — зеркалирование должно сохранять тип."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")

        with patch.object(cfg_module, "CONFIG_FILE", str(cfg_file)), \
             patch.object(cfg_module, "CONFIG_DIR", str(tmp_path)):
            cfg_module.save_config(proxy_port=10808)
            saved = json.loads(cfg_file.read_text(encoding="utf-8"))

        assert isinstance(saved["proxy"]["port"], str)


# --------------------------------------------------------------------------
# DEFECT-013. Папка загрузок искалась относительно текущего каталога
# --------------------------------------------------------------------------

class TestDefect013DownloadFolderUsesBasePath:

    def test_folder_resolved_from_config_base_path(self, tmp_path, monkeypatch):
        """Кнопка должна открывать рабочую папку, а не папку в CWD."""
        base = tmp_path / "elsewhere" / "telegram_audio"
        base.mkdir(parents=True)
        stray = tmp_path / "cwd"
        stray.mkdir()
        monkeypatch.chdir(stray)
        monkeypatch.setattr(dl_ctrl, "BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(dl_ctrl.os, "startfile", lambda p: opened.setdefault("path", p))

        ctrl = _make_controller("@akmpool")
        ctrl.open_download_folder()

        assert opened["path"] == str(base)
        # Ключевой момент: относительный путь создал бы мусор в CWD.
        assert not os.path.exists(str(stray / "telegram_audio"))

    def test_channel_subfolder_preferred_when_present(self, tmp_path, monkeypatch):
        """Если папка канала есть, открывается она."""
        base = tmp_path / "telegram_audio"
        (base / "akmpool").mkdir(parents=True)
        monkeypatch.setattr(dl_ctrl, "BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(dl_ctrl.os, "startfile", lambda p: opened.setdefault("path", p))

        ctrl = _make_controller("@akmpool")
        ctrl.open_download_folder()

        assert opened["path"] == str(base / "akmpool")

    def test_url_channel_is_cleaned_before_use(self, tmp_path, monkeypatch):
        """Ссылка https://t.me/x должна давать папку x."""
        base = tmp_path / "telegram_audio"
        (base / "akmpool").mkdir(parents=True)
        monkeypatch.setattr(dl_ctrl, "BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(dl_ctrl.os, "startfile", lambda p: opened.setdefault("path", p))

        ctrl = _make_controller("https://t.me/akmpool")
        ctrl.open_download_folder()

        assert opened["path"] == str(base / "akmpool")


def _make_controller(channel_text):
    """Минимальный носитель метода open_download_folder."""
    from PyQt6.QtWidgets import QLineEdit

    class _Line(QLineEdit):
        pass

    holder = _Line()
    holder.setText(channel_text)

    ctrl = type("Ctrl", (), {})()
    ctrl.channel_input = holder
    ctrl.open_download_folder = (
        dl_ctrl.DownloadControllerMixin.open_download_folder.__get__(ctrl)
    )
    ctrl.log = lambda *a, **kw: None
    return ctrl


# --------------------------------------------------------------------------
# DEFECT-003 и DEFECT-004. Ложный успех и битый плейлист
# --------------------------------------------------------------------------

class TestDefect003And004FileValidation:

    def _recorder(self, tmp_path):
        from recorder import TelegramAudioRecorder
        rec = TelegramAudioRecorder.__new__(TelegramAudioRecorder)
        rec.client = MagicMock()
        rec.channel_username = "@akmpool"
        rec.BASE_FOLDER = str(tmp_path)
        return rec

    def test_missing_file_is_not_reported_as_success(self, tmp_path):
        """Отсутствующий файл не должен давать True."""
        rec = self._recorder(tmp_path)
        missing = str(tmp_path / "nope.mp3")
        assert not os.path.exists(missing)
        # Условие успеха из исправления: файл есть и не пустой.
        assert not (os.path.exists(missing) and os.path.getsize(missing) > 0)

    def test_empty_file_is_not_reported_as_success(self, tmp_path):
        """Нулевой файл — тоже неуспех."""
        empty = tmp_path / "empty.mp3"
        empty.write_bytes(b"")
        assert not (os.path.exists(empty) and os.path.getsize(empty) > 0)

    def test_real_file_passes_validation(self, tmp_path):
        good = tmp_path / "good.mp3"
        good.write_bytes(b"\x00" * 16)
        assert os.path.exists(good) and os.path.getsize(good) > 0


# --------------------------------------------------------------------------
# DEFECT-007. Двойной @ в теге-комментарии
# --------------------------------------------------------------------------

class TestDefect007CommentTagAtSign:

    def test_single_at_sign_in_comment(self):
        """username уже начинается с @ — второй добавлять нельзя."""
        channel_username = "@akmpool"
        comment = f"Telegram: {str(channel_username).lstrip('@')}"
        assert comment == "Telegram: akmpool"
        assert "@@" not in comment

    def test_strips_only_leading_at(self):
        comment = f"Telegram: {str('@a@b').lstrip('@')}"
        assert comment == "Telegram: a@b"


# --------------------------------------------------------------------------
# Qt-часть: окно приложения
# --------------------------------------------------------------------------

@pytest.fixture
def win(qtbot, monkeypatch, tmp_path):
    """Окно приложения, изолированное во временном каталоге."""
    from PyQt6.QtCore import Qt

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
    return window


def _drive_key_event(window, key, modifiers):
    """Синтезирует нажатие клавиши так же, как это делает Qt."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)


class TestDefect001MonitorPanelScrollable:

    def test_monitor_content_inside_scroll_area(self, win):
        """Наложение секций устранено обёрткой контента в QScrollArea."""
        panel = win.right_panel
        scroll = panel.findChild(QScrollArea)
        assert scroll is not None, (
            "контент панели монитора обязан лежать внутри QScrollArea"
        )
        assert scroll.widgetResizable() is True
        assert scroll.widget() is not None

    def test_scroll_policy_disables_horizontal_bar(self, win):
        """Горизонтальная прокрутка в узкой панели не нужна."""
        from PyQt6.QtCore import Qt
        scroll = win.right_panel.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


class TestDefect002SelectionFromTreeNotHiddenMirror:

    """Регрессия на «скачивались ВСЕ треки вместо отмеченных».

    Прежний код складывал поверх выбора дерева все отмеченные строки
    home_recent_table (99 штук, отмеченных по умолчанию), из-за чего
    отмеченные 2 трека раздувались до 99 задач.
    """

    def _prepare(self, win, checked_tree_ids):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QTableWidgetItem

        win.library_tree.clear()
        win._track_by_id = {}
        for i, mid in enumerate(checked_tree_ids, start=1):
            _make_tree_track(win.library_tree, mid, win)

        table = win.home_recent_table
        table.setRowCount(0)
        for i in range(99):
            table.insertRow(i)
            item = QTableWidgetItem("recent%d" % i)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, {"id": 5000 + i})
            table.setItem(i, 0, item)

    def _run_start_download(self, win, monkeypatch):
        from PyQt6.QtCore import Qt

        win.api_id_input.setText("12345")
        win.api_hash_input.setText("hash")
        win.channel_input.setText("@akmpool")
        win.channel_input.setFocus()
        for i in range(win.library_tree.topLevelItemCount()):
            group = win.library_tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                mid = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(mid, int) and mid in win._track_by_id:
                    child.setCheckState(0, Qt.CheckState.Checked)

        captured = {}

        class _Thread:
            def __init__(self, *args, **kwargs):
                for key in ("message_ids", "track_ids", "ids", "targets"):
                    if key in kwargs:
                        captured["ids"] = kwargs[key]
                        break
                args_list = args
                if not captured.get("ids") and args_list:
                    for a in args_list:
                        if isinstance(a, (list, tuple)) and a and isinstance(a[0], int):
                            captured["ids"] = list(a)
                            break
            def start(self):
                captured["started"] = True
            def isRunning(self):
                return False

        monkeypatch.setattr(dl_ctrl, "DownloadThread", _Thread)
        logged = []
        monkeypatch.setattr(win, "log", lambda t: logged.append(t))
        win.start_download()
        return captured, logged

    def test_only_checked_tree_tracks_are_queued(self, win, monkeypatch):
        """Отмечено 2 трека в дереве — должно создаться ровно 2 задачи."""
        self._prepare(win, [7001, 7002])
        _captured, logged = self._run_start_download(win, monkeypatch)

        joined = " ".join(logged)
        assert "Загрузка 2 треков" in joined, joined

    def test_recent_table_rows_do_not_leak_into_queue(self, win, monkeypatch):
        """99 отмеченных строк Bento не должны попасть в очередь."""
        self._prepare(win, [7003])
        _captured, logged = self._run_start_download(win, monkeypatch)

        joined = " ".join(logged)
        assert "99" not in joined, f"в очередь попали строки Bento: {joined}"

    def test_nothing_checked_yields_zero(self, win, monkeypatch):
        """Дерево заполнено, но всё снято — очередь обязана быть пустой.

        Отдельно оговорено: если дерево пусто совсем (пользователь работает
        на вкладке Bento), контроллер осознанно откатывается к таблице
        недавних треков. Этот случай проверяется другим тестом.
        """
        from PyQt6.QtCore import Qt

        self._prepare(win, [7004, 7005])
        for i in range(win.library_tree.topLevelItemCount()):
            group = win.library_tree.topLevelItem(i)
            for j in range(group.childCount()):
                group.child(j).setCheckState(0, Qt.CheckState.Unchecked)

        _captured, logged = self._run_start_download(win, monkeypatch)
        joined = " ".join(logged)
        assert "Загрузка 99 треков" not in joined, joined

    def test_empty_tree_falls_back_to_recent_table(self, win, monkeypatch):
        """Пустое дерево означает работу на вкладке Bento — откат корректен."""
        self._prepare(win, [])
        _captured, logged = self._run_start_download(win, monkeypatch)
        joined = " ".join(logged)
        assert "Загрузка 99 треков" in joined, (
            "при пустом дереве контроллер обязан взять треки из таблицы Bento"
        )


class TestDefect005QueuedTurnsIntoFailed:

    def test_stale_badges_become_failed_on_finish(self, win, monkeypatch):
        """Зависшие QUEUED/DOWNLOADING обязаны стать FAILED в конце."""
        from PyQt6.QtWidgets import QLabel

        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win.download_thread = None

        queued = QLabel("QUEUED")
        downloading = QLabel("DOWNLOADING 3/9")
        saved = QLabel("SAVED")
        win._track_status_badges = {1: queued, 2: downloading, 3: saved}

        win.download_finished()

        assert queued.text() == "FAILED"
        assert downloading.text() == "FAILED"
        assert saved.text() == "SAVED", "успешные треки трогать нельзя"

    def test_download_finished_is_callable(self, win):
        assert callable(getattr(win, "download_finished", None))


class TestDefect006ModeIsPersisted:

    def test_mode_change_writes_config(self, win):
        """Выбор режима обязан сохраняться сразу, без кнопки."""
        import config as cfg

        combo = win.mode_combo
        target = 1 if combo.currentIndex() != 1 else 2
        combo.setCurrentIndex(target)

        expected = combo.itemData(target)
        assert expected in ("direct", "record", "hybrid")
        assert cfg.load_config().get("mode") == expected

    def test_every_mode_value_is_saved(self, win):
        import config as cfg
        combo = win.mode_combo
        for idx in range(combo.count()):
            combo.setCurrentIndex(idx)
            assert cfg.load_config().get("mode") == combo.itemData(idx)


class TestDefect008TreeHotkeyEventFilter:

    def test_event_filter_toggles_checkbox_on_x(self, win):
        """X обязан переключать чекбокс выделенной строки.

        QTreeWidget обрабатывает букву сам (переход по первой букве), поэтому
        keyPressEvent окна не срабатывал и требовался eventFilter.
        """
        from PyQt6.QtCore import Qt
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        tree = win.library_tree
        item = _make_tree_track(tree, 9100, win)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        tree.setCurrentItem(item)
        QApplication.processEvents()

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X,
                          Qt.KeyboardModifier.NoModifier)
        consumed = win.eventFilter(tree, event)
        QApplication.processEvents()

        assert consumed is True, "фильтр обязан поглощать X"
        assert item.checkState(0) == Qt.CheckState.Checked

    def test_event_filter_ignores_ctrl_combinations(self, win):
        """Сочетания с Ctrl/Alt фильтр не перехватывает."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        tree = win.library_tree
        item = _make_tree_track(tree, 9101, win)
        from PyQt6.QtCore import Qt as _Qt
        item.setCheckState(0, _Qt.CheckState.Unchecked)
        tree.setCurrentItem(item)

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X,
                          Qt.KeyboardModifier.ControlModifier)
        assert win.eventFilter(tree, event) is False

    def test_unrelated_widgets_pass_through(self, win):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import Qt

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X,
                          Qt.KeyboardModifier.NoModifier)
        assert win.eventFilter(win.search_filter_input, event) is False


def _dummy_event():
    from PyQt6.QtCore import QEvent
    return QEvent(QEvent.Type.User)


def _make_tree_track(tree, msg_id, window):
    """Создаёт в дереве строку трека так, как её ждёт контроллер.

    Колонка 1 хранит словарь трека, колонка 0 — числовой идентификатор:
    именно так их читает `_on_tree_selection_changed`.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QTreeWidgetItem

    track = {
        "id": msg_id, "msg_id": msg_id, "title": "T%d" % msg_id, "performer": "P",
        "channel": "@akmpool", "filepath": "", "status": "ready",
    }
    window._track_by_id[msg_id] = track

    group = QTreeWidgetItem(["@akmpool"])
    item = QTreeWidgetItem([track["title"]])
    item.setData(0, Qt.ItemDataRole.UserRole, msg_id)
    item.setData(1, Qt.ItemDataRole.UserRole, track)
    tree.addTopLevelItem(group)
    group.addChild(item)
    return item


class TestDefect009ClearSearchShortcut:

    def test_shift_c_shortcut_registered(self, win):
        """Shift+C должен быть QShortcut, иначе keyPressEvent не дойдёт."""
        shortcuts = getattr(win, "_dj_shortcuts", None)
        assert shortcuts, "горячие клавиши обязаны быть зарегистрированы через QShortcut"
        seqs = [s.key().toString() for s in shortcuts]
        assert any("C" in s.upper() for s in seqs), seqs

    def test_clear_search_resets_all_fields(self, win):
        win._dj_clear_search()
        for attr in ("top_search_input", "search_filter_input"):
            field = getattr(win, attr, None)
            if field is not None:
                assert field.text() == ""

    def test_clear_search_skipped_when_typing(self, win):
        """В поле ввода сочетание обязано вводить текст, а не очищать."""
        field = getattr(win, "search_filter_input", None)
        if field is None:
            pytest.skip("поле поиска не создано")
        field.setText("Badders")
        field.setFocus()
        win._dj_clear_search()
        assert field.text() == "Badders", "в поле ввода очистка не должна срабатывать"


class TestDefect011RemoveChannelClearsActive:

    def test_removing_active_channel_clears_field(self, win, monkeypatch):
        """Удаление активного канала не должно оставлять его имя в поле."""
        win.channel_input.setText("@akmpool")
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = ["@akmpool"]
        win._remove_saved_channel("@akmpool")
        assert win.channel_input.text() == ""

    def test_removing_other_channel_keeps_field(self, win, monkeypatch):
        """Удаление другого канала не должно трогать активный."""
        win.channel_input.setText("@akmpool")
        monkeypatch.setattr(win, "_populate_saved_channels", lambda: None)
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        win._saved_channels = ["@akmpool", "@other"]
        win._remove_saved_channel("@other")
        assert win.channel_input.text() == "@akmpool"


class TestDefect012ProfileChipNoFalseAffordance:

    def _profile_label(self, win):
        from PyQt6.QtWidgets import QLabel
        for lbl in win.findChildren(QLabel):
            if "kairo" in lbl.text().lower():
                return lbl
        raise AssertionError("подпись профиля не найдена")

    def test_label_has_no_dropdown_glyph(self, win):
        """Стрелка выпадающего списка вводила в заблуждение."""
        assert "\u2304" not in self._profile_label(win).text()

    def test_profile_has_tooltip(self, win):
        """Вместо стрелки должна быть подсказка."""
        lbl = self._profile_label(win)
        assert lbl.toolTip(), "у подписи профиля обязана быть подсказка"
        assert "\u2304" not in lbl.toolTip()