"""
Cerebro principal: orquesta la conversación.

Responsabilidades de este módulo, en orden de aparición:
- Sesión: el estado mutable de cada conversación (historial, confirmaciones).
- Contexto: system prompt con identidad, memoria y notas del cerebro.
- Streaming + TTS: entrega por frases mientras el modelo genera.
- Consultas al LLM: consultar_llama / consultar_llama_stream.
- Manejadores: una función chica por intención (_cmd_*).
- Despacho: procesar_comando detecta la intención (reglas + clasificador
  LLM, ver core/intenciones.py) y llama al manejador que corresponde.

La comprensión de texto (detección de intenciones y extractores) vive en
core/intenciones.py; acá solo se re-exporta lo necesario para mantener la
API pública de siempre (brain.detectar_intencion, brain.normalizar_texto…).
"""

import datetime
import re
import ollama
import subprocess
import shutil
import os
import threading

from core import cerebro
from core import intenciones
# Re-export: la capa de comprensión vive en core/intenciones.py, pero estos
# nombres siguen disponibles como brain.* (los usan la API, la UI y los tests).
from core.intenciones import (
    normalizar_texto, limpiar_texto_base, _contiene, es_intencion_busqueda,
    detectar_intencion, extraer_consulta_busqueda, extraer_recuerdo,
    extraer_olvido, extraer_preferencia, extraer_objeto_apertura,
    clasificar_objeto_apertura, normalizar_nombre_programa,
    extraer_ruta_archivo, extraer_tipo_analisis, extraer_conversion,
)
from config import (
    ASSISTANT_NAME, ASSISTANT_CREATOR,
    MODELO_CONVERSACION, MODELO_RAPIDO, KEEP_ALIVE, NUM_CTX,
    OPCIONES_CONVERSACION,
)
from core.memoria_semantica import recordar, guardar_recuerdo as guardar_recuerdo_semantico
from core import memoria_auto
from actions.system_actions import buscar_en_internet, abrir_programa, convertir_documento
from core.memory import cargar_recuerdos, guardar_recuerdo, leer_recuerdos, olvidar_recuerdo, borrar_todos_los_recuerdos
from core.preferences import cargar_preferencias, guardar_preferencia, obtener_preferencia
from core.vision import ver_pantalla
from actions.agent_actions import planificar_tarea, extraer_programa_con_llama, ALIAS_PROGRAMAS, buscar_aplicaciones_sistema
from core.search import buscar_web, formatear_resultados
from core.code_analyzer import analizar_archivo, analizar_proyecto, guardar_reporte
from core.dataset_collector import guardar_interaccion, guardar_par_entrenamiento
from core.code_reviewer import revisar_codigo
from core.auditoria import auditar_proyecto
from core.sandbox import (
    ejecutar_codigo, probar_proyecto, probar_cambio_en_proyecto,
    crear_y_probar, guardar_codigo_validado, verificar_sintaxis,
    extraer_codigo,
)
from core import auto_mejora
from core import agenda
from core import pensador

DEBUG_MODE = False


# --- Sesión -----------------------------------------------------------------

class Sesion:
    """Estado mutable de UNA conversación: historial + flujo de confirmaciones.
    Aislarlo en un objeto permite que la API atienda a varios clientes sin que
    compartan historial ni confirmaciones. Antes eran globales de módulo y, con
    la API expuesta por ngrok, dos usuarios concurrentes se pisaban el estado
    (uno podía confirmar la tarea pendiente de otro, o ver su conversación)."""

    def __init__(self):
        self.historial = []
        self.opciones_pendientes = []
        self.esperando_confirmacion_borrado = False
        self.esperando_confirmacion_tarea = False
        self.plan_pendiente = ""
        self.plan_nombre = ""
        # Persistencia (core/sesiones.py). id=None => sesión efímera, como
        # siempre: los tests y las llamadas sin sesión no tocan disco.
        self.id = None
        self.nombre = None
        self.creada = ""
        self.actualizada = ""          # última escritura a disco (ISO)
        self.contexto_anterior = ""    # digest de la sesión pasada, va al system prompt
        self.historial_anterior = []   # mensajes de la sesión pasada, para la UI


# Sesión por defecto: la usa la CLI (un solo usuario) y cualquier llamada que no
# pase una sesión explícita. La API crea una Sesion por cliente (X-Session-Id).
_sesion_default = Sesion()

# Tope de mensajes que mandamos al modelo. Sin esto el historial crece sin
# límite: cada turno se hace más lento y más caro, y termina desbordando la
# ventana de contexto. 20 = ~10 intercambios recientes.
MAX_HISTORIAL = 20

# Tope de caracteres por nota del cerebro inyectada al system prompt. Las
# notas entraban COMPLETAS: tres notas grandes sumaban ~10.000 caracteres y
# el system prompt solo ya desbordaba la ventana de contexto (medido).
MAX_CHARS_NOTA = 1500


# --- Contexto del proyecto ---------------------------------------------------

# El contexto del proyecto (context.md) es estático: lo leemos una sola vez y
# lo cacheamos, en vez de tocar disco en cada turno de conversación.
_CONTEXTO_PROYECTO = None

def _cargar_contexto_proyecto():
    global _CONTEXTO_PROYECTO
    if _CONTEXTO_PROYECTO is None:
        ruta = os.path.join(os.path.dirname(__file__), "..", "context.md")
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                crudo = f.read()
            # context.md es una plantilla: el nombre y el creador salen de
            # config.py, así se cambian en UN solo lugar.
            _CONTEXTO_PROYECTO = (
                crudo.replace("{ASSISTANT_NAME}", ASSISTANT_NAME)
                     .replace("{ASSISTANT_CREATOR}", ASSISTANT_CREATOR)
            )
        except Exception:
            _CONTEXTO_PROYECTO = ""
    return _CONTEXTO_PROYECTO


# --- Streaming + TTS por frases -------------------------------------------
# Sink opcional de voz: si está seteado (una función que consume un iterable de
# frases), consultar_llama va entregando cada frase TERMINADA a medida que el
# modelo la genera, para que el TTS empiece a hablar sin esperar la respuesta
# completa. La capa de UI lo instala con usar_sink_de_frases().
_frase_sink = None
# Marca si el último turno se resolvió por streaming (ya se habló en vivo), para
# que la UI no vuelva a reproducir la respuesta entera.
ULTIMO_TURNO_STREAMEADO = False

