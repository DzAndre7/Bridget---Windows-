import pyautogui
import time
import ollama
import os
import glob
from core.vision import capturar_pantalla, ver_pantalla
from config import ASSISTANT_NAME, MODELO_RAPIDO, KEEP_ALIVE

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.5
DEBUG_MODE = False

ALIAS_PROGRAMAS = {
    "visual studio code": "code",
    "vs code": "code",
    "vscode": "code",
    "firefox": "firefox",
    "chrome": "google-chrome-stable",
    "spotify": "spotify",
    "discord": "discord",
    "terminal": "alacritty",
}

def buscar_aplicaciones_sistema(termino):
    termino = termino.lower()
    resultados = []

    # Buscar en /usr/share/applications/
    archivos = glob.glob("/usr/share/applications/*.desktop")
    if DEBUG_MODE: 
        print(f"DEBUG: encontrados {len(archivos)} archivos .desktop")
    for archivo in archivos:
        try: 
            with open(archivo, "r", encoding="utf-8") as f:
                contenido = f.read()
                nombre = "" 
                comando = "" 
                for linea in contenido.splitlines():
                    if linea.startswith("Name=") and not nombre:
                        nombre = linea.split("=", 1)[1].strip().lower()
                    if linea.startswith("Exec=") and not comando:
                        comando = linea.split("=", 1)[1].strip().split()[0]
                if termino in nombre: 
                    if DEBUG_MODE:
                        print(f"DEBUG MATCH: nombre='{nombre}' comando='{comando}'")
                if termino in nombre and comando:
                    resultados.append((nombre, comando))
        except:
            continue
    return resultados    

def clickear(x, y):
    pyautogui.click(x, y)

def escribir(texto):
    pyautogui.write(texto, interval=0.05)

def presionar(tecla):
    pyautogui.press(tecla)

def esperar(segundos):
    time.sleep(segundos)
def planificar_tarea(instruccion):
    prompt = f"""
Sos {ASSISTANT_NAME}, un agente que controla una PC con Arch Linux.
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
