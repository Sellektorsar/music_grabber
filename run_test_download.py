"""
Скрипт для реальной проверки скачивания.
Создаёт TelegramClient, проходит аутентификацию (через консоль),
запускает TelegramAudioRecorder и выводит прогресс в реальном времени.
"""
import asyncio
import sys
import os
import time
import socks
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from recorder import TelegramAudioRecorder
import recorder as rec_module

# Конфигурация
API_ID = 26222233
API_HASH = "67bf29f522f05a42ae3d6601f0fbd97f"
CHANNEL = "@akmpool"
MODE = "hybrid"
DATE_FROM = datetime(2026, 6, 27)
DATE_TO = datetime(2026, 6, 29, 23, 59, 59)

# Ускоряем (убираем задержку между сообщениями для теста)
rec_module._DOWNLOAD_DELAY = 0.1


def console_log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


async def main():
    print("=" * 60)
    print("ЗАПУСК ТЕСТОВОГО СКАЧИВАНИЯ")
    print(f"API_ID: {API_ID}")
    print(f"CHANNEL: {CHANNEL}")
    print(f"MODE: {MODE}")
    print(f"DATE: {DATE_FROM.date()} .. {DATE_TO.date()}")
    print("=" * 60)

    proxy = (socks.SOCKS5, "127.0.0.1", 10808)
    client = TelegramClient("session_test", API_ID, API_HASH, proxy=proxy)
    await client.connect()

    me = await client.get_me()
    print(f"Авторизован как: {me.first_name} {me.last_name or ''}\n")

    # Запускаем рекордер
    progress_data = {}
    last_progress_time = 0

    def on_progress(data):
        nonlocal last_progress_time
        progress_data.update(data)
        now = time.time()
        if now - last_progress_time >= 1.0:  # Печатаем раз в секунду
            print(
                f"  Просмотрено: {data.get('total_scanned', 0):4d} | "
                f"Аудио: {data.get('audio_found', 0):3d} | "
                f"Загружено: {data.get('downloaded', 0):3d} | "
                f"Пропущено: {data.get('skipped', 0):3d} | "
                f"Уже есть: {data.get('already_exists', 0):3d} | "
                f"ETA: {data.get('eta_seconds', 0):.0f}с"
            )
            cur = data.get("current_file", "")
            if cur:
                print(f"  Файл: {cur}")
            last_progress_time = now

    def on_log(msg):
        console_log(msg)

    print("--- ЗАПУСК СКАЧИВАНИЯ ---\n")
    recorder = TelegramAudioRecorder(
        client, CHANNEL, MODE,
        DATE_FROM, DATE_TO,
        logger_callback=on_log,
        progress_callback=on_progress,
    )

    await recorder.start()

    print("\n--- ИТОГ ---")
    print(f"Просмотрено сообщений:  {progress_data.get('total_scanned', 0)}")
    print(f"Аудио найдено:          {progress_data.get('audio_found', 0)}")
    print(f"Загружено:              {progress_data.get('downloaded', 0)}")
    print(f"Пропущено:              {progress_data.get('skipped', 0)}")
    print(f"Уже существовало:       {progress_data.get('already_exists', 0)}")

    # Проверяем файлы на диске
    base = rec_module.BASE_FOLDER
    print(f"\nФайлы на диске ({base}):")
    if os.path.isdir(base):
        for root, dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".mp3"):
                    fp = os.path.join(root, f)
                    size = os.path.getsize(fp)
                    print(f"  {os.path.relpath(fp, base)}  ({size / 1024:.0f} KB)")
    else:
        print("  Папка не найдена!")

    await client.disconnect()
    print("\nГотово.")


if __name__ == "__main__":
    asyncio.run(main())
