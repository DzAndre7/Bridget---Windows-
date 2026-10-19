"""
Capa de comprensión de texto: acá vive todo lo que convierte el mensaje
del usuario en una intención y en los datos que esa intención necesita
(rutas, recuerdos, preferencias, etc.).

Detección en dos niveles:
1. Reglas (detectar_intencion): frases clave, instantáneo y gratis.
   Resuelve los pedidos con formulación conocida.
2. LLM (clasificar_con_llm): si las reglas no reconocen nada, un modelo
   chico clasifica el mensaje contra el catálogo INTENCIONES_LLM. Así
   "fijate qué tenés en la pantalla" llega a ver_pantalla aunque no
   coincida con ninguna frase exacta.

detectar() combina los dos niveles. brain.py solo llama a detectar() y
despacha; este módulo no sabe nada de sesiones, TTS ni de Ollama: el LLM
entra como una función que se pasa por parámetro (mismo patrón que
cerebro.clasificar_nota), así que se testea con un modelo falso.
"""

import re
import unicodedata

from actions.agent_actions import ALIAS_PROGRAMAS


def normalizar_texto(texto):
    texto = texto.lower()

    #quita tildes
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto


def limpiar_texto_base(texto, assistant_name):
    texto = texto.lower().strip()

    ruido_inicial = [
        f"{assistant_name.lower()},",
        assistant_name.lower(),
        "hola",
        "buenas",
        "buenas noches",
        "buenas tardes",
        "buen día",
        "buen dia",
        "por favor",
        "podrías",
        "podrias",
        "podés",
        "podes",
        "che",
    ]

    ruido_inicial.sort(key=len, reverse=True)

    cambios = True
    while cambios:
        cambios = False

        for ruido in ruido_inicial:
            if texto.startswith(ruido):
                texto = texto[len(ruido):].strip(" ,¿?.,;:!")
                cambios = True
    texto = " ".join(texto.split())
    return texto


def es_intencion_busqueda(texto):
    texto = texto.lower()

    verbos_busqueda = [
        "buscar", "busca", "buscá", "buscame", "búscame",
        "encontrar", "encontra", "encontrá",
        "averiguar", "averigua", "averiguá"
    ]

    contexto_web = [
        "internet", "google", "web", "online"
    ]

    # con límites de palabra: 'busca' no debe matchear dentro de 'buscador'
    tiene_verbo = _contiene(texto, verbos_busqueda)
    tiene_contexto_web = _contiene(texto, contexto_web)

    return tiene_verbo and tiene_contexto_web


def extraer_consulta_busqueda(texto, assistant_name):
    texto = limpiar_texto_base(texto, assistant_name)

    palabras_a_sacar = {
        "buscar", "busca", "buscá", "buscame", "búscame",
        "encontrar", "encontra", "encontrá",
        "averiguar", "averigua", "averiguá",
        "internet", "google", "web", "online",
    }

    # nos quedamos solo con las palabras que no son "comando de búsqueda".
    # (Antes, si la consulta eran TODAS palabras de comando, `consulta` quedaba
    # sin asignar y esto lanzaba UnboundLocalError, rompiendo procesar_comando.)
    consulta_limpia = [
        p.strip(" ,¿?.,;:!") for p in texto.split()
        if p.strip(" ,¿?.,;:!").lower() not in palabras_a_sacar
    ]

    consulta = " ".join(" ".join(consulta_limpia).split()).strip()

    # sacamos conectores sueltos que hayan quedado al inicio o al final
    for sufijo in (" en la", " en el", " en"):
        if consulta.endswith(sufijo):
            consulta = consulta[: -len(sufijo)].strip()
    for prefijo in ("en la ", "en el ", "en "):
        if consulta.startswith(prefijo):
            consulta = consulta[len(prefijo):].strip()

    return consulta if consulta else None


# Cache de regex compilados: las listas de frases son fijas, así que cada
# frase se compila una sola vez en la vida del proceso.
_regex_frases = {}


