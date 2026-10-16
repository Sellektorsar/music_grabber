from PyQt6.QtWidgets import QApplication
import os
import sys
from gui import MainWindow
import logging
import logging.handlers

logger = logging.getLogger(__name__)


def setup_logging():
    try:
        from config import BASE_PATH
        log_dir = os.path.join(BASE_PATH, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[
            logging.StreamHandler(),
            file_handler,
        ])
    except Exception as e:
        logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
        logging.warning(f"Не удалось настроить файловое логгирование: {e}")


def main():
    setup_logging()

    # Глобальный перехватчик необработанных исключений — запись в файл
    import traceback
    from config import get_base_dir

    def excepthook(exc_type, exc_value, exc_tb):
        crash_log = os.path.join(get_base_dir(), "crash.log")
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_value}\n")
            f.write("".join(traceback.format_tb(exc_tb)))
            f.write("\n")
        # Вызов оригинального обработчика
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook

    app = QApplication(sys.argv)

    # Защита от одновременного запуска нескольких экземпляров (Single Instance)
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    server_name = "TelegramAudioDownloader_IPC_Server"
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(500):
        socket.write(b"ACTIVATE")
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        logger.info("Приложение уже запущено. Фокус передан в существующее окно.")
        sys.exit(0)

    server = QLocalServer()
    server.removeServer(server_name)
    server.listen(server_name)

    window = MainWindow()
    window.resize(1280, 750)
    window.show()

    def on_new_connection():
        client_conn = server.nextPendingConnection()
        if client_conn:
            client_conn.waitForReadyRead(500)
            msg = client_conn.readAll().data()
            if b"ACTIVATE" in msg:
                window.showNormal()
                window.raise_()
                window.activateWindow()
            client_conn.disconnectFromServer()

    server.newConnection.connect(on_new_connection)
    try:
        exit_code = app.exec()
    except Exception as e:
        # Тот же абсолютный путь, что и у перехватчика sys.excepthook.
        # Относительный "crash.log" писался в текущий каталог процесса,
        # и при запуске из ярлыка два файла оказывались в разных местах.
        crash_log = os.path.join(get_base_dir(), "crash.log")
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"EXCEPTION in app.exec(): {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
