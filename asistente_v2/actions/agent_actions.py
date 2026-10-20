import time
from core.local_models import ollama
from core.app_permissions import find_apps, require_automation
from config import ASSISTANT_NAME, MODELO_RAPIDO, KEEP_ALIVE

DEBUG_MODE = False
ALIAS_PROGRAMAS = {}  # Compatibilidad de imports; la autoridad es la allowlist local.


def buscar_aplicaciones_sistema(termino):
    return find_apps(termino)


def _desktop(confirmed):
    require_automation(confirmed)
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.5
    return pyautogui


def clickear(x, y, *, confirmado=False):
    _desktop(confirmado).click(x, y)


def escribir(texto, *, confirmado=False):
    _desktop(confirmado).write(texto, interval=0.05)


def presionar(tecla, *, confirmado=False):
    _desktop(confirmado).press(tecla)


def esperar(segundos):
    time.sleep(segundos)
def planificar_tarea(instruccion):
    prompt = f"""
Sos {ASSISTANT_NAME}, un asistente que propone acciones para la plataforma actual.
Tarea solicitada: {instruccion}

Describí en lenguaje natural y de forma concisa los pasos que vas a seguir para completar la tarea.
No ejecutes nada todavía, solo describí el plan.
"""
    respuesta = ollama.chat(
        model=MODELO_RAPIDO,
        messages=[{"role": "user", "content": prompt}],
        keep_alive=KEEP_ALIVE,
    )
    return respuesta["message"]["content"]

def extraer_programa_con_llama(texto):
    respuesta = ollama.chat(
        model=MODELO_RAPIDO,
        messages=[{
            "role": "user",
            "content": f"Extraé SOLO el nombre de la aplicación mencionada en este texto, una o dos palabras máximo, sin explicaciones, sin comandos, sin comillas. Solo el nombre. Texto: '{texto}'"
        }],
        keep_alive=KEEP_ALIVE,
    )
    resultado = respuesta["message"]["content"].strip().lower()
    if DEBUG_MODE: 
        print (f"DEBUG EXTRACCION: '{resultado}'")
    return resultado