def _regex_frase(frase):
    """Compila (y cachea) un regex que matchea la frase como palabra(s)
    completa(s): 'hora' matchea 'qué hora es' pero NO 'ahora'. Si la frase
    empieza o termina en un símbolo (ej: 'analiza /'), no se exige límite
    de palabra en ese borde, porque '/' ya no es letra."""
    patron = _regex_frases.get(frase)
    if patron is None:
        limpia = normalizar_texto(frase)
        inicio = r"(?<!\w)" if limpia[:1].isalnum() else ""
        fin = r"(?!\w)" if limpia[-1:].isalnum() else ""
        patron = re.compile(inicio + re.escape(limpia) + fin)
        _regex_frases[frase] = patron
    return patron


def _contiene(texto, frases):
    """True si alguna de `frases` aparece en `texto` como palabra(s)
    completa(s), ignorando tildes. Antes se buscaba por substring y cualquier
    palabra que CONTUVIERA la frase disparaba la intención: 'ahora' contenía
    'hora', 'confuso' contenía 'uso', 'borrador' contenía 'borra'. En una
    charla normal eso secuestraba mensajes enteros hacia comandos; con
    límites de palabra solo matchea la palabra real."""
    return any(_regex_frase(f).search(texto) for f in frases)


def _contiene_stem(texto, stems):
    """True si alguna palabra del texto EMPIEZA con alguno de `stems`:
    'record' cubre recordá/recordas/recordar sin listar cada conjugación.
    Ojo: un stem también matchea la palabra exacta ('récord' matchea el stem
    'record'), así que los stems solo se usan en reglas que exigen ADEMÁS
    otra condición (otra palabra clave en el mismo mensaje)."""
    return any(
        re.search(r"(?<!\w)" + re.escape(normalizar_texto(s)), texto)
        for s in stems
    )


# Frases que piden EXPLÍCITAMENTE pensar a fondo. Las usa la regla de
# detección y también brain, para distinguir el pedido explícito (respuesta
# extensa) de la derivación automática (respuesta corta, formato de charla).
FRASES_PENSAR_PROFUNDO = [
    "pensalo bien", "pensalo en serio", "pensalo a fondo",
    "pensá a fondo", "pensa a fondo", "pensemos en serio",
    "modo profundo", "consultalo con tu revisor",
    "preguntale a tu revisor", "preguntale al grande",
]


def pide_pensar_explicito(texto):
    return _contiene(texto, FRASES_PENSAR_PROFUNDO)


