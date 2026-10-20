"""Captura acotada por botón. PortAudio selecciona WASAPI/MME/ALSA según el host."""
import threading
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from core.runtime_paths import temporary_file
from core.audio_io import device
from core.listen import escuchar_audio

FRECUENCIA = 16000
_grabando = False
_frames = []
_samples = 0
_stream = None
_lock = threading.Lock()


def iniciar_grabacion():
    global _grabando, _frames, _stream, _samples
    with _lock:
        if _grabando:
            return False
        _frames, _samples = [], 0
        _grabando = True

        def callback(indata, frames_count, time_info, status):
            global _samples
            if _grabando and _samples < FRECUENCIA * 60:
                chunk = indata[:FRECUENCIA * 60 - _samples].copy()
                _frames.append(chunk)
                _samples += len(chunk)

        try:
            _stream = sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype='int16',
                                     device=device('input'), callback=callback)
            _stream.start()
            return True
        except BaseException:
            _grabando = False
            if _stream is not None:
                _stream.close()
                _stream = None
            raise


def detener_grabacion():
    global _grabando, _stream, _frames
    with _lock:
        if not _grabando:
            return ""
        _grabando = False
        if _stream is not None:
            try:
                _stream.stop()
            finally:
                _stream.close()
                _stream = None
        frames, _frames = _frames, []
    if not frames:
        return ""
    audio = np.concatenate(frames, axis=0)
    with temporary_file() as path:
        write(path, FRECUENCIA, audio)
        return escuchar_audio(path) or ""
