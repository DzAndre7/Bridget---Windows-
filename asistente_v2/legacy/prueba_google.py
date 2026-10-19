# prueba_google.py
# Prueba de Google Cloud TTS. Liviano: solo una llamada web, sin modelos pesados.

import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOOGLE_TTS_API_KEY")
if not API_KEY:
    raise ValueError("Falta GOOGLE_TTS_API_KEY en el .env")

# El texto que va a decir
texto = (
    "Hola usuario, soy Bridget. Esta es mi nueva voz, generada con Google. "
    "Estuve revisando tus notas sobre Nmap y puedo ayudarte cuando quieras. "
    "Decime si este tono te resulta cómodo."
)

# La URL de la API de Google TTS, con tu clave
url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={API_KEY}"

# Configuración de la voz y el audio
# Probamos varias voces masculinas en español latino, con tono más grave y suave
voces = [
    "es-US-Chirp3-HD-Charon",
    "es-US-Chirp3-HD-Enceladus",
    "es-US-Chirp3-HD-Iapetus",
    "es-US-Chirp3-HD-Schedar",
    "es-US-Chirp3-HD-Umbriel",
]

for voz in voces:
    payload = {
        "input": {"text": texto},
        "voice": {
            "languageCode": "es-US",
            "name": voz
        },
        "audioConfig": {
        "audioEncoding": "LINEAR16"
        }
    }

    print(f"Generando con {voz}...")
    respuesta = requests.post(url, json=payload)

    if respuesta.status_code == 200:
        audio_base64 = respuesta.json()["audioContent"]
        audio_bytes = base64.b64decode(audio_base64)
        nombre = f"prueba_{voz}.wav"
        with open(nombre, "wb") as f:
            f.write(audio_bytes)
        print(f"  ✅ {nombre}")
    else:
        print(f"  ❌ Error {respuesta.status_code}: {respuesta.text}")