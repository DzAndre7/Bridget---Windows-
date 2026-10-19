"""
Ruta híbrida de pensamiento: dolphin3 local lleva la charla del día a día,
pero cuando el usuario pide pensar EN SERIO ("pensalo bien", "modo
profundo"), la pregunta viaja al modelo grande (MODELO_REVISOR, un 70B vía
Groq) — el mismo revisor externo que ya usaba code_reviewer, ahora también
para conversación. Si no hay internet o API key, devuelve None y el que
llama decide el fallback (responder con el modelo local, avisando).
"""

import os

from dotenv import load_dotenv

from config import MODELO_REVISOR, ASSISTANT_NAME, ASSISTANT_CREATOR

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Cuántos mensajes recientes de la charla local acompañan a la pregunta:
# suficiente para que el 70B entienda de qué venían hablando, sin mandarle
# la sesión entera a un servicio externo.
MENSAJES_DE_CONTEXTO = 6
MAX_CHARS_POR_MENSAJE = 1000


def _mensajes(pregunta, historial, extenso=True):
    sistema = (
        f"Sos {ASSISTANT_NAME}, el asistente personal de {ASSISTANT_CREATOR}. "
        "Te pidieron pensar esto EN PROFUNDIDAD: razoná con calma, considerá "
        "ángulos que no sean obvios, sé honesto con las dudas y respondé en "
        "español rioplatense, claro y sin relleno. "
    )
    if extenso:
        # pedido explícito ("pensalo bien"): que se explaye
        sistema += "Podés extenderte lo que haga falta."
    else:
        # derivación automática: misma calidad de razonamiento, pero con el
        # formato de charla de siempre — la respuesta se escucha por voz y
        # el usuario no pidió un ensayo
        sistema += (
            "FORMATO: máximo dos o tres párrafos cortos, sin listas ni "
            "viñetas, texto corrido natural, como una persona inteligente "
            "charlando."
        )
    mensajes = [{"role": "system", "content": sistema}]
    for m in (historial or [])[-MENSAJES_DE_CONTEXTO:]:
        rol = m.get("role")
        if rol in ("user", "assistant"):
            mensajes.append({"role": rol, "content": str(m.get("content", ""))[:MAX_CHARS_POR_MENSAJE]})
    mensajes.append({"role": "user", "content": pregunta})
    return mensajes


def pensar_profundo(pregunta, historial=None, extenso=True):
    """Consulta al modelo grande. `extenso=False` es la derivación
    automática: misma profundidad, formato corto de charla. Devuelve el
    texto de la respuesta, o None si no se pudo (sin key, sin internet,
    error del servicio): nunca lanza, porque la charla tiene que seguir
    aunque el mundo exterior falle."""
    if not GROQ_API_KEY:
        return None
    try:
        from groq import Groq  # import perezoso: el módulo se importa en cada arranque
        cliente = Groq(api_key=GROQ_API_KEY)
        respuesta = cliente.chat.completions.create(
            model=MODELO_REVISOR,
            messages=_mensajes(pregunta, historial, extenso=extenso),
        )
        return respuesta.choices[0].message.content
    except Exception as e:
        print(f"DEBUG PENSADOR ERROR: {e}")
        return None
