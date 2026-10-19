"""
Sandbox: entorno controlado donde Bridget puede crear, ejecutar y probar
código sin riesgo para el sistema ni para su propio código fuente.

Niveles de aislamiento, de adentro hacia afuera:
1. Proceso separado: nada se ejecuta dentro del proceso del asistente.
2. Directorio temporal descartable: el código corre con cwd y HOME en una
   carpeta que se borra al terminar. No ve el proyecto real.
3. Límites de recursos (CPU, memoria, tamaño de archivos que puede crear).
4. Sin acceso a la red (si el sistema soporta `unshare`, que en Arch sí).

Regla de oro: el código del proyecto NUNCA se prueba en vivo. Para probar
un cambio, se copia asistente_v2 completo a una carpeta temporal, se aplica
el cambio en la COPIA y se corre pytest ahí. El original no se toca.

Los snippets arbitrarios (código generado por el LLM o pegado por el
usuario) corren con red bloqueada y límites estrictos. Las pruebas del
propio proyecto corren con red habilitada (son código de confianza y
algunos módulos esperan poder hablar con Ollama local), pero siempre
sobre la copia temporal.
"""

import functools
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

from config import ASSISTANT_NAME

# asistente_v2/ (la carpeta raíz del código del asistente)
RUTA_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Acá se guardan los scripts que Bridget creó y que pasaron sus pruebas
WORKSPACE = os.path.join(RUTA_PROYECTO, "sandbox_workspace")

TIMEOUT_SNIPPET = 15      # segundos para un script suelto
TIMEOUT_PRUEBAS = 300     # segundos para la suite completa del proyecto
LIMITE_MEMORIA = 2 * 1024 ** 3   # 2 GB de memoria virtual
LIMITE_ARCHIVO = 10 * 1024 ** 2  # 10 MB máximo por archivo creado
LIMITE_SALIDA = 8000      # caracteres de stdout/stderr que conservamos

# Qué NO copiar al clonar el proyecto para probarlo (caches y datos pesados)
_IGNORAR_EN_COPIA = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", "*.pyc", ".git",
    "reports", "inbox", "sandbox_workspace", "venv", "venv311",
    "sesiones", "mejoras_pendientes", "mejoras_aplicadas", "mejoras_descartadas",
)


def _recortar(texto, limite=LIMITE_SALIDA):
    """Conserva el final del texto, que es donde suele estar el error útil."""
    if texto and len(texto) > limite:
        return "(...salida recortada...)\n" + texto[-limite:]
    return texto or ""


def _aplicar_limites():
    """Corre en el hijo justo antes de exec: pone límites de recursos.
    Si algún límite no se puede aplicar (hard limit del sistema más bajo),
    seguimos igual: preferimos ejecutar con menos límites a no ejecutar."""
    for recurso, valor in [
        (resource.RLIMIT_AS, LIMITE_MEMORIA),
        (resource.RLIMIT_FSIZE, LIMITE_ARCHIVO),
        (resource.RLIMIT_CORE, 0),
    ]:
        try:
            resource.setrlimit(recurso, (valor, valor))
        except (ValueError, OSError):
            pass


@functools.lru_cache(maxsize=1)
def _puede_bloquear_red():
    """True si `unshare -r -n` funciona en este sistema (namespaces de
    usuario sin privilegios). Se prueba una sola vez por sesión."""
    try:
        prueba = subprocess.run(
            ["unshare", "-r", "-n", "true"],
            capture_output=True, timeout=5,
        )
        return prueba.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _entorno_minimo(carpeta, con_display=False):
    """Entorno de ejecución reducido: HOME apunta a la carpeta temporal,
    así el código probado no puede ensuciar el home real por descuido.

    `con_display` pasa las variables de la sesión gráfica: hace falta para
    la suite del propio proyecto (pyautogui exige DISPLAY al importarse),
    pero a los snippets arbitrarios se las negamos a propósito, para que
    código desconocido no pueda controlar mouse/teclado/pantalla."""
    entorno = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": carpeta,
        "TMPDIR": carpeta,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if con_display:
        for variable in ["DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"]:
            if variable in os.environ:
                entorno[variable] = os.environ[variable]
    return entorno


def _ejecutar_aislado(comando, carpeta, timeout, bloquear_red=True,
                      con_display=False):
    """Corre `comando` dentro de `carpeta` con límites y (si se puede) sin
    red. Devuelve un dict crudo con salida, errores y código de retorno."""
    if bloquear_red and _puede_bloquear_red():
        comando = ["unshare", "-r", "-n"] + comando

    try:
        proceso = subprocess.run(
            comando,
            cwd=carpeta,
            env=_entorno_minimo(carpeta, con_display),
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_aplicar_limites,
            start_new_session=True,
        )
        return {
            "salida": _recortar(proceso.stdout),
            "errores": _recortar(proceso.stderr),
            "codigo_retorno": proceso.returncode,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "salida": _recortar(e.stdout.decode("utf-8", "replace") if e.stdout else ""),
            "errores": f"El código superó el límite de {timeout} segundos y fue cortado.",
            "codigo_retorno": -1,
            "timeout": True,
        }


