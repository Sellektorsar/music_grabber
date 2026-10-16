"""Тесты на карточку трека Bento Studio.

Карточка -- место, где DJ правит теги перед тем, как файл уедет в
плеер. Отсюда три обязательства:

* очистка промо-тегов и скобок должна работать по кнопке и обновлять
  и поля, и подписи;
* сохранение обязано обновлять и файл, и запись в базе;
* любая ошибка записи не должна ни ронять карточку, ни оставлять
  подписи в неправдоподобном виде.

Алиасы ``inspect_track`` и ``save_id3`` существуют для совместимости со
старым кодом Bento Grid, поэтому их поведение тоже зафиксировано.

Подменяется ``audio_converter.write_id3_tags``: карточка находит функцию
записи через getattr именно там, поэтому подмена имени в самом модуле
карточки ничего бы не дала.
"""

import contextlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def card(qtbot, tmp_path):
    from ui.bento_widgets import TrackInspectorCard

    widget = TrackInspectorCard()
    qtbot.addWidget(widget)
    widget._current_track = {
        "id": 1, "title": "GAZ", "performer": "Zivert",
        "filename": "Zivert - GAZ.mp3",
        # карточка читает путь из file_path/path, а не из filepath
        "file_path": str(tmp_path / "t.mp3"),
        "duration": 240, "file_size": 9_000_000, "bpm": "128", "key": "8A",
    }
    (tmp_path / "t.mp3").write_bytes(b"\x00" * 2048)
    return widget


@contextlib.contextmanager
def _id3_writer(**kw):
    """Подменяет функцию записи тегов.

    Карточка берёт ``write_id3_metadata`` через getattr, если он есть,
    и только потом ``write_id3_tags``. Подменять нужно оба имени,
    иначе результат зависит от того, создал ли псевдоним какой-то другой
    тест, -- а именно это и делало проверку нестабильной.
    """
    mock = MagicMock(**kw)
    with patch("audio_converter.write_id3_metadata", mock), \
            patch("audio_converter.write_id3_tags", mock):
        yield mock


class TestCleanPromo:
    """Кнопка очистки промо-тегов."""

    def test_channel_links_are_removed(self, card):
        card.edit_title.setText("GAZ - t.me/kutsuevpool")
        card.edit_artist.setText("@TechnoPulse")
        card.clean_promo()
        assert "t.me" not in card.edit_title.text()
        assert "@TechnoPulse" not in card.edit_artist.text()

    def test_promo_brackets_are_removed(self, card):
        card.edit_title.setText("GAZ [320 kbps]")
        card.clean_promo()
        assert "320" not in card.edit_title.text()
        assert card.edit_title.text() == "GAZ"

    def test_meaningful_brackets_are_kept(self, card):
        """«DJ Edit» -- часть названия, а не рекламный мусор."""
        card.edit_title.setText("GAZ (DJ Edit)")
        card.clean_promo()
        assert card.edit_title.text() == "GAZ (DJ Edit)"

    def test_fields_and_labels_stay_in_sync(self, card):
        """Подпись обязана совпадать с тем, что лежит в поле ввода."""
        card.edit_title.setText("GAZ [320 kbps]")
        card.edit_artist.setText("Zivert")
        card.clean_promo()
        assert card.lbl_title.text() == card.edit_title.text()
        assert card.lbl_artist.text() == card.edit_artist.text()

    def test_empty_fields_get_placeholders(self, card):
        card.edit_title.setText("")
        card.edit_artist.setText("")
        card.clean_promo()
        assert card.lbl_title.text() == "Unknown Title"
        assert card.lbl_artist.text() == "Unknown Artist"

    def test_plain_title_is_preserved(self, card):
        card.edit_title.setText("GAZ")
        card.edit_artist.setText("Zivert")
        card.clean_promo()
        assert card.edit_title.text() == "GAZ"
        assert card.edit_artist.text() == "Zivert"


class TestSaveTags:
    """Сохранение отредактированных тегов."""

    def test_tags_are_written_to_file(self, card):
        card.edit_title.setText("Новое название")
        card.edit_artist.setText("Новый артист")
        with _id3_writer() as writer:
            card.save_tags()
        writer.assert_called_once()
        assert writer.call_args.kwargs["title"] == "Новое название"
        assert writer.call_args.kwargs["artist"] == "Новый артист"

    def test_labels_show_saved_values(self, card):
        card.edit_title.setText("Новое название")
        card.edit_artist.setText("Новый артист")
        with _id3_writer():
            card.save_tags()
        assert card.lbl_title.text() == "Новое название"
        assert card.lbl_artist.text() == "Новый артист"

    def test_empty_values_fall_back_to_placeholder(self, card):
        card.edit_title.setText("")
        card.edit_artist.setText("")
        with _id3_writer():
            card.save_tags()
        assert card.lbl_title.text() == "Unknown Title"

    def test_signal_is_emitted(self, card):
        """Bento Grid слушает этот сигнал, чтобы обновить таблицу."""
        seen = []
        card.tags_saved.connect(lambda data: seen.append(data))
        with _id3_writer():
            card.save_tags()
        assert seen, "сигнал сохранения должен уходить подписчикам"

    def test_write_failure_does_not_break_card(self, card):
        """Ошибка записи тегов не должна ронять интерфейс."""
        card.edit_title.setText("Название")
        card.edit_artist.setText("Артист")
        with _id3_writer(side_effect=PermissionError("файл занят")):
            card.save_tags()
        assert card.lbl_title.text() == "Название"


class TestSaveTagsDatabase:
    """Сохранение должно попадать и в базу, но только для известных треков."""

    def test_database_updated_for_known_track(self, card):
        card._current_track["channel_id"] = "akmpool"
        card._current_track["message_id"] = 42
        with _id3_writer(), patch("database.record_download") as record:
            card.save_tags()
        record.assert_called_once()
        kwargs = record.call_args.kwargs
        assert kwargs["channel_id"] == "akmpool"
        assert kwargs["message_id"] == 42

    def test_database_skipped_without_channel(self, card):
        """Трек без привязки к каналу в базе не появляется."""
        card._current_track.pop("channel_id", None)
        card._current_track["message_id"] = 42
        with _id3_writer(), patch("database.record_download") as record:
            card.save_tags()
        record.assert_not_called()

    def test_database_failure_does_not_break_save(self, card):
        card._current_track["channel_id"] = "akmpool"
        card._current_track["message_id"] = 42
        card.edit_title.setText("Название")
        with _id3_writer(), \
                patch("database.record_download", side_effect=RuntimeError("БД")):
            card.save_tags()
        assert card.lbl_title.text() == "Название"


class TestCompatibilityAliases:
    """Алиасы для Bento Grid Studio."""

    def test_inspect_track_delegates_to_display(self, card):
        card.display_track = MagicMock()
        card.inspect_track({"title": "GAZ"})
        card.display_track.assert_called_once_with({"title": "GAZ"})

    def test_inspect_track_accepts_none(self, card):
        card.display_track = MagicMock()
        card.inspect_track(None)
        card.display_track.assert_called_once_with(None)

    def test_save_id3_delegates_to_save_tags(self, card):
        card.save_tags = MagicMock(return_value={"title": "GAZ"})
        assert card.save_id3() == {"title": "GAZ"}
        card.save_tags.assert_called_once()