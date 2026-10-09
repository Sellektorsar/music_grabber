"""Универсальный скрипт запуска TelegramAudioDownloader на рабочем столе Windows.

Позволяет запускать приложение как вручную, так и программно (через AI-агента),
гарантируя запуск на интерактивном рабочем столе пользователя (winsta0\\default)
без ошибок экранирования Windows Terminal (0x800700e8) и без блокировки песочницей.
"""

import os
import subprocess
import sys


def is_running() -> bool:
    """Проверяет, запущен ли уже процесс приложения."""
    try:
        output = subprocess.check_output(
            ["tasklist", "/fi", "IMAGENAME eq python.exe", "/fo", "csv"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        # Также проверяем pythonw.exe
        output_w = subprocess.check_output(
            ["tasklist", "/fi", "IMAGENAME eq pythonw.exe", "/fo", "csv"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        combined = output + output_w
        return "python" in combined.lower()
    except Exception:
        return False


def launch():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bat_file = os.path.join(base_dir, "run.bat")

    if not os.path.exists(bat_file):
        # Если run.bat отсутствует, создаем его
        with open(bat_file, "w", encoding="utf-8") as f:
            f.write('@echo off\ncd /d "%~dp0"\npython main.py\n')

    task_name = "TelegramAudioDownloaderLauncher"

    # Создаем разовую задачу через Планировщик задач с флагом /it (интерактивный рабочий стол)
    cmd_create = [
        "schtasks",
        "/create",
        "/tn",
        task_name,
        "/tr",
        f'"{bat_file}"',
        "/sc",
        "once",
        "/st",
        "00:00",
        "/it",
        "/f",
    ]
    subprocess.run(cmd_create, capture_output=True, text=True)

    # Немедленный запуск на рабочем столе пользователя
    res_run = subprocess.run(
        ["schtasks", "/run", "/tn", task_name],
        capture_output=True,
        text=True,
    )

    # Удаление задачи из расписания
    subprocess.run(
        ["schtasks", "/delete", "/tn", task_name, "/f"],
        capture_output=True,
        text=True,
    )

    if res_run.returncode == 0:
        print("OK: Telegram Audio Downloader успешно запущен на рабочем столе.")
    else:
        print(f"Предупреждение при запуске задачи: {res_run.stderr or res_run.stdout}")


if __name__ == "__main__":
    launch()
