import os
import re

from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from dotenv import load_dotenv
from config import ENV_FILE

load_dotenv(ENV_FILE)


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
            "Configurá una ruta absoluta Windows o Linux, por ejemplo C:/Notas/Bridget"
        )
    # expanduser convierte '~' en la ruta real del home, si lo usaras
    vault = Path(ruta_cruda).expanduser()
    if not vault.is_absolute():
        raise ValueError("VAULT_PATH debe ser absoluto")
    vault = vault.resolve()
    if not vault.exists():
        raise FileNotFoundError(f"El vault no existe en la ruta: {vault}")
    if not vault.is_dir():
        raise NotADirectoryError(f"La ruta del vault no es una carpeta: {vault}")
    return vault

CARPETAS_INTERNAS = frozenset({".trash", ".obsidian", ".stfolder", ".stversions", ".stignore"})


def _es_interno(nombre):
    name = nombre.casefold()
    return name in CARPETAS_INTERNAS or name.startswith((".syncthing.", "~syncthing~"))


def _es_nota_valida(ruta, vault=None):
    """Solo Markdown dentro del vault, sin enlaces/reparse points ni internos."""
    try:
        vault = vault or _get_vault_path()
        relative = ruta.relative_to(vault)
        if any(_es_interno(part) for part in relative.parts):
            return False
        if ruta.suffix.casefold() != ".md" or not ruta.is_file():
            return False
        ruta.resolve(strict=True).relative_to(vault)
        return not any(p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) & 0x400
                       for p in (ruta, *ruta.parents) if p != vault and vault in p.parents)
    except (OSError, ValueError, RuntimeError):
        return False


def _iterar_notas(vault):
    # Podar antes de descender: tampoco recorrer versiones de Syncthing ni
    # junctions Windows que podrían salir del vault. Todas las consultas lo usan.
    for root, directories, files in os.walk(vault, topdown=True, followlinks=False):
        folder = Path(root)
        visible = []
        for name in directories:
            child = folder / name
            try:
                if not (_es_interno(name) or child.is_symlink()
                        or getattr(child.lstat(), "st_file_attributes", 0) & 0x400):
                    visible.append(name)
            except OSError:
                continue
        directories[:] = sorted(visible, key=str.casefold)
        for name in sorted(files, key=str.casefold):
            note = folder / name
            if _es_nota_valida(note, vault):
                yield note


def listar_notas():
    """Lista notas visibles; no lee su contenido ni escribe en el vault."""
    return list(_iterar_notas(_get_vault_path()))


def leer_nota(nombre):
    """Lee UTF-8 por título, ruta relativa o absoluta dentro del vault.

    Admite separadores Windows en rutas relativas; nunca abre rutas excluidas.
    Con títulos duplicados conviene indicar subcarpeta/nota.md.
    """
    vault = _get_vault_path()
    name = str(nombre).strip()
    local = Path(name)
    if local.is_absolute():
        name = local.relative_to(vault).as_posix()
    elif PureWindowsPath(name).drive or name.startswith("\\"):
        raise ValueError("La ruta debe pertenecer al vault configurado")
    else:
        name = name.replace("\\", "/")
    relative = PurePosixPath(name)
    if not name or any(part == ".." or _es_interno(part) for part in relative.parts):
        raise ValueError("Ruta de nota no permitida")
    target = relative.as_posix()
    if relative.suffix.casefold() != ".md":
        target += ".md"
    for note in _iterar_notas(vault):
        candidate = note.relative_to(vault).as_posix() if "/" in target else note.name
        if candidate.casefold() == target.casefold():
            return note.read_text(encoding="utf-8-sig")
    return None


def buscar_en_notas(texto):
    """Búsqueda literal sin distinguir mayúsculas en nombre y contenido UTF-8."""
    query = texto.strip().casefold()
    if not query:
        return []
    results = []
    for note in _iterar_notas(_get_vault_path()):
        try:
            content = note.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        index = content.casefold().find(query)
        if index >= 0 or query in note.stem.casefold():
            position = max(index, 0)
            excerpt = content[max(0, position - 80):position + 80].strip()
            results.append({"nota": note.name, "ruta": str(note), "fragmento": f"...{excerpt}..."})
    return results


def _limpiar_nombre_archivo(titulo):
    """
    Convierte un título en un nombre de archivo seguro y portable.
    Saca caracteres que rompen en algún sistema operativo (/ \\ : * ? " < > |),
    colapsa espacios, y recorta largo excesivo.
    """
    # sacamos caracteres prohibidos en nombres de archivo
    limpio = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '', titulo)
    # colapsamos espacios múltiples a uno solo
    limpio = re.sub(r'\s+', ' ', limpio).strip().rstrip(". ")
    # límite de largo razonable para el nombre
    if len(limpio) > 80:
        limpio = limpio[:80].strip()
    # si quedó vacío por algún motivo, ponemos algo
    if not limpio:
        limpio = "nota sin titulo"
    if limpio.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        limpio = "nota " + limpio
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
    relative = Path(carpeta)
    if relative.is_absolute() or any(part.casefold() in {"..", ".obsidian", ".trash"} for part in relative.parts):
        raise ValueError("Carpeta de nota no permitida")
    destino = vault / relative
    destino.resolve().relative_to(vault)
    destino.mkdir(parents=True, exist_ok=True)

    ruta = destino / f"{nombre}.md"

    contador = 2
    while ruta.exists():
        ruta = destino / f"{nombre} ({contador}).md"
        contador += 1

    texto = _construir_nota(titulo, contenido, origen="conversación", enlaces=enlaces, tags=tags)

    try:
        with ruta.open("x", encoding="utf-8") as stream:
            stream.write(texto)
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
    destino.resolve().relative_to(vault)
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
        with ruta.open("x", encoding="utf-8") as stream:
            stream.write(texto)
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
    for nota in _iterar_notas(vault):
        try:
            contenido = nota.read_text(encoding="utf-8-sig")
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