import sys 
import datetime 
sys.stdout.reconfigure(encoding="utf-8")

from config import ASSISTANT_NAME, ASSISTANT_CREATOR
import core.brain as brain
from core.brain import procesar_comando, consultar_llama, usar_sink_de_frases
from core import sesiones
from core.memory import obtener_nombre_preferido, guardar_recuerdo
from core.voice import hablar, hablar_interrumpible, hablar_por_frases
from core.listen import escuchar

VOZ_ACTIVADA = True


def _hablar_respuesta(respuesta):
    """Habla una respuesta que NO pasó por el streaming (intención determinística).
    Si el turno ya se resolvió por streaming, no hace nada: ya se habló en vivo."""
    if brain.ULTIMO_TURNO_STREAMEADO:
        return
    if "```" in respuesta:
        hablar("Revisá el código en pantalla.")
    else:
        hablar(limpiar_para_tts(respuesta))

def limpiar_para_tts(texto):
    import re
    texto = re.sub(r'\*+', '', texto)  # quita asteriscos
    texto = re.sub(r'^\d+\.\s', '', texto, flags=re.MULTILINE)  # quita numeración
    texto = re.sub(r'^[-•]\s', '', texto, flags=re.MULTILINE)  # quita viñetas
    texto = re.sub(r'`+', '', texto)  # quita comillas de código
    return texto.strip()

def obtener_saludo(): 
    hora = datetime.datetime.now().hour 

    if 5 <= hora < 12:
        return "Buenos días, estoy listo para arrancar."

    elif 12 <= hora < 18:
        return "Buenas tardes, listo cuando vos quieras."

    else: 
        return "Buenas noches, decime qué hacemos hoy."

def modo_voz(sesion=None):
    print(f"{ASSISTANT_NAME}: Modo voz activado. Decí 'salir del modo voz' para volver.")
    hablar("Modo voz activado. Te escucho.")
    # streaming: las respuestas del LLM se hablan por frases a medida que se generan
    usar_sink_de_frases(hablar_por_frases)

    while True:
        texto = escuchar()

        if not texto or not texto.strip():
            continue

        nombre_usuario = obtener_nombre_preferido() or "Usuario"
        print(f"{nombre_usuario} (voz): {texto}")

        texto_lower = texto.lower()
        if "salir" in texto_lower and ("voz" in texto_lower or "boss" in texto_lower or "modo" in texto_lower):
            usar_sink_de_frases(None)
            hablar("Saliendo del modo voz.")
            print(f"{ASSISTANT_NAME}: Modo voz desactivado.")
            break

        respuesta = procesar_comando(texto, ASSISTANT_NAME, sesion)
        print(f"{ASSISTANT_NAME}: {respuesta}")
        _hablar_respuesta(respuesta)

import threading

def modo_voz_interrumpible(sesion=None):
    from core.listen import escuchar_fragmento
    print(f"{ASSISTANT_NAME}: Modo voz activado. Decí 'salir del modo voz' para volver.")
    hablar("Modo voz activado. Te escucho.")
    # este modo usa su propia reproducción interrumpible (barge-in) sobre la
    # respuesta completa, así que desactivamos el sink de streaming por frases.
    usar_sink_de_frases(None)

    while True:
        texto = escuchar()

        if not texto or not texto.strip():
            continue

        nombre_usuario = obtener_nombre_preferido() or "Usuario"
        print(f"{nombre_usuario} (voz): {texto}")

        texto_lower = texto.lower()
        if "salir" in texto_lower and ("voz" in texto_lower or "boss" in texto_lower or "modo" in texto_lower):
            hablar("Saliendo del modo voz.")
            print(f"{ASSISTANT_NAME}: Modo voz desactivado.")
            break

        respuesta = procesar_comando(texto, ASSISTANT_NAME, sesion)
        print(f"{ASSISTANT_NAME}: {respuesta}")

        if "```" in respuesta:
            hablar("Revisá el código en pantalla.")
            continue

        # --- Reprocucción interrumpible ---
        interrumpido = threading.Event()

        def vigilar_interrupcion():
            while not interrumpido.is_set():
                fragmento = escuchar_fragmento(1.0)
                if any(palabra in fragmento for palabra in ["para", "pará", "pera", "par", "pala", "stop", "basta", "callate", "calla"]):
                    interrumpido.set()
                    break
        
        proceso_audio = hablar_interrumpible(limpiar_para_tts(respuesta))

        hilo_vigilancia = threading.Thread(target=vigilar_interrupcion, daemon=True)
        hilo_vigilancia.start()

        while proceso_audio.poll() is None: 
            if interrumpido.is_set():
                proceso_audio.terminate()
                hablar("¿Qué pasó? Te escucho...")
                break
        
        interrumpido.set() 
        hilo_vigilancia.join(timeout=0.5)

