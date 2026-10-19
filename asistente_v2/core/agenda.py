"""
Agenda y recordatorios: "recordame mañana a las nueve llamar al médico".

Tres piezas:
1. Almacenamiento: asistente_v2/agenda.json, una lista de recordatorios
   {id, texto, cuando (ISO), creado, avisado}. Escritura atómica, como
   las sesiones.
2. Extracción (extraer_recordatorio): el modelo convierte el lenguaje
   natural ("mañana a la tarde", "el viernes a las 8") en una fecha
   absoluta, con la fecha/hora actual como referencia en el prompt. El
   formato de respuesta es rígido (FECHA:/TEXTO:) y la validación es
   nuestra: fecha bien formada y en el futuro, o no se agenda nada.
3. Avisador (iniciar_avisador): un hilo daemon revisa la agenda cada
   INTERVALO_AVISADOR segundos y, cuando un recordatorio vence, lo dice
   por voz y manda una notificación de escritorio. El TTS se importa
   perezoso adentro del aviso: importar este módulo no carga nada pesado.
"""

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta

AGENDA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agenda.json"
)

INTERVALO_AVISADOR = 20  # segundos entre revisiones de la agenda

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# --- Almacenamiento ----------------------------------------------------------

def cargar_agenda():
    if not os.path.exists(AGENDA_FILE):
        return []
    try:
        with open(AGENDA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _guardar_agenda(items):
    temporal = AGENDA_FILE + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(temporal, AGENDA_FILE)


def agendar(texto, cuando):
    """Agrega un recordatorio. `cuando` es un datetime o un string ISO."""
    if isinstance(cuando, datetime):
        cuando = cuando.isoformat(timespec="minutes")
    items = cargar_agenda()
    item = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "texto": texto,
        "cuando": cuando,
        "creado": datetime.now().isoformat(timespec="minutes"),
        "avisado": False,
    }
    items.append(item)
    _guardar_agenda(items)
    return item


def pendientes():
    """Recordatorios aún no avisados, del más próximo al más lejano."""
    return sorted(
        (r for r in cargar_agenda() if not r.get("avisado")),
        key=lambda r: r["cuando"],
    )


def vencidos(ahora=None):
    """Pendientes cuya hora ya pasó: son los que hay que avisar."""
    ahora = (ahora or datetime.now()).isoformat(timespec="minutes")
    return [r for r in pendientes() if r["cuando"] <= ahora]


def marcar_avisado(id_item):
    items = cargar_agenda()
    for r in items:
        if r["id"] == id_item:
            r["avisado"] = True
    _guardar_agenda(items)


def cancelar(id_item):
    """Saca un recordatorio de la agenda. Devuelve True si existía."""
    items = cargar_agenda()
    filtrados = [r for r in items if r["id"] != id_item]
    if len(filtrados) == len(items):
        return False
    _guardar_agenda(filtrados)
    return True


def buscar(fragmento):
    """Pendientes cuyo texto comparte alguna palabra significativa con
    `fragmento` (para "cancelá el recordatorio del médico"). Las palabras
    del pedido en sí (cancelar, recordatorio...) no cuentan como match."""
    ruido = {
        "cancela", "cancelá", "cancelar", "borra", "borrá", "borrar",
        "elimina", "eliminá", "saca", "sacá", "recordatorio", "recordatorios",
        "alarma", "alarmas", "agenda", "para", "sobre",
    }
    palabras = {
        p.strip("¿?¡!.,;:") for p in fragmento.lower().split()
        if len(p.strip("¿?¡!.,;:")) > 3
    } - ruido
    if not palabras:
        return []
    return [
        r for r in pendientes()
        if palabras & {w.strip(".,;:") for w in r["texto"].lower().split()}
    ]


def formatear(cuando):
    """'2026-07-14T09:00' -> 'martes 14/7 a las 09:00', para respuestas
    habladas."""
    if isinstance(cuando, str):
        cuando = datetime.fromisoformat(cuando)
    return f"{DIAS[cuando.weekday()]} {cuando.day}/{cuando.month} a las {cuando.strftime('%H:%M')}"


# --- Extracción de fecha/hora con el modelo -----------------------------------

