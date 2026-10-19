import json
import os
import threading

PREFERENCES_FILE = "preferences.json"
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
    preferencias = cargar_preferencias()
    preferencias[tipo] = valor

    try:
        with lock:  # evita pisadas si dos requests guardan a la vez
            with open(PREFERENCES_FILE, "w", encoding="utf-8") as archivo:
                json.dump(preferencias, archivo, ensure_ascii=False, indent=4)
    except (IOError, PermissionError) as e:
        print(f"Ocurrió un error al guardar la preferencia: {e}")
        return False
    return True

def obtener_preferencia(tipo):
    preferencias = cargar_preferencias()
    return preferencias.get(tipo, None)
