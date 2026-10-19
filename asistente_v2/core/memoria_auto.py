"""
Memoria proactiva: detecta datos durables del usuario en la charla y los
guarda sola en la memoria semántica, sin que haga falta decir "recordá que".
(Antes la memoria era 100% pasiva: en meses de uso juntó 11 datos.)

Diseño en dos niveles, el mismo patrón que intenciones.py:
1. Heurística (parece_dato_personal): regex baratos con marcadores de
   primera persona. Corre en CADA turno, así que tiene que ser gratis.
   Si no hay marcador, no se molesta al modelo.
2. LLM (extraer_dato): reformula el dato en tercera persona, o contesta
   NADA si en realidad no había nada durable ("tengo una duda" no es un
   dato de la vida del usuario).

El guardado deduplica por similitud de embeddings contra la memoria
existente: si ya hay un recuerdo casi igual, no se guarda de nuevo.
brain.py llama a procesar_turno() en un hilo aparte DESPUÉS de responder,
así que nada de esto agrega latencia al turno de conversación.
"""

import re

from core import memoria_semantica

# Marcadores de primera persona que sugieren un dato durable del usuario.
# Deliberadamente conservadores: un falso positivo solo gasta una llamada
# al modelo en segundo plano; un marcador demasiado amplio la gastaría en
# cada turno.
_MARCADORES = [
    r"\bme llamo\b", r"\bme dicen\b", r"\bmi nombre es\b",
    r"\bme gusta\b", r"\bno me gusta\b", r"\bme encanta\b", r"\bodio\b",
    r"\bprefiero\b", r"\bsoy\b", r"\btengo\b", r"\bvivo en\b",
    r"\btrabajo\b", r"\bestudio\b", r"\bmi cumpleaños\b", r"\bcumplo\b",
    r"\bmi (?:hermana|hermano|vieja|viejo|madre|padre|novia|novio|amigo|amiga|perro|perra|gato|gata)\b",
]

# Similitud coseno (documento contra documento) a partir de la cual dos
# recuerdos se consideran el mismo dato y no se vuelve a guardar.
UMBRAL_DUPLICADO = 0.9


def parece_dato_personal(texto):
    """Nivel 1: ¿el mensaje tiene pinta de traer un dato personal? Solo
    regex, sin modelo: esto corre en cada turno de conversación."""
    t = texto.lower()
    return any(re.search(m, t) for m in _MARCADORES)


def extraer_dato(texto_usuario, funcion_llm):
    """Nivel 2: le pide al modelo el dato durable del mensaje, reformulado
    en tercera persona ("El usuario vive en Córdoba"). Devuelve None si el
    modelo decide que no había nada que recordar."""
    prompt = (
        "Del siguiente mensaje de un usuario a su asistente, extraé UN dato "
        "personal durable que valga la pena recordar a futuro (gustos, datos "
        "de su vida, personas cercanas, fechas importantes). Reformulalo en "
        "tercera persona, corto y literal, empezando con 'El usuario'. Si no "
        "hay ningún dato durable (charla pasajera, preguntas, pedidos), "
        "respondé exactamente NADA.\n\n"
        f"Mensaje: \"{texto_usuario}\"\n\n"
        "Dato:"
    )
    respuesta = (funcion_llm(prompt) or "").strip().strip('"')
    # respuestas largas suelen ser al modelo "explicando" en vez de extraer
    if not respuesta or respuesta.upper().startswith("NADA") or len(respuesta) > 200:
        return None
    return respuesta


def guardar_si_es_nuevo(dato):
    """Guarda el dato en la memoria semántica salvo que ya exista uno casi
    idéntico. El dedupe compara embeddings de documento contra documento
    (mismo prefijo que los guardados: un texto idéntico da similitud 1.0).
    Devuelve True si efectivamente guardó."""
    memoria = memoria_semantica.cargar_memoria()
    if memoria:
        embedding = memoria_semantica.obtener_embedding(dato)
        parecidos = memoria_semantica.puntuar_memoria(
            memoria, embedding, top_k=1, umbral=UMBRAL_DUPLICADO
        )
        if parecidos:
            return False
    memoria_semantica.guardar_recuerdo(dato, categoria="auto")
    return True


def procesar_turno(texto_usuario, funcion_llm):
    """Pipeline completo para un turno: heurística -> LLM -> dedupe ->
    guardar. Pensado para correr en segundo plano: NUNCA lanza, porque un
    error acá no puede romper (ni ensuciar) la conversación."""
    try:
        if not parece_dato_personal(texto_usuario):
            return False
        dato = extraer_dato(texto_usuario, funcion_llm)
        if not dato:
            return False
        return guardar_si_es_nuevo(dato)
    except Exception:
        return False
