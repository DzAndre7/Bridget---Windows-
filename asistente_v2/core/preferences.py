from core.runtime_paths import data_file
import json
import os
from core.storage import write_json
import threading

PREFERENCES_FILE = data_file("preferences.json", "preferences.json")
lock = threading.Lock()

def cargar_preferencias():
    if not os.path.exists(PREFERENCES_FILE):
        return {}

    try:
        with open(PREFERENCES_FILE, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def guardar_preferencia(tipo, valor):
    try:
        with lock:
            preferencias = cargar_preferencias()
            preferencias[tipo] = valor
            write_json(PREFERENCES_FILE, preferencias)
    except (OSError, ValueError):
        return False
    return True


def obtener_preferencia(tipo):
    preferencias = cargar_preferencias()
    return preferencias.get(tipo, None)
