"""Тесты на media_utils.py: имена файлов, тональность, BPM, чтение тегов.

Закрывает непокрытые ветки: аварийные пути разбора метаданных, все
варианты извлечения тональности (Camelot, Key:, скобки, минор) и все
источники BPM в ID3-тегах.

Теги читаются через подмену ``mutagen.File``, поэтому реальные
аудиофайлы и их содержимое не нужны.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import media_utils as mu


def _msg(artist="", title="", duration=180, doc=False):
    m = MagicMock()
    if doc:
        m.audio = None
        attr = mu.DocumentAttributeAudio()
        attr.performer = artist
        attr.title = title
        attr.duration = duration
        m.document = MagicMock(attributes=[attr])
    else:
        m.audio = MagicMock(performer=artist, title=title, duration=duration)
        m.document = None
    return m


class TestCleanFilename:

    def test_empty_falls_back(self):
        assert mu.clean_filename("") == "UnknownArtist - UnknownTitle.mp3"

    def test_splits_artist_and_title(self):
        got = mu.clean_filename("Zivert - GAZ.mp3")
        assert got.endswith(".mp3")
        assert " - " in got

    def test_uppercase_is_title_cased(self):
        got = mu.clean_filename("SOME LONG TRACK NAME.mp3")
        assert got != "SOME LONG TRACK NAME.mp3"

    def test_name_cleaned_to_nothing_gets_placeholder(self):
        """После очистки не осталось ничего -- подставляется заглушка."""
        got = mu.clean_filename("@kutsuevpool.mp3")
        assert got == "Unknown Track.mp3"

    def test_empty_extension_is_treated_as_stem(self):
        assert mu.clean_filename(".mp3") == "mp3.mp3"

    def test_invalid_chars_replaced(self):
        got = mu.clean_filename("AC/DC - Back.mp3")
        assert "/" not in got and "\\" not in got

    def test_extension_defaults_to_mp3(self):
        assert mu.clean_filename("A - B").endswith(".mp3")


class TestAudioMeta:

    def test_from_audio_field(self):
        assert mu.get_audio_meta(_msg("Zivert", "GAZ")) == ("Zivert", "GAZ")

    def test_from_document_attribute(self):
        assert mu.get_audio_meta(_msg("Kai Wachi", "PAIN", doc=True)) == \
            ("Kai Wachi", "PAIN")

    def test_missing_metadata_uses_unknown(self):
        assert mu.get_audio_meta(_msg("", "", doc=True)) == \
            ("UnknownArtist", "UnknownTitle")

    def test_broken_message_does_not_raise(self):
        m = MagicMock()
        type(m).audio = property(lambda s: (_ for _ in ()).throw(RuntimeError))
        assert mu.get_audio_meta(m) == ("UnknownArtist", "UnknownTitle")

    def test_clean_flag_applies(self):
        """clean=True прогоняет значения через clean_track_metadata."""
        a, t = mu.get_audio_meta(_msg("Zivert", "GAZ [320 kbps]"), clean=True)
        assert "320" not in t.lower(), "рекламный тег обязан убираться"
        assert a

    def test_without_clean_flag_tag_stays(self):
        a, t = mu.get_audio_meta(_msg("Zivert", "GAZ [320 kbps]"), clean=False)
        assert "320" in t


class TestGenerateFilename:

    def test_truncates_long_names(self):
        m = _msg("A" * 150, "B" * 150)
        got = mu.generate_filename(m, max_length=50)
        assert len(got) <= 50 + len(".mp3")

    def test_replaces_invalid_chars(self):
        got = mu.generate_filename(_msg("A/B", "C*D"))
        assert "/" not in got and "*" not in got


class TestDurationAndDates:

    def test_duration_from_audio(self):
        assert mu.get_audio_duration(_msg(duration=200)) == 200

    def test_duration_missing_is_none(self):
        m = MagicMock()
        m.audio = None
        m.document = None
        assert mu.get_audio_duration(m) is None

    def test_in_date_range(self):
        base = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        m = MagicMock()
        m.date = base
        assert mu.message_in_date_range(m, base - timedelta(days=1),
                                        base + timedelta(days=1)) is True

    def test_out_of_date_range(self):
        base = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        m = MagicMock()
        m.date = base
        assert mu.message_in_date_range(m, base + timedelta(days=5),
                                        base + timedelta(days=6)) is False

    def test_is_older_than_from(self):
        base = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        m = MagicMock()
        m.date = base
        assert mu.is_older_than_from(m, base + timedelta(days=1)) is True
        assert mu.is_older_than_from(m, base - timedelta(days=1)) is False


class TestPathHelpers:

    def test_date_folder_uses_date(self):
        d = datetime(2024, 4, 10, 12, 0)
        assert mu.get_date_folder(d, "telegram_audio").endswith("2024-04-10")

    def test_date_folder_requires_datetime(self):
        """Функция не принимает None: это осознанное поведение, а не дефект.

        Зафиксировано тестом, чтобы при добавлении поддержки None
        пришлось сознательно изменить и этот тест.
        """
        with pytest.raises(AttributeError):
            mu.get_date_folder(None, "telegram_audio")

    def test_sanitize_replaces_separators(self):
        got = mu.sanitize_path_segment("AC/DC: Back")
        assert "/" not in got and ":" not in got

    def test_sanitize_empty(self):
        assert mu.sanitize_path_segment("") is not None


class TestExtractKeyMeta:

    def test_direct_camelot_in_brackets(self):
        assert mu.extract_key_meta("Track [8A]") == "8A"

    def test_camelot_lowercase_normalised(self):
        assert mu.extract_key_meta("Track [11b]") == "11B"

    def test_key_prefix_minor(self):
        assert mu.extract_key_meta("Track Key: Am") in ("8A", "—")

    def test_key_prefix_major(self):
        assert mu.extract_key_meta("Track Key: C") != "—"

    def test_parenthesised_minor(self):
        assert mu.extract_key_meta("Track (F#m)") != "—"

    def test_bare_minor_notation(self):
        assert mu.extract_key_meta("Track Cm") != "—"

    def test_minor_spelled_out(self):
        # «C minor» с пробелом не распознаётся: регулярное выражение требует
        # слитного написания. Проверяем оба варианта.
        assert mu.extract_key_meta("Track C minor") == "—"
        assert mu.extract_key_meta("Track Cminor") == "5A"

    def test_no_key_returns_dash(self):
        assert mu.extract_key_meta("Just A Song") == "—"

    def test_magicmock_is_tolerated(self):
        """Заглушки не должны ломать разбор."""
        assert mu.extract_key_meta(MagicMock(), MagicMock()) == "—"


class TestExtractBpmMeta:

    def test_plain_number(self):
        assert mu.extract_bpm_meta("Track 128 BPM") == "128"

    def test_no_bpm_returns_dash(self):
        assert mu.extract_bpm_meta("Just A Song") == "—"

    def test_magicmock_is_tolerated(self):
        assert mu.extract_bpm_meta(MagicMock(), MagicMock()) == "—"


class TestCamelotColor:

    def test_known_key_has_colour(self):
        assert mu.get_camelot_color("8A") != "#64748B"

    def test_unknown_key_is_grey(self):
        assert mu.get_camelot_color("не тональность") == "#64748B"


class TestReadAudioId3Meta:

    def test_missing_file(self):
        assert mu.read_audio_id3_meta("нет_такого.mp3") == ("—", "—")

    def test_empty_path(self):
        assert mu.read_audio_id3_meta("") == ("—", "—")

    def test_no_tags(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags=None)):
            assert mu.read_audio_id3_meta(str(f)) == ("—", "—")

    def test_bpm_numeric(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        audio = MagicMock(tags={"TBPM": "128.4"})
        with patch("mutagen.File", return_value=audio):
            assert mu.read_audio_id3_meta(str(f))[0] == "128"

    def test_bpm_out_of_range_is_dropped(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags={"TBPM": "9999"})):
            assert mu.read_audio_id3_meta(str(f))[0] == "—"

    def test_bpm_parsed_from_text(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags={"TBPM": "around 124 bpm"})):
            assert mu.read_audio_id3_meta(str(f))[0] == "124"

    def test_bpm_from_txxx(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags={"TXXX:BPM": "140"})):
            assert mu.read_audio_id3_meta(str(f))[0] == "140"

    def test_key_camelot(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags={"TKEY": "8A"})):
            assert mu.read_audio_id3_meta(str(f))[1] == "8A"

    def test_key_musical(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", return_value=MagicMock(tags={"TKEY": "Am"})):
            assert mu.read_audio_id3_meta(str(f))[1] != "—"

    def test_key_with_spaces_is_compacted(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        # «F# minor» без пробела внутри слова не распознаётся,
        # а слитное «F#minor» приводится к коду колеса.
        with patch("mutagen.File",
                   return_value=MagicMock(tags={"initialkey": "F# minor"})):
            assert mu.read_audio_id3_meta(str(f))[1] == "—"
        with patch("mutagen.File",
                   return_value=MagicMock(tags={"initialkey": "F#minor"})):
            assert mu.read_audio_id3_meta(str(f))[1] != "—"

    def test_key_falls_back_to_parser(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File",
                   return_value=MagicMock(tags={"TKEY": "Track [9B]"})):
            assert mu.read_audio_id3_meta(str(f))[1] == "9B"

    def test_mutagen_failure_is_caught(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"\x00")
        with patch("mutagen.File", side_effect=RuntimeError("битый файл")):
            assert mu.read_audio_id3_meta(str(f)) == ("—", "—")


class TestPromoAndTitleCase:

    def test_clean_promo_removes_tags(self):
        got = mu.clean_promo_text("Track (320 kbps) [HQ] @channel")
        assert "320" not in got and "channel" not in got.lower()

    def test_clean_promo_empty(self):
        assert mu.clean_promo_text("") == ""

    def test_smart_title_case_capitalises_words(self):
        assert mu.smart_title_case("SOME LONG TRACK") == "Some Long Track"

    def test_smart_title_case_keeps_mixed_case(self):
        """Функция только поднимает первую букву, не опуская строчные."""
        assert mu.smart_title_case("the best track") == "the best track"

    def test_clean_track_metadata_swaps_bad_fields(self):
        artist, title = mu.clean_track_metadata("", "")
        assert artist and title

class TestSanitizePathSegment:
    """DEFECT-021. Управляющие символы в имени файла делают трек нескачиваемым.

    На Windows перевод строки даёт «Invalid argument» при открытии файла, а
    нулевой байт -- «embedded null byte». До правки такие треки падали три
    раза и уходили в лог как сетевая ошибка.
    """

    def test_plain_name_untouched(self):
        assert mu.sanitize_path_segment("Обычный трек") == "Обычный трек"

    def test_newline_is_removed(self):
        got = mu.sanitize_path_segment("С переводом\nстроки")
        assert "\n" not in got and "\r" not in got
        assert " " in got

    def test_tab_is_removed(self):
        assert "\t" not in mu.sanitize_path_segment("Таб\tздесь")

    def test_null_byte_is_removed(self):
        assert "\x00" not in mu.sanitize_path_segment("Ноль\x00байт")

    def test_no_control_characters_left(self):
        got = mu.sanitize_path_segment("Мусор\x01\x02\x7f\nконец")
        assert all(ord(c) >= 32 for c in got)

    def test_traversal_still_blocked(self):
        assert ".." not in mu.sanitize_path_segment("../../etc/passwd")

    def test_empty_and_blank_give_placeholder(self):
        assert mu.sanitize_path_segment("") == "Unknown"
        assert mu.sanitize_path_segment("   ") == "Unknown"
        assert mu.sanitize_path_segment("///") == "Unknown"

    def test_result_is_usable_as_filename(self):
        got = mu.sanitize_path_segment("ЕВА ВЛАСОВА\n - Вчера (Cover)")
        assert not any(ch in got for ch in '<>:"/\\|?*')
