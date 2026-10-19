
import os
import subprocess
import sys

def _comando_abrir():
    if sys.platform.startswith("linux"):
        return "xdg-open"
    elif sys.platform == "darwin":
        return "open"
    elif sys.platform.startswith("win"):
        return "start"
    return "xdg-open"

def abrir_programa(nombre_programa):
    nombre_programa = nombre_programa.lower().strip()
    comando = _comando_abrir()
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen([nombre_programa], shell=True)
        else:
            subprocess.Popen([comando, nombre_programa])
        return True 
    except Exception:
        return False

def buscar_en_internet(consulta):
    if not consulta.strip():
        return False
    url = f"https://www.google.com/search?q={consulta.replace(' ', '+')}"
    comando = _comando_abrir()
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen([comando, url], shell=True)
        else:
            subprocess.Popen([comando, url])
        return True
    except Exception:
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

