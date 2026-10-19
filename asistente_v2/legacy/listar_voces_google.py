# listar_voces_google.py
# Le pregunta a Google qué voces de español tiene realmente disponibles.

import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GOOGLE_TTS_API_KEY")

# Endpoint que lista todas las voces disponibles
url = f"https://texttospeech.googleapis.com/v1/voices?key={API_KEY}"

respuesta = requests.get(url)
data = respuesta.json()

# Filtramos solo las de español y las mostramos ordenadas
voces_es = []
for voz in data.get("voices", []):
    for idioma in voz["languageCodes"]:
        if idioma.startswith("es"):
            voces_es.append((idioma, voz["name"], voz["ssmlGender"]))

# Ordenamos por código de idioma y nombre
voces_es.sort()

print(f"Voces de español disponibles: {len(voces_es)}\n")
for idioma, nombre, genero in voces_es:
    print(f"  {idioma:8} | {genero:8} | {nombre}")