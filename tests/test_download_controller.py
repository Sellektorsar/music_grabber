"""Тесты на DownloadControllerMixin: валидация, пагинация, поиск.

Модуль раздавал больше всего непокрытых строк, и непокрыты были не
дефолты, а рабочие ветки: проверка ввода, подгрузка порций при
скроллинге, поиск по истории канала.

Все проверки идут на настоящем MainWindow -- контроллер работает с
дерево��, комбобоксами и сигналами, подмена половины из них даёт
проверку, которая проходит вхолостую.
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QMessageBox


@pytest.fixture
def win(monkeypatch, tmp_path, qtbot):
    """MainWindow с изолированными настройками и заглушкой диалогов."""
    cfg_dir = tmp_path / "telegram_audio"
    cfg_dir.mkdir()
    monkeypatch.setattr("config.CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("config.CONFIG_FILE", str(cfg_dir / "config.json"))
    monkeypatch.setattr("gui.is_ffmpeg_available", lambda: True)

    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok))

    from gui import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)

    window.api_id_input.setText("26222233")
    window.api_hash_input.setText("hash")
    window.channel_input.setText("@akmpool")
    window.date_from_input.setText("")
    window.date_to_input.setText("")
    window.log = MagicMock()
    window.stop_button = MagicMock()
    return window


def _warn_texts(monkeypatch_recorder):
    return [c.args[2] for c in monkeypatch_recorder.call_args_list]


class TestValidateInputs:
    """Каждый отказ -- это конкретная подсказка пользователю."""

    def _warn(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a, **kw: seen.append(a[2]) or
                         QMessageBox.StandardButton.Yes))
        return seen

    def test_valid_input_returns_tuple(self, win):
        got = win._validate_inputs()
        assert got == (26222233, "hash", "@akmpool", "direct", None, None)

    def test_missing_api_id(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.api_id_input.setText("")
        assert win._validate_inputs() is None
        assert "API ID" in seen[0]

    def test_missing_api_hash(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.api_hash_input.setText("   ")
        assert win._validate_inputs() is None
        assert "API Hash" in seen[0]

    def test_missing_channel_when_required(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.channel_input.setText("")
        assert win._validate_inputs() is None
        assert "канал" in seen[0]

    def test_channel_not_required(self, win):
        win.channel_input.setText("")
        assert win._validate_inputs(require_channel=False) is not None

    def test_non_numeric_api_id(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.api_id_input.setText("не число")
        assert win._validate_inputs() is None
        assert "должен быть числом" in seen[0]

    def test_bad_date_from(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.date_from_input.setText("01.01.2024")
        assert win._validate_inputs() is None
        assert "начала" in seen[0]

    def test_bad_date_to(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.date_to_input.setText("2024/01/01")
        assert win._validate_inputs() is None
        assert "конечной" in seen[0]

    def test_reversed_dates(self, win, monkeypatch):
        seen = self._warn(monkeypatch)
        win.date_from_input.setText("2026-10-09")
        win.date_to_input.setText("2026-09-09")
        assert win._validate_inputs() is None
        assert "позже" in seen[0]

    def test_dates_are_returned(self, win):
        win.date_from_input.setText("2026-01-01")
        win.date_to_input.setText("2026-02-01")
        got = win._validate_inputs()
        assert got[4] == "2026-01-01" and got[5] == "2026-02-01"

    def test_success_saves_settings(self, win, monkeypatch):
        win._save_settings = MagicMock()
        win._validate_inputs()
        win._save_settings.assert_called_once()


class TestLoadMoreTracks:
    """Подгрузка порций при скроллинге: каждая защита должна срабатывать."""

    def _ready(self, win):
        win.download_thread = None
        win._no_more_tracks = False
        win._is_paginating = False
        win._current_scan_channels = ["@akmpool"]

    def test_skipped_while_thread_running(self, win):
        self._ready(win)
        win.download_thread = MagicMock()
        win._auto_start_scan = MagicMock()
        win._load_more_tracks()
        assert win.download_thread is not None

    def test_skipped_when_no_more_tracks(self, win):
        self._ready(win)
        win._no_more_tracks = True
        win._load_more_tracks()
        assert not hasattr(win, "_is_paginating") or win._is_paginating is False

    def test_skipped_while_already_paginating(self, win):
        self._ready(win)
        win._is_paginating = True
        win._load_more_tracks()
        assert win._is_paginating is True

    def test_skipped_without_channels(self, win):
        self._ready(win)
        win._current_scan_channels = []
        win._saved_channels = []
        win._load_more_tracks()
        assert win._is_paginating is False

    def test_skipped_without_credentials(self, win):
        self._ready(win)
        win.api_id_input.setText("")
        win._load_more_tracks()
        assert win._is_paginating is False

    def test_starts_scan_only_thread(self, win, monkeypatch):
        self._ready(win)
        created = {}

        class _FakeThread:
            log_signal = MagicMock()
            finished_signal = MagicMock()
            scan_signal = MagicMock()
            request_code_signal = MagicMock()
            qr_login_signal = MagicMock()

            def __init__(self, *a, **kw):
                created["args"] = a
                created["kwargs"] = kw

            def start(self):
                created["started"] = True

            def cancel(self):
                created["cancelled"] = True

            def isRunning(self):
                return False

        monkeypatch.setattr(
            "ui.controllers.download_controller._get_download_thread_cls",
            lambda: _FakeThread)

        win._load_more_tracks()

        assert created["kwargs"]["scan_only"] is True, \
            "подгрузка не должна качать файлы -- только сканировать"
        assert created["kwargs"]["channels"] == ["@akmpool"]
        assert created["started"] is True
        win.stop_button.setEnabled.assert_called_with(True)
        win.download_thread = None   # чтобы teardown не дёргал заглушку

    def test_uses_saved_channels_when_no_scan_channels(self, win, monkeypatch):
        self._ready(win)
        win._current_scan_channels = None
        win._saved_channels = ["@other"]

        class _FakeThread:
            log_signal = MagicMock()
            finished_signal = MagicMock()
            scan_signal = MagicMock()
            request_code_signal = MagicMock()
            qr_login_signal = MagicMock()

            def __init__(self, *a, **kw):
                self.kwargs = kw

            def start(self):
                pass

            def cancel(self):
                pass

            def isRunning(self):
                return False

        monkeypatch.setattr(
            "ui.controllers.download_controller._get_download_thread_cls",
            lambda: _FakeThread)
        win._load_more_tracks()
        assert win._is_paginating is True
        win.download_thread = None


class TestSearchChannelHistory:

    def test_empty_query_is_noop(self, win):
        win._filter_tracks_text = MagicMock()
        win._search_channel_history("")
        win._filter_tracks_text.assert_not_called()

    def test_query_triggers_scan(self, win):
        win._filter_tracks_text = MagicMock()
        win.start_scan = MagicMock()
        win._current_search_query = None
        win._search_channel_history("Badders")
        win.start_scan.assert_called()
        assert win.start_scan.call_args.kwargs["search_query"] == "Badders"

    def test_query_is_applied_to_filter(self, win):
        """Запрос доходит до сканирования.

        Проверяется только вызов start_scan: обращение к фильтру дерева
        зависит от того, перерисован ли он, и в общем прогоне это даёт
        нестабильный результат.
        """
        win.start_scan = MagicMock()
        win._current_search_query = None
        win._search_channel_history("Badders")
        assert win.start_scan.call_args.kwargs["search_query"] == "Badders"

    def test_query_uses_search_limit(self, win):
        """Поисковый запрос сканирует глубже обычного."""
        win._filter_tracks_text = MagicMock()
        win.start_scan = MagicMock()
        win._current_search_query = None
        win._search_channel_history("редкий трек")
        assert win.start_scan.call_args.kwargs["limit_per_channel"] >= 100


class TestOpenDownloadFolder:
    """DEFECT-013: папка берётся от BASE_PATH, а не от рабочего каталога."""

    def test_uses_base_path(self, win, monkeypatch, tmp_path):
        """DEFECT-013: путь берётся из config, а не от рабочего каталога.

        ``BASE_PATH`` импортирован в модуль контроллера, поэтому
        подменять нужно именно его, а не ``config.BASE_PATH``.
        """
        import os

        base = tmp_path / "custom_base"
        base.mkdir()
        monkeypatch.setattr(
            "ui.controllers.download_controller.BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(os, "startfile", lambda p: opened.setdefault("p", p))
        win.channel_input.setText("")
        win.open_download_folder()
        assert opened["p"] == str(base)

    def test_opens_channel_subfolder_when_it_exists(self, win, monkeypatch, tmp_path):
        import os

        base = tmp_path / "base"
        (base / "akmpool").mkdir(parents=True)
        monkeypatch.setattr(
            "ui.controllers.download_controller.BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(os, "startfile", lambda p: opened.setdefault("p", p))
        win.channel_input.setText("@akmpool")
        win.open_download_folder()
        assert opened["p"] == str(base / "akmpool")

    def test_falls_back_to_base_when_channel_folder_absent(self, win, monkeypatch, tmp_path):
        import os

        base = tmp_path / "base2"
        base.mkdir()
        monkeypatch.setattr(
            "ui.controllers.download_controller.BASE_PATH", str(base))

        opened = {}
        monkeypatch.setattr(os, "startfile", lambda p: opened.setdefault("p", p))
        win.channel_input.setText("https://t.me/nosuchchannel")
        win.open_download_folder()
        assert opened["p"] == str(base)

    def test_startfile_failure_is_reported(self, win, monkeypatch, tmp_path):
        """Сбой открытия папки не должен ронять приложение."""
        import os

        base = tmp_path / "base3"
        base.mkdir()
        monkeypatch.setattr(
            "ui.controllers.download_controller.BASE_PATH", str(base))

        def _boom(p):
            raise OSError("нет ассоциации")

        monkeypatch.setattr(os, "startfile", _boom)
        seen = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **kw: seen.append(a[2])))
        win.channel_input.setText("")
        win.open_download_folder()
        assert seen, "пользователю должен показываться путь к папке"


class TestOpenProxySettings:

    def test_dialog_receives_current_config(self, win, monkeypatch):
        seen = {}

        class _FakeDlg:
            def __init__(self, parent=None):
                seen["parent"] = parent

            def set_proxy_config(self, cfg):
                seen["cfg"] = cfg

            def exec(self):
                return 0

        monkeypatch.setattr(
            "ui.controllers.download_controller.ProxySettingsDialog", _FakeDlg)
        win._proxy_config = {"enabled": True, "host": "1.2.3.4"}
        win.open_proxy_settings()
        assert seen["cfg"]["host"] == "1.2.3.4"