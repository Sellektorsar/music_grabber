"""Тесты записи аудиопотока (`audio_capture.py`).

Модуль покрывался на 16 %: основной сценарий записи и обработка отмены
не проверялись ни разу. Звуковое устройство подменено заглушкой, поэтому
проверяется логика: нормализация, отмена, досрочное завершение, уборка
временных файлов и поведение при ошибках.
"""

import os

import numpy as np
import pytest

import audio_capture as cap


class TestSaveRecording:

    def test_normalizes_float_samples_to_int16(self, tmp_path, monkeypatch):
        """Данные с плавающей точкой должны быть приведены к int16."""
        captured = {}

        def _write(path, fs, data):
            captured["dtype"] = data.dtype
            captured["max"] = int(np.max(data))
            captured["path"] = path

        monkeypatch.setattr(cap, "scipy_write", _write)
        monkeypatch.setattr(cap, "convert_to_mp3", lambda *a, **kw: None)

        data = np.array([[0.5, -0.5], [1.0, -1.0]], dtype=np.float32)
        out = tmp_path / "a.mp3"
        cap.save_recording(data, 44100, str(out))

        assert captured["dtype"] == np.int16
        assert captured["max"] == 32767

    def test_zero_data_does_not_divide_by_zero(self, tmp_path, monkeypatch):
        """Полная тишина не должна приводить к делению на ноль."""
        captured = {}
        monkeypatch.setattr(cap, "scipy_write",
                            lambda p, fs, d: captured.update(dtype=d.dtype))
        monkeypatch.setattr(cap, "convert_to_mp3", lambda *a, **kw: None)

        data = np.zeros((4, 2), dtype=np.float32)
        cap.save_recording(data, 44100, str(tmp_path / "silent.mp3"))

        assert captured["dtype"] == np.int16

    def test_int16_passes_through_untouched(self, tmp_path, monkeypatch):
        """Уже int16 данные не должны пересчитываться."""
        captured = {}
        monkeypatch.setattr(cap, "scipy_write",
                            lambda p, fs, d: captured.update(raw=d.copy()))
        monkeypatch.setattr(cap, "convert_to_mp3", lambda *a, **kw: None)

        data = np.array([[100, -100]], dtype=np.int16)
        cap.save_recording(data, 44100, str(tmp_path / "a.mp3"))

        assert np.array_equal(captured["raw"], data)

    def test_temp_wav_removed_after_success(self, tmp_path, monkeypatch):
        """Временный WAV обязан исчезнуть после конвертации."""
        def _write(path, fs, data):
            with open(path, "wb") as f:
                f.write(b"RIFF")

        monkeypatch.setattr(cap, "scipy_write", _write)
        monkeypatch.setattr(cap, "convert_to_mp3", lambda *a, **kw: None)

        out = tmp_path / "a.mp3"
        cap.save_recording(np.zeros((2, 2), dtype=np.int16), 44100, str(out))

        assert not os.path.exists(str(out) + ".wav")

    def test_temp_wav_removed_even_when_conversion_fails(self, tmp_path, monkeypatch):
        """Ошибка конвертации не должна оставлять мусор на диске."""
        def _write(path, fs, data):
            with open(path, "wb") as f:
                f.write(b"RIFF")

        monkeypatch.setattr(cap, "scipy_write", _write)

        def _boom(*a, **kw):
            raise RuntimeError("ffmpeg failed")

        monkeypatch.setattr(cap, "convert_to_mp3", _boom)

        out = tmp_path / "a.mp3"
        with pytest.raises(RuntimeError):
            cap.save_recording(np.zeros((2, 2), dtype=np.int16), 44100, str(out))

        assert not os.path.exists(str(out) + ".wav"), "WAV обязан быть убран в finally"

    def test_bitrate_is_forwarded(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(cap, "scipy_write", lambda *a, **kw: None)
        monkeypatch.setattr(cap, "convert_to_mp3",
                            lambda *a, **kw: seen.update(kw))
        cap.save_recording(np.zeros((2, 2), dtype=np.int16), 44100,
                           str(tmp_path / "a.mp3"), bitrate="256k")
        assert seen.get("bitrate") == "256k"


class TestRecordAudio:

    def _drive_callback(self, monkeypatch, buffers):
        """Подменяет звуковое устройство: блоки аудио приходят из sleep().

        Реальный поток звука приходит во время `sd.sleep`, поэтому заглушка
        вызывает колбэк именно оттуда. Если колбэк не двигает счётчик
        кадров, цикл `while current_frame < frames` в record_audio крутится
        бесконечно — поэтому сверх заготовленных блоков подаётся тишина,
        как это делает настоящее устройство.
        """
        state = {"index": 0, "callback": None, "aborted": False}

        class _Stream:
            def __init__(self, **kwargs):
                state["callback"] = kwargs["callback"]
                state["samplerate"] = kwargs["samplerate"]
                state["channels"] = kwargs["channels"]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _sleep(_seconds):
            cb = state["callback"]
            if cb is None:
                return
            idx = state["index"]
            state["index"] += 1
            block = (buffers[idx] if idx < len(buffers)
                     else np.zeros((100, 2), dtype=np.float32))
            try:
                cb(block, len(block), None, None)
            except cap.sd.CallbackAbort:
                state["aborted"] = True

        monkeypatch.setattr(cap.sd, "InputStream", _Stream)
        monkeypatch.setattr(cap.sd, "sleep", _sleep)
        return state

    def test_full_duration_is_saved(self, tmp_path, monkeypatch):
        """Полная запись должна сохраниться целиком."""
        fs = 1000
        saved = {}
        buffers = [np.ones((100, 2), dtype=np.float32) * 0.5 for _ in range(10)]
        monkeypatch.setattr(cap, "save_recording",
                            lambda data, rate, name, **kw: saved.update(
                                frames=len(data), rate=rate, name=name))
        self._drive_callback(monkeypatch, buffers)

        cap.record_audio(1.0, str(tmp_path / "rec.mp3"), sample_rate=fs)

        assert saved["frames"] == 1000
        assert saved["rate"] == fs

    def test_stream_is_stereo_44100_by_default(self, tmp_path, monkeypatch):
        """По умолчанию должно быть стерео 44.1 кГц."""
        captured = {}

        class _Stream:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(cap.sd, "InputStream", _Stream)
        monkeypatch.setattr(cap.sd, "sleep", lambda s: None)
        monkeypatch.setattr(cap, "save_recording", lambda *a, **kw: None)

        # Отмена сразу: цикл завершается на первой же проверке.
        cap.record_audio(0.01, str(tmp_path / "r.mp3"), is_cancelled_fn=lambda: True)

        assert captured["samplerate"] == 44100
        assert captured["channels"] == 2

    def test_cancellation_saves_partial_audio(self, tmp_path, monkeypatch):
        """Отмена сохраняет то, что успело записаться."""
        fs = 1000
        buffers = [np.ones((100, 2), dtype=np.float32) * 0.4 for _ in range(10)]
        saved = {}
        monkeypatch.setattr(cap, "save_recording",
                            lambda data, rate, name, **kw: saved.update(frames=len(data)))
        cancel = self._drive_callback(monkeypatch, buffers)

        # Цикл проверяет отмену до сна, поэтому счётчик разрешает отмену
        # только после того, как часть данных уже записана.
        calls = {"n": 0}

        def _cancel():
            calls["n"] += 1
            return calls["n"] > 6

        logs = []
        cap.record_audio(1.0, str(tmp_path / "rec.mp3"), sample_rate=fs,
                         is_cancelled_fn=_cancel, log_callback=logs.append)

        assert saved, "отменённая запись тоже должна сохраняться"
        assert 0 < saved["frames"] < 1000, "сохраняется только записанная часть"
        assert any("прервана" in m for m in logs)

    def test_no_data_logs_and_saves_nothing(self, tmp_path, monkeypatch):
        """Запись без единого кадра не должна создавать файл."""
        saved = []
        monkeypatch.setattr(cap, "save_recording", lambda *a, **kw: saved.append(a))
        self._drive_callback(monkeypatch, [])

        logs = []
        cap.record_audio(1.0, str(tmp_path / "rec.mp3"), sample_rate=1000,
                         is_cancelled_fn=lambda: True, log_callback=logs.append)

        assert saved == []
        assert any("нет данных" in m for m in logs)

    def test_device_error_is_logged_not_raised(self, tmp_path, monkeypatch):
        """Ошибка устройства не должна подниматься в поток GUI."""
        class _Stream:
            def __init__(self, **kwargs):
                raise OSError("no audio device")

        monkeypatch.setattr(cap.sd, "InputStream", _Stream)

        logs = []
        cap.record_audio(1.0, str(tmp_path / "rec.mp3"),
                         log_callback=logs.append)

        assert any("Ошибка записи аудио" in m for m in logs)

    def test_callback_aborts_when_cancelled(self, tmp_path, monkeypatch):
        """Колбэк обязан прерывать поток при отмене.

        Проверяется напрямую: цикл в record_audio проверяет отмену ДО сна,
        поэтому при всегда истинной отмене до колбэка дело не доходит.
        """
        state = self._drive_callback(monkeypatch, [])
        # sounddevice подменён заглушкой, поэтому CallbackAbort там не класс:
        # настоящий тип исключения задаётся явно.
        abort_type = type("CallbackAbort", (Exception,), {})
        monkeypatch.setattr(cap.sd, "CallbackAbort", abort_type)
        monkeypatch.setattr(cap, "save_recording", lambda *a, **kw: None)
        monkeypatch.setattr(cap.sd, "sleep", lambda s: None)
        monkeypatch.setattr(cap.sd, "InputStream", _CatchingStream(state))

        cap.record_audio(1.0, str(tmp_path / "r.mp3"), sample_rate=1000,
                         is_cancelled_fn=lambda: True)

        # После выхода колбэк доступен: вызываем его с отменой.
        cb = state["callback"]
        assert cb is not None, "колбэк должен быть передан в InputStream"
        with pytest.raises(abort_type):
            cb(np.ones((10, 2), dtype=np.float32), 10, None, None)


class _CatchingStream:
    """Заглушка устройства: только запоминает колбэк и сразу выходит."""

    def __init__(self, state):
        self.state = state

    def __call__(self, **kwargs):
        self.state["callback"] = kwargs.get("callback")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False