"""Тесты на разбор метаданных: тональность, BPM, шаблон имени файла.

Именно эти функции решают, попадёт ли трек в подборку DJ по гармонии и
темпу. Цена ошибки несимметрична: неверно прочитанный BPM отправляет
трек не в тот фильтр, поэтому проверяются не только удачные случаи, но и
границы диапазона и отказ от лишних цифр в названии.
"""

import os

import pytest

from media_utils import (extract_bpm_meta, extract_key_meta,
                         format_export_path, message_in_date_range,
                         is_older_than_from)


class TestExtractKeyCamelot:
    """Готовые коды Camelot в названии."""

    @pytest.mark.parametrize("code", ["8A", "8B", "1A", "12B", "5B"])
    def test_plain_camelot(self, code):
        assert extract_key_meta(f"Track [{code}]", "") == code

    def test_camelot_in_round_brackets(self):
        assert extract_key_meta("Track (9A)", "") == "9A"

    def test_camelot_uppercase_is_normalised(self):
        assert extract_key_meta("Track [8a]", "") == "8A"

    def test_nothing_found(self):
        assert extract_key_meta("GAZ", "Zivert") == "—"

    def test_number_in_brackets_is_not_a_key(self):
        """Номер трека в квадратных скобках -- не тональность."""
        assert extract_key_meta("Track [12]", "") == "—"


class TestExtractKeyMusical:
    """Обозначения нот переводятся в Camelot."""

    def test_minor_note_in_brackets(self):
        """Ля минор в нотации Camelot -- 8A."""
        assert extract_key_meta("Track [Am]", "") == "8A"

    def test_minor_note_with_spaces(self):
        assert extract_key_meta("Track [A minor]", "") == "8A"

    def test_minor_note_in_word(self):
        assert extract_key_meta("Am - Some Track", "") == "8A"

    def test_minor_abbreviation(self):
        assert extract_key_meta("Cm Journey", "") == "5A"

    def test_no_key_returns_dash(self):
        assert extract_key_meta("GAZ", "Zivert") == "—"

    def test_empty_input(self):
        assert extract_key_meta("", "") == "—"


class TestExtractBpm:
    """Извлечение темпа из названия."""

    def test_bpm_suffix(self):
        assert extract_bpm_meta("Track 128 BPM") == "128"

    def test_bpm_lowercase(self):
        assert extract_bpm_meta("Track 128 bpm") == "128"

    def test_russian_abbreviation(self):
        assert extract_bpm_meta("Track 140 БПМ") == "140"

    def test_bpm_in_brackets(self):
        assert extract_bpm_meta("Track [128]") == "128"

    def test_bpm_in_brackets_with_suffix(self):
        assert extract_bpm_meta("Track [128 BPM]") == "128"

    def test_bpm_in_round_brackets(self):
        assert extract_bpm_meta("Track (126 BPM)") == "126"

    def test_bpm_in_artist_field(self):
        """Темп часто пишут в имени исполнителя."""
        assert extract_bpm_meta("Track", "Zivert 124 BPM") == "124"

    def test_prefixed_number(self):
        assert extract_bpm_meta("128 - Track Name") == "128"

    def test_no_bpm(self):
        assert extract_bpm_meta("GAZ", "Zivert") == "—"

    def test_out_of_range_ignored(self):
        """300 BPM -- опечатка, а не темп: принять его нельзя."""
        assert extract_bpm_meta("Track 300 BPM") == "—"

    def test_too_low_ignored(self):
        assert extract_bpm_meta("Track 30 BPM") == "—"

    @pytest.mark.parametrize("value", ["60", "219"])
    def test_range_edges_are_accepted(self, value):
        assert extract_bpm_meta(f"Track {value} BPM") == value

    def test_220_is_out_of_supported_range(self):
        """Регулярка намеренно ограничивает диапазон 219 темпами."""
        assert extract_bpm_meta("Track 220 BPM") == "—"

    def test_year_is_not_a_tempo(self):
        """Год в названии не должен становиться темпом."""
        assert extract_bpm_meta("Live 2019", "") == "—"

    def test_empty_inputs(self):
        assert extract_bpm_meta("", "") == "—"


