"""Тесты точки входа `main.py`.

Модуль не покрывался ни одним тестом (0 %): это точка входа, а её
логика — создание лог-файла, перехват необработанных исключений и защита
от второго экземпляра — как раз то, что ломается незаметно.
"""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def clean_sys_excepthook():
    """Восстанавливает sys.excepthook после теста."""
    import sys
    original = sys.excepthook
    yield
    sys.excepthook = original


def _isolate_base(tmp_path, monkeypatch):
    """Уводит рабочую папку во временный каталог.

    main() ставит глобальный sys.excepthook, который пишет по пути
    config.get_base_dir(). Без перенаправления тест создал бы настоящий
    crash.log рядом с данными пользователя.
    """
    base = tmp_path / "base"
    base.mkdir(exist_ok=True)
    monkeypatch.setattr("config.get_base_dir", lambda: str(base))
    return base


class TestSetupLogging:

    def test_creates_log_dir_and_file(self, tmp_path, monkeypatch):
        import main as main_mod
        monkeypatch.setattr(main_mod.os, "makedirs", lambda *a, **kw: None)

        created = {}

        class _Handler(logging.Handler):
            def __init__(self, *args, **kwargs):
                created["path"] = kwargs.get("filename") or (args[0] if args else None)
                super().__init__()

        with patch("logging.handlers.RotatingFileHandler", _Handler):
            main_mod.setup_logging()

        assert created["path"], "файл лога должен создаваться"
        assert created["path"].endswith("app.log")

    def test_rotating_file_bounded(self, tmp_path, monkeypatch):
        """Лог не должен расти бесконечно."""
        import main as main_mod
        seen = {}

        def _fake(*args, **kwargs):
            seen.update(kwargs)
            return logging.NullHandler()

        with patch("logging.handlers.RotatingFileHandler", _fake):
            main_mod.setup_logging()

        assert seen.get("maxBytes") == 5 * 1024 * 1024
        assert seen.get("backupCount") == 3

    def test_falls_back_when_log_dir_unavailable(self, tmp_path, monkeypatch):
        """Нет прав на папку — приложение обязано всё равно запуститься."""
        import main as main_mod

        def _boom(*a, **kw):
            raise OSError("access denied")

        monkeypatch.setattr(main_mod.os, "makedirs", _boom)

        with patch("logging.handlers.RotatingFileHandler",
                   side_effect=OSError("nope")):
            main_mod.setup_logging()   # не должно бросать


class TestCrashLogPaths:

    def test_excepthook_and_exec_handler_use_same_location(self):
        """Оба обработчика обязаны писать crash.log в одно место.

        Перехватчик sys.excepthook пишет по абсолютному пути из
        config.get_base_dir(), а обработчик исключений внутри app.exec()
        открывает просто "crash.log" — то есть относительно текущего
        каталога процесса. При запуске из ярлыка два файла окажутся в
        разных местах, и настоящая причина падения может потеряться.
        """
        import main as main_mod
        from config import get_base_dir

        source = open(main_mod.__file__, encoding="utf-8").read()

        assert 'os.path.join(get_base_dir(), "crash.log")' in source, (
            "перехватчик должен использовать единый абсолютный путь"
        )
        # Ветка app.exec() обязана писать туда же, а не в CWD.
        assert 'open("crash.log"' not in source, (
            "относительный crash.log в app.exec() расходится с перехватчиком"
        )
        assert os.path.isabs(os.path.join(get_base_dir(), "crash.log"))