def detectar_intencion(texto):
    """Nivel 1: detección por reglas (frases clave). Rápida y determinística.
    Si nada matchea devuelve 'desconocida'; detectar() decide si consultar
    al clasificador LLM después."""
    texto = texto.lower().strip()

    if _contiene(texto, [
        "busca en internet", "buscá en internet", "busca online", "modo conectado", "busca en la web"
    ]):
        return "buscar_web"

    elif es_intencion_busqueda(texto):
        return "buscar_en_internet"

    elif texto in ["s", "y", "confirmar borrado"]:
        return "confirmar_borrado"

    elif extraer_nota_directa(texto) is not None:
        return "anotar_nota"

    elif _contiene(texto, [
        "guarda esto", "guardá esto", "guarda eso", "guardá eso",
        "anota esto", "anotá esto", "anota eso", "anotá eso",
        "guarda en tu cerebro", "guardá en tu cerebro",
        "guarda en el cerebro", "guardá en el cerebro",
        "guarda esto en tu cerebro", "guardá esto en tu cerebro"
    ]):
        return "guardar_en_cerebro"

    # Sandbox: van ANTES de "ejecutar_tarea" porque frases como
    # "ejecutá este código" matchearían "ejecutá" y abrirían una app.
    elif _contiene(texto, [
        "creá y probá", "crea y prueba", "generá y probá", "genera y prueba",
        "escribí y probá", "escribe y prueba", "programá y probá",
        "crear y probar", "creá y testeá",
    ]):
        return "crear_y_probar_codigo"

    elif _contiene(texto, [
        "probá tu código", "prueba tu código", "probate",
        "corré tus pruebas", "corre tus pruebas", "corré tus tests",
        "corre tus tests", "ejecutá tus pruebas", "ejecuta tus pruebas",
        "ejecutá tus tests", "ejecuta tus tests", "probá tus tests",
    ]):
        return "probar_proyecto_sandbox"

    elif _contiene(texto, [
        "probá este código", "prueba este código", "probá el código",
        "prueba el código", "probá el archivo", "prueba el archivo",
        "ejecutá este código", "ejecuta este código", "corré este código",
        "corre este código", "en el sandbox", "en la sandbox",
    ]):
        return "probar_codigo_sandbox"

    # Auto-mejora: también antes de "ejecutar_tarea" y de "mejorar_codigo"
    # (que matchea la palabra suelta "mejora").
    elif _contiene(texto, [
        "mejorate", "automejorate", "auto mejora", "automejora",
        "mejorá tu código", "mejora tu propio código", "mejorá tu propio código",
        "proponé una mejora", "propone una mejora", "proponeme una mejora",
        "proponete una mejora",
    ]):
        return "auto_mejora"

    elif _contiene(texto, [
        "qué mejoras tenés", "que mejoras tenes", "qué mejoras hay",
        "mejoras pendientes", "listá las mejoras", "lista las mejoras",
        "lista de mejoras",
    ]):
        return "listar_mejoras"

    elif _contiene(texto, [
        "aplicá la mejora", "aplica la mejora", "aplicá esa mejora",
        "aplica esa mejora", "acepto la mejora", "aceptá la mejora",
    ]):
        return "aplicar_mejora"

    elif _contiene(texto, [
        "descartá la mejora", "descarta la mejora", "rechazá la mejora",
        "rechaza la mejora", "no apliques la mejora",
    ]):
        return "descartar_mejora"

    elif _contiene(texto, [
        "qué chats", "que chats", "chats guardados", "qué sesiones",
        "que sesiones", "sesiones guardadas", "lista de chats",
        "listá los chats", "lista los chats",
    ]):
        return "listar_sesiones"

    # Sin "hacé/hace": es el verbo más ambiguo del español rioplatense
    # ("hace calor", "hace mucho que..."). Los pedidos con "haceme" siguen
    # matcheando; el resto lo resuelve el clasificador LLM con contexto.
    elif _contiene(texto, [
        "ejecutá", "ejecuta", "ejecutame", "haceme", "abrí", "abri", "abrime",
        "mandá", "manda", "mandame", "escribile", "enviá", "envia", "enviame",
        "inicia", "iniciá",
    ]):
        return "ejecutar_tarea"

    # Pensamiento profundo: el pedido explícito de calidad manda la pregunta
    # al modelo grande (70B vía Groq) en vez del local. (La derivación
    # AUTOMÁTICA de preguntas complejas la decide el clasificador LLM de
    # nivel 2 con el catálogo; acá solo el pedido explícito.)
    elif pide_pensar_explicito(texto):
        return "pensar_profundo"

    # Agenda: va antes que la memoria porque "recordame mañana..." comparte
    # raíz con "recordá que..." (memoria) pero es una alarma, no un dato.
    elif _contiene(texto, [
        "que tengo agendado", "qué tengo agendado", "que hay agendado",
        "mis recordatorios", "que recordatorios", "qué recordatorios",
        "mis alarmas", "que alarmas", "qué alarmas", "mi agenda",
        "en la agenda",
    ]):
        return "listar_recordatorios"

    elif _contiene_stem(texto, ["cancel", "borr", "elimin", "sac"]) and \
            _contiene(texto, ["recordatorio", "recordatorios", "alarma", "alarmas"]):
        return "cancelar_recordatorio"

    elif _contiene(texto, [
        "recordame", "recuerdame", "acordame", "avisame", "agendame",
        "agenda que", "poneme una alarma", "pone una alarma",
        "poné una alarma", "poneme un recordatorio",
    ]):
        return "crear_recordatorio"

    elif _contiene_stem(texto, ["borr", "olvid", "elimin"]) and \
            _contiene(texto, ["todos", "toda", "todo"]) and \
            _contiene(texto, ["recuerdos", "memoria"]):
        return "borrar_todos_los_recuerdos"

    elif _contiene(texto, ["olvida que", "olvidá que", "olvidate de", "olvidate que"]) or (
        _contiene_stem(texto, ["borr", "elimin"])
        and _contiene(texto, ["recuerdo", "recuerdos"])
    ):
        return "olvidar_recuerdo"

    # Guardar va ANTES que leer: "recordá que mi hermana..." trae la palabra
    # "mi" y con el orden inverso caía en leer_recuerdos.
    elif _contiene(texto, [
        "recordá que", "recorda que", "recuerda que", "acordate",
        "no te olvides",
    ]):
        return "guardar_recuerdo"

    elif (_contiene_stem(texto, ["record", "acord", "recuerd"]) or
          _contiene(texto, ["sabes", "sabés"])) and _contiene(texto, ["mi", "mis"]):
        return "leer_recuerdos"

    elif _contiene(texto, [
        "qué hora", "que hora", "hora es", "tenés hora", "tenes hora",
        "tienes hora", "tenés la hora", "tienes la hora", "decime la hora",
        "dame la hora", "dime la hora",
    ]):
        return "consultar_hora"

    elif _contiene(texto, [
        "cómo te llamas", "como te llamas", "cuál es tu nombre", "cual es tu nombre",
        "tu nombre", "quién sos", "quien sos"
    ]):
        return "consultar_nombre"

    elif _contiene(texto, [
    "hola", "buenas", "buen día", "buen dia", "buenas tardes", "buenas noches"
    ]):
        if len(texto.split()) < 4:
            return "saludo"

    # "uso" solo como palabra Y con una herramienta cerca: antes el substring
    # "uso" (¡adentro de "confuso"!) mandaba charla común a guardar_preferencia.
    elif _contiene(texto, ["uso"]) and _contiene(texto, ["navegador", "editor", "programa"]):
        return "guardar_preferencia"

    elif _contiene(texto, [
        "mirá mi pantalla", "mira mi pantalla", "mirá la pantalla", "mira la pantalla",
        "observá mi pantalla", "observa mi pantalla", "observá la pantalla",
        "qué ves en mi pantalla", "que ves en mi pantalla", "ves mi pantalla"
    ]):
        return "ver_pantalla"

    elif _contiene(texto, [
        "analiza mi proyecto", "analiza el proyecto", "analizá mi proyecto",
        "analiza /", "analizá /", "revisa el proyecto"
    ]):
        return "analizar_proyecto"

    elif _contiene(texto, [
        "analiza el archivo", "analizá el archivo", "revisa el archivo"
    ]):
        return "analizar_archivo"

    elif _contiene(texto, [
        "solo errores", "solo seguridad", "solo optimizacion", "solo calidad",
        "solo errores de", "solo seguridad de", "busca errores", "busca vulnerabilidades"
    ]):
        return "analizar_con_filtro"

    # Verbos de mejora SOLO si el mensaje habla de código: "me gustaría
    # mejorar mi inglés" o "arreglá eso que dijiste" son charla, no un
    # pedido de refactor. Sin la palabra de contexto, decide el clasificador
    # LLM (que sí entiende la diferencia).
    elif _contiene_stem(texto, ["optimiz", "mejora", "refactoriz", "corrig", "corregi", "arregl"]) and (
        _contiene(texto, ["codigo", "archivo", "funcion", "script", "programa", "proyecto"])
        or any(ind in texto for ind in ["/home/", "/tmp/", "~/", ".py"])
    ):
        return "mejorar_codigo"

    elif _contiene(texto, [
        "buscá errores", "busca errores", "encontrá errores", "encontrar errores",
    ]):
        return "mejorar_codigo"

    # Va ANTES que leer_archivo: un pedido de conversión también trae una
    # ruta ("/nota.md") y caería ahí si no se chequea primero.
    elif _contiene(texto, [
        "convertí", "converti", "convertime", "convertilo", "convertila",
        "pasame", "pasalo a", "pasala a", "pasá a", "pasa a",
        "exportá a", "exporta a", "exportalo a", "exportala a",
    ]) and extraer_conversion(texto)[0]:
        return "convertir_documento"

    elif any(indicador in texto for indicador in  ["/home/", "/tmp/", "~/", ".py", ".txt", ".md", ".json"]):
        return "leer_archivo"

    elif _contiene(texto, [
        "auditá tu código", "audita tu código", "auditá tu codigo", "audita tu codigo",
        "auditoría", "auditoria", "auditate", "revisá todo tu código", "autoauditoría"
    ]):
        return "auditar_codigo"

    return "desconocida"


