"""Тесты на перерисовку дерева с сохранением состояния.

Сканирование в несколько заходов не должно обнулять то, что пользователь
уже отметил: иначе после подгрузки следующей порции треков пришлось бы
заново расставлять галочки перед загрузкой. Здесь и проверяется именно
эта гарантия, а также освобождение старых виджетов-бейджей -- при
перерисовке их десятки, и утечка памяти была бы заметна.
"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt


def _track(**kw):
    base = {
        "id": 1, "channel": "akmpool", "title": "GAZ", "performer": "Zivert",
        "filename": "Zivert - GAZ.mp3", "duration": 240, "bpm": "128",
        "size": 9_000_000, "already_exists": False, "is_duplicate": False,
        "key": "8A", "status": "READY", "filepath": "",
    }
    base.update(kw)
    return base


@pytest.fixture
def w(monkeypatch, tmp_path, qtbot):
    cfg_dir = tmp_path / "telegram_audio"
    cfg_dir.mkdir()
    monkeypatch.setattr("config.CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(cfg_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    from gui import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.log = MagicMock()
    win._updating_tree = False
    return win


def _check_state(w, track_id):
    return w._track_item_by_id[track_id].checkState(0)


class TestPreservedCheckState:
    """Отметки пользователя переживают перерисовку.

    Важная особенность: свежие треки приходят отмеченными -- весь
    результат скана сразу готов к загрузке. Поэтому проверяется не
    «осталось ли отмечено», а «сохранилось ли снятие отметки».
    """

    def test_fresh_tracks_are_ticked_by_default(self, w):
        """Скан сразу готов к загрузке -- снимать галочки не нужно."""
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        assert _check_state(w, 1) == Qt.CheckState.Checked
        assert _check_state(w, 2) == Qt.CheckState.Checked

    def test_unticking_survives_rerender(self, w):
        """Снятая пользователем отметка не должна возвращаться."""
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        w._track_item_by_id[1].setCheckState(0, Qt.CheckState.Unchecked)

        w._render_tracks_in_tree([_track(id=1), _track(id=2)],
                                 preserve_state=True)

        assert _check_state(w, 1) == Qt.CheckState.Unchecked

    def test_other_tracks_stay_ticked(self, w):
        w._render_tracks_in_tree([_track(id=1), _track(id=2)])
        w._track_item_by_id[1].setCheckState(0, Qt.CheckState.Unchecked)

        w._render_tracks_in_tree([_track(id=1), _track(id=2)],
                                 preserve_state=True)

        assert _check_state(w, 2) == Qt.CheckState.Checked

    def test_new_track_is_ticked_by_default(self, w):
        """Трек из следующей порции приходит готовым к загрузке."""
        w._render_tracks_in_tree([_track(id=1)])
        w._track_item_by_id[1].setCheckState(0, Qt.CheckState.Unchecked)

        w._render_tracks_in_tree([_track(id=1), _track(id=99)],
                                 preserve_state=True)

        assert _check_state(w, 99) == Qt.CheckState.Checked

    def test_without_preserve_state_returns_to_default(self, w):
        """Без сохранения состояния дерево возвращается к «всё отмечено»."""
        w._render_tracks_in_tree([_track(id=1)])
        w._track_item_by_id[1].setCheckState(0, Qt.CheckState.Unchecked)

        w._render_tracks_in_tree([_track(id=1)], preserve_state=False)

        assert _check_state(w, 1) == Qt.CheckState.Checked


class TestPreservedExpansion:
    """Развёрнутые группы остаются развёрнутыми."""

    def test_expanded_group_stays_expanded(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        top_before = w.library_tree.topLevelItem(0)
        top_before.setExpanded(True)
        label = top_before.text(0).split("   (")[0].strip()

        w._render_tracks_in_tree([_track(id=1)], preserve_state=True)

        top_after = w.library_tree.topLevelItem(0)
        assert top_after.text(0).split("   (")[0].strip() == label
        assert top_after.isExpanded() is True

    def test_collapsed_group_stays_collapsed(self, w):
        w._render_tracks_in_tree([_track(id=1)])
        w.library_tree.topLevelItem(0).setExpanded(False)

        w._render_tracks_in_tree([_track(id=1)], preserve_state=True)

        assert w.library_tree.topLevelItem(0).isExpanded() is False


class TestWidgetDisposal:
    """Старые бейджи и волны освобождаются при перерисовке."""

    def test_old_badges_are_released(self, w):
        badge = MagicMock()
        w._render_tracks_in_tree([_track(id=1)])
        w._track_status_badges[1] = badge

        w._render_tracks_in_tree([_track(id=1)])

        badge.setParent.assert_called_once_with(None)
        badge.deleteLater.assert_called_once()

    def test_old_waveforms_are_released(self, w):
        wave = MagicMock()
        w._render_tracks_in_tree([_track(id=1)])
        w._track_waveforms[1] = wave

        w._render_tracks_in_tree([_track(id=1)])

        wave.setParent.assert_called_once_with(None)
        wave.deleteLater.assert_called_once()

    def test_registries_hold_new_widgets(self, w):
        """После перерисовки реестры должны ссылаться на новые виджеты."""
        w._render_tracks_in_tree([_track(id=1)])
        old_badge = w._track_status_badges[1]
        old_wave = w._track_waveforms[1]

        w._render_tracks_in_tree([_track(id=1)])

        assert w._track_status_badges[1] is not old_badge
        assert w._track_waveforms[1] is not old_wave

    def test_broken_badge_does_not_break_rerender(self, w):
        """Упавший виджет не должен валить перерисовку целиком."""
        w._render_tracks_in_tree([_track(id=1)])
        broken = MagicMock()
        broken.setParent.side_effect = RuntimeError("уже удалён")
        w._track_status_badges[1] = broken

        w._render_tracks_in_tree([_track(id=1)])

        assert _check_state(w, 1) is not None

    def test_updating_flag_is_cleared_after_rerender(self, w):
        """Забытый флаг заблокировал бы обновление дерева навсегда."""
        w._render_tracks_in_tree([_track(id=1)])
        assert w._updating_tree is False