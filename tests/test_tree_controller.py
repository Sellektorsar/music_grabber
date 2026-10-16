"""Тесты логики дерева библиотеки (`ui/controllers/tree_controller.py`).

Модуль держался на 76 %. Непроверенными оставались самые значимые
места: двойной клик по строке и группе, вычисление статуса SAVED/QUEUED,
подгрузка треков при прокрутке и восстановление состояния дерева.
Именно эти функции отвечают за правдивость интерфейса, поэтому тесты
заточены именно на них.
"""

import os
from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTreeWidgetItem


@pytest.fixture
def win(qtbot, monkeypatch, tmp_path):
    """Окно приложения, изолированное во временном каталоге."""
    from PyQt6.QtWidgets import QMessageBox

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


def make_track(mid, filepath="", title="T", performer="P", channel="@akmpool"):
    return {"id": mid, "msg_id": mid, "title": title, "performer": performer,
            "channel": channel, "filepath": filepath, "status": "ready"}


def add_track_item(tree, track, parent=None, checked=False):
    """Создаёт строку трека в ожидаемом контроллером виде."""
    item = QTreeWidgetItem([track["title"]])
    item.setData(0, Qt.ItemDataRole.UserRole, track["id"])
    item.setData(1, Qt.ItemDataRole.UserRole, track)
    if parent is None:
        tree.addTopLevelItem(item)
    else:
        parent.addChild(item)
    if checked:
        item.setCheckState(0, Qt.CheckState.Checked)
    else:
        item.setCheckState(0, Qt.CheckState.Unchecked)
    return item


class TestDoubleClickOnTree:

    def test_group_click_toggles_expansion(self, win):
        """Клик по группе разворачивает и сворачивает её."""
        tree = win.library_tree
        tree.clear()
        group = QTreeWidgetItem(["@akmpool   (2 трека)"])
        tree.addTopLevelItem(group)
        add_track_item(tree, make_track(1), parent=group)
        add_track_item(tree, make_track(2), parent=group)

        group.setExpanded(False)
        win._on_tree_item_double_clicked(group, 0)
        assert group.isExpanded() is True

        win._on_tree_item_double_clicked(group, 0)
        assert group.isExpanded() is False

    def test_track_click_falls_back_to_search_results(self, win, monkeypatch):
        """Если в UserRole нет словаря, трек ищется в результатах сканирования."""
        tree = win.library_tree
        tree.clear()
        track = make_track(11, title="Raya", performer="Zericxxn")
        win._scan_results = [track]
        item = QTreeWidgetItem([track["title"]])
        item.setData(0, Qt.ItemDataRole.UserRole, 11)
        tree.addTopLevelItem(item)

        played = []
        monkeypatch.setattr(win, "play_audio_file",
                            lambda path, title=None: played.append((path, title)))
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)

        win._on_tree_item_double_clicked(item, 0)

        assert played == [], "трек без файла нельзя отдавать в плеер"
        assert "Raya" in win.player_title_label.text(), (
            "трек должен быть опознан по результатам сканирования"
        )

    def test_existing_file_opens_player(self, win, monkeypatch, tmp_path):
        """Файл на диске должен уйти в плеер с названием «исполнитель - трек»."""
        tree = win.library_tree
        tree.clear()
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"\x00" * 32)

        track = make_track(12, filepath=str(audio), title="Song", performer="Artist")
        item = add_track_item(tree, track)

        played = []
        monkeypatch.setattr(win, "play_audio_file",
                            lambda path, title=None: played.append((path, title)))
        monkeypatch.setattr(win, "log", lambda *a, **kw: None)
        # Убираем обработчик предпрослушивания, чтобы сработал запасной путь.

        win._on_tree_item_double_clicked(item, 0)

        assert played, "файл на диске обязан уйти в плеер"
        path, title = played[0]
        assert path == str(audio)
        assert title == "Artist - Song"

    def test_missing_file_shows_pending_message(self, win, monkeypatch, tmp_path):
        """Нет файла — плеер показывает, что трек ещё не скачан."""
        tree = win.library_tree
        tree.clear()
        track = make_track(13, filepath=str(tmp_path / "nope.mp3"),
                           title="Ghost", performer="Nobody")
        item = add_track_item(tree, track)

        played = []
        monkeypatch.setattr(win, "play_audio_file",
                            lambda *a, **kw: played.append(a))

        win._on_tree_item_double_clicked(item, 0)

        assert played == [], "отсутствующий файл нельзя отдавать в плеер"
        text = win.player_title_label.text()
        assert "не скачан" in text
        assert "Nobody - Ghost" in text


class TestTableStatuses:

    def _prepare(self, win, tracks):
        win._scan_results = tracks
        win._track_status_badges = {t["id"]: QLabel("QUEUED") for t in tracks}
        win.channel_input.setText("@akmpool")
        return win._track_status_badges

    def test_existing_file_becomes_saved(self, win, monkeypatch, tmp_path):
        """Файл на диске обязан давать статус SAVED."""
        audio = tmp_path / "have.mp3"
        audio.write_bytes(b"\x00" * 8)
        badges = self._prepare(win, [make_track(20, filepath=str(audio))])

        win._refresh_table_statuses()

        assert badges[20].text() == "SAVED"

    def test_missing_file_stays_queued(self, win, monkeypatch, tmp_path):
        """Нет файла — статус QUEUED, ложного SAVED быть не должно."""
        badges = self._prepare(
            win, [make_track(21, filepath=str(tmp_path / "no.mp3"))])
        monkeypatch.setattr("database.is_downloaded", lambda *a, **kw: False)

        win._refresh_table_statuses()

        assert badges[21].text() != "SAVED"

    def test_no_scan_results_is_noop(self, win):
        """Без результатов сканирования обновление не должно ничего трогать."""
        win._scan_results = []
        win._track_status_badges = {}
        win._refresh_table_statuses()   # не должно бросать

    def test_empty_filepath_is_not_saved(self, win, monkeypatch):
        """Пустой путь не считается скачанным."""
        badges = self._prepare(win, [make_track(22, filepath="")])
        monkeypatch.setattr("database.is_downloaded", lambda *a, **kw: False)

        win._refresh_table_statuses()

        assert badges[22].text() != "SAVED"