class TestSingleInstanceGuard:

    def _patched_main(self, already_running, tmp_path):
        import main as main_mod

        app = MagicMock()
        app.exec.return_value = 0

        window = MagicMock()
        server = MagicMock()

        socket = MagicMock()
        socket.waitForConnected.return_value = already_running

        patches = [
            patch.object(main_mod, "QApplication", MagicMock(return_value=app)),
            patch.object(main_mod, "MainWindow", MagicMock(return_value=window)),
            patch("gui.MainWindow", MagicMock(return_value=window)),
            patch("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket)),
            patch("PyQt6.QtNetwork.QLocalServer", MagicMock(return_value=server)),
        ]
        return patches, app, window, server, socket

    def test_second_instance_exits_without_window(self, tmp_path, monkeypatch):
        """Второй запуск обязан передать фокус и выйти, не создавая окна."""
        import main as main_mod

        app = MagicMock()
        window = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = True

        window_factory = MagicMock(return_value=window)
        monkeypatch.setattr(main_mod, "MainWindow", window_factory)
        monkeypatch.setattr("gui.MainWindow", window_factory)
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock())
        _isolate_base(tmp_path, monkeypatch)

        with pytest.raises(SystemExit) as exc:
            main_mod.main()

        assert exc.value.code == 0
        window_factory.assert_not_called()
        socket.write.assert_called_once_with(b"ACTIVATE")

    def test_first_instance_creates_window_and_server(self, tmp_path, monkeypatch):
        """Первый запуск создаёт сервер, окно и уходит в цикл событий."""
        import main as main_mod

        app = MagicMock()
        app.exec.return_value = 0
        window = MagicMock()
        server = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = False

        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock(return_value=server))

        with pytest.raises(SystemExit) as exc:
            main_mod.main()

        assert exc.value.code == 0
        server.removeServer.assert_called_once()
        server.listen.assert_called_once()
        window.show.assert_called_once()
        window.resize.assert_called_once_with(1280, 750)

    def test_activation_message_raises_window(self, tmp_path, monkeypatch):
        """Сообщение ACTIVATE должно поднять уже открытое окно."""
        import main as main_mod

        app = MagicMock()
        app.exec.return_value = 0
        window = MagicMock()
        server = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = False

        captured = {}

        def _connect(handler):
            captured["handler"] = handler

        server.newConnection.connect.side_effect = _connect

        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock(return_value=server))

        with pytest.raises(SystemExit):
            main_mod.main()

        client = MagicMock()
        client.readAll.return_value.data.return_value = b"ACTIVATE"
        server.nextPendingConnection.return_value = client

        captured["handler"]()

        window.showNormal.assert_called_once()
        window.raise_.assert_called_once()
        client.disconnectFromServer.assert_called_once()


class TestUncaughtExceptions:

    def test_exec_exception_is_logged_and_exit_code_is_one(self, tmp_path, monkeypatch):
        """Падение внутри цикла событий обязано попасть в crash.log.

        Тест намеренно НЕ подменяет builtins.open: глобальная подмена
        ломает сам pytest (зависает на чтении файлов). Вместо этого
        процесс переводится во временный каталог, и настоящий файл
        читается с диска — заодно это проверяет и путь.
        """
        import main as main_mod

        monkeypatch.chdir(tmp_path)
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setattr("config.get_base_dir", lambda: str(base))
        app = MagicMock()
        app.exec.side_effect = RuntimeError("boom")
        window = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = False

        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock())
        _isolate_base(tmp_path, monkeypatch)

        with pytest.raises(SystemExit) as exc:
            main_mod.main()

        assert exc.value.code == 1
        written = (base / "crash.log").read_text(encoding="utf-8")
        assert "boom" in written

    def test_exec_crash_log_lands_in_base_dir(self, tmp_path, monkeypatch):
        """После исправления crash.log пишется в рабочую папку приложения.

        Раньше файл появлялся в текущем каталоге процесса, и при запуске
        из ярлыка его нельзя было найти рядом с данными.
        """
        import main as main_mod

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.chdir(workdir)

        app = MagicMock()
        app.exec.side_effect = RuntimeError("boom2")
        window = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = False

        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock())
        _isolate_base(tmp_path, monkeypatch)
        monkeypatch.setattr("config.get_base_dir", lambda: str(base))

        with pytest.raises(SystemExit):
            main_mod.main()

        assert not (workdir / "crash.log").exists(), "в рабочий каталог писать нельзя"
        assert (base / "crash.log").exists(), "crash.log обязан лежать в рабочей папке"

    def test_excepthook_installed(self, tmp_path, monkeypatch, clean_sys_excepthook):
        """После запуска перехватчик необработанных исключений обязан стоять."""
        import sys
        import main as main_mod

        app = MagicMock()
        app.exec.return_value = 0
        window = MagicMock()
        socket = MagicMock()
        socket.waitForConnected.return_value = False

        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "MainWindow", MagicMock(return_value=window))
        monkeypatch.setattr(main_mod, "QApplication", MagicMock(return_value=app))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalSocket", MagicMock(return_value=socket))
        monkeypatch.setattr("PyQt6.QtNetwork.QLocalServer", MagicMock())
        _isolate_base(tmp_path, monkeypatch)

        original_hook = sys.excepthook
        with pytest.raises(SystemExit):
            main_mod.main()

        assert sys.excepthook is not original_hook
        assert sys.excepthook.__name__ == "excepthook"