import subprocess
import os
import sys
import base64
import uuid
import tempfile
import threading
import queue
import requests
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

import builtins
_print_original = builtins.print

def _print_seguro(*args, **kwargs):
    try:
        _print_original(*args, **kwargs)
    except UnicodeEncodeError:
        pass

builtins.print = _print_seguro

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

AUDIO_SALIDA = "/tmp/bridget_respuesta.wav"

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
            _tts_local = TTS(model_name="tts_models/es/css10/vits", progress_bar=False).to("cuda")
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
        respuesta = requests.post(GOOGLE_URL, json=payload, timeout=15)
        if respuesta.status_code == 200:
            audio_bytes = base64.b64decode(respuesta.json()["audioContent"])
            with open(salida, "wb") as f:
                f.write(audio_bytes)
            return True
        else:
            _print_original(f"Google TTS error {respuesta.status_code}, usando voz local.")
            return False
    except Exception as e:
        _print_original(f"Google TTS falló ({e}), usando voz local.")
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

def _generar(texto, salida=AUDIO_SALIDA):
    """Genera el audio en `salida`: prueba Google primero, cae a Coqui si falla."""
    if _generar_google(texto, salida):
        return True
    return _generar_coqui(texto, salida)

def hablar(texto):
    # Reproducción local (secuencial): un solo archivo fijo está bien.
    if _generar(texto, AUDIO_SALIDA):
        subprocess.run(["paplay", AUDIO_SALIDA])

def hablar_interrumpible(texto):
    if _generar(texto, AUDIO_SALIDA):
        proceso = subprocess.Popen(["paplay", AUDIO_SALIDA])
        return proceso
    return None

def generar_audio(texto):
    """Genera audio sin reproducir y retorna la ruta. Usa un archivo ÚNICO por
    llamada: así dos requests concurrentes de la API (/speak) no se pisan el wav."""
    salida = os.path.join(tempfile.gettempdir(), f"bridget_tts_{uuid.uuid4().hex}.wav")
    if _generar(texto, salida):
        return salida
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
            subprocess.run(["paplay", ruta])
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

    hilo.join(timeout=2)
    return " ".join(habladas)