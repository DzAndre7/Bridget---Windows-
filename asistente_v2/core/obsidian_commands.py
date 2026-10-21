"""Consultas Markdown de solo lectura; nunca solicitan código ni usan sandbox."""
import re
from dataclasses import dataclass
from pathlib import Path

NOTE_SCOPE = r"(?:(?:todas?\s+)?(?:las?|mis?|tus?|unas?)\s+)?notas?(?:\s+markdown)?"
VAULT_SCOPE = r"(?:(?:el|mi|tu)\s+)?(?:obsidian|vault|cerebro)"
CONTEXT = rf"(?:en|de|del)\s+{VAULT_SCOPE}"
SCOPE = rf"(?:{NOTE_SCOPE}(?:\s+{CONTEXT})?|{VAULT_SCOPE})"
LEADING_SCOPE = re.compile(rf"^(?:en\s+)?{SCOPE}(?=\s|$)", re.I)
TRAILING_SCOPE = re.compile(rf"\s+(?:en|de|del)\s+{SCOPE}$", re.I)
SEARCH = re.compile(r"^(?:busc[aá]|buscar|buscame|b[uú]scame|encontr[aá]|encontrar|encontrame)\s+(.+)$", re.I)
LIST = re.compile(r"^(?:list[aá]|listar|mostr[aá](?:me)?|muestra(?:me)?)\s+(.+)$", re.I)
READ = re.compile(r"^(?:le[eé]|leer|l[eé]eme|leeme|mostr[aá](?:me)?|muestra(?:me)?|abr[ií]|abre)\s+(.+)$", re.I)
INTENCIONES_OBSIDIAN = frozenset({"buscar_notas_obsidian", "listar_notas_obsidian", "leer_nota_obsidian"})


@dataclass(frozen=True)
class ConsultaObsidian:
    intencion: str
    argumento: str = ""


def _argument(text):
    text = text.strip().strip(": ")
    text = re.sub(r"^(?:(?:las|mis|tus|unas)\s+)?notas?\s+(?=sobre\b|acerca de\b|que\b)", "", text, flags=re.I)
    text = re.sub(r"^(?:sobre|acerca de|relacionadas? con|que (?:hablen? de|contengan|mencionen)|con|llamad[ao]s?|titulad[ao]s?)\s+", "", text, flags=re.I)
    for left, right in [('"', '"'), ("'", "'"), ('«', '»'), ('“', '”')]:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            return text[1:-1].strip()
    return text.strip()


def parsear_consulta(texto):
    """Reglas sobre el mensaje original: no normalizar títulos, acentos ni rutas.

    Solo verbos de consulta al inicio; mencionar Obsidian no vuelve seguro un
    pedido de ejecutar código. Lo que va entre comillas es dato de la consulta.
    """
    text = texto.strip().strip("¿?").strip()
    text = re.sub(r"^(?:(?:por favor|pod[eé]s|podr[ií]as|puedes|bridget)[,:]?\s+)+", "", text, flags=re.I)
    if re.fullmatch(rf"(?:qu[eé]|cu[aá]les)\s+(?:son\s+)?{NOTE_SCOPE}(?:\s+(?:ten[eé]s|tienes|hay))?(?:\s+{CONTEXT})?", text, re.I):
        return ConsultaObsidian("listar_notas_obsidian")
    listing = LIST.match(text)
    if listing and re.fullmatch(SCOPE, listing[1], re.I):
        return ConsultaObsidian("listar_notas_obsidian")
    search = SEARCH.match(text)
    if search:
        rest = search[1]
        stripped = LEADING_SCOPE.sub("", rest, count=1)
        trailing = TRAILING_SCOPE.sub("", stripped)
        if stripped != rest or trailing != stripped:
            return ConsultaObsidian("buscar_notas_obsidian", _argument(trailing))
    read = READ.match(text)
    if read:
        rest = read[1]
        # Singular: "mostrame mis notas" es listado, "mostrame la nota X" lectura.
        stripped = re.sub(r"^(?:(?:la|mi|tu|una)\s+)?nota(?:\s+markdown)?(?=\s|$)", "", rest, count=1, flags=re.I)
        trailing = TRAILING_SCOPE.sub("", stripped)
        if stripped != rest or trailing != stripped:
            return ConsultaObsidian("leer_nota_obsidian", _argument(trailing))
    return None


def resolver_consulta(texto):
    """Devuelve datos de notas directamente, sin clasificador, LLM o subprocess."""
    consulta = parsear_consulta(texto)
    if consulta is None:
        return 'Usá: «listá notas de Obsidian», «buscá en Obsidian sobre un tema» o «leé la nota "Título" de Obsidian».'
    from core import cerebro
    try:
        if consulta.intencion == "listar_notas_obsidian":
            notes = cerebro.listar_notas()
            if not notes:
                return "No encontré notas Markdown visibles en el vault de Obsidian."
            vault = cerebro._get_vault_path()
            paths = [note.relative_to(vault).as_posix() for note in notes]
            result = "Notas de Obsidian:\n" + "\n".join(f"- {path}" for path in paths[:50])
            return result + (f"\nHay {len(paths) - 50} notas más." if len(paths) > 50 else "")
        if not consulta.argumento:
            return "Indicá el texto a buscar o el título de la nota de Obsidian."
        if consulta.intencion == "buscar_notas_obsidian":
            found = cerebro.buscar_en_notas(consulta.argumento)
            if not found:
                return "No encontré notas de Obsidian que coincidan con esa búsqueda."
            vault = cerebro._get_vault_path()
            lines = [f"- {Path(r['ruta']).relative_to(vault).as_posix()}: {r['fragmento']}" for r in found[:20]]
            return "Coincidencias en Obsidian:\n" + "\n".join(lines) + (f"\nHay {len(found) - 20} coincidencias más." if len(found) > 20 else "")
        content = cerebro.leer_nota(consulta.argumento)
        if content is None:
            return "No encontré esa nota Markdown dentro del vault de Obsidian."
        return f"Nota de Obsidian: {consulta.argumento}\n\n" + content[:12000] + ("\n[Vista recortada a 12000 caracteres.]" if len(content) > 12000 else "")
    except (OSError, ValueError, RuntimeError):
        return "No pude consultar Obsidian. Revisá VAULT_PATH, los permisos de lectura y que la nota esté dentro del vault y sea UTF-8."
