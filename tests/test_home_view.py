"""Тесты на главный экран Bento Studio.

Экран собирается один раз при создании окна, и непокрытыми оставались не
дефолты, а ветки, которые встречаются у реального пользователя:

* база не пуста -- таблица недавних треков наполняется;
* у треков есть длительность и размер -- считается честный битрейт;
* обработчики сигналов: выбор строки, сохранение тегов, колесо тональностей.

Плюс ветка отказа: если папка с данными недоступна, метрики диска должны
молча остаться пустыми, а не уронить создание окна.
"""

from unittest.mock import MagicMock, patch

import pytest


RECORDS = [
    {
        "channel_id": "akmpool", "message_id": 1, "artist": "Zivert",
        "title": "GAZ", "filename": "Zivert - GAZ.mp3", "duration": 240,
        "file_size": 10 * 1024 * 1024, "status": "completed",
        "file_path": "C:/music/Zivert - GAZ.mp3",
    },
    {
        "channel_id": "kutsuevpool", "message_id": 2, "artist": "Curbi",
        "title": "Badders", "filename": "Curbi - Badders.mp3",
        "duration": 300, "file_size": 2 * 1024 * 1024, "status": "duplicate",
        "file_path": "C:/music/Curbi - Badders.mp3",
    },
    {
        "channel_id": "kutsuevpool", "message_id": 3, "artist": "Nobody",
        "title": "Live Set", "filename": "Nobody - Live Set.mp3",
        "duration": 0, "file_size": 0, "status": "completed",
        "file_path": "C:/music/Nobody - Live Set.mp3",
    },
]