class TestLazyLoadingOnScroll:

    def test_load_more_triggered_near_bottom(self, win, monkeypatch):
        """Докрутка до конца обязана подгружать следующую порцию."""
        bar = win.library_tree.verticalScrollBar()
        monkeypatch.setattr(bar, "maximum", lambda: 1000)
        called = []
        monkeypatch.setattr(win, "_load_more_tracks", lambda: called.append(1))

        win._on_tree_scroll(800)
        assert called, "близко к низу должна идти подгрузка"

    def test_no_load_more_at_top(self, win, monkeypatch):
        """В начале списка подгрузка не запускается."""
        bar = win.library_tree.verticalScrollBar()
        monkeypatch.setattr(bar, "maximum", lambda: 1000)
        called = []
        monkeypatch.setattr(win, "_load_more_tracks", lambda: called.append(1))

        win._on_tree_scroll(10)
        assert called == []

    def test_no_load_more_when_list_short(self, win, monkeypatch):
        """Короткий список прокручивать нечего."""
        bar = win.library_tree.verticalScrollBar()
        monkeypatch.setattr(bar, "maximum", lambda: 0)
        called = []
        monkeypatch.setattr(win, "_load_more_tracks", lambda: called.append(1))

        win._on_tree_scroll(0)
        assert called == []


class TestCheckedTracksFromMirror:

    """Сборщик `get_checked_tracks` читает скрытое зеркало `track_list`.

    Это не путь загрузки (его обходит `start_download`), но зеркало
    должно оставаться в согласованном состоянии, иначе расходятся
    счётчики.
    """

    def test_mirror_yields_checked_tracks(self, win):
        from PyQt6.QtWidgets import QListWidgetItem

        win._track_by_id = {30: make_track(30), 31: make_track(31)}
        win.track_list.clear()

        a = QListWidgetItem("a")
        a.setData(Qt.ItemDataRole.UserRole, 30)
        a.setCheckState(Qt.CheckState.Checked)
        b = QListWidgetItem("b")
        b.setData(Qt.ItemDataRole.UserRole, 31)
        b.setCheckState(Qt.CheckState.Unchecked)
        win.track_list.addItem(a)
        win.track_list.addItem(b)

        got = win.get_checked_tracks()
        assert [t["id"] for t in got] == [30]

    def test_unknown_id_is_skipped(self, win):
        from PyQt6.QtWidgets import QListWidgetItem

        win._track_by_id = {}
        win.track_list.clear()
        ghost = QListWidgetItem("ghost")
        ghost.setData(Qt.ItemDataRole.UserRole, 999)
        ghost.setCheckState(Qt.CheckState.Checked)
        win.track_list.addItem(ghost)

        assert win.get_checked_tracks() == []

    def test_empty_mirror_returns_empty_list(self, win):
        win._track_by_id = {}
        win.track_list.clear()
        assert win.get_checked_tracks() == []


class TestSearchFiltering:

    """Фильтр прячет элементы в скрытом зеркале `track_list` и в дереве."""

    def _prepare(self, win, tracks):
        from PyQt6.QtWidgets import QListWidgetItem

        win.library_tree.clear()
        win.track_list.clear()
        win._track_by_id = {t["id"]: t for t in tracks}
        win._scan_results = tracks

        group = QTreeWidgetItem(["@akmpool   (%d треков)" % len(tracks)])
        win.library_tree.addTopLevelItem(group)
        for t in tracks:
            it = QListWidgetItem(t["title"])
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            win.track_list.addItem(it)
            add_track_item(win.library_tree, t, parent=group)
        return group

    def _hidden_titles(self, win):
        return [win.track_list.item(i).text()
                for i in range(win.track_list.count())
                if win.track_list.item(i).isHidden()]

    def test_filter_hides_non_matching(self, win):
        """Поиск обязан оставить только совпадения."""
        self._prepare(win, [
            make_track(50, title="Raya", performer="Zericxxn"),
            make_track(51, title="GAZ", performer="Zivert"),
        ])
        win._filter_tracks_text("raya")
        hidden = self._hidden_titles(win)
        assert hidden == ["GAZ"]

    def test_empty_query_hides_nothing(self, win):
        """Пустой запрос обязан вернуть все треки."""
        self._prepare(win, [
            make_track(52, title="Raya"),
            make_track(53, title="GAZ"),
        ])
        win._filter_tracks_text("raya")
        win._filter_tracks_text("")
        assert self._hidden_titles(win) == []

    def test_both_search_fields_stay_in_sync(self, win):
        """Оба поля поиска обязаны показывать одинаковый текст."""
        win._filter_tracks_text("zivert")
        assert win.search_filter_input.text() == "zivert"
        assert win.top_search_input.text() == "zivert"

    def test_no_match_hides_everything(self, win):
        """Запрос без совпадений не должен оставлять видимых треков."""
        self._prepare(win, [make_track(54, title="Raya")])
        win._filter_tracks_text("нет-такого")
        assert self._hidden_titles(win) == ["Raya"]
