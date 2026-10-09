from PyQt6.QtWidgets import QApplication
import os
import sys
from gui import MainWindow
import logging
import logging.handlers

logger = logging.getLogger(__name__)


def setup_logging():
    try:
        log_dir = "telegram_audio/logs"
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

    def excepthook(exc_type, exc_value, exc_tb):
        with open("crash.log", "a", encoding="utf-8") as f:
            f.write(f"UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_value}\n")
            f.write("".join(traceback.format_tb(exc_tb)))
            f.write("\n")
        # Вызов оригинального обработчика
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1280, 750)
    window.show()
    try:
        exit_code = app.exec()
    except Exception as e:
        with open("crash.log", "a", encoding="utf-8") as f:
            f.write(f"EXCEPTION in app.exec(): {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
