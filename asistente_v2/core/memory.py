from core.runtime_paths import data_file
import json
import os
from core.storage import write_json
import threading
import re

_lock = threading.RLock()


def _locked(function):
    from functools import wraps
    @wraps(function)
    def guarded(*args, **kwargs):
        with _lock:
            return function(*args, **kwargs)
    return guarded


DISPARADORES = [
    "me puedes decir",
    "me podes decir",
    "pudes decirme",
    "podes decirme",
    "llamame ",
    "llámame "
]

# Ruta absoluta anclada a la raíz del proyecto (core/ -> asistente_v2/ -> raíz).
# Antes era relativa ("memory.json"), así que apuntaba a un archivo distinto
# según desde qué carpeta se lanzara la app (raíz vs. asistente_v2/ en la web).
MEMORY_FILE = data_file("memory.json", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory.json",
))

def cargar_recuerdos():
    if not os.path.exists(MEMORY_FILE):
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except json.JSONDecodeError as e:
        print(f"Error al decodificar JSON: {e}")
        return []
    except FileNotFoundError as e:
        print(f"Error al abrir archivo: {e}")
        return []

@_locked
def guardar_recuerdo(recuerdo):
    recuerdos = cargar_recuerdos()

    if recuerdo not in recuerdos:
        recuerdos.append(recuerdo)

        write_json(MEMORY_FILE, recuerdos)

        return True
    return False

def leer_recuerdos():
    return cargar_recuerdos()

@_locked
def olvidar_recuerdo(recuerdo):

    recuerdos = cargar_recuerdos()

    if recuerdo in recuerdos:
        recuerdos.remove(recuerdo)

        write_json(MEMORY_FILE, recuerdos)
        return True
    return False

@_locked
def borrar_todos_los_recuerdos():
    write_json(MEMORY_FILE, [])
    return True

def obtener_nombre_preferido():
    recuerdos = cargar_recuerdos()

    patron = re.compile("|".join(DISPARADORES), re.IGNORECASE)

    for recuerdo in recuerdos:
        coincidencia = patron.search(recuerdo)

        if coincidencia:
            nombre = recuerdo[coincidencia.end():].strip(" ,¿?.,;:!")
            if nombre:
                return nombre.title()
    return None
