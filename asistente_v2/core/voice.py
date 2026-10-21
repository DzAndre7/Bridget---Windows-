import os
import sys
import base64
import threading
import queue
from contextlib import contextmanager
from dotenv import load_dotenv
from config import ENV_FILE

from core.runtime_paths import temporary_file
from core.audio_io import play_wav

load_dotenv(ENV_FILE)

_print_original = print

@contextmanager
def silenciar_salida():
    with open(os.devnull, "w") as devnull:
        viejo_stdout = sys.stdout
        viejo_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = viejo_stdout
            sys.stderr = viejo_stderr


# --- Configuración de Google TTS (voz principal) ---
GOOGLE_API_KEY = os.getenv("GOOGLE_TTS_API_KEY")
GOOGLE_URL = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_API_KEY}"
VOZ_GOOGLE = "es-US-Chirp3-HD-Enceladus"
IDIOMA_GOOGLE = "es-US"

# --- Coqui (voz de respaldo) se carga SOLO si hace falta ---
_tts_local = None  # arranca en None; se carga la primera vez que falle Google

def _cargar_coqui():
    """Carga Coqui solo cuando se necesita (respaldo). Así no ocupa GPU de gusto."""
    global _tts_local
    if _tts_local is None:
        from TTS.api import TTS
        with silenciar_salida():
            import torch
            dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
            _tts_local = TTS(model_name="tts_models/es/css10/vits", progress_bar=False).to(dispositivo)
    return _tts_local

def _generar_google(texto, salida):
    """Intenta generar el audio con Google en `salida`. Devuelve True si lo logró."""
    if not GOOGLE_API_KEY:
        return False
    payload = {
        "input": {"text": texto},
        "voice": {"languageCode": IDIOMA_GOOGLE, "name": VOZ_GOOGLE},
        "audioConfig": {"audioEncoding": "LINEAR16"}
    }
    try:
        import requests
        respuesta = requests.post(GOOGLE_URL, json=payload, timeout=15)
        if respuesta.status_code == 200:
            audio_bytes = base64.b64decode(respuesta.json()["audioContent"])
            with open(salida, "wb") as f:
                f.write(audio_bytes)
            return True
        else:
            _print_original(f"Google TTS error {respuesta.status_code}, usando voz local.")
            return False
    except Exception:
        _print_original("Google TTS no disponible, usando voz local.")
        return False

def _generar_coqui(texto, salida):
    """Respaldo: genera con Coqui local en `salida`."""
    try:
        modelo = _cargar_coqui()
        with silenciar_salida():
            modelo.tts_to_file(text=texto, file_path=salida)
        return True
    except Exception as e:
        _print_original(f"Error generando audio local: {e}")
        return False

def _generar(texto, salida):
    """auto: Google si fue configurado, SAPI en Windows y Coqui de respaldo.

    BRIDGET_TTS=windows/coqui/google fuerza proveedor. No descarga modelos al importar.
    """
    provider = os.environ.get("BRIDGET_TTS", "auto").casefold()
    if provider not in {"auto", "windows", "google", "coqui"}:
        raise ValueError("BRIDGET_TTS debe ser auto/windows/google/coqui")
    if provider in {"auto", "google"} and _generar_google(texto, salida):
        return True
    if provider == "google":
        return False
    if provider == "windows" or (provider == "auto" and sys.platform == "win32"):
        try:
            from core.windows_native import synthesize
            synthesize(texto, salida)
            return os.path.getsize(salida) > 44
        except Exception:
            if provider == "windows":
                return False
    return _generar_coqui(texto, salida)


def hablar(texto):
    with temporary_file() as path:
        if _generar(texto, path):
            play_wav(path)


def hablar_interrumpible(texto):
    path = generar_audio(texto)
    return play_wav(path, blocking=False, cleanup=True) if path else None


def generar_audio(texto):
    """El receptor es responsable de borrar el WAV devuelto (API/UI/reproductor)."""
    import tempfile
    fd, path = tempfile.mkstemp(prefix="bridget_tts_", suffix=".wav")
    os.close(fd)
    try:
        if _generar(texto, path):
            return path
    except BaseException:
        os.unlink(path)
        raise
    os.unlink(path)
    return None


def hablar_por_frases(frases):
    """Sintetiza y reproduce una secuencia de frases en PIPELINE: mientras suena
    una frase, ya se va sintetizando la siguiente. Bloquea hasta terminar de
    hablar todo. Sirve como 'sink' de streaming: al consumir el iterable `frases`
    (que es un generador conectado al stream del LLM) va tirando de la generación.

    Devuelve el texto realmente hablado (útil para acumular/loguear).
    """
    cola = queue.Queue(maxsize=8)
    FIN = object()
    habladas = []

    def _productor():
        # sintetiza en un hilo aparte y encola (frase, ruta_wav)
        try:
            for frase in frases:
                frase = (frase or "").strip()
                if not frase:
                    continue
                try:
                    ruta = generar_audio(frase)
                except Exception as e:
                    _print_original(f"TTS falló en una frase: {e}")
                    ruta = None
                if ruta:
                    cola.put((frase, ruta))
        finally:
            cola.put(FIN)  # SIEMPRE cerramos la cola, aunque algo falle

    hilo = threading.Thread(target=_productor, daemon=True)
    hilo.start()

    # el hilo principal reproduce en orden; borra cada wav temporal al terminarlo
    while True:
        item = cola.get()
        if item is FIN:
            break
        frase, ruta = item
        habladas.append(frase)
        try:
            play_wav(ruta)
        except Exception:
            _print_original("No se pudo reproducir una frase; revisar dispositivo de salida.")
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

    hilo.join(timeout=2)
    return " ".join(habladas)
