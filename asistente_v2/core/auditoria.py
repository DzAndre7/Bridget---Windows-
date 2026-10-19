import os
import logging
from concurrent.futures import ThreadPoolExecutor

from datetime import datetime
from core.code_analyzer import obtener_archivos_python
from core.code_reviewer import revisar_codigo
from config import ASSISTANT_NAME

REPORTES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")

def leer_codigo(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"El archivo {ruta} no existe.")
        return None
    except UnicodeDecodeError:
        logging.error(f"Error al decodificar el archivo {ruta}.")
        return None

def auditar_proyecto():
    ruta_proyecto = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    archivos = obtener_archivos_python(ruta_proyecto)

    if not archivos:
        return "No se encontraron archivos para auditar."

    os.makedirs(REPORTES_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_reporte = os.path.join(REPORTES_DIR, f"auditoria_{timestamp}.md")

    with open(ruta_reporte, "w", encoding="utf-8") as reporte:
        reporte.write(f"# Auditoría de código de {ASSISTANT_NAME}\n\n")
        reporte.write(f"Fecha: {datetime.now().isoformat()}\n\n")
        reporte.write(f"Archivos auditados: {len(archivos)}\n\n---\n\n")

        for archivo in archivos:
            nombre = os.path.basename(archivo)
            logging.info(f"Auditando: {nombre}")
            codigo = leer_codigo(archivo)

            if not codigo:
                continue

            revision = revisar_codigo(codigo, objetivo="auditar este código y señalar errores, riesgos y mejoras concretas")

            reporte.write(f"## {nombre}\n\n")
            if revision:
                reporte.write(f"{revision}\n\n---\n\n")
            else:
                reporte.write("(El revisor no estuvo disponible para este archivo.)\n\n---\n\n")

    return f"Auditoría completada. Reporte guardado en: {ruta_reporte}"