def usar_sink_de_frases(fn):
    """Registra (o limpia con None) el sink de voz por frases."""
    global _frase_sink
    _frase_sink = fn


def limpiar_para_tts(texto):
    """Saca marcado Markdown que no debería leerse en voz alta."""
    texto = re.sub(r'`+', '', texto)
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s*', '', texto)
    texto = re.sub(r'^\s*\d+\.\s+', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^\s*[-•]\s+', '', texto, flags=re.MULTILINE)
    return texto.strip()


_FIN_ORACION = re.compile(r'[.!?…]+["\'”’)\]]?\s+|\n+')

def _extraer_oraciones(buffer):
    """Corta oraciones COMPLETAS del buffer. Devuelve (oraciones, resto)."""
    oraciones = []
    ultimo = 0
    for m in _FIN_ORACION.finditer(buffer):
        oraciones.append(buffer[ultimo:m.end()])
        ultimo = m.end()
    return oraciones, buffer[ultimo:]


def frasear(tokens):
    """Agrupa un stream de fragmentos de texto en frases listas para hablar.
    Salta los bloques de código (```) y avisa una sola vez que hay código en
    pantalla, en vez de leerlo en voz alta."""
    buffer = ""
    en_codigo = False
    aviso_dado = False
    for tok in tokens:
        if not tok:
            continue
        buffer += tok
        while "```" in buffer:
            idx = buffer.find("```")
            if not en_codigo:
                oraciones, _ = _extraer_oraciones(buffer[:idx])
                for o in oraciones:
                    o = limpiar_para_tts(o)
                    if o:
                        yield o
                buffer = buffer[idx + 3:]
                en_codigo = True
                if not aviso_dado:
                    aviso_dado = True
                    yield "Revisá el código en pantalla."
            else:
                buffer = buffer[idx + 3:]
                en_codigo = False
        if en_codigo:
            buffer = buffer[-2:]  # dentro de código: nada que hablar (deja cola por ``` partido)
            continue
        oraciones, buffer = _extraer_oraciones(buffer)
        for o in oraciones:
            o = limpiar_para_tts(o)
            if o:
                yield o
    if not en_codigo:
        o = limpiar_para_tts(buffer)
        if o:
            yield o


# --- Consultas al LLM --------------------------------------------------------

def _preparar_sistema(texto, sesion):
    """Construye el system prompt (identidad + memoria + cerebro + contexto del
    proyecto) y agrega el turno del usuario al historial de la sesión.
    Devuelve el system prompt."""
    contexto_proyecto = _cargar_contexto_proyecto()  # cacheado, no toca disco cada turno
    if DEBUG_MODE:
        print(f"DEBUG CONTEXTO: {contexto_proyecto[:100] if contexto_proyecto else 'VACÍO'}")

    recuerdos = leer_recuerdos()
    contexto_memoria = "; ".join(recuerdos) if recuerdos else ""

    # Buscar recuerdos semánticos relevantes. Si ollama/embeddings falla, no
    # rompemos la respuesta entera: seguimos sin recuerdos semánticos.
    try:
        recuerdos_semanticos = recordar(texto[:500], top_k=3)
    except Exception as e:
        if DEBUG_MODE:
            print(f"DEBUG SEMANTICA FALLÓ: {e}")
        recuerdos_semanticos = []
    if DEBUG_MODE:
        print(f"DEBUG SEMANTICA: {[r['texto'][:40] for r in recuerdos_semanticos]}")
    if recuerdos_semanticos:
        contexto_semantico = "\n".join([f"- {r['texto']}" for r in recuerdos_semanticos])
        contexto_memoria = contexto_memoria + "\n\nRecuerdos relevantes para este momento:\n" + contexto_semantico if contexto_memoria else "Recuerdos relevantes para este momento:\n" + contexto_semantico
        # Si entre lo recuperado hay resúmenes de charlas pasadas
        # (indexadas por sesiones.indexar_charla), lo invitamos a
        # retomarlas: es lo que convierte "memoria" en continuidad.
        if any(r.get("categoria") == "charla" for r in recuerdos_semanticos):
            contexto_memoria += (
                "\nSi una de esas charlas anteriores viene al caso, retomala "
                "con naturalidad (por ejemplo: «me acordé de que hablamos de "
                "esto, ¿al final cómo te fue?»). Si no viene al caso, no la "
                "menciones."
            )

    # Buscar en el cerebro (vault de Obsidian) notas relevantes. También
    # blindado: un vault mal configurado no debe tumbar la conversación.
    try:
        notas_cerebro = cerebro.consultar_cerebro(texto, max_notas=3)
    except Exception as e:
        if DEBUG_MODE:
            print(f"DEBUG CEREBRO FALLÓ: {e}")
        notas_cerebro = []
    if DEBUG_MODE:
        print(f"DEBUG CEREBRO: {[n['titulo'] for n in notas_cerebro]}")

    # Armamos el system prompt base SIEMPRE (no depende de si hay memoria)
    sistema = (
        f"Sos {ASSISTANT_NAME}, un asistente personal creado por {ASSISTANT_CREATOR}. "
        "Naciste el 17 de abril de 2026. "
        "Respondés siempre en español salvo que se te indique otro idioma. "
        "Tu tono es tranquilo, directo y natural — como una persona inteligente charlando, no un manual. "
        "Nunca te presentés ni describas quién sos. Respondé directamente lo que te preguntan. "
        f"Nunca menciones Llama, Meta ni tu modelo base. Si te preguntan quién te creó, decí solo '{ASSISTANT_CREATOR}'. "
        "FORMATO: Máximo 2 párrafos cortos. Sin listas numeradas ni viñetas. Texto corrido siempre. "
        "Si un tema necesita enumerar cosas, incorporalas naturalmente en el texto separadas por comas."
    )

    # Agregamos lo que sabe del usuario, solo si hay algo
    if contexto_memoria:
        sistema += f"\n\nLo que sabés sobre el usuario:\n{contexto_memoria}"

    # Las notas del cerebro van con INSTRUCCIÓN EXPLÍCITA y bien separadas
    if notas_cerebro:
        contexto_notas = "\n\n".join(
            [f"### {n['titulo']}\n{n['contenido'][:MAX_CHARS_NOTA]}" for n in notas_cerebro]
        )
        sistema += (
            "\n\n=== NOTAS DE TU CEREBRO ===\n"
            f"Las siguientes notas son TUYAS, escritas por vos y {ASSISTANT_CREATOR}. "
            "Son tu fuente principal de verdad sobre estos temas. "
            "Cuando respondas algo relacionado, basate en estas notas ANTES que en tu conocimiento general. "
            "Si una nota tiene información específica, usá esa información concreta en tu respuesta.\n\n"
            "IMPORTANTE: respondé directamente con la información, de forma natural."
            "NO digas 'recuerdo que', 'soy capaz de recordar', 'estoy familiarizado con'"
            "Simplemente respondé como si fuera conocimiento tuyo, directo.\n\n"
            + contexto_notas
        )

    if contexto_proyecto:
        sistema += f"\n\nContexto de tu arquitectura y proyecto:\n{contexto_proyecto}"

    # Memoria de la sesión anterior: retomar la charla con naturalidad,
    # sin arrastrar la historia completa de todos los días.
    if sesion.contexto_anterior:
        sistema += (
            "\n\n=== TU CONVERSACIÓN ANTERIOR ===\n"
            "Esto es lo último que hablaron la sesión pasada. Tenélo presente "
            "para dar continuidad si el usuario retoma el tema; no lo menciones "
            "si no viene al caso.\n\n" + sesion.contexto_anterior
        )

    sesion.historial.append({"role": "user", "content": texto})
    return sistema


def consultar_llama_stream(texto, sesion=None):
    """Consulta al LLM en modo streaming: cede los fragmentos de texto a medida
    que el modelo los genera. Actualiza el historial de la sesión y el dataset al
    terminar (incluso si el stream se corta a mitad)."""
    sesion = sesion or _sesion_default
    sistema = _preparar_sistema(texto, sesion)
    partes = []
    try:
        # Solo mandamos los últimos MAX_HISTORIAL mensajes: acota latencia, costo
        # y evita desbordar la ventana de contexto en charlas largas.
        stream = ollama.chat(
            model=MODELO_CONVERSACION,
            messages=[{"role": "system", "content": sistema}] + sesion.historial[-MAX_HISTORIAL:],
            stream=True,
            keep_alive=KEEP_ALIVE,
            options={"num_ctx": NUM_CTX, **OPCIONES_CONVERSACION},
        )
        for chunk in stream:
            parte = chunk["message"]["content"]
            if parte:
                partes.append(parte)
                yield parte
    finally:
        if partes:
            contenido = "".join(partes)
            sesion.historial.append({"role": "assistant", "content": contenido})
            if len(sesion.historial) > MAX_HISTORIAL:
                del sesion.historial[:-MAX_HISTORIAL]
            guardar_interaccion(texto, contenido)


def consultar_llama(texto, sesion=None):
    """Devuelve la respuesta completa como string (contrato original, usado por
    todo procesar_comando). Si hay un sink de voz activo, además va hablando por
    frases mientras el modelo genera, sin esperar la respuesta completa."""
    global ULTIMO_TURNO_STREAMEADO
    gen = consultar_llama_stream(texto, sesion)

    if _frase_sink is None:
        ULTIMO_TURNO_STREAMEADO = False
        return "".join(gen)

    partes = []
    def _captura():
        for t in gen:
            partes.append(t)
            yield t
    try:
        # el sink consume las frases (y con ellas el stream) hablando en pipeline
        _frase_sink(frasear(_captura()))
    finally:
        for _ in gen:  # garantiza agotar el generador (guarda historial/dataset)
            pass
    ULTIMO_TURNO_STREAMEADO = True
    return "".join(partes)


def _llm_directo(prompt, max_tokens=None):
    """Consulta directa al modelo para trabajo interno (clasificar
    intenciones, verificaciones sí/no, generar propuestas de auto-mejora):
    sin historial, sin dataset, sin TTS (a diferencia de consultar_llama).
    TODO trabajo interno debe pasar por acá: usar consultar_llama para esto
    contaminaba el historial y el dataset con prompts internos, y con voz
    activa hasta los decía en voz alta.
    Usa MODELO_RAPIDO, que por defecto es el MISMO modelo de conversación:
    en 6 GB de VRAM solo entra un modelo, y usar otro obligaría a
    descargarlo y recargarlo (10-15 s por turno, medido).
    `max_tokens` acota la generación cuando se espera una respuesta corta
    (una palabra de clasificación no necesita generar sin límite)."""
    opciones = {"num_ctx": NUM_CTX, "temperature": 0}
    if max_tokens:
        opciones["num_predict"] = max_tokens
    respuesta = ollama.chat(
        model=MODELO_RAPIDO,
        messages=[{"role": "user", "content": prompt}],
        keep_alive=KEEP_ALIVE,
        options=opciones,
    )
    return respuesta["message"]["content"]


# --- Archivos ----------------------------------------------------------------

def leer_archivo(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def escribir_archivo(ruta, contenido):
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return True
    except Exception:
        return False


# --- Manejadores: una función por intención -----------------------------------
# Todos comparten la misma firma (texto, texto_original, sesion, assistant_name)
# para poder despacharlos desde la tabla MANEJADORES. `texto` viene normalizado
# (minúsculas, sin tildes); `texto_original` es lo que escribió el usuario.

def _cmd_ejecutar_tarea(texto, texto_original, sesion, assistant_name):
    # Verificación interna: va por _llm_directo, NO por consultar_llama.
    # Antes este prompt entraba al historial y al dataset (aparecía
    # "¿El siguiente mensaje pide...?" como si lo hubiera dicho el usuario)
    # y con voz activa el asistente decía "sí"/"no" en voz alta.
    verificacion = _llm_directo(f"¿El siguiente mensaje pide explícitamente abrir o ejecutar una aplicación o programa? Respondé solo 'sí' o 'no'. Mensaje: '{texto_original}'", max_tokens=5)
    if "no" in verificacion.lower():
        return consultar_llama(texto_original, sesion)
    programa = extraer_programa_con_llama(texto_original)
    resultados = buscar_aplicaciones_sistema(programa)

    if len(resultados) == 0:
        return f"No encontré ninguna aplicación que coincida con '{programa}' en el sistema."

    elif len(resultados) == 1:
        nombre, comando = resultados[0]
        sesion.esperando_confirmacion_tarea = True
        sesion.plan_pendiente = comando
        sesion.plan_nombre = nombre
        return f"Encontré '{sesion.plan_nombre}'. ¿Lo abro?"

    else:
        letras = ["a", "b", "c", "d"]
        opciones_texto = "\n".join([f"{letras[i]}) {nombre}" for i, (nombre, comando) in enumerate(resultados)])
        sesion.opciones_pendientes = list(resultados)
        sesion.esperando_confirmacion_tarea = True
        sesion.plan_pendiente = ""
        return f"Encontré varias opciones:\n{opciones_texto}\n¿Cuál querés abrir?"


def _cmd_borrar_todos_los_recuerdos(texto, texto_original, sesion, assistant_name):
    sesion.esperando_confirmacion_borrado = True
    return "¿Estás seguro? Escribí 'confirmar borrado, S/Y' para eliminar toda la memoria de forma permanente."


def _cmd_confirmar_borrado(texto, texto_original, sesion, assistant_name):
    if sesion.esperando_confirmacion_borrado:
        borrar_todos_los_recuerdos()
        sesion.esperando_confirmacion_borrado = False
        return "Todos los recuerdos han sido borrados."
    else:
        return "No hay ninguna acción de borrado pendiente de confirmación."


def _cmd_buscar_en_internet(texto, texto_original, sesion, assistant_name):
    consulta = extraer_consulta_busqueda(texto, assistant_name)

    if consulta:
        exito = buscar_en_internet(consulta)
        if exito:
            return f'Buscando "{consulta}" en internet...'
        return "No pude hacer la búsqueda."

    return "Decime qué querés buscar."


def _cmd_consultar_hora(texto, texto_original, sesion, assistant_name):
    ahora = datetime.datetime.now().strftime("%H:%M")
    return f"Son las {ahora}"


def _cmd_consultar_nombre(texto, texto_original, sesion, assistant_name):
    return f"Me llamo {assistant_name}"


def _cmd_saludo(texto, texto_original, sesion, assistant_name):
    return "Hola, ¿cómo estás?"


def _cmd_auditar_codigo(texto, texto_original, sesion, assistant_name):
    print("Iniciando auto-auditoría. Esto puede tardar un par de minutos...")
    return auditar_proyecto()


def _cmd_crear_y_probar_codigo(texto, texto_original, sesion, assistant_name):
    print("Creando código y probándolo en el sandbox (puede tomar varias vueltas)...")
    resultado = crear_y_probar(texto_original, lambda p: consultar_llama(p, sesion))

    if resultado["exito"]:
        ruta = guardar_codigo_validado(resultado["codigo"], descripcion=texto_original)
        salida = resultado["resultado"]["salida"].strip() or "(sin salida)"
        return (
            f"Listo: el código pasó sus pruebas en el sandbox al intento "
            f"{resultado['intentos']} de {resultado['max_intentos']}. "
            f"Lo guardé en {ruta}\n\n--- SALIDA ---\n{salida[:800]}"
        )
    return (
        f"No logré un código que pase las pruebas después de "
        f"{resultado['intentos']} intentos. Último error "
        f"({resultado['resultado']['etapa']}):\n"
        f"{resultado['resultado']['errores'][-800:]}"
    )


def _cmd_probar_proyecto_sandbox(texto, texto_original, sesion, assistant_name):
    print("Copiando el proyecto a un sandbox y corriendo mis pruebas ahí...")
    resultado = probar_proyecto()

    if resultado["exito"]:
        return f"Todas mis pruebas pasaron en el sandbox.\n\n{resultado['salida'][-600:]}"
    if resultado["etapa"] == "timeout":
        return f"Las pruebas tardaron demasiado y las corté.\n\n{resultado['errores'][-600:]}"
    return (
        f"Hay pruebas que fallan en el sandbox:\n\n"
        f"{resultado['salida'][-1200:]}\n{resultado['errores'][-400:]}"
    )


def _cmd_probar_codigo_sandbox(texto, texto_original, sesion, assistant_name):
    rutas = re.findall(r'[~/][\w/\.\-]+', texto_original)
    if rutas:
        ruta = os.path.expanduser(rutas[0])
        codigo = leer_archivo(ruta)
        if codigo is None:
            return f"No pude leer {ruta}."
    else:
        # el código viene en el propio mensaje, después de los dos puntos
        _, _, resto = texto_original.partition(":")
        codigo = extraer_codigo(resto.strip())
        if not codigo:
            return "Pasame el código después de dos puntos, o la ruta de un archivo .py."

    print("Ejecutando en el sandbox (proceso aislado, sin red)...")
    resultado = ejecutar_codigo(codigo)

    if resultado["exito"]:
        salida = resultado["salida"].strip() or "(terminó bien, sin salida)"
        return f"El código corrió bien en el sandbox.\n\n--- SALIDA ---\n{salida[:1000]}"
    return (
        f"El código falló en el sandbox (etapa: {resultado['etapa']}).\n\n"
        f"{resultado['errores'][-1000:]}"
    )


def _cmd_auto_mejora(texto, texto_original, sesion, assistant_name):
    # ¿pidió un archivo puntual, o elegimos nosotros?
    rutas = re.findall(r'[~/\w][\w/\.\-]*\.py', texto_original)
    if rutas:
        archivo = os.path.expanduser(rutas[0])
    else:
        archivo = auto_mejora.elegir_archivo()
        if not archivo:
            return "No encontré ningún archivo candidato para mejorar (¿todos tienen mejoras pendientes?)."

    print(f"Auto-mejora: revisando {archivo}, proponiendo y probando en el sandbox...")
    resultado = auto_mejora.proponer_mejora(archivo, _llm_directo)

    if resultado["exito"]:
        lineas_diff = resultado["diff"].strip() or "(sin cambios)"
        return (
            f"Propuse una mejora para {resultado['archivo']} y PASÓ todas las "
            f"pruebas en el sandbox (intento {resultado['intentos']}). "
            f"No toqué el archivo real: la propuesta quedó como {resultado['id']}.\n\n"
            f"--- DIFF ---\n{lineas_diff[:2000]}\n\n"
            "Decime 'aplicá la mejora' para escribirla, o 'descartá la mejora' si no te convence."
        )
    return (
        f"Intenté mejorar {resultado.get('archivo', archivo)} pero no lo logré: "
        f"{resultado['motivo']}. No toqué nada."
    )


def _cmd_listar_mejoras(texto, texto_original, sesion, assistant_name):
    mejoras = auto_mejora.listar_mejoras()
    if not mejoras:
        return "No hay mejoras pendientes de revisión."
    lineas = [
        f"- {m['id']}: {m['archivo']} (propuesta el {m['fecha'][:16].replace('T', ' ')})"
        for m in mejoras
    ]
    return ("Mejoras esperando tu decisión:\n" + "\n".join(lineas) +
            "\n\nDecime 'aplicá la mejora <id>' o 'descartá la mejora <id>'.")


def _extraer_id_mejora(texto_original):
    """Busca un id de mejora (aaaammdd_hhmmss) en el mensaje; si no hay,
    usa la más reciente pendiente."""
    encontrado = re.search(r'\d{8}_\d{6}', texto_original)
    if encontrado:
        return encontrado.group(0)
    mejoras = auto_mejora.listar_mejoras()
    return mejoras[0]["id"] if mejoras else None


def _cmd_aplicar_mejora(texto, texto_original, sesion, assistant_name):
    id_mejora = _extraer_id_mejora(texto_original)
    if not id_mejora:
        return "No hay ninguna mejora pendiente para aplicar."

    print(f"Re-verificando la mejora {id_mejora} en el sandbox antes de aplicar...")
    resultado = auto_mejora.aplicar_mejora(id_mejora)
    if resultado["exito"]:
        return (f"Mejora {id_mejora} aplicada a {resultado['archivo']} "
                "(re-verificada en el sandbox antes de escribir).")
    return f"No apliqué la mejora {id_mejora}: {resultado['motivo']}"


def _cmd_descartar_mejora(texto, texto_original, sesion, assistant_name):
    id_mejora = _extraer_id_mejora(texto_original)
    if not id_mejora:
        return "No hay ninguna mejora pendiente para descartar."
    resultado = auto_mejora.descartar_mejora(id_mejora)
    if resultado["exito"]:
        return f"Mejora {id_mejora} descartada (quedó archivada por si cambiás de idea)."
    return f"No pude descartarla: {resultado['motivo']}"


def _cmd_listar_sesiones(texto, texto_original, sesion, assistant_name):
    from core import sesiones  # import perezoso: evita el ciclo brain<->sesiones
    guardadas = sesiones.listar()
    if not guardadas:
        return "Todavía no hay chats guardados."
    lineas = [
        f"- {s['nombre']} ({s['mensajes']} mensajes, última vez {s['actualizada'][:16].replace('T', ' ')})"
        for s in guardadas[:10]
    ]
    return "Chats guardados (los más recientes):\n" + "\n".join(lineas)


def _cmd_mejorar_codigo(texto, texto_original, sesion, assistant_name):
    if DEBUG_MODE:
        print("DEBUG: entrando a mejorar_codigo")
    rutas = re.findall(r'[~/][\w/\.\-]+', texto_original)
    if not rutas:
        codigo_mejorado = consultar_llama(f"Mejorá este código. Devolvé ÚNICAMENTE el código mejorado:\n\n{texto_original}", sesion)
        print(f"\n--- CÓDIGO MEJORADO ---\n{codigo_mejorado}\n---")
        return "Revisá el código mejorado arriba."

    ruta = os.path.expanduser(rutas[0])
    contenido = leer_archivo(ruta)
    if not contenido:
        return f"No pude leer {ruta}."

    codigo_mejorado = consultar_llama(f"Reescribí este código Python completo con mejoras. Tu respuesta debe empezar DIRECTAMENTE con 'import' o 'def' o '#'. CERO explicaciones, CERO texto antes o después del código:\n\n{contenido}", sesion)
    print(f"\n--- VERSIÓN DE DOLPHIN ---\n{codigo_mejorado}\n---")

    print("\nConsultando al revisor experto...")
    revision = revisar_codigo(codigo_mejorado, objetivo="revisar esta mejora y señalar errores o mejoras adicionales")
    if revision:
        print(f"\n--- REVISIÓN DEL EXPERTO ---\n{revision}\n---")
        guardar_par_entrenamiento(contenido, codigo_mejorado, revision)
        print("(Par de entrenamiento guardado)")
    else:
        print("\n(El revisor externo no está disponible, seguí con la versión de dolphin.)")

    # Antes de ofrecer guardar, probamos la mejora en el sandbox:
    # si el archivo es parte del proyecto, corremos la suite entera
    # sobre una copia temporal; si es externo, al menos la sintaxis.
    print("\nProbando la mejora en el sandbox...")
    prueba = probar_cambio_en_proyecto(ruta, codigo_mejorado)
    if prueba["etapa"] == "fuera_del_proyecto":
        ok_sintaxis, error_sintaxis = verificar_sintaxis(codigo_mejorado)
        if ok_sintaxis:
            print("Sandbox: el archivo es externo al proyecto; la sintaxis es válida.")
        else:
            print(f"Sandbox: OJO, la versión nueva tiene un error de sintaxis: {error_sintaxis}")
    elif prueba["exito"]:
        print("Sandbox: todas las pruebas del proyecto pasan con esta versión.")
    else:
        print(
            f"Sandbox: OJO, esta versión ROMPE el proyecto (etapa: {prueba['etapa']}):\n"
            f"{prueba['salida'][-1200:]}\n{prueba['errores'][-400:]}"
        )

    confirmacion = input("¿Querés guardar la versión de dolphin? (si/no): ")
    if confirmacion.strip().lower() in ["si", "sí", "s", "yes"]:
        escribir_archivo(ruta, codigo_mejorado)
        return "Código guardado."
    return "Código no guardado."

def _cmd_anotar_nota(texto, texto_original, sesion, assistant_name):
    contenido = intenciones.extraer_nota_directa(texto_original)
    if not contenido:
        return "Decime qué querés que anote, por ejemplo: anotá: tu pensamiento acá."

    # Clasificamos TU texto tal cual, sin generar una respuesta conversacional
    # sobre él. Trabajo interno => _llm_directo (no ensucia historial ni dataset).
    clasificacion = cerebro.clasificar_nota(contenido, _llm_directo)
    titulo = clasificacion["titulo"]
    categoria = clasificacion["categoria"]
    tags = clasificacion["tags"]

    ruta = cerebro.guardar_nota(
        titulo=titulo,
        contenido=contenido,
        carpeta=categoria,
        tags=tags
    )
    if ruta:
        texto_tags = (" con tags " + ", ".join(tags)) if tags else ""
        return f"Anotado en «{categoria}» como «{titulo}»{texto_tags}."
    else:
        return "Quise anotarlo pero algo falló al escribir la nota."
    

def _cmd_guardar_en_cerebro(texto, texto_original, sesion, assistant_name):
    # Buscamos la última cosa que dijo el asistente en el historial.
    # Recorremos de atrás para adelante hasta encontrar un mensaje suyo.
    ultima_respuesta = None
    for mensaje in reversed(sesion.historial):
        if mensaje["role"] == "assistant":
            ultima_respuesta = mensaje["content"]
            break

    if not ultima_respuesta:
        return "No tengo nada reciente para guardar todavía. Decime algo primero y después pedime que lo guarde."

    # Clasificamos la nota: en una sola llamada al LLM obtenemos
    # título, categoría (carpeta) y tags. Reemplaza a generar_titulo.
    # Trabajo interno => _llm_directo (no ensucia historial ni dataset).
    clasificacion = cerebro.clasificar_nota(ultima_respuesta, _llm_directo)
    titulo = clasificacion["titulo"]
    categoria = clasificacion["categoria"]
    tags = clasificacion["tags"]

    ruta = cerebro.guardar_nota(
        titulo=titulo,
        contenido=ultima_respuesta,
        carpeta=categoria,      # la categoría decide la subcarpeta
        tags=tags
    )
    if ruta:
        # armamos un mensaje que muestra dónde y cómo lo guardó
        texto_tags = (" con tags " + ", ".join(tags)) if tags else ""
        return f"Guardado en «{categoria}» como «{titulo}»{texto_tags}."
    else:
        return "Quise guardarlo pero algo falló al escribir la nota."


def _cmd_guardar_recuerdo(texto, texto_original, sesion, assistant_name):
    recuerdo = extraer_recuerdo(texto)

    if recuerdo:
        guardado = guardar_recuerdo(recuerdo)

        # También a la memoria semántica: la lista simple entra ENTERA al
        # system prompt en cada turno (no escala); la semántica recupera
        # solo lo relevante por embeddings.
        try:
            guardar_recuerdo_semantico(recuerdo, categoria="usuario")
        except Exception:
            pass  # sin embeddings el recuerdo igual quedó en la lista

        if guardado:
            return f"Listo, voy a recordar que {recuerdo}."

        else:
            return f"Eso ya lo recordaba: {recuerdo}."

    return "No entendí qué querés que recuerde."


def _cmd_pensar_profundo(texto, texto_original, sesion, assistant_name):
    """Ruta híbrida: la pregunta va al modelo grande (70B vía Groq) con los
    últimos mensajes como contexto. Llega acá por dos caminos: pedido
    explícito ("pensalo bien" -> respuesta extensa) o derivación automática
    del clasificador ante una pregunta compleja (-> respuesta corta, formato
    de charla). La respuesta entra al historial para que el modelo local
    pueda seguir la charla desde ahí. Sin internet o sin key, responde el
    modelo local — avisando solo si el pedido fue explícito."""
    explicito = intenciones.pide_pensar_explicito(texto)
    respuesta = pensador.pensar_profundo(texto_original, sesion.historial, extenso=explicito)
    if respuesta is None:
        local = consultar_llama(texto_original, sesion) or "no pude generar una respuesta"
        if explicito:
            return "(No pude llegar a mi revisor externo, te lo pienso yo:) " + local
        return local

    sesion.historial.append({"role": "user", "content": texto_original})
    sesion.historial.append({"role": "assistant", "content": respuesta})
    if len(sesion.historial) > MAX_HISTORIAL:
        del sesion.historial[:-MAX_HISTORIAL]
    return respuesta


def _cmd_crear_recordatorio(texto, texto_original, sesion, assistant_name):
    que, cuando = agenda.extraer_recordatorio(texto_original, _llm_directo)
    if not que or not cuando:
        return (
            "No me quedó claro para cuándo. Repetímelo con el día y la hora, "
            "por ejemplo: recordame mañana a las nueve llamar al médico."
        )
    agenda.agendar(que, cuando)
    return f"Listo, agendado para el {agenda.formatear(cuando)}: {que}."


def _cmd_listar_recordatorios(texto, texto_original, sesion, assistant_name):
    proximos = agenda.pendientes()
    if not proximos:
        return "No tenés nada agendado por ahora."
    partes = [f"{r['texto']}, el {agenda.formatear(r['cuando'])}" for r in proximos]
    return "Tenés agendado: " + "; ".join(partes) + "."


def _cmd_cancelar_recordatorio(texto, texto_original, sesion, assistant_name):
    coincidencias = agenda.buscar(texto_original)
    if not coincidencias:
        return "No encontré ningún recordatorio que coincida con eso."
    if len(coincidencias) > 1:
        partes = [f"{r['texto']} ({agenda.formatear(r['cuando'])})" for r in coincidencias]
        return "Hay varios que coinciden: " + "; ".join(partes) + ". Decime cuál con más detalle."
    agenda.cancelar(coincidencias[0]["id"])
    return f"Cancelado: {coincidencias[0]['texto']}."


def _cmd_leer_recuerdos(texto, texto_original, sesion, assistant_name):
    recuerdos = leer_recuerdos()

    if recuerdos:
        recuerdos_texto = "; ".join(recuerdos)
        return f"Esto recuerdo de vos: {recuerdos_texto}"
    return "Todavía no tengo recuerdos guardados sobre vos."


def _cmd_olvidar_recuerdo(texto, texto_original, sesion, assistant_name):
    recuerdo = extraer_olvido(texto)

    if recuerdo:
        olvidado = olvidar_recuerdo(recuerdo)

        if olvidado:
            return f"Listo, ya no voy a recordar que {recuerdo}."
        else:
            return f"No encontré ese recuerdo: {recuerdo}."

    return "No entendí qué querés que olvide."


def _cmd_guardar_preferencia(texto, texto_original, sesion, assistant_name):
    tipo, valor = extraer_preferencia(texto)

    if tipo and valor:
        guardar_preferencia(tipo, valor)
        return f"Perfecto, voy a usar {valor} como {tipo}."

    return "No entendí la preferencia."


def _cmd_ver_pantalla(texto, texto_original, sesion, assistant_name):
    descripcion = ver_pantalla()
    return consultar_llama(f"Estoy viendo esto en mi pantalla: {descripcion}. Ayudame en base a eso.", sesion)


def _cmd_buscar_web(texto, texto_original, sesion, assistant_name):
    resultados = buscar_web(texto_original)
    contexto = formatear_resultados(resultados)
    return consultar_llama(f"El usuario preguntó: {texto_original}\n\nEncontré esta información en internet:\n{contexto}\n\nRespondé de forma concisa en 2-3 oraciones basándote en esa información.", sesion)


def _cmd_analizar_archivo(texto, texto_original, sesion, assistant_name):
    ruta = extraer_ruta_archivo(texto_original)
    tipo_analisis = extraer_tipo_analisis(texto_original)

    if not ruta:
        return "Necesito que me indiques la ruta del archivo. Ejemplo: 'analiza /ruta/del/archivo.py'"

    if not os.path.exists(ruta):
        return f"No encontré el archivo en: {ruta}"

    resultado = analizar_archivo(ruta, tipo_analisis)

    if not resultado:
        return f"No pude analizar el archivo: {ruta}"

    ruta_reporte = guardar_reporte(resultado, formato="markdown", tipo="archivo")
    return f"Análisis completado. Reporte guardado en: {ruta_reporte}\n\n{resultado['analisis']}"


def _cmd_analizar_proyecto(texto, texto_original, sesion, assistant_name):
    ruta = extraer_ruta_archivo(texto_original)
    tipo_analisis = extraer_tipo_analisis(texto_original)

    if not ruta:
        return "Necesito que me indiques la ruta del proyecto. Ejemplo: 'analiza mi proyecto /ruta/del/proyecto'"

    if not os.path.isdir(ruta):
        return f"No encontré la carpeta en: {ruta}"

    resultado = analizar_proyecto(ruta, tipo_analisis)

    if not resultado:
        return f"No encontré archivos Python en: {ruta}"

    ruta_reporte = guardar_reporte(resultado, formato="markdown", tipo="proyecto")
    return f"Análisis del proyecto completado. Reporte guardado en: {ruta_reporte}\nArchivos analizados: {resultado['archivos_analizados']}"


def _cmd_analizar_con_filtro(texto, texto_original, sesion, assistant_name):
    ruta = extraer_ruta_archivo(texto_original)
    tipo_analisis = extraer_tipo_analisis(texto_original)

    if not ruta:
        return "Necesito que me indiques el archivo o proyecto. Ejemplo: 'solo errores de /ruta/archivo.py'"

    if os.path.isfile(ruta):
        resultado = analizar_archivo(ruta, tipo_analisis)
        ruta_reporte = guardar_reporte(resultado, formato="markdown", tipo="archivo")
        return f"Análisis de {tipo_analisis} completado.\nReporte: {ruta_reporte}\n\n{resultado['analisis']}"
    elif os.path.isdir(ruta):
        resultado = analizar_proyecto(ruta, tipo_analisis)
        ruta_reporte = guardar_reporte(resultado, formato="markdown", tipo="proyecto")
        return f"Análisis del proyecto completado. Reporte guardado en: {ruta_reporte}"
    else:
        return f"No encontré archivo o carpeta en: {ruta}"


def _cmd_convertir_documento(texto, texto_original, sesion, assistant_name):
    ruta, extension = extraer_conversion(texto_original)
    if not ruta:
        return "No encontré qué archivo querés convertir. Ejemplo: 'convertí /ruta/archivo.md a pdf'."
    if not extension:
        return f"Encontré el archivo ({ruta}) pero no a qué formato lo querés pasar. Decime algo como 'a pdf' o 'a word'."

    ok, resultado = convertir_documento(os.path.expanduser(ruta), extension)
    if ok:
        return f"Listo, lo convertí: {resultado}"
    return f"No pude convertirlo: {resultado}"


def _cmd_leer_archivo(texto, texto_original, sesion, assistant_name):
    rutas = re.findall(r'[~/][\w/\.\-]+', texto_original)
    if rutas:
        ruta = os.path.expanduser(rutas[0])
        contenido = leer_archivo(ruta)
        if contenido:
            return consultar_llama(f"El usuario te pidió: {texto_original}\n\nContenido del archivo:\n{contenido}", sesion)
        else:
            return f"No pude leer el archivo {ruta}."
    return "No encontré ninguna ruta de archivo en tu mensaje."


# Tabla de despacho: intención → manejador. Las intenciones que no figuran
# acá (desconocida, abrir_navegador, abrir_opera…) caen en conversación normal.
MANEJADORES = {
    "ejecutar_tarea": _cmd_ejecutar_tarea,
    "borrar_todos_los_recuerdos": _cmd_borrar_todos_los_recuerdos,
    "confirmar_borrado": _cmd_confirmar_borrado,
    "buscar_en_internet": _cmd_buscar_en_internet,
    "consultar_hora": _cmd_consultar_hora,
    "consultar_nombre": _cmd_consultar_nombre,
    "saludo": _cmd_saludo,
    "auditar_codigo": _cmd_auditar_codigo,
    "crear_y_probar_codigo": _cmd_crear_y_probar_codigo,
    "probar_proyecto_sandbox": _cmd_probar_proyecto_sandbox,
    "probar_codigo_sandbox": _cmd_probar_codigo_sandbox,
    "auto_mejora": _cmd_auto_mejora,
    "listar_mejoras": _cmd_listar_mejoras,
    "aplicar_mejora": _cmd_aplicar_mejora,
    "descartar_mejora": _cmd_descartar_mejora,
    "listar_sesiones": _cmd_listar_sesiones,
    "mejorar_codigo": _cmd_mejorar_codigo,
    "guardar_en_cerebro": _cmd_guardar_en_cerebro,
    "guardar_recuerdo": _cmd_guardar_recuerdo,
    "leer_recuerdos": _cmd_leer_recuerdos,
    "crear_recordatorio": _cmd_crear_recordatorio,
    "listar_recordatorios": _cmd_listar_recordatorios,
    "cancelar_recordatorio": _cmd_cancelar_recordatorio,
    "pensar_profundo": _cmd_pensar_profundo,
    "olvidar_recuerdo": _cmd_olvidar_recuerdo,
    "guardar_preferencia": _cmd_guardar_preferencia,
    "ver_pantalla": _cmd_ver_pantalla,
    "buscar_web": _cmd_buscar_web,
    "analizar_archivo": _cmd_analizar_archivo,
    "analizar_proyecto": _cmd_analizar_proyecto,
    "analizar_con_filtro": _cmd_analizar_con_filtro,
    "leer_archivo": _cmd_leer_archivo,
    "convertir_documento": _cmd_convertir_documento,
    "guardar_en_cerebro": _cmd_guardar_en_cerebro,
    "anotar_nota": _cmd_anotar_nota,
}


# --- Despacho ------------------------------------------------------------------

def _resolver_confirmacion_tarea(texto_original, sesion):
    """La sesión estaba esperando un sí/no (o una opción a/b/c/d) para abrir
    una aplicación. Resuelve esa confirmación y limpia el estado."""
    if DEBUG_MODE:
        print(f"DEBUG ENTRANDO A CONFIRMACION con texto: '{texto_original}'")

    if sesion.opciones_pendientes and texto_original.strip().lower() in ["a", "b", "c", "d"]:
        letras = ["a", "b", "c", "d"]
        indice = letras.index(texto_original.strip().lower())
        if indice < len(sesion.opciones_pendientes):
            nombre, comando = sesion.opciones_pendientes[indice]
            sesion.esperando_confirmacion_tarea = False
            sesion.opciones_pendientes.clear()
            if DEBUG_MODE:
                print(f"DEBUG COMANDO: '{comando}'")
            try:
                proc = subprocess.Popen([comando], env=os.environ.copy())
                if DEBUG_MODE:
                    print(f"DEBUG PID: {proc.pid}")
                return f"Ejecutando {nombre}..."
            except Exception as e:
                if DEBUG_MODE:
                    print(f"DEBUG ERROR: {type(e).__name__}: {e}")
                return f"No pude abrir {nombre}."

    if texto_original.strip().lower().replace("í", "i") in ["si", "s", "yes", "y"]:
        sesion.esperando_confirmacion_tarea = False
        comando = ALIAS_PROGRAMAS.get(sesion.plan_pendiente, None)
        if not comando:
            comando = shutil.which(sesion.plan_pendiente)
        if not comando:
            primera_palabra = sesion.plan_pendiente.split()[0]
            comando = shutil.which(primera_palabra)
        if comando:
            try:
                subprocess.Popen([comando], env=os.environ.copy())
                return f"Ejecutando {sesion.plan_nombre}..."
            except Exception as e:
                if DEBUG_MODE:
                    print(f"DEBUG ERROR: {type(e).__name__}: {e}")
                return f"No pude abrir {sesion.plan_pendiente}."
        else:
            return f"No encontré {sesion.plan_pendiente} en el sistema."
    else:
        sesion.esperando_confirmacion_tarea = False
        sesion.plan_pendiente = ""
        return "Tarea cancelada."


def _cerrar_turno(sesion, texto_original, respuesta, len_historial_antes):
    """Persistencia por turno (solo sesiones con id). Si el manejador fue
    determinístico (no pasó por consultar_llama y por eso no tocó el
    historial), registramos el intercambio igual: el chat guardado debe
    reflejar TODO lo que se habló, no solo los turnos del LLM."""
    if not sesion.id:
        return respuesta

    if respuesta and len(sesion.historial) == len_historial_antes:
        sesion.historial.append({"role": "user", "content": texto_original})
        sesion.historial.append({"role": "assistant", "content": respuesta})
        if len(sesion.historial) > MAX_HISTORIAL:
            del sesion.historial[:-MAX_HISTORIAL]

    from core import sesiones  # import perezoso: evita el ciclo brain<->sesiones
    sesiones.guardar(sesion)
    return respuesta


def procesar_comando(texto, assistant_name, sesion=None):
    global ULTIMO_TURNO_STREAMEADO
    sesion = sesion or _sesion_default

    # arranca en False cada turno: solo consultar_llama con sink lo pone en True.
    # Así las respuestas determinísticas (hora, saludo, etc.) las habla la UI.
    ULTIMO_TURNO_STREAMEADO = False

    if DEBUG_MODE:
        print(f"DEBUG - ESPERANDO_TAREA: {sesion.esperando_confirmacion_tarea} | texto: {texto}")

    texto_original = texto
    len_historial_antes = len(sesion.historial)

    if sesion.esperando_confirmacion_tarea:
        respuesta = _resolver_confirmacion_tarea(texto_original, sesion)
        return _cerrar_turno(sesion, texto_original, respuesta, len_historial_antes)

    texto = normalizar_texto(texto)

    # Detección en dos niveles: reglas primero (gratis); si no reconocen nada,
    # el modelo clasifica el mensaje contra el catálogo de intenciones.
    # max_tokens acota la clasificación a un nombre de intención: el nombre
    # más largo del catálogo ronda los 8 tokens, generar más es tirar tiempo.
    intencion = intenciones.detectar(texto, funcion_llm=lambda p: _llm_directo(p, max_tokens=12))

    manejador = MANEJADORES.get(intencion)
    if manejador:
        respuesta = manejador(texto, texto_original, sesion, assistant_name)
    else:
        # Sin intención reconocida: conversación normal
        respuesta = consultar_llama(texto_original, sesion) or "no pude generar una respuesta"

    # Memoria proactiva: si el mensaje trae pinta de dato personal, un hilo
    # de fondo lo extrae y lo guarda DESPUÉS de responder (cero latencia
    # agregada al turno). Solo en sesiones persistentes: los tests y las
    # llamadas efímeras no disparan trabajo de fondo ni tocan disco.
    if sesion.id and intencion not in ("guardar_recuerdo",) and \
            memoria_auto.parece_dato_personal(texto_original):
        threading.Thread(
            target=memoria_auto.procesar_turno,
            args=(texto_original, _llm_directo),
            daemon=True,
        ).start()

    return _cerrar_turno(sesion, texto_original, respuesta, len_historial_antes)