def verificar_sintaxis(codigo):
    """Chequeo barato antes de ejecutar nada.
    Devuelve (True, None) o (False, descripción del error)."""
    try:
        compile(codigo, "<sandbox>", "exec")
        return True, None
    except SyntaxError as e:
        return False, f"Línea {e.lineno}: {e.msg}"


def extraer_codigo(respuesta):
    """Saca el código de una respuesta de LLM: si viene entre fences
    markdown (```python ... ```) devuelve el primer bloque; si no,
    devuelve el texto tal cual."""
    bloque = re.search(r"```(?:python)?\s*\n(.*?)```", respuesta, re.DOTALL)
    if bloque:
        return bloque.group(1).strip()
    return respuesta.strip()


def ejecutar_codigo(codigo, timeout=TIMEOUT_SNIPPET, bloquear_red=True):
    """Ejecuta un script Python suelto en el sandbox.
    Devuelve un dict con:
      exito: True si terminó sin error
      etapa: 'sintaxis' | 'ejecucion' | 'timeout' | 'ok'
      salida / errores / codigo_retorno
    """
    ok, error = verificar_sintaxis(codigo)
    if not ok:
        return {
            "exito": False, "etapa": "sintaxis",
            "salida": "", "errores": f"Error de sintaxis: {error}",
            "codigo_retorno": -1,
        }

    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        ruta = os.path.join(carpeta, "codigo.py")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(codigo)

        crudo = _ejecutar_aislado(
            [sys.executable, ruta], carpeta, timeout, bloquear_red
        )

    if crudo["timeout"]:
        etapa = "timeout"
    elif crudo["codigo_retorno"] != 0:
        etapa = "ejecucion"
    else:
        etapa = "ok"

    return {
        "exito": etapa == "ok",
        "etapa": etapa,
        "salida": crudo["salida"],
        "errores": crudo["errores"],
        "codigo_retorno": crudo["codigo_retorno"],
    }


def probar_codigo(codigo, pruebas, timeout=60):
    """Ejecuta `pruebas` (tests de pytest) contra `codigo` en el sandbox.
    El código queda como `solucion.py`, así que las pruebas deben importar
    `from solucion import ...`. Devuelve el mismo dict que ejecutar_codigo."""
    for nombre, fuente in [("código", codigo), ("pruebas", pruebas)]:
        ok, error = verificar_sintaxis(fuente)
        if not ok:
            return {
                "exito": False, "etapa": "sintaxis",
                "salida": "", "errores": f"Error de sintaxis en {nombre}: {error}",
                "codigo_retorno": -1,
            }

    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        with open(os.path.join(carpeta, "solucion.py"), "w", encoding="utf-8") as f:
            f.write(codigo)
        with open(os.path.join(carpeta, "test_solucion.py"), "w", encoding="utf-8") as f:
            f.write(pruebas)

        crudo = _ejecutar_aislado(
            [sys.executable, "-m", "pytest", "-q", "test_solucion.py"],
            carpeta, timeout, bloquear_red=True,
        )

    if crudo["timeout"]:
        etapa = "timeout"
    elif crudo["codigo_retorno"] != 0:
        etapa = "pruebas"
    else:
        etapa = "ok"

    return {
        "exito": etapa == "ok",
        "etapa": etapa,
        "salida": crudo["salida"],
        "errores": crudo["errores"],
        "codigo_retorno": crudo["codigo_retorno"],
    }


def _copiar_proyecto(origen, destino):
    """Clona el proyecto (sin caches ni datos pesados) para probar sobre
    la copia. Devuelve la ruta de la copia."""
    copia = os.path.join(destino, "proyecto")
    shutil.copytree(origen, copia, ignore=_IGNORAR_EN_COPIA)
    return copia


def _correr_suite(copia, timeout):
    """Corre pytest en la copia del proyecto. Si existe tests/, corre solo
    esa carpeta (los test_*.py sueltos en la raíz son experimentos viejos
    que pueden necesitar servicios externos)."""
    argumentos = [sys.executable, "-m", "pytest", "-q"]
    if os.path.isdir(os.path.join(copia, "tests")):
        argumentos.append("tests")
    # Red y sesión gráfica habilitadas: es la suite del propio proyecto
    # (código de confianza) corriendo sobre la copia, y sus imports
    # (pyautogui) exigen DISPLAY aunque los tests no muevan el mouse.
    return _ejecutar_aislado(
        argumentos, copia, timeout, bloquear_red=False, con_display=True
    )


def probar_proyecto(ruta_proyecto=None, timeout=TIMEOUT_PRUEBAS):
    """Corre la suite de pruebas del proyecto en una copia temporal.
    Sirve como chequeo de salud: '¿mi código actual está sano?'."""
    origen = ruta_proyecto or RUTA_PROYECTO

    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        copia = _copiar_proyecto(origen, carpeta)
        crudo = _correr_suite(copia, timeout)

    if crudo["timeout"]:
        etapa = "timeout"
    elif crudo["codigo_retorno"] != 0:
        etapa = "pruebas"
    else:
        etapa = "ok"

    return {
        "exito": etapa == "ok",
        "etapa": etapa,
        "salida": crudo["salida"],
        "errores": crudo["errores"],
        "codigo_retorno": crudo["codigo_retorno"],
    }


