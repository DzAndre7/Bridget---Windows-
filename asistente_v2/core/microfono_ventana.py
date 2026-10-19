# core/microfono_ventana.py
# Captura de micrófono para la interfaz gráfica.
# Graba mientras se mantiene apretado el botón, y transcribe con Whisper al soltar.

import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
import threading
from core.listen import escuchar_audio  # reusamos la transcripción que ya tenés

FRECUENCIA = 16000
ARCHIVO_TEMP = "/tmp/bridget_microfono_ventana.wav"

# Estado de la grabación
_grabando = False
_frames = []
_stream = None
_lock = threading.Lock()


def iniciar_grabacion():
    """Empieza a capturar audio del micrófono. Se llama al apretar el botón."""
    global _grabando, _frames, _stream
    with _lock:
        if _grabando:
            return  # ya está grabando
        _frames = []
        _grabando = True

    def callback(indata, frames_count, time_info, status):
        if _grabando:
            _frames.append(indata.copy())

    _stream = sd.InputStream(
        samplerate=FRECUENCIA,
        channels=1,
        dtype='int16',
        callback=callback
    )
    _stream.start()
    return True


def detener_grabacion():
    """Para la grabación, guarda el audio y lo transcribe. Devuelve el texto."""
    global _grabando, _stream
    with _lock:
        if not _grabando:
            return ""
        _grabando = False

    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None

    if not _frames:
        return ""

    # juntamos todo el audio capturado y lo guardamos
    audio = np.concatenate(_frames, axis=0)
    write(ARCHIVO_TEMP, FRECUENCIA, audio)

    # transcribimos reusando la función que ya tenés
    texto = escuchar_audio(ARCHIVO_TEMP)
    return texto if texto else ""
