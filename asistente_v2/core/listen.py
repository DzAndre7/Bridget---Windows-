import sounddevice as sd
import numpy as np
import webrtcvad
import warnings
warnings.filterwarnings("ignore")
from scipy.io.wavfile import write

from config import MODELO_STT

# El modelo de voz se carga recién la primera vez que alguien usa la voz,
# no al importar este módulo. Antes, abrir la ventana ya pagaba ese costo
# aunque nunca hablaras — y en una máquina con poca RAM eso disparaba el
# OOM killer contra otras aplicaciones.
#
# Motor: faster-whisper (CTranslate2, int8). Es varias veces más rápido que
# openai-whisper en CPU y con menos RAM, lo que permite subir de "base" a
# "small" — el salto de precisión en español es enorme (con "base" salían
# cosas como "Mola Rick" por "Hola Rick"). Si faster-whisper no está
# instalado, caemos al whisper clásico para no dejar a nadie sin oídos.
_MODELO_WHISPER = None  # tupla (motor, modelo)

def _obtener_whisper():
    global _MODELO_WHISPER
    if _MODELO_WHISPER is None:
        print("(cargando el modelo de voz por primera vez...)")
        try:
            from faster_whisper import WhisperModel
            _MODELO_WHISPER = ("faster", WhisperModel(MODELO_STT, device="cpu", compute_type="int8"))
        except ImportError:
            import whisper
            _MODELO_WHISPER = ("clasico", whisper.load_model(MODELO_STT, device="cpu"))
    return _MODELO_WHISPER


def _transcribir(ruta):
    """Transcripción unificada: mismos resultados llamando por micrófono,
    archivo o fragmento. vad_filter recorta los silencios, que es donde
    whisper alucina texto que nadie dijo ("¡Gracias por ver!")."""
    motor, modelo = _obtener_whisper()
    if motor == "faster":
        segmentos, _ = modelo.transcribe(ruta, language="es", vad_filter=True)
        return " ".join(s.text.strip() for s in segmentos).strip()
    return modelo.transcribe(ruta, language="es")["text"].strip()

ARCHIVO_TEMP = "/tmp/bridget_escucha.wav"
FRECUENCIA = 16000
DURACION_SILENCIO = 1.6 # segundos de silencio para cortar

def escuchar():
    print("🎙️ Escuchando...")

    vad = webrtcvad.Vad(2) #agresividad 0-3

    frames = []
    silencio_frames = 0 
    hablando = False 
    frames_por_segundo = 50 
    frame_duracion = 1000 // frames_por_segundo #ms por frame
    frame_size = FRECUENCIA * frame_duracion // 1000 

    with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype='int16') as stream:
        while True:
            frame, _ = stream.read(frame_size)
            frame_bytes = frame.tobytes()

            es_voz = vad.is_speech(frame_bytes, FRECUENCIA)

            if es_voz:
                hablando = True
                silencio_frames = 0 
                frames.append(frame)
            elif hablando:
                silencio_frames += 1 
                frames.append(frame)

                if silencio_frames > frames_por_segundo * DURACION_SILENCIO:
                    break

    audio = np.concatenate(frames, axis=0)
    write(ARCHIVO_TEMP, FRECUENCIA, audio)

    print(" 🎬 Procesando...")
    return _transcribir(ARCHIVO_TEMP)

def escuchar_audio(ruta_archivo):
    try:
        return _transcribir(ruta_archivo)
    except Exception as e:
        print(f"Error al transcibir: {e}")
        return None

def escuchar_fragmento(duracion=1.5):
    import sounddevice as sd 
    import numpy as np 
    from scipy.io.wavfile import write

    audio = sd.rec(int(duracion * FRECUENCIA), samplerate=FRECUENCIA, channels=1, dtype='int16')
    sd.wait()
    write("/tmp/bridget_fragmento.wav", FRECUENCIA, audio)
    return _transcribir("/tmp/bridget_fragmento.wav").lower()