def probar_cambio_en_proyecto(ruta_archivo, nuevo_codigo,
                              ruta_proyecto=None, timeout=TIMEOUT_PRUEBAS):
    """Prueba una versión nueva de un archivo del proyecto SIN tocar el
    original: copia el proyecto a una carpeta temporal, escribe ahí el
    archivo modificado y corre la suite completa sobre la copia.

    Devuelve un dict con exito/etapa/salida/errores. Etapas posibles:
    'fuera_del_proyecto', 'sintaxis', 'pruebas', 'timeout', 'ok'.
    """
    origen = os.path.abspath(ruta_proyecto or RUTA_PROYECTO)
    absoluta = os.path.abspath(
        ruta_archivo if os.path.isabs(ruta_archivo)
        else os.path.join(origen, ruta_archivo)
    )
    relativa = os.path.relpath(absoluta, origen)

    if relativa.startswith(".."):
        return {
            "exito": False, "etapa": "fuera_del_proyecto",
            "salida": "",
            "errores": f"{ruta_archivo} no pertenece al proyecto {origen}.",
            "codigo_retorno": -1,
        }

    ok, error = verificar_sintaxis(nuevo_codigo)
    if not ok:
        return {
            "exito": False, "etapa": "sintaxis",
            "salida": "", "errores": f"Error de sintaxis: {error}",
            "codigo_retorno": -1,
        }

    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        copia = _copiar_proyecto(origen, carpeta)
        destino = os.path.join(copia, relativa)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            f.write(nuevo_codigo)

        crudo = _correr_suite(copia, timeout)

    if crudo["timeout"]:
        etapa = "timeout"
    elif crudo["codigo_retorno"] != 0:
        etapa = "pruebas"
    else:
        etapa = "ok"

    return {
        "exito": etapa == "ok",
        "etapa": etapa,
        "salida": crudo["salida"],
        "errores": crudo["errores"],
        "codigo_retorno": crudo["codigo_retorno"],
        "archivo": relativa,
    }


def crear_y_probar(descripcion, funcion_llm, max_intentos=3,
                   timeout=TIMEOUT_SNIPPET):
    """Ciclo crear → probar → corregir: le pide código al LLM, lo ejecuta
    en el sandbox y, si falla, le devuelve el error al LLM para que lo
    corrija. Hasta `max_intentos` vueltas.

    `funcion_llm` es la función que consulta el modelo (se pasa como
    parámetro para no acoplar sandbox.py con brain.py, igual que en
    cerebro.clasificar_nota).

    Devuelve: {exito, codigo, resultado, intentos, max_intentos}
    """
    prompt = (
        f"Escribí un script Python completo que haga esto: {descripcion}\n\n"
        "Requisitos:\n"
        "- Debe poder ejecutarse directamente con `python script.py`.\n"
        "- Solo biblioteca estándar de Python, sin acceso a internet.\n"
        "- Incluí al final asserts que verifiquen que funciona; si todos "
        "pasan, imprimí 'PRUEBAS OK'.\n"
        "- Respondé SOLO con el código, sin explicaciones."
    )

    codigo = ""
    resultado = {
        "exito": False, "etapa": "sin_intentos",
        "salida": "", "errores": "El LLM no devolvió código.",
        "codigo_retorno": -1,
    }

    for intento in range(1, max_intentos + 1):
        respuesta = funcion_llm(prompt)
        codigo = extraer_codigo(respuesta)
        resultado = ejecutar_codigo(codigo, timeout=timeout)

        if resultado["exito"]:
            return {
                "exito": True, "codigo": codigo, "resultado": resultado,
                "intentos": intento, "max_intentos": max_intentos,
            }

        # le mostramos el error al modelo para que corrija en la próxima vuelta
        prompt = (
            "El script que escribiste falló al ejecutarse en el sandbox.\n\n"
            f"CÓDIGO:\n{codigo}\n\n"
            f"ERROR ({resultado['etapa']}):\n{resultado['errores'][-2000:]}\n\n"
            "Corregilo. Respondé SOLO con el código completo corregido, "
            "sin explicaciones."
        )

    return {
        "exito": False, "codigo": codigo, "resultado": resultado,
        "intentos": max_intentos, "max_intentos": max_intentos,
    }


def guardar_codigo_validado(codigo, descripcion="", carpeta=None):
    """Guarda un script que ya pasó por el sandbox en sandbox_workspace/,
    con un encabezado que documenta de dónde salió. Devuelve la ruta."""
    destino = carpeta or WORKSPACE
    os.makedirs(destino, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(destino, f"script_{timestamp}.py")

    encabezado = (
        f"# Generado por {ASSISTANT_NAME} y probado en el sandbox el {datetime.now().isoformat()}\n"
    )
    if descripcion:
        encabezado += f"# Pedido original: {descripcion}\n"

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(encabezado + "\n" + codigo + "\n")

    return ruta