def extraer_recordatorio(texto, funcion_llm, ahora=None):
    """Devuelve (texto_a_recordar, datetime) o (None, None) si el pedido no
    trae un cuándo entendible. El modelo hace la conversión de lenguaje
    natural a fecha absoluta; acá solo validamos."""
    ahora = ahora or datetime.now()
    # El calendario de la semana va resuelto en el prompt: a un modelo de
    # 8B la cuenta "¿qué fecha cae el viernes?" le sale mal seguido
    # (probado: respondía jueves). Leerlo de una tabla no falla.
    semana = ", ".join(
        f"{DIAS[d.weekday()]} {d.strftime('%Y-%m-%d')}" + (" (hoy)" if i == 0 else "")
        for i, d in ((i, ahora + timedelta(days=i)) for i in range(7))
    )
    # Un ejemplo resuelto rinde más que describir el formato: probado con
    # dolphin3, que sin ejemplo inventaba sus propias etiquetas.
    prompt = (
        f"Hoy es {DIAS[ahora.weekday()]} {ahora.strftime('%Y-%m-%d')} y son "
        f"las {ahora.strftime('%H:%M')}. Próximos días: {semana}.\n"
        "Del pedido de abajo extraé la fecha futura absoluta y la acción a "
        "recordar (sin palabras como 'recordame' o 'alarma'). Si dice la "
        "hora en palabras, convertila a números (por ejemplo: «a las tres "
        "de la tarde» = 15:00, «a las tres» = 15:00, «a la mañana» = "
        "09:00). Solo si NO menciona ninguna hora, usá 09:00.\n\n"
        "Ejemplo: si hoy fuera 2026-01-04 y el pedido dijera «recordame "
        "mañana a las dos y media comprar entradas», la respuesta sería:\n"
        "FECHA: 2026-01-05 14:30\n"
        "TEXTO: comprar entradas\n\n"
        "Respondé SOLO esas dos líneas. Si el pedido no dice cuándo, "
        "respondé exactamente SIN_FECHA.\n\n"
        f"Pedido: \"{texto}\""
    )
    try:
        respuesta = funcion_llm(prompt) or ""
    except Exception:
        return None, None

    m_fecha = re.search(r"FECHA:\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})", respuesta)
    if not m_fecha:
        return None, None
    # etiqueta tolerante: aunque el ejemplo dice TEXTO:, el modelo a veces
    # etiqueta a su manera; si no hay etiqueta conocida, tomamos la línea
    # que sigue a FECHA y le sacamos cualquier "ETIQUETA:" que traiga.
    m_texto = re.search(r"TEXTO\s*:\s*(.+)", respuesta, re.IGNORECASE)
    if not m_texto:
        resto = respuesta[m_fecha.end():].strip()
        primera_linea = resto.splitlines()[0].strip() if resto else ""
        m_texto = re.match(r"(?:[A-ZÁÉÍÓÚÜÑ ¿?]+:\s*)?(.+)", primera_linea)
    if not m_texto:
        return None, None
    try:
        cuando = datetime.fromisoformat(f"{m_fecha.group(1)} {m_fecha.group(2)}")
    except ValueError:
        return None, None
    if cuando <= ahora:
        return None, None  # una alarma para el pasado es un malentendido
    que = m_texto.group(1).strip().strip('"').rstrip(".")
    return (que, cuando) if que else (None, None)


# --- Avisador ------------------------------------------------------------------

def _avisar_default(texto):
    """Aviso por defecto: notificación de escritorio + voz + push al celu.
    La voz se importa acá adentro (perezoso: cargar Coqui al importar agenda
    repetiría el problema de RAM que ya tuvo la ventana con Whisper)."""
    try:
        subprocess.run(
            ["notify-send", "-u", "critical", "Bridget", texto], timeout=5
        )
    except Exception:
        pass
    try:
        from core.voice import hablar
        hablar(texto)
    except Exception:
        pass
    try:
        from core import push
        push.enviar_notificacion("Bridget", texto)
    except Exception:
        pass


def revisar_y_avisar(avisar=None, ahora=None):
    """Una pasada del avisador: avisa los vencidos y los marca. Separada del
    bucle para poder probarla sin hilos ni relojes."""
    avisar = avisar or _avisar_default
    avisados = 0
    for r in vencidos(ahora):
        try:
            avisar(f"Recordatorio: {r['texto']}")
        except Exception:
            pass
        marcar_avisado(r["id"])
        avisados += 1
    return avisados


_hilo_avisador = None


def iniciar_avisador(avisar=None, intervalo=INTERVALO_AVISADOR):
    """Lanza el hilo daemon que revisa la agenda. Idempotente por proceso:
    llamarlo dos veces no duplica hilos."""
    global _hilo_avisador
    if _hilo_avisador is not None and _hilo_avisador.is_alive():
        return _hilo_avisador

    def _bucle():
        while True:
            try:
                revisar_y_avisar(avisar)
            except Exception:
                pass  # el avisador no debe morir nunca
            time.sleep(intervalo)

    _hilo_avisador = threading.Thread(target=_bucle, daemon=True)
    _hilo_avisador.start()
    return _hilo_avisador
