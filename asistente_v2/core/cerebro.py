import os
import re

from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_vault_path():
    """
    Lee la ruta del vault desde .env (VAULT_PATH).
    Expande '~' si lo usaras, y verifica que la carpeta exista.
    Devuelve un objeto Path listo para usar.
    """
    ruta_cruda = os.getenv("VAULT_PATH")
    if not ruta_cruda:
        raise ValueError(
            "VAULT_PATH no está definido en .env. "
            "Agregá una línea como: VAULT_PATH=/home/bridget/Documentos/Obsidian/cerebro"
        )
    # expanduser convierte '~' en la ruta real del home, si lo usaras
    vault = Path(ruta_cruda).expanduser()
    if not vault.exists():
        raise FileNotFoundError(f"El vault no existe en la ruta: {vault}")
    if not vault.is_dir():
        raise NotADirectoryError(f"La ruta del vault no es una carpeta: {vault}")
    return vault

def _es_nota_valida(ruta):
    """
    Decide si una nota debe ser leída por Bridget.
    Ignora las carpetas internas de Obsidian: .trash (papelera) y .obsidian (configuración de la app). El cerebro real son tus notas,
    no la basura ni la config.
    """

    partes = ruta.parts 
    carpetas_ignoradas = {".trash", ".obsidian"}
    #si alguna carpeta de la ruta está en la lista negra, no es válida
    return not any(parte in carpetas_ignoradas for parte in partes)

def listar_notas():
    """
    Recorre todo el vault (incluyendo subcarpetas) y devuelve una lista
    con la ruta de cada nota .md encontrada.
    Es la base para que Bridget 'sepa' qué tiene en la cabeza.
    """
    vault = _get_vault_path()
    notas = [n for n in vault.rglob("*.md") if _es_nota_valida(n)]
    return notas
   

def leer_nota(nombre):
    """
    Busca una nota por su nombre (con o sin la extensión .md) y devuelve
    su contenido como texto. Si hay varias con el mismo nombre, devuelve
    la primera que encuentra. Si no existe, devuelve None.
    """
    vault = _get_vault_path()
    # normalizamos: aceptamos 'mi nota' o 'mi nota.md'
    if not nombre.endswith(".md"):
        nombre = nombre + ".md"

    for nota in vault.rglob("*.md"):
        if not _es_nota_valida(nota):
            continue
        if nota.name.lower() == nombre.lower():
            try:
                return nota.read_text(encoding="utf-8")
            except Exception as e:
                return f"[Error al leer la nota: {e}]"
    return None


def buscar_en_notas(texto):
    """
    Busca un texto dentro del contenido de todas las notas.
    Devuelve una lista de diccionarios con el nombre de la nota y un
    fragmento de contexto donde aparece el texto.
    Esta es la función que Bridget más va a usar: '¿qué sé sobre X?'.
    """
    vault = _get_vault_path()
    texto_lower = texto.lower()
    resultados = []

    for nota in vault.rglob("*.md"):
        if not _es_nota_valida(nota):
            continue
        try:
            contenido = nota.read_text(encoding="utf-8")
        except Exception:
            continue  # si una nota falla, la salteamos sin romper todo

        if texto_lower in contenido.lower():
            # buscamos la posición para dar un fragmento de contexto
            pos = contenido.lower().find(texto_lower)
            inicio = max(0, pos - 80)
            fin = min(len(contenido), pos + 80)
            fragmento = contenido[inicio:fin].strip()
            resultados.append({
                "nota": nota.name,
                "ruta": str(nota),
                "fragmento": f"...{fragmento}..."
            })

    return resultados

def _limpiar_nombre_archivo(titulo):
    """
    Convierte un título en un nombre de archivo seguro y portable.
    Saca caracteres que rompen en algún sistema operativo (/ \\ : * ? " < > |),
    colapsa espacios, y recorta largo excesivo.
    """
    # sacamos caracteres prohibidos en nombres de archivo
    limpio = re.sub(r'[/\\:*?"<>|]', '', titulo)
    # colapsamos espacios múltiples a uno solo
    limpio = re.sub(r'\s+', ' ', limpio).strip()
    # límite de largo razonable para el nombre
    if len(limpio) > 80:
        limpio = limpio[:80].strip()
    # si quedó vacío por algún motivo, ponemos algo
    if not limpio:
        limpio = "nota sin titulo"
    return limpio


def _construir_nota(titulo, contenido, origen, enlaces=None, tags=None):
    """
    Arma el texto markdown completo de una nota con formato consistente:
    título, contenido, tags, y un bloque de metadatos al final.
    'tags' es una lista de etiquetas (sin #, se agregan acá).
    """
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    # bloque de tags al estilo Obsidian (#tag)
    bloque_tags = ""
    if tags:
        linea_tags = " ".join(f"#{t}" for t in tags)
        bloque_tags = f"\n\n{linea_tags}"

    bloque_enlaces = ""
    if enlaces:
        lineas_enlace = "\n".join(f"[[{e}]]" for e in enlaces)
        bloque_enlaces = f"\n\n## Relacionado\n{lineas_enlace}"

    nota = f"""# {titulo}

{contenido}{bloque_tags}{bloque_enlaces}

---
*Creado: {fecha}*
*Origen: {origen}*
"""
    return nota

def guardar_nota(titulo, contenido, carpeta="conversaciones", enlaces=None, tags=None):
    """
    Guardado DIRECTO: crea una nota de pleno derecho en el vault.
    Es lo que se usa cuando VOS decís 'guardá esto'.
    Devuelve la ruta de la nota creada, o None si falló.

    carpeta: subcarpeta destino (la categoría: 'personal', 'conocimiento', etc.)
    enlaces: lista opcional de notas a relacionar con [[ ]]
    tags: lista opcional de etiquetas para la nota
    """
    vault = _get_vault_path()
    nombre = _limpiar_nombre_archivo(titulo)
    destino = vault / carpeta

    destino.mkdir(parents=True, exist_ok=True)

    ruta = destino / f"{nombre}.md"

    contador = 2
    while ruta.exists():
        ruta = destino / f"{nombre} ({contador}).md"
        contador += 1

    texto = _construir_nota(titulo, contenido, origen="conversación", enlaces=enlaces, tags=tags)

    try:
        ruta.write_text(texto, encoding="utf-8")
        return str(ruta)
    except Exception as e:
        print(f"[Error al guardar nota: {e}]")
        return None


def guardar_en_inbox(titulo, contenido, motivo=""):
    """
    Captura a INBOX: cuando Bridget ESTIMA que algo vale, lo deja acá
    pendiente de tu revisión. No ensucia el cerebro directamente.
    'motivo' es por qué Bridget creyó que valía la pena (para que vos
    decidas al revisar).
    Devuelve la ruta, o None si falló.
    """
    vault = _get_vault_path()
    nombre = _limpiar_nombre_archivo(titulo)
    destino = vault / "_inbox"
    destino.mkdir(parents=True, exist_ok=True)

    ruta = destino / f"{nombre}.md"
    contador = 2
    while ruta.exists():
        ruta = destino / f"{nombre} ({contador}).md"
        contador += 1

    # en el inbox agregamos el motivo de la estimación
    contenido_con_motivo = contenido
    if motivo:
        contenido_con_motivo += f"\n\n> **Por qué lo guardé:** {motivo}"

    texto = _construir_nota(
        titulo, contenido_con_motivo, origen="estimación (pendiente de revisión)"
    )

    try:
        ruta.write_text(texto, encoding="utf-8")
        return str(ruta)
    except Exception as e:
        print(f"[Error al guardar en inbox: {e}]")
        return None

def generar_titulo(contenido, funcion_llm):
    """
    Genera un título corto (máx 3 palabras) para una nota, usando el LLM.
    'funcion_llm' es la función que consulta tu modelo (ej: consultar_llama),
    se pasa como parámetro para no acoplar cerebro.py con brain.py.
    Si el modelo se va de tema, recorta a las primeras 3 palabras.
    """
    prompt = (
        "Generá un título de máximo 3 palabras para esta nota."
        "Respondé SOLO el título, sin comillas, sin explicación, sin punto final.\n\n"
        f"Nota:\n{contenido[:500]}"
    )
    try:
        titulo = funcion_llm(prompt).strip()
        #red de seguridad: si dolphin3 se zarpó y escribió de más, 
        #recortamos a las primeras 3 palabras
        palabras = titulo.split()
        if len(palabras) > 3:
            titulo = " ".join(palabras[:3])

        titulo = titulo.strip('"\'.:').strip()
        if not titulo: 
            return "Nota sin titulo"
        return titulo 
    except Exception:
        return "Nota sin titulo"

# Palabras vacías: frecuentes pero sin valor para buscar. Las ignoramos
# para que no contaminen la búsqueda (ej: "sobre" matcheaba notas irrelevantes).
STOPWORDS = {
    "sobre", "sabes", "sabés", "saber", "para", "como", "cómo", "que", "qué",
    "cual", "cuál", "donde", "dónde", "cuando", "cuándo", "porque", "por",
    "con", "sin", "los", "las", "una", "uno", "del", "este", "esta", "eso",
    "esto", "tiene", "hacer", "puede", "decime", "contame", "explicame",
    "explicáme", "decirme", "algo", "todo", "muy", "más", "mas", "pero",
}

# Categorías fijas del cerebro. De general a específico: por ahora estas cuatro
# amplias; más adelante se subdivide con tags o subcarpetas según haga falta.
CATEGORIAS_VALIDAS = {"personal", "conocimiento", "proyectos", "conversaciones"}


def clasificar_nota(contenido, funcion_llm):
    """
    En una sola llamada al LLM, obtiene categoría, tags y título de una nota.
    Devuelve un dict: {"categoria": str, "tags": [str], "titulo": str}.
    'funcion_llm' es la función que consulta el modelo (se pasa como parámetro
    para no acoplar cerebro.py con brain.py, igual que generar_titulo).

    Tiene red de seguridad: si el modelo devuelve algo raro, cae a valores
    por defecto seguros en vez de romper.
    """
    prompt = (
        "Analizá esta nota y respondé EXACTAMENTE en este formato, sin agregar nada más:\n"
        "CATEGORIA: <una de: personal, conocimiento, proyectos, conversaciones>\n"
        "TAGS: <entre 2 y 4 palabras clave separadas por comas, sin #>\n"
        "TITULO: <máximo 3 palabras>\n\n"
        "Guía para la categoría:\n"
        "- personal: datos del usuario, gustos, preferencias, su vida\n"
        "- conocimiento: información factual, técnica, cosas aprendidas\n"
        "- proyectos: código, tareas, cosas en las que trabaja\n"
        "- conversaciones: charlas generales que no entran en las otras\n\n"
        f"Nota:\n{contenido[:600]}"
    )

    # valores por defecto seguros, por si algo falla
    resultado = {
        "categoria": "conversaciones",
        "tags": [],
        "titulo": "Nota sin titulo"
    }

    try:
        respuesta = funcion_llm(prompt).strip()
    except Exception:
        return resultado

    # parseamos línea por línea, buscando cada campo
    for linea in respuesta.splitlines():
        linea = linea.strip()
        arriba = linea.upper()

        if arriba.startswith("CATEGORIA:"):
            cat = linea.split(":", 1)[1].strip().lower()
            # solo aceptamos categorías válidas; si inventó otra, queda el default
            if cat in CATEGORIAS_VALIDAS:
                resultado["categoria"] = cat

        elif arriba.startswith("TAGS:"):
            crudo = linea.split(":", 1)[1].strip()
            # separamos por coma, limpiamos, sacamos '#' si lo puso igual
            tags = [
                t.strip().lstrip("#").replace(" ", "_")
                for t in crudo.split(",")
                if t.strip()
            ]
            # respetamos el rango 2-4: recortamos si se zarpó
            resultado["tags"] = tags[:4]

        elif arriba.startswith("TITULO:"):
            titulo = linea.split(":", 1)[1].strip().strip('"\'.:').strip()
            palabras = titulo.split()
            if len(palabras) > 3:
                palabras = palabras[:3]
            # sacamos conectores sueltos al final (evita títulos como "Horario nocturno y")
            conectores = {"y", "o", "e", "u", "de", "con", "en", "a", "el", "la"}
            while palabras and palabras[-1].lower() in conectores:
                palabras.pop()
            titulo = " ".join(palabras)
            if titulo:
                resultado["titulo"] = titulo

    return resultado

def consultar_cerebro(texto, max_notas=3):
    """
    Busca en el cerebro notas relevantes a lo que el usuario está preguntando.
    Devuelve una lista de diccionarios con 'titulo' y 'contenido', lista para
    inyectar en el contexto del LLM. Sigue el mismo patrón que recordar() de
    memoria_semantica, para integrarse igual en consultar_llama.

    Por ahora usa búsqueda por palabras clave (Opción A). Más adelante se le
    puede enchufar búsqueda semántica encima sin cambiar cómo se usa acá.
    """
    # extraemos palabras significativas de la consulta (sacamos las muy cortas,
    # que suelen ser conectores: 'de', 'la', 'que', etc.)
    # sacamos palabras cortas Y stopwords (frecuentes pero sin significado)
    palabras = [
        p.strip("¿?¡!.,;:") for p in texto.lower().split()
        if len(p) > 3 and p.strip("¿?¡!.,;:") not in STOPWORDS
    ]
    if not palabras:
        return []

    # Si el vault no está configurado o no existe, no rompemos la respuesta
    # entera: esta función corre en CADA turno de conversación.
    try:
        vault = _get_vault_path()
    except Exception:
        return []

    # UNA sola pasada por el disco: leemos cada nota una vez y contamos cuántas
    # palabras de la consulta matchean. (Antes se releía todo el vault una vez
    # por palabra, y luego otra vez para levantar el contenido de las top.)
    puntuadas = []
    for nota in vault.rglob("*.md"):
        if not _es_nota_valida(nota):
            continue
        try:
            contenido = nota.read_text(encoding="utf-8")
        except Exception:
            continue  # una nota rota no debe frenar la búsqueda

        contenido_lower = contenido.lower()
        matches = sum(1 for p in palabras if p in contenido_lower)
        if matches:
            puntuadas.append((matches, nota.name, contenido))

    if not puntuadas:
        return []

    # más palabras de la consulta matcheadas => nota más relevante
    puntuadas.sort(key=lambda x: x[0], reverse=True)

    return [
        {"titulo": nombre.replace(".md", ""), "contenido": contenido}
        for _, nombre, contenido in puntuadas[:max_notas]
    ]