# --- Nivel 2: clasificación con LLM ----------------------------------------
# Catálogo de intenciones que el clasificador puede elegir. No están todas:
# solo las que un modelo chico puede distinguir bien y cuyos manejadores
# degradan con gracia si falta algún dato (piden la ruta, avisan, etc.).
# "conversar" es la válvula de escape: cualquier cosa que no encaje.
INTENCIONES_LLM = {
    "buscar_en_internet": "pide buscar información en internet o en la web",
    "ejecutar_tarea": "pide abrir o ejecutar una aplicación o programa del sistema",
    "consultar_hora": "pregunta qué hora es",
    "ver_pantalla": "pide que mires o describas lo que hay en la pantalla",
    "guardar_recuerdo": "pide que recuerdes un dato sobre el usuario",
    "crear_recordatorio": "pide agendar, recordarle o avisarle algo en un momento dado (alarma, recordatorio, cita, turno)",
    "listar_recordatorios": "pregunta qué tiene agendado: sus recordatorios, alarmas o agenda",
    "cancelar_recordatorio": "pide cancelar o borrar un recordatorio, alarma o cita agendada",
    "pensar_profundo": "pregunta compleja o abierta que merece una respuesta pensada en profundidad (análisis, decisiones importantes, comparaciones, explicaciones técnicas o filosóficas elaboradas), o pedido explícito de pensar a fondo",
    "leer_recuerdos": "pregunta qué recordás o sabés del usuario",
    "olvidar_recuerdo": "pide que olvides o borres un recuerdo puntual",
    "guardar_en_cerebro": "pide guardar lo último conversado en tus notas",
    "auditar_codigo": "pide que audites o revises todo tu propio código fuente",
    "mejorar_codigo": "pide que mejores, optimices o corrijas un código o archivo",
    "analizar_archivo": "pide un análisis de un archivo de código concreto",
    "analizar_proyecto": "pide un análisis de una carpeta o proyecto entero",
    "crear_y_probar_codigo": "pide que escribas o crees un programa/script/código nuevo y verifiques que funciona",
    "probar_codigo_sandbox": "pide que ejecutes o pruebes un código o archivo dado",
    "probar_proyecto_sandbox": "pide que corras tus propios tests o pruebas",
    "auto_mejora": "pide que te mejores a vos misma: que propongas una mejora a tu propio código",
    "listar_mejoras": "pregunta qué mejoras propuestas están pendientes de revisión",
    "aplicar_mejora": "pide aplicar o aceptar una mejora que habías propuesto",
    "descartar_mejora": "pide descartar o rechazar una mejora que habías propuesto",
    "listar_sesiones": "pregunta qué chats o sesiones guardadas existen",
    "convertir_documento": "pide convertir, exportar o pasar un archivo a otro formato (pdf, word, html, epub, etc.)",
    "conversar": "cualquier otra cosa: charla, preguntas generales, opiniones, pedidos que no encajan arriba",
}


def clasificar_con_llm(texto, funcion_llm):
    """Nivel 2: clasifica el mensaje contra INTENCIONES_LLM usando el modelo.
    Devuelve el nombre de una intención del catálogo, o 'desconocida' si el
    modelo eligió 'conversar', respondió cualquier cosa, o falló. Nunca
    lanza: un clasificador caído se comporta igual que 'no entendí' y la
    conversación sigue por el camino normal."""
    opciones = "\n".join(
        f"- {nombre}: {descripcion}"
        for nombre, descripcion in INTENCIONES_LLM.items()
    )
    # El mensaje del usuario va al FINAL a propósito: todo lo anterior es
    # idéntico turno a turno, así que Ollama reusa ese prefijo del caché de
    # prompt y solo evalúa el mensaje nuevo.
    prompt = (
        "Sos el clasificador de intenciones de un asistente personal de voz. "
        "Elegí UNA sola intención para el mensaje del usuario.\n\n"
        f"Intenciones posibles:\n{opciones}\n\n"
        "Guía: ante la duda elegí 'conversar'. Verbos como mejorar, arreglar "
        "o probar solo son intenciones de código si el mensaje habla de "
        "código, archivos o programas. La charla liviana, los saludos y las "
        "preguntas simples son 'conversar'; 'pensar_profundo' es para "
        "preguntas que necesitan análisis elaborado: armar planes o rutinas, "
        "comparar caminos o decisiones, explicar en profundidad temas "
        "técnicos o filosóficos. El mensaje viene de voz transcripta: puede "
        "traer palabras mal transcriptas.\n\n"
        "Ejemplos:\n"
        "- \"che, ¿tenés idea de qué hora es?\" -> consultar_hora\n"
        "- \"me gustaría mejorar mi inglés\" -> conversar\n"
        "- \"fijate cuánto sale el dólar hoy\" -> buscar_en_internet\n"
        "- \"abrime el navegador\" -> ejecutar_tarea\n"
        "- \"acordate de que mañana tengo turno con el médico\" -> guardar_recuerdo\n"
        "- \"¿probaste alguna vez el mate dulce?\" -> conversar\n"
        "- \"¿me conviene especializarme en redes o en seguridad ofensiva? "
        "dame un análisis de los dos caminos\" -> pensar_profundo\n"
        "- \"¿cómo podría organizar mis estudios este año?\" -> pensar_profundo\n"
        "- \"¿por qué los humanos soñamos? explicámelo bien\" -> pensar_profundo\n"
        "- \"¿cómo andás?\" -> conversar\n"
        "- \"pasame /home/bridget/informe.md a pdf\" -> convertir_documento\n\n"
        f"Mensaje del usuario: \"{texto}\"\n\n"
        "Respondé SOLO con el nombre exacto de la intención (por ejemplo: "
        "conversar), sin explicaciones ni puntuación."
    )

    try:
        respuesta = funcion_llm(prompt).strip().lower()
    except Exception:
        return "desconocida"

    # match exacto primero; si el modelo agregó texto alrededor, buscamos
    # el primer nombre del catálogo que aparezca en la respuesta
    eleccion = None
    if respuesta in INTENCIONES_LLM:
        eleccion = respuesta
    else:
        for nombre in INTENCIONES_LLM:
            if nombre in respuesta:
                eleccion = nombre
                break

    if eleccion is None or eleccion == "conversar":
        return "desconocida"
    return eleccion


def detectar(texto, funcion_llm=None):
    """Detección completa: reglas primero; si no reconocen nada y hay un
    modelo disponible, clasifica con LLM. 'desconocida' significa 'seguí
    por conversación normal'."""
    intencion = detectar_intencion(texto)
    if intencion != "desconocida" or funcion_llm is None:
        return intencion

    # mensajes de una sola palabra ("ok", "dale"): no vale la pena gastar
    # una llamada al modelo, casi seguro es conversación
    if len(texto.split()) < 2:
        return intencion

    return clasificar_con_llm(texto, funcion_llm)


# --- Extractores: sacan los datos que cada intención necesita ---------------

def extraer_recuerdo(texto):
    texto = texto.strip()

    frases_disparadoras = [
        "recordá que",
        "recorda que",
        "recuerdas que",
        "te acordas de"
    ]

    texto_lower = texto.lower()

    for frase in frases_disparadoras:
        if frase in texto_lower:
            inicio = texto_lower.find(frase) + len(frase)
            recuerdo = texto[inicio:].strip(" ,¿?.,;:!")
            return recuerdo
    return None


def extraer_olvido(texto):
    texto = texto.strip()
    texto_lower = texto.lower()

    frases_disparadoras = [
        "olvidate que",
        "olvida que",
        "olvidá qué",
        "borra el recuerdo de que",
        "borrá el recuerdo de que",
        "el recuerdo de que",
        "olvida",
        "olvidá que",
        "olvidate de"
    ]

    for frase in frases_disparadoras:
        if frase in texto_lower:
            inicio = texto_lower.find(frase) + len(frase)
            recuerdo = texto[inicio:].strip(" ,¿?.,;:!")
            return recuerdo
    return None

def extraer_nota_directa(texto):
    """Detecta 'anotá: <texto>' / 'escribí: <texto>' / 'guardá: <texto>'
    (con o sin tilde, mayúsculas variables) y devuelve el texto tal cual,
    palabra por palabra. Es para capturar un pensamiento del usuario
    textualmente, sin que pase por el modelo ni se convierta en la
    respuesta de Bridget sobre el tema."""
    texto = texto.strip()
    texto_lower = texto.lower()

    disparadores = ["nota","anota", "anotá", "escribi", "escribí", "guarda", "guardá"]

    for disp in disparadores:
        patron = disp + ":"
        if texto_lower.startswith(patron):
            contenido = texto[len(patron):].strip()
            return contenido if contenido else None

    return None


def extraer_preferencia(texto):
    texto = texto.lower().strip()

    herramientas = ["navegador", "editor", "programa"]

    for herramienta in herramientas:
        if herramienta in texto:
            if "uso" in texto:
                partes = texto.split("uso", 1)
                valor = partes[1].strip(" ,¿?.,;:!")
                return herramienta, valor
    return None, None


# Formatos que pandoc sabe convertir, con la extensión de salida real
# (así "word"/"powerpoint" también se reconocen, no solo la extensión).
_FORMATOS_PANDOC = {
    "pdf": "pdf",
    "word": "docx", "docx": "docx",
    "odt": "odt", "opendocument": "odt",
    "html": "html",
    "epub": "epub",
    "markdown": "md", "md": "md",
    "texto plano": "txt", "txt": "txt",
    "rtf": "rtf",
    "powerpoint": "pptx", "pptx": "pptx",
    "latex": "tex",
}


def extraer_conversion(texto):
    """De un pedido como 'convertí /ruta/archivo.md a pdf' saca
    (ruta, extension_destino). (None, None) si no hay ninguna ruta en el
    mensaje; (ruta, None) si hay ruta pero no se reconoce el formato pedido."""
    rutas = re.findall(r'[~/][\w/\.\-]+', texto)
    if not rutas:
        return None, None
    ruta = rutas[0]

    # el formato se busca en lo que queda DESPUÉS de sacar la ruta: si no,
    # la propia extensión del archivo de entrada (ej. ".md") se confundiría
    # con el formato de destino pedido.
    resto = texto.replace(ruta, "")
    for palabra, extension in _FORMATOS_PANDOC.items():
        if _contiene(resto, [palabra]):
            return ruta, extension
    return ruta, None


def extraer_objeto_apertura(texto):
    palabras = texto.split()

    disparadores = ["abrí", "abre", "abrir", "abri", "iniciá", "ejecutá"]

    for i, palabra in enumerate(palabras):
        if palabra in disparadores:
            objeto = " ".join(palabras[i + 1:])
            return objeto.strip()

    return None


def clasificar_objeto_apertura(objeto):
    if not objeto:
        return None, None

    objeto = objeto.lower()

    categorias = ["navegador", "editor", "reproductor"]

    palabras = objeto.split()
    palabras_filtradas = [p for p in palabras if p not in ["el", "la", "los", "las"]]

    objeto_limpio = " ".join(palabras_filtradas)
    objeto_limpio = normalizar_nombre_programa(objeto_limpio)

    if objeto_limpio in categorias:
        return "categoria", objeto_limpio

    if objeto_limpio in ALIAS_PROGRAMAS:
        return "programa", objeto_limpio

    return None, None


def normalizar_nombre_programa(objeto):
    if not objeto:
        return None
    objeto = objeto.lower().strip()

    alias_programas = {
        "vs code": "vscode",
        "visual studio code": "vscode",
        "google chrome": "chrome",
        "bloc de notas": "notepad",
        "bloq de notas": "notepad",
        "notas": "notepad",
        "calculadora": "calc"
    }

    if objeto in alias_programas:
        return alias_programas[objeto]

    return objeto


def extraer_ruta_archivo(texto):
    """Extrae la ruta de un archivo del comando."""
    patron = r'(/[a-zA-Z0-9_\-./~]+\.py|/[a-zA-Z0-9_\-./~]+)'
    coincidencias = re.findall(patron, texto)
    if coincidencias:
        return coincidencias[0].strip()
    return None


def extraer_tipo_analisis(texto):
    """Extrae el tipo de análisis si se menciona específicamente."""
    texto_lower = texto.lower()

    if "solo errores" in texto_lower or "solo bugs" in texto_lower:
        return "errores"
    elif "solo seguridad" in texto_lower or "vulnerabilidades" in texto_lower:
        return "seguridad"
    elif "solo optimizacion" in texto_lower or "solo performance" in texto_lower:
        return "optimizacion"
    elif "solo calidad" in texto_lower or "solo estilo" in texto_lower:
        return "calidad"

    return "completo"