def main():
    # Sesión persistente: chat nuevo que recuerda el anterior (core/sesiones.py).
    # Con funcion_llm, la charla anterior se resume a memoria semántica en
    # segundo plano (sesiones.indexar_charla).
    sesion = sesiones.abrir_sesion(assistant_name=ASSISTANT_NAME, funcion_llm=brain._llm_directo)
    # Recordatorios: el hilo avisador habla y notifica cuando vencen.
    from core import agenda
    agenda.iniciar_avisador()
    if sesion.historial_anterior:
        print("— de la sesión anterior —")
        for mensaje in sesion.historial_anterior[-4:]:
            quien = "Vos" if mensaje.get("role") == "user" else ASSISTANT_NAME
            contenido = " ".join(str(mensaje.get("content", "")).split())
            if len(contenido) > 120:
                contenido = contenido[:120] + "…"
            print(f"  {quien}: {contenido}")
        print("— hoy —")

    saludo = obtener_saludo()
    print(f"{ASSISTANT_NAME}: {saludo}")

    while True:
        # cada turno arranca sin sink; se instala solo para el chat normal de abajo
        usar_sink_de_frases(None)
        nombre_usuario = obtener_nombre_preferido() or ASSISTANT_CREATOR
        user_input = input(f"{nombre_usuario}: ")

        if user_input.lower().strip() == "escuchame": 
            user_input = escuchar()
            print(f"{nombre_usuario} (voz): {user_input}")

        if user_input.lower().strip() in ["modo voz", "modo audio", "manos libres"]:
            modo_voz_interrumpible(sesion)
            continue

        if user_input.lower().strip() in ["activar voz", "activá voz", "modo texto", "silencio", "callate"]:
            global VOZ_ACTIVADA
            VOZ_ACTIVADA = not VOZ_ACTIVADA
            estado = "activada" if VOZ_ACTIVADA else "desactivada"
            print(f"{ASSISTANT_NAME}: Voz {estado}.")
            continue

        if user_input.lower() in ["salir", "exit", "quit", "adiós", "adios"]:
            print(f"{ASSISTANT_NAME}: Nos vemos.")
            break

        elif user_input.lower() in ["cerrar", "fin sesion", "fin sesión"]:
            resumen = consultar_llama("Hacé un resumen breve de los temas importantes que hablamos en esta sesión. Si no hablamos de nada relevante, decilo.", sesion)
            print(f"{ASSISTANT_NAME}: {resumen}")
            hablar(resumen)
            confirmacion = input("Querés guardar este resumen en la memoria? (si/no): ")
            if confirmacion.strip().lower() in ["si", "sí", "s", "yes"]:
                guardar_recuerdo(resumen)
                print(f"{ASSISTANT_NAME}: Resumen guardado.")
            print(f"{ASSISTANT_NAME}: Nos vemos.")
            break

        # streaming por frases solo si la voz está activada
        usar_sink_de_frases(hablar_por_frases if VOZ_ACTIVADA else None)
        respuesta = procesar_comando(user_input, ASSISTANT_NAME, sesion)
        if respuesta is None:
            respuesta = "No pude generar una respuesta."
        print(f"{ASSISTANT_NAME}: {respuesta}")
        if VOZ_ACTIVADA:
            _hablar_respuesta(respuesta)

if __name__ == "__main__":
    main()