"""Модуль записи аудиопотока через звуковое устройство (sounddevice) и нормализации."""

import os
import logging
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as scipy_write
from audio_converter import convert_to_mp3

logger = logging.getLogger(__name__)


def save_recording(
    data: np.ndarray,
    fs: int,
    filename: str,
    bitrate: str = "192k",
    log_callback=None,
) -> None:
    """Нормализует сырые аудиосэмплы, сохраняет во временный WAV и конвертирует в MP3."""
    log = log_callback or logger.info
    if data.dtype != np.int16:
        max_abs = np.max(np.abs(data))
        if max_abs > 0:
            data = (data / max_abs * 32767).astype(np.int16)
        else:
            data = data.astype(np.int16)

    wav_temp = filename + ".wav"
    try:
        scipy_write(wav_temp, fs, data)
        convert_to_mp3(wav_temp, filename, bitrate=bitrate)
        log(f"Аудио записано и конвертировано: {filename}")
    finally:
        if os.path.exists(wav_temp):
            try:
                os.remove(wav_temp)
            except Exception:
                pass


def record_audio(
    duration: float,
    filename: str,
    is_cancelled_fn=None,
    sample_rate: int = 44100,
    bitrate: str = "192k",
    log_callback=None,
) -> None:
    """Записывает стерео-аудио заданной длительности со звукового устройства."""
    log = log_callback or logger.info
    try:
        fs = sample_rate
        frames = int(duration * fs)
        log(f"Запись аудио длительностью {duration} сек. в файл {filename}")

        recording = np.zeros((frames, 2), dtype=np.float32)
        current_frame = 0

        def callback(indata, frames_per_buffer, time_info, status):
            nonlocal current_frame
            if is_cancelled_fn and is_cancelled_fn():
                raise sd.CallbackAbort()
            remaining = frames - current_frame
            if remaining <= 0:
                return
            to_copy = min(frames_per_buffer, remaining)
            recording[current_frame : current_frame + to_copy] = indata[:to_copy]
            current_frame += to_copy

        with sd.InputStream(
            samplerate=fs, channels=2, callback=callback, blocksize=4096
        ):
            while current_frame < frames:
                if is_cancelled_fn and is_cancelled_fn():
                    break
                sd.sleep(0.1)

        cancelled = is_cancelled_fn() if is_cancelled_fn else False
        if cancelled:
            recording = recording[:current_frame]
            log(f"Запись прервана, сохранено {current_frame / fs:.1f} сек.")
        elif current_frame < frames:
            recording = recording[:current_frame]

        if current_frame > 0:
            save_recording(recording, fs, filename, bitrate=bitrate, log_callback=log)
        else:
            log("Запись не выполнена (нет данных).")
    except Exception as e:
        log(f"Ошибка записи аудио: {e}")
        logger.error("Ошибка в record_audio", exc_info=True)