class TestDateHelpers:
    """Фильтрация по диапазону дат."""

    class _Msg:
        def __init__(self, date):
            self.date = date

    def test_inside_range(self):
        import datetime

        msg = self._Msg(datetime.datetime(2026, 1, 15))
        assert message_in_date_range(
            msg, datetime.datetime(2026, 1, 1),
            datetime.datetime(2026, 2, 1)) is True

    def test_before_range(self):
        import datetime

        msg = self._Msg(datetime.datetime(2025, 12, 31))
        assert message_in_date_range(
            msg, datetime.datetime(2026, 1, 1),
            datetime.datetime(2026, 2, 1)) is False

    def test_after_range(self):
        import datetime

        msg = self._Msg(datetime.datetime(2026, 3, 1))
        assert message_in_date_range(
            msg, datetime.datetime(2026, 1, 1),
            datetime.datetime(2026, 2, 1)) is False

    def test_message_without_date_is_skipped(self):
        """Сообщение без даты не должно обрывать сканирование."""
        import datetime

        assert message_in_date_range(
            self._Msg(None), datetime.datetime(2026, 1, 1),
            datetime.datetime(2026, 2, 1)) is False

    def test_no_bounds_accepts_everything(self):
        """Без заданных границ фильтр не отсеивает ничего."""
        assert message_in_date_range(self._Msg(None), None, None) is True

    def test_older_than_start(self):
        import datetime

        assert is_older_than_from(
            self._Msg(datetime.datetime(2025, 1, 1)),
            datetime.datetime(2026, 1, 1)) is True
        assert is_older_than_from(
            self._Msg(datetime.datetime(2026, 1, 2)),
            datetime.datetime(2026, 1, 1)) is False

    def test_older_without_date_is_skipped(self):
        assert is_older_than_from(self._Msg(None), None) is False


class TestFormatExportPath:
    """Построение пути по шаблону."""

    def test_default_pattern(self, tmp_path):
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path), pattern="{date}/{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="128")
        assert path.replace("\\", "/").endswith("2026-04-04/Zivert - GAZ.mp3")

    def test_missing_pattern_falls_back_to_default(self, tmp_path):
        """Пустой шаблон из настроек не должен ломать экспорт."""
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path), pattern="",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="—")
        assert path.endswith(".mp3")

    def test_default_pattern_survives_unknown_bpm(self, tmp_path):
        """Шаблон по умолчанию вообще не содержит {bpm}.

        Наблюдение: если пользователь добавит {bpm} в свой шаблон, то при
        неизвестном темпе в имени останутся пустые скобки -- ``GAZ ().mp3``.
        Проверяется именно штатный путь, чтобы регрессия шаблона была
        видна.
        """
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path),
            pattern="{date}/{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="—")
        name = os.path.basename(path)
        assert name == "Zivert - GAZ.mp3"
        assert "(" not in name

    def test_result_stays_inside_base_folder(self, tmp_path):
        """Шаблон не должен уводить запись за пределы папки приложения."""
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path), pattern="{title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="—")
        assert os.path.abspath(path).startswith(os.path.abspath(str(tmp_path)))

    def test_unsafe_characters_are_removed(self, tmp_path):
        """Слеши и двоеточия в названии ломают путь -- они заменяются."""
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path), pattern="{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="AC/DC", title="Track: Live", bpm="—")
        name = os.path.basename(path)
        assert "/" not in name
        assert ":" not in name
        assert name.endswith(".mp3")

    def test_result_is_writable(self, tmp_path):
        """Сгенерированное имя должно реально создаваться на диске."""
        import datetime

        path = format_export_path(
            base_folder=str(tmp_path), pattern="{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="AC/DC", title="Track: Live", bpm="—")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x00")
        assert os.path.exists(path)

    def test_same_name_is_left_as_is(self, tmp_path):
        """Шаблон не добавляет суффикс: защита от перезаписи выше по коду.

        Проверяется, чтобы формат имени оставался предсказуемым: при
        одинаковых названиях файл перезаписывается, а не размножается.
        """
        import datetime

        first = format_export_path(
            base_folder=str(tmp_path), pattern="{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="—")
        os.makedirs(os.path.dirname(first), exist_ok=True)
        with open(first, "wb") as fh:
            fh.write(b"\x00")

        second = format_export_path(
            base_folder=str(tmp_path), pattern="{artist} - {title}.mp3",
            date_val=datetime.datetime(2026, 4, 4), channel="@chan",
            artist="Zivert", title="GAZ", bpm="—")
        assert second == first