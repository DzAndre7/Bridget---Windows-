"""
Persistencia de sesiones: los chats sobreviven a los reinicios.

Cómo funciona:
- Cada sesión se guarda como un JSON en asistente_v2/sesiones/ (id, nombre,
  fechas e historial). brain.procesar_comando la persiste turno a turno.
- Cada arranque (CLI o ventana) abre una sesión NUEVA que recibe dos cosas
  de la sesión anterior:
    * contexto_anterior: un resumen de los últimos mensajes, que va al
      system prompt para que el asistente retome la charla con naturalidad
      (recuerda la sesión anterior, no toda la historia de días).
    * historial_anterior: los mensajes tal cual, para que la interfaz los
      muestre al abrir y nunca arranques frente a una ventana vacía.
- La API REST persiste una sesión por cliente (X-Session-Id), así una
  conversación remota también sobrevive a un reinicio del servidor.

Este módulo importa brain (por la clase Sesion); brain NUNCA importa este
módulo en el nivel superior (solo adentro de la función que guarda), así
no hay ciclo de imports.
"""

import json
import os
import re
import threading
from datetime import datetime

from core.brain import Sesion
from core import memoria_semantica

DIR_SESIONES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sesiones")

# cuántos mensajes de la sesión anterior mostramos/inyectamos
MENSAJES_ANTERIORES = 12
MAX_CHARS_DIGEST = 1600


def _ruta(id_sesion):
    return os.path.join(DIR_SESIONES, f"{id_sesion}.json")


def _id_seguro(texto):
    """Convierte un id arbitrario (ej: el X-Session-Id de un cliente remoto)
    en un nombre de archivo seguro."""
    limpio = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(texto))[:64]
    return limpio or "sesion"


def guardar(sesion):
    """Escribe la sesión a disco (escritura atómica: tmp + rename, así un
    corte a mitad de escritura no corrompe el chat)."""
    if not sesion.id:
        return False
    os.makedirs(DIR_SESIONES, exist_ok=True)
    datos = {
        "id": sesion.id,
        "nombre": sesion.nombre or sesion.id,
        "creada": getattr(sesion, "creada", datetime.now().isoformat()),
        "actualizada": datetime.now().isoformat(),
        "historial": sesion.historial,
        # preservar la marca si la sesión se recargó y se volvió a guardar
        "indexada": getattr(sesion, "indexada", False),
        # la memoria de la charla anterior también sobrevive a un reinicio
        # del servidor (las sesiones de la API viven más que el proceso)
        "contexto_anterior": sesion.contexto_anterior,
        "historial_anterior": sesion.historial_anterior,
    }
    ruta = _ruta(sesion.id)
    temporal = ruta + ".tmp"
    try:
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
        sesion.actualizada = datos["actualizada"]
        return True
    except Exception as e:
        print(f"[sesiones] no pude guardar {sesion.id}: {e}")
        return False


def cargar(id_sesion):
    """Levanta una sesión guardada. Devuelve None si no existe o está rota."""
    try:
        with open(_ruta(id_sesion), "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return None

    sesion = Sesion()
    sesion.id = datos["id"]
    sesion.nombre = datos.get("nombre", sesion.id)
    sesion.creada = datos.get("creada", "")
    sesion.historial = datos.get("historial", [])
    sesion.indexada = datos.get("indexada", False)
    sesion.actualizada = datos.get("actualizada", "")
    sesion.contexto_anterior = datos.get("contexto_anterior", "")
    sesion.historial_anterior = datos.get("historial_anterior", [])
    return sesion


def listar():
    """Metadatos de todas las sesiones guardadas, la más reciente primero."""
    if not os.path.isdir(DIR_SESIONES):
        return []
    sesiones = []
    for nombre in os.listdir(DIR_SESIONES):
        if not nombre.endswith(".json"):
            continue
        try:
            with open(os.path.join(DIR_SESIONES, nombre), "r", encoding="utf-8") as f:
                datos = json.load(f)
            sesiones.append({
                "id": datos["id"],
                "nombre": datos.get("nombre", datos["id"]),
                "actualizada": datos.get("actualizada", ""),
                "mensajes": len(datos.get("historial", [])),
            })
        except Exception:
            continue
    sesiones.sort(key=lambda s: s["actualizada"], reverse=True)
    return sesiones


def _digest(historial, assistant_name="Asistente"):
    """Convierte los últimos mensajes en texto plano compacto para el system
    prompt. Truncamos cada mensaje: para dar continuidad alcanza el tema,
    no hace falta el texto completo."""
    lineas = []
    for mensaje in historial[-MENSAJES_ANTERIORES:]:
        quien = "Usuario" if mensaje.get("role") == "user" else assistant_name
        contenido = " ".join(str(mensaje.get("content", "")).split())
        if len(contenido) > 220:
            contenido = contenido[:220] + "…"
        lineas.append(f"{quien}: {contenido}")
    texto = "\n".join(lineas)
    return texto[-MAX_CHARS_DIGEST:]


def _ya_indexada(id_sesion):
    try:
        with open(_ruta(id_sesion), "r", encoding="utf-8") as f:
            return bool(json.load(f).get("indexada"))
    except Exception:
        return True  # ante la duda, no reindexar (peor duplicar que perder)


def _marcar_indexada(id_sesion):
    """Anota en el archivo de la sesión que ya fue resumida a la memoria
    semántica, para no volver a indexarla en cada arranque."""
    try:
        ruta = _ruta(id_sesion)
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        datos["indexada"] = True
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
    except Exception:
        pass


def indexar_charla(previa, funcion_llm, assistant_name="Asistente"):
    """Resume una charla con el modelo y la guarda en la memoria semántica
    (categoría 'charla', con la fecha adentro del texto). Cuando el usuario
    vuelva a tocar el tema —aunque pasen semanas— recordar() la trae al
    system prompt y el asistente puede retomarla («che, ¿al final cómo te
    fue con eso?»). Nunca lanza: corre en un hilo de fondo al arrancar y un
    error acá no puede frenar el arranque."""
    try:
        if not previa or len(previa.historial) < 4:
            return False  # dos intercambios o menos no son "una charla"
        prompt = (
            "Resumí esta conversación en una o dos oraciones en tercera "
            "persona, nombrando los temas concretos y cualquier cosa que "
            "haya quedado pendiente o por hacer. Solo el resumen, sin "
            "opiniones.\n\n" + _digest(previa.historial, assistant_name)
        )
        resumen = (funcion_llm(prompt) or "").strip()
        if not resumen:
            return False
        fecha = (previa.creada or datetime.now().isoformat())[:10]
        memoria_semantica.guardar_recuerdo(
            f"En una charla del {fecha} hablaron de: {resumen}",
            categoria="charla",
        )
        _marcar_indexada(previa.id)
        return True
    except Exception:
        return False


def abrir_sesion(nombre=None, assistant_name="Asistente", funcion_llm=None):
    """Abre la sesión de un nuevo arranque: crea una sesión nueva y le carga
    la memoria de la ANTERIOR (la más reciente que tenga mensajes), tanto
    para el modelo (contexto_anterior) como para la interfaz
    (historial_anterior). Devuelve la sesión lista para usar.

    Si viene `funcion_llm`, además indexa la charla anterior a la memoria
    semántica en un hilo de fondo (el modelo puede estar frío al arrancar y
    no queremos demorar la ventana). Es opt-in a propósito: los tests y los
    usos sin modelo no disparan trabajo de fondo."""
    anteriores = [s for s in listar() if s["mensajes"] > 0]

    sesion = Sesion()
    # id único aunque se abran dos sesiones en el mismo segundo
    base_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    id_sesion, contador = base_id, 2
    while os.path.exists(_ruta(id_sesion)):
        id_sesion = f"{base_id}_{contador}"
        contador += 1
    sesion.id = id_sesion
    sesion.nombre = nombre or f"charla {datetime.now().strftime('%d/%m %H:%M')}"
    sesion.creada = datetime.now().isoformat()

    if anteriores:
        previa = cargar(anteriores[0]["id"])
        if previa and previa.historial:
            sesion.contexto_anterior = _digest(previa.historial, assistant_name)
            sesion.historial_anterior = previa.historial[-MENSAJES_ANTERIORES:]

            if funcion_llm and not _ya_indexada(previa.id):
                threading.Thread(
                    target=indexar_charla,
                    args=(previa, funcion_llm, assistant_name),
                    daemon=True,
                ).start()

    guardar(sesion)
    return sesion


# Horas de inactividad tras las cuales una sesión de la API se considera
# una charla terminada y se rota (digest + indexado + historial limpio).
HORAS_CHARLA_VIEJA = 6


def refrescar_si_vieja(sesion, funcion_llm=None, assistant_name="Asistente",
                       horas_corte=HORAS_CHARLA_VIEJA):
    """Rotación in-place para las sesiones de la API (una por cliente, id
    fijo): si pasaron más de `horas_corte` desde el último mensaje, la
    charla vieja se convierte en memoria —digest al system prompt,
    historial_anterior para la UI, resumen a memoria semántica si hay
    funcion_llm— y el historial arranca de cero. Así el celular tiene el
    mismo modelo de memoria que la ventana: cada retomada es un chat nuevo
    que recuerda el anterior, en vez de una única charla eterna.
    Devuelve True si rotó."""
    if not sesion.historial or not getattr(sesion, "actualizada", ""):
        return False
    try:
        ultima = datetime.fromisoformat(sesion.actualizada)
    except ValueError:
        return False
    if (datetime.now() - ultima).total_seconds() < horas_corte * 3600:
        return False

    if funcion_llm:
        # la copia congela el historial: el hilo no ve la sesión ya vaciada
        congelada = Sesion()
        congelada.id = sesion.id
        congelada.creada = sesion.actualizada  # la fecha de la charla es su último día
        congelada.historial = list(sesion.historial)
        threading.Thread(
            target=indexar_charla,
            args=(congelada, funcion_llm, assistant_name),
            daemon=True,
        ).start()

    sesion.contexto_anterior = _digest(sesion.historial, assistant_name)
    sesion.historial_anterior = sesion.historial[-MENSAJES_ANTERIORES:]
    sesion.historial = []
    guardar(sesion)
    return True


def cargar_o_crear(id_cliente):
    """Para la API: cada cliente (X-Session-Id) tiene UNA sesión persistente
    con ese id. Si existe se retoma con todo su historial; si no, se crea."""
    id_sesion = _id_seguro(id_cliente)
    sesion = cargar(id_sesion)
    if sesion is not None:
        return sesion

    sesion = Sesion()
    sesion.id = id_sesion
    sesion.nombre = f"remota {id_sesion}"
    sesion.creada = datetime.now().isoformat()
    guardar(sesion)
    return sesion
