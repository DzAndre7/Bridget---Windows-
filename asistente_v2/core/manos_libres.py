# core/manos_libres.py
# Ciclo de escucha continua para el modo manos libres.
# Escucha, detecta voz y silencio (webrtcvad), transcribe, y avisa a la ventana.

import sounddevice as sd
import numpy as np
import webrtcvad
import threading
from scipy.io.wavfile import write
from core.listen import escuchar_audio  # reusamos la transcripción

FRECUENCIA = 16000
ARCHIVO_TEMP = "/tmp/bridget_manoslibres.wav"
DURACION_SILENCIO = 1.6  # segundos de silencio para cortar (igual que listen.py)

# Estado del modo
_activo = False
_pausado = False  # se pausa mientras Bridget habla (clave para no escucharse)
_hilo = None
_ventana = None  # referencia a la ventana de pywebview para avisarle


def configurar_ventana(ventana):
    """Guarda la referencia a la ventana para poder ejecutar JS desde el hilo."""
    global _ventana
    _ventana = ventana


def iniciar():
    """Activa el modo manos libres: arranca el ciclo de escucha en un hilo."""
    global _activo, _hilo
    if _activo:
        return
    _activo = True
    _hilo = threading.Thread(target=_ciclo, daemon=True)
    _hilo.start()


def detener():
    """Desactiva el modo manos libres."""
    global _activo
    _activo = False


def pausar():
    """Pausa la escucha (mientras Bridget habla, para no escucharse a sí misma)."""
    global _pausado
    _pausado = True


def reanudar():
    """Reanuda la escucha después de que Bridget terminó de hablar."""
    global _pausado
    _pausado = False


def _ciclo():
    """El ciclo principal: escucha, detecta, transcribe, avisa. Corre en un hilo."""
    vad = webrtcvad.Vad(2)
    frames_por_segundo = 50
    frame_duracion = 1000 // frames_por_segundo
    frame_size = FRECUENCIA * frame_duracion // 1000

    while _activo:
        # Si está pausado (Bridget hablando), esperamos sin escuchar
        if _pausado:
            sd.sleep(100)
            continue

        # Escuchamos hasta detectar una frase completa (voz + silencio final)
        frames = []
        silencio_frames = 0
        hablando = False

        try:
            with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype='int16') as stream:
                while _activo and not _pausado:
                    frame, _ = stream.read(frame_size)
                    frame_bytes = frame.tobytes()

                    try:
                        es_voz = vad.is_speech(frame_bytes, FRECUENCIA)
                    except Exception:
                        es_voz = False

                    if es_voz:
                        hablando = True
                        silencio_frames = 0
                        frames.append(frame)
                    elif hablando:
                        silencio_frames += 1
                        frames.append(frame)
                        if silencio_frames > frames_por_segundo * DURACION_SILENCIO:
                            break  # terminó la frase
        except Exception as e:
            print(f"Error en escucha manos libres: {e}")
            sd.sleep(200)
            continue

        # Si no se capturó nada (o se desactivó), seguimos
        if not frames or not _activo or _pausado:
            continue

        # Guardamos y transcribimos
        audio = np.concatenate(frames, axis=0)
        write(ARCHIVO_TEMP, FRECUENCIA, audio)
        texto = escuchar_audio(ARCHIVO_TEMP)

        # Si transcribió algo, avisamos a la ventana para que lo procese
        if texto and texto.strip() and _ventana is not None:
            pausar()
            # Escapamos el texto para meterlo seguro en JS
            texto_seguro = texto.strip().replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
            try:
                _ventana.evaluate_js(f"window.recibirVozManosLibres('{texto_seguro}')")
            except Exception as e:
                print(f"Error avisando a la ventana: {e}")
