import json 
import os 
import re 

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
MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory.json",
)

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
    
def guardar_recuerdo(recuerdo):
    recuerdos = cargar_recuerdos() 

    if recuerdo not in recuerdos: 
        recuerdos.append(recuerdo)

        with open(MEMORY_FILE, "w", encoding="utf-8") as archivo: json.dump(recuerdos, archivo, ensure_ascii=False, indent=4)

        return True
    return False

def leer_recuerdos():
    return cargar_recuerdos()

def olvidar_recuerdo(recuerdo):

    recuerdos = cargar_recuerdos()

    if recuerdo in recuerdos:
        recuerdos.remove(recuerdo)

        with open(MEMORY_FILE, "w", encoding="utf-8") as archivo: json.dump(recuerdos, archivo, ensure_ascii=False, indent=4)
        return True
    return False

def borrar_todos_los_recuerdos():
    with open(MEMORY_FILE, "w", encoding="utf-8") as archivo: json.dump([], archivo, ensure_ascii=False, indent=4)
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