"""
Unit tests for Bento Grid Studio widgets (CamelotWheelWidget and TrackInspectorCard).
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QColor, QImage
from PyQt6.QtWidgets import QWidget

import audio_converter
from ui.bento_widgets import (
    CamelotWheelWidget,
    TrackInspectorCard,
    create_track_artwork_placeholder,
    MINOR_CAMELOT_KEYS,
    MAJOR_CAMELOT_KEYS,
    ALL_CAMELOT_KEYS,
)


def _create_sample_image_bytes() -> bytes:
    """Создает валидные байты PNG изображения для тестирования обложки."""
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(QColor("#00E5FF"))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba.data())


class TestCamelotWheelWidget:
    """Тесты интерактивного Camelot-колеса и расчета гармонических ключей."""

    def test_init_and_button_grid(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        assert wheel.selected_key() is None
        assert len(wheel._buttons) == 24

        for k in MINOR_CAMELOT_KEYS:
            assert k in wheel._buttons
            assert wheel._buttons[k].text() == k

        for k in MAJOR_CAMELOT_KEYS:
            assert k in wheel._buttons
            assert wheel._buttons[k].text() == k

        assert wheel.btn_reset is not None
        assert "RESET" in wheel.btn_reset.text()

    def test_harmonic_calculations_standard(self):
        """Проверка стандартных гармонических переходов (Same opp, +1, -1)."""
        # 8A Minor (A-Minor)
        matches_8a = CamelotWheelWidget.get_compatible_keys("8A")
        assert len(matches_8a) == 3
        # Opposite letter same number: 8B
        assert "8B" in matches_8a
        # +1 same letter: 9A
        assert "9A" in matches_8a
        # -1 same letter: 7A
        assert "7A" in matches_8a

        # 8B Major (C-Major)
        matches_8b = CamelotWheelWidget.get_compatible_keys("8B")
        assert len(matches_8b) == 3
        assert "8A" in matches_8b
        assert "9B" in matches_8b
        assert "7B" in matches_8b

    def test_harmonic_calculations_wraparound_high(self):
        """Проверка перехода через границу 12 -> 1."""
        # 12A Minor
        matches_12a = CamelotWheelWidget.get_compatible_keys("12A")
        assert len(matches_12a) == 3
        assert "12B" in matches_12a
        assert "1A" in matches_12a  # 12 + 1 wrapping to 1
        assert "11A" in matches_12a

        # 12B Major
        matches_12b = CamelotWheelWidget.get_compatible_keys("12B")
        assert len(matches_12b) == 3
        assert "12A" in matches_12b
        assert "1B" in matches_12b  # 12 + 1 wrapping to 1
        assert "11B" in matches_12b

    def test_harmonic_calculations_wraparound_low(self):
        """Проверка перехода через границу 1 -> 12."""
        # 1A Minor
        matches_1a = CamelotWheelWidget.get_compatible_keys("1A")
        assert len(matches_1a) == 3
        assert "1B" in matches_1a
        assert "2A" in matches_1a
        assert "12A" in matches_1a  # 1 - 1 wrapping to 12

        # 1B Major
        matches_1b = CamelotWheelWidget.get_compatible_keys("1B")
        assert len(matches_1b) == 3
        assert "1A" in matches_1b
        assert "2B" in matches_1b
        assert "12B" in matches_1b  # 1 - 1 wrapping to 12

    def test_harmonic_calculations_invalid(self):
        assert CamelotWheelWidget.get_compatible_keys("") == []
        assert CamelotWheelWidget.get_compatible_keys("XYZ") == []
        assert CamelotWheelWidget.get_compatible_keys("13A") == []
        assert CamelotWheelWidget.get_compatible_keys("0A") == []

    def test_key_selected_signal_and_highlight(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        with qtbot.waitSignal(wheel.key_selected, timeout=1000) as blocker:
            wheel._buttons["8A"].click()

        assert blocker.args == ["8A"]
        assert wheel.selected_key() == "8A"
        assert wheel._compatible_keys == {"8B", "9A", "7A"}

    def test_highlight_compatible_method(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        matches = wheel.highlight_compatible("5B")
        assert set(matches) == {"5A", "6B", "4B"}
        assert wheel.selected_key() == "5B"
        assert wheel._compatible_keys == {"5A", "6B", "4B"}

    def test_case_insensitivity(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        matches = wheel.highlight_compatible("  8a  ")
        assert set(matches) == {"8B", "9A", "7A"}
        assert wheel.selected_key() == "8A"

    def test_clear_selection_and_signal(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        wheel.highlight_compatible("8A")
        assert wheel.selected_key() == "8A"

        with qtbot.waitSignal(wheel.key_cleared, timeout=1000):
            wheel.clear_selection()

        assert wheel.selected_key() is None
        assert len(wheel._compatible_keys) == 0

    def test_reset_button_click(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        wheel.highlight_compatible("10A")
        assert wheel.selected_key() == "10A"

        with qtbot.waitSignal(wheel.key_cleared, timeout=1000):
            wheel.btn_reset.click()

        assert wheel.selected_key() is None

    def test_highlight_invalid_clears(self, qtbot):
        wheel = CamelotWheelWidget()
        qtbot.addWidget(wheel)

        wheel.highlight_compatible("8A")
        assert wheel.selected_key() == "8A"

        matches = wheel.highlight_compatible("UNKNOWN")
        assert matches == []
        assert wheel.selected_key() is None


class TestTrackInspectorCard:
    """Тесты карточки инспектора треков и редактирования ID3 тегов."""

    def test_init_ui(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        assert card.objectName() == "bentoCard"
        assert card.artwork_preview is not None
        assert card.artwork_preview.width() == 100
        assert card.artwork_preview.height() == 100

        assert card.edit_title is not None
        assert card.edit_artist is not None
        assert card.edit_album is not None
        assert card.edit_genre is not None
        assert card.edit_year is not None

        assert card.badge_key is not None
        assert card.badge_bpm is not None
        assert card.badge_bitrate is not None

        assert card.btn_save_tags is not None
        assert card.lbl_export_preview is not None

    def test_display_track_full_metadata(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        track_data = {
            "title": "Strobe",
            "artist": "deadmau5",
            "album": "For Lack of a Better Name",
            "genre": "Progressive House",
            "year": "2009",
            "bpm": "128",
            "key": "8A",
            "bitrate": "320 kbps",
            "channel": "Electronic Classics",
        }

        card.display_track(track_data)

        # Проверка полей ввода
        assert card.edit_title.text() == "Strobe"
        assert card.edit_artist.text() == "deadmau5"
        assert card.edit_album.text() == "For Lack of a Better Name"
        assert card.edit_genre.text() == "Progressive House"
        assert card.edit_year.text() == "2009"

        # Проверка заголовков
        assert card.lbl_title.text() == "Strobe"
        assert card.lbl_artist.text() == "deadmau5"

        # Проверка бейджей
        assert card.badge_key.text() == "8A"
        assert card.badge_bpm.text() == "128 BPM"
        assert card.badge_bitrate.text() == "320 kbps"

        # Проверка шаблона экспорта
        assert card.lbl_export_preview.text() == "Electronic Classics/deadmau5 - Strobe.mp3"

    def test_display_track_metadata_auto_extraction(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        # BPM и тональность зашиты в название трека
        track_data = {
            "title": "Deep Vibe [124 bpm] [6A]",
            "artist": "DJ Kairos",
            "channel": "DeepHousePool",
        }

        card.display_track(track_data)

        assert card.badge_bpm.text() == "124 BPM"
        assert card.badge_key.text() == "6A"
        assert card.lbl_export_preview.text() == "DeepHousePool/DJ Kairos - Deep Vibe [124 bpm] [6A].mp3"

    def test_display_track_with_artwork(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        art_bytes = _create_sample_image_bytes()
        track_data = {
            "title": "Neon Lights",
            "artist": "Kraftwerk",
            "artwork_bytes": art_bytes,
        }

        card.display_track(track_data)

        pix = card.artwork_preview.pixmap()
        assert pix is not None
        assert not pix.isNull()

    def test_export_template_dynamic_updating(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        track_data = {
            "title": "Around The World",
            "artist": "Daft Punk",
            "channel": "FrenchTouch",
        }
        card.display_track(track_data)
        assert card.lbl_export_preview.text() == "FrenchTouch/Daft Punk - Around The World.mp3"

        # Изменение названия в поле ввода
        card.edit_title.setText("One More Time")
        assert card.lbl_export_preview.text() == "FrenchTouch/Daft Punk - One More Time.mp3"

        # Изменение исполнителя в поле ввода
        card.edit_artist.setText("Stardust")
        assert card.lbl_export_preview.text() == "FrenchTouch/Stardust - One More Time.mp3"

    def test_save_tags_signal_and_persistence(self, qtbot, tmp_path):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        # Создаем временный файл
        dummy_file = tmp_path / "test_track.mp3"
        dummy_file.write_bytes(b"ID3dummydata")

        track_data = {
            "title": "Original Title",
            "artist": "Original Artist",
            "file_path": str(dummy_file),
            "channel_id": "channel_101",
            "message_id": 42,
        }
        card.display_track(track_data)

        # Редактируем поля
        card.edit_title.setText("Updated Title")
        card.edit_artist.setText("Updated Artist")
        card.edit_genre.setText("Techno")
        card.edit_year.setText("2026")

        mock_write = MagicMock(return_value=True)
        mock_record_db = MagicMock(return_value=True)

        with patch("audio_converter.write_id3_metadata", mock_write):
            with patch("database.record_download", mock_record_db):
                with qtbot.waitSignal(card.tags_saved, timeout=1000) as blocker:
                    card.btn_save_tags.click()

        saved_data = blocker.args[0]
        assert saved_data["title"] == "Updated Title"
        assert saved_data["artist"] == "Updated Artist"
        assert saved_data["genre"] == "Techno"
        assert saved_data["year"] == "2026"

        # Проверяем вызов write_id3_metadata
        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args
        assert kwargs["title"] == "Updated Title"
        assert kwargs["artist"] == "Updated Artist"
        assert kwargs["genre"] == "Techno"
        assert kwargs["year"] == "2026"
        assert kwargs["filepath"] == str(dummy_file)

        # Проверяем вызов БД
        mock_record_db.assert_called_once()
        _, db_kwargs = mock_record_db.call_args
        assert db_kwargs["channel_id"] == "channel_101"
        assert db_kwargs["message_id"] == 42
        assert db_kwargs["title"] == "Updated Title"
        assert db_kwargs["artist"] == "Updated Artist"

    def test_display_empty_track_graceful(self, qtbot):
        card = TrackInspectorCard()
        qtbot.addWidget(card)

        card.display_track(None)
        assert card.edit_title.text() == ""
        assert card.badge_key.text() == "—"
        assert card.badge_bpm.text() == "— BPM"

        card.display_track({})
        assert card.edit_title.text() == ""


def test_create_track_artwork_placeholder(qtbot):
    pix = create_track_artwork_placeholder(100)
    assert not pix.isNull()
    assert pix.width() == 100
    assert pix.height() == 100


class TestReadId3Metadata:
    """Проверка псевдонима read_id3_metadata и обработки граничных случаев."""

    def test_alias_symmetry_and_callable(self):
        assert hasattr(audio_converter, "read_id3_metadata")
        assert audio_converter.read_id3_metadata is audio_converter.read_id3_tags
        assert hasattr(audio_converter, "write_id3_metadata")
        assert audio_converter.write_id3_metadata is audio_converter.write_id3_tags

    def test_read_id3_metadata_valid_audio(self, tmp_path):
        from pydub.generators import Sine
        test_file = str(tmp_path / "valid_sample.mp3")
        tone = Sine(440).to_audio_segment(duration=50)
        tone.export(test_file, format="mp3")

        audio_converter.write_id3_metadata(
            test_file,
            title="Final Gate Title",
            artist="Final Gate Artist",
            album="Gate Album",
            genre="Trance",
            year="2026",
            key="8A",
            bpm=128,
        )

        meta = audio_converter.read_id3_metadata(test_file)
        assert meta.get("title") == "Final Gate Title"
        assert meta.get("artist") == "Final Gate Artist"
        assert meta.get("album") == "Gate Album"
        assert meta.get("genre") == "Trance"
        assert meta.get("year") == "2026"
        assert meta.get("key") == "8A"
        assert meta.get("bpm") == "128"

    def test_read_id3_metadata_missing_file(self, tmp_path):
        missing = str(tmp_path / "non_existent_file.mp3")
        res = audio_converter.read_id3_metadata(missing)
        assert res == {}

    def test_read_id3_metadata_corrupted_file(self, tmp_path):
        corrupted = str(tmp_path / "corrupted_file.mp3")
        with open(corrupted, "wb") as f:
            f.write(b"NOT_A_VALID_MP3_OR_ID3_HEADER_TRASH_BYTES_12345")
        res = audio_converter.read_id3_metadata(corrupted)
        assert res == {}