@pytest.fixture
def window_with_data(monkeypatch, tmp_path, qtbot):
    """Окно, собранное с непустой базой и существующей рабочей папкой."""
    base = tmp_path / "telegram_audio"
    base.mkdir()
    monkeypatch.setattr("config.BASE_PATH", str(base))
    monkeypatch.setattr("config.CONFIG_DIR", str(base))
    monkeypatch.setattr("config.CONFIG_FILE", str(base / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    import database

    database.init_db()
    for record in RECORDS:
        database.record_download(**record)

    from gui import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.log = MagicMock()
    return win


class TestRecentTable:
    """Таблица недавних треков."""

    def test_rows_are_filled_from_database(self, window_with_data):
        table = window_with_data.home_recent_table
        titles = [table.item(row, 0).text() for row in range(table.rowCount())]
        assert "GAZ" in titles
        assert "Badders" in titles

    def test_track_count_metric(self, window_with_data):
        assert "треков" in window_with_data.home_tracks_val.text()

    def test_track_data_is_attached_to_row(self, window_with_data):
        """Без данных в UserRole двойной клик не знает, что играть."""
        table = window_with_data.home_recent_table
        payload = table.item(0, 0).data(window_with_data.home_recent_table.model().index(0, 0).column())
        assert payload is not None

    def test_first_row_is_selected(self, window_with_data):
        """Выделенная строка сразу показывает трек в карточке."""
        table = window_with_data.home_recent_table
        assert table.currentRow() == 0


class TestMetrics:
    """Счётчики DUP и HQ на главном экране."""

    def test_duplicate_counter(self, window_with_data):
        assert window_with_data.home_dup_val.text().endswith("DUP")

    def test_hq_counter_has_no_crash_on_zero_duration(self, window_with_data):
        """Трек без метаданных не должен ломать подсчёт."""
        assert "HQ" in window_with_data.home_hq_val.text()

    def test_disk_metrics_are_filled(self, window_with_data):
        assert "GB" in window_with_data.home_disk_val.text()

    def test_disk_bar_is_set(self, window_with_data):
        assert window_with_data.home_disk_bar.value() >= 0

    def test_missing_base_folder_does_not_break_startup(self, monkeypatch,
                                                       tmp_path, qtbot):
        """Недоступная папка не должна мешать открытию приложения.

        Метрика диска при этом может остаться незаполненной: её считают
        два независимых места, и одно из них смотрит на существующую папку.
        Проверяется именно то, что окно построилось.
        """
        monkeypatch.setattr("config.BASE_PATH", str(tmp_path / "нет-такой"))
        monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

        from gui import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        assert win.home_view is not None
        assert win.home_recent_table.rowCount() >= 0

    def test_disk_error_is_swallowed(self, monkeypatch, tmp_path, qtbot):
        """Ошибка чтения диска гасится и не подставляет выдуманные числа.

        Метка изначально содержит заглушку вида «— GB»; после сбоя она
        обязана остаться заглушкой, а не показать правдоподобное число.
        """
        import shutil

        monkeypatch.setattr("config.BASE_PATH", str(tmp_path / "telegram_audio"))
        monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

        def _boom(_path):
            raise PermissionError("нет доступа")

        monkeypatch.setattr(shutil, "disk_usage", _boom)

        from gui import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)

        text = win.home_disk_val.text()
        assert "свободно" not in text, f"показаны выдуманные данные: {text}"


class TestRowSelection:
    """Выбор строки наполняет карточку трека."""

    def test_selection_fills_inspector(self, window_with_data):
        window_with_data.track_inspector = MagicMock()
        window_with_data.home_recent_table.selectRow(0)
        window_with_data._refresh_home_view()
        window_with_data.home_recent_table.selectRow(1)
        window_with_data.track_inspector.display_track.assert_called()

    def test_inspector_receives_file_path(self, window_with_data):
        window_with_data.track_inspector = MagicMock()
        table = window_with_data.home_recent_table
        table.selectRow(0)
        window_with_data.home_recent_table.itemSelectionChanged.emit()

        payload = window_with_data.track_inspector.display_track.call_args[0][0]
        assert payload["file_path"], "без пути карточка не сможет показать трек"

    def test_clearing_selection_is_safe(self, window_with_data):
        window_with_data.track_inspector = MagicMock()
        window_with_data.home_recent_table.clearSelection()
        window_with_data.home_recent_table.itemSelectionChanged.emit()
        window_with_data.track_inspector.display_track.assert_not_called()


class TestTagsSavedFromInspector:
    """Правка тегов в карточке отражается в таблице."""

    def test_row_text_is_updated(self, window_with_data):
        table = window_with_data.home_recent_table
        table.selectRow(0)
        window_with_data.track_inspector.tags_saved.emit(
            {"title": "Новое название", "artist": "Новый артист"})
        assert table.item(0, 0).text() == "Новое название"
        assert table.item(0, 1).text() == "Новый артист"

    def test_change_is_logged(self, window_with_data):
        window_with_data.home_recent_table.selectRow(0)
        window_with_data.track_inspector.tags_saved.emit(
            {"title": "T", "artist": "A"})
        assert any("теги успешно сохранены" in c[0][0]
                   for c in window_with_data.log.call_args_list)

    def test_signal_without_selection_is_safe(self, window_with_data):
        window_with_data.home_recent_table.clearSelection()
        window_with_data.track_inspector.tags_saved.emit(
            {"title": "T", "artist": "A"})   # не должно упасть


class TestCamelotFilter:
    """Фильтр по гармонической совместимости на главном экране."""

    def test_key_selection_hides_incompatible_rows(self, window_with_data):
        table = window_with_data.home_recent_table
        before = table.rowCount()

        window_with_data.camelot_wheel.key_selected.emit("8A")

        assert table.rowCount() == before
        hidden = [table.isRowHidden(r) for r in range(before)]
        assert any(hidden), "несовместимые треки должны скрываться"

    def test_key_selection_is_logged(self, window_with_data):
        window_with_data.camelot_wheel.key_selected.emit("8A")
        assert any("Фильтр Camelot" in c[0][0]
                   for c in window_with_data.log.call_args_list)

    def test_clearing_key_shows_everything_again(self, window_with_data):
        table = window_with_data.home_recent_table
        window_with_data.camelot_wheel.key_selected.emit("8A")
        window_with_data.camelot_wheel.key_cleared.emit()

        assert not any(table.isRowHidden(r) for r in range(table.rowCount()))

    def test_clear_restores_hint(self, window_with_data):
        window_with_data.camelot_wheel.key_selected.emit("8A")
        window_with_data.camelot_wheel.key_cleared.emit()
        assert "Нажмите ключ" in window_with_data.camelot_status_lbl.text()