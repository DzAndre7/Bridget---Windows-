import os
import subprocess
import webbrowser
from urllib.parse import urlencode
from core.app_permissions import approved_apps, policy


def abrir_programa(nombre_programa, *, confirmado=False):
    if confirmado is not True:
        return False
    command = approved_apps().get(nombre_programa.casefold().strip())
    if not command:
        return False
    try:
        subprocess.Popen([command], shell=False)
        return True
    except OSError:
        return False


def buscar_en_internet(consulta, *, confirmado=False):
    if confirmado is not True or policy().get("browser") is not True or not consulta.strip():
        return False
    url = "https://www.google.com/search?" + urlencode({"q": consulta})
    try:
        return webbrowser.open(url)
    except (OSError, webbrowser.Error):
        return False


def convertir_documento(ruta_entrada, extension_destino, ruta_salida=None):
    """Convierte un archivo a otro formato con pandoc (pdf, docx, html, md,
    epub, txt, rtf, pptx, tex — cualquier par que pandoc sepa convertir; el
    formato en sí lo infiere de la extensión de cada archivo). Devuelve
    (True, ruta_salida) o (False, motivo)."""
    ruta_entrada = os.path.expanduser(ruta_entrada)
    if not os.path.isfile(ruta_entrada):
        return False, f"no encontré el archivo {ruta_entrada}"

    if not ruta_salida:
        base, _ext = os.path.splitext(ruta_entrada)
        ruta_salida = f"{base}.{extension_destino}"

    comando = ["pandoc", ruta_entrada, "-o", ruta_salida]
    if extension_destino == "pdf":
        # el motor por defecto de pandoc para PDF es pdflatex, que no está
        # instalado (ni pandoc mismo lo trae); weasyprint sí, vía pip, sin sudo.
        comando += ["--pdf-engine=weasyprint"]

    try:
        resultado = subprocess.run(
            comando,
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return False, "pandoc no está instalado en este sistema"
    except subprocess.TimeoutExpired:
        return False, "la conversión tardó demasiado y se canceló"

    if resultado.returncode != 0:
        return False, resultado.stderr.strip()[:500] or "pandoc falló sin más detalle"
    return True, ruta_salida

