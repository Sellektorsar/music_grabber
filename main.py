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
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(700, 500)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
