"""API portable de sandbox. Sin backend validado, toda ejecución se rechaza.

Compilar sintaxis no ejecuta el programa. Copiar archivos y crear procesos no
son barreras de seguridad. Las entradas del usuario, del modelo y los tests
(incluidos conftest y cambios propios) tienen la misma política de aislamiento.
"""
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path

from config import ASSISTANT_NAME
from core.sandbox_backends import EstadoBackend, ResultadoBackend, SolicitudEjecucion, obtener_backend

RUTA_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(RUTA_PROYECTO, "sandbox_workspace")
TIMEOUT_SNIPPET = 15
TIMEOUT_PRUEBAS = 300
LIMITE_MEMORIA = 2 * 1024 ** 3
LIMITE_ARCHIVO = 10 * 1024 ** 2
LIMITE_SALIDA = 8000
LIMITE_COPIA = 10 * 1024 ** 2
LIMITE_ARCHIVOS = 500
LIMITE_PROCESOS = 32

_OMITIR = {
    "__pycache__", ".pytest_cache", ".git", ".venv", "venv", "venv311", "env",
    "reports", "inbox", "sandbox_workspace", "sesiones", "assets", "node_modules",
    "mejoras_pendientes", "mejoras_aplicadas", "mejoras_descartadas",
}
# Solo código y recursos necesarios para las pruebas; no snapshots de datos.
_EXTENSIONES = {".py", ".html", ".css", ".js", ".png"}
_RECURSOS = {"context.md", "config_presencia.json", "manifest.json"}


def _fallo(etapa, mensaje):
    return {"exito": False, "etapa": etapa, "salida": "",
            "errores": mensaje, "codigo_retorno": -1}


def estado_aislamiento():
    """Consulta sin iniciar runtimes, red, modelos ni procesos."""
    try:
        estado = obtener_backend().estado()
        if isinstance(estado, EstadoBackend):
            return estado
    except Exception:
        pass
    return EstadoBackend("no_disponible", "No se pudo verificar el aislamiento; no se ejecutó código.")


def _comprobar_backend(backend):
    try:
        estado = backend.estado()
        if not isinstance(estado, EstadoBackend) or not estado.disponible:
            return _fallo("aislamiento_no_disponible", getattr(estado, "motivo", "") or
                          "El backend no acredita todas las garantías de aislamiento.")
    except Exception:
        return _fallo("aislamiento_no_disponible", "No se pudo verificar el aislamiento; no se ejecutó código.")
    return None


def _recortar(texto, limite=LIMITE_SALIDA):
    return (texto or "")[:limite]


def verificar_sintaxis(codigo):
    """Solo compila: nunca importa módulos ni evalúa el código recibido."""
    if not isinstance(codigo, str) or len(codigo) > LIMITE_ARCHIVO:
        return False, "El código debe ser texto de tamaño limitado."
    try:
        compile(codigo, "<sandbox>", "exec")
        return True, None
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        if isinstance(error, SyntaxError):
            return False, f"Línea {error.lineno}: {error.msg}"
        return False, f"Código inválido: {type(error).__name__}"


def extraer_codigo(respuesta):
    bloque = re.search(r"```(?:python)?\s*\n(.*?)```", respuesta, re.DOTALL)
    return bloque.group(1).strip() if bloque else respuesta.strip()


def _ejecutar(backend, carpeta, timeout, operacion, etapa_error):
    # Se vuelve a comprobar justo antes de despachar: no se confía en un cache.
    rechazo = _comprobar_backend(backend)
    if rechazo:
        return rechazo
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= TIMEOUT_PRUEBAS:
        return _fallo("solicitud_invalida", "El timeout debe ser un entero entre 1 y 300 segundos.")
    solicitud = SolicitudEjecucion(
        operacion=operacion, carpeta_entrada=Path(carpeta), timeout=timeout,
        limite_cpu=timeout, limite_procesos=LIMITE_PROCESOS,
        limite_memoria=LIMITE_MEMORIA, limite_archivo=LIMITE_ARCHIVO,
        limite_salida=LIMITE_SALIDA,
    )
    try:
        resultado = backend.ejecutar(solicitud)
    except Exception:
        return _fallo("aislamiento_no_disponible", "El backend falló; no se considera validado el código.")
    if not isinstance(resultado, ResultadoBackend) or not (
        resultado.aislamiento_verificado is True and resultado.limpieza_verificada is True
        and type(resultado.codigo_retorno) is int and type(resultado.timeout) is bool
        and isinstance(resultado.salida, str) and isinstance(resultado.errores, str)
    ):
        return _fallo("aislamiento_no_disponible", "El backend no acreditó aislamiento y limpieza completos.")
    etapa = "timeout" if resultado.timeout else (
        "ok" if resultado.codigo_retorno == 0 else etapa_error
    )
    return {"exito": etapa == "ok", "etapa": etapa,
            "salida": _recortar(resultado.salida), "errores": _recortar(resultado.errores),
            "codigo_retorno": resultado.codigo_retorno}


def ejecutar_codigo(codigo, timeout=TIMEOUT_SNIPPET, bloquear_red=True):
    ok, error = verificar_sintaxis(codigo)
    if not ok:
        return _fallo("sintaxis", error)
    # Se conserva el parámetro por compatibilidad, pero ya no permite relajar red.
    if bloquear_red is not True:
        return _fallo("politica_aislamiento", "No se permite ejecutar código con red habilitada.")
    backend = obtener_backend()
    rechazo = _comprobar_backend(backend)
    if rechazo:
        return rechazo
    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        Path(carpeta, "codigo.py").write_text(codigo, encoding="utf-8")
        return _ejecutar(backend, carpeta, timeout, "script", "ejecucion")


def probar_codigo(codigo, pruebas, timeout=60):
    for nombre, fuente in [("código", codigo), ("pruebas", pruebas)]:
        ok, error = verificar_sintaxis(fuente)
        if not ok:
            return _fallo("sintaxis", f"Error de sintaxis en {nombre}: {error}")
    backend = obtener_backend()
    rechazo = _comprobar_backend(backend)
    if rechazo:
        return rechazo
    with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
        Path(carpeta, "solucion.py").write_text(codigo, encoding="utf-8")
        Path(carpeta, "test_solucion.py").write_text(pruebas, encoding="utf-8")
        return _ejecutar(backend, carpeta, timeout, "pytest", "pruebas")


def _es_enlace(ruta):
    datos = ruta.lstat()
    return stat.S_ISLNK(datos.st_mode) or bool(
        getattr(datos, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _ruta_proyecto(origen, archivo):
    """Comprueba pertenencia real, incluyendo enlaces/junctions y otra unidad."""
    if _es_enlace(Path(origen)):
        raise ValueError("El origen no puede ser un enlace ni junction.")
    base = Path(origen).resolve(strict=True)
    ruta = Path(archivo)
    candidata = ruta if ruta.is_absolute() else base / ruta
    # No aceptar destinos a través de symlinks aunque apunten dentro del proyecto.
    # Se rechazan otras unidades/UNC léxicamente antes de resolver o consultar.
    sin_resolver = candidata.relative_to(base)
    actual = base
    for parte in sin_resolver.parts:
        if parte == "..":
            raise ValueError("La ruta no debe contener '..'.")
        actual = actual / parte
        try:
            es_enlace = _es_enlace(actual)
        except FileNotFoundError:
            continue
        if es_enlace:
            raise ValueError("No se permiten enlaces ni junctions.")
    relativa = candidata.resolve(strict=False).relative_to(base)
    if relativa.suffix != ".py":
        raise ValueError("Solo se prueban cambios en archivos Python.")
    return relativa


def _copiar_proyecto(origen, destino):
    """Snapshot reducido; nunca se considera una barrera de seguridad.

    Sin seguir symlinks/reparse points y sin copiar secretos, memorias o entornos.
    Un backend futuro debe ingerirlo como datos y volver a comprobar los límites.
    """
    origen = Path(origen)
    if _es_enlace(origen):
        raise ValueError("El origen no puede ser un enlace ni junction.")
    origen = origen.resolve(strict=True)
    copia = Path(destino) / "proyecto"
    copia.mkdir()
    total = cantidad = 0
    for directorio, carpetas, archivos in os.walk(origen, followlinks=False):
        raiz = Path(directorio)
        permitidas = []
        for nombre in carpetas:
            if nombre.casefold() in _OMITIR or nombre.startswith("."):
                continue
            if _es_enlace(raiz / nombre):
                raise ValueError("No se copian enlaces ni junctions.")
            permitidas.append(nombre)
        carpetas[:] = permitidas
        for nombre in archivos:
            ruta = raiz / nombre
            if nombre.startswith(".") or not (ruta.suffix.lower() in _EXTENSIONES or nombre in _RECURSOS):
                continue
            if _es_enlace(ruta) or not stat.S_ISREG(ruta.stat().st_mode) or ruta.stat().st_nlink > 1:
                raise ValueError("Solo se copian archivos regulares, sin enlaces.")
            total += ruta.stat().st_size
            cantidad += 1
            if total > LIMITE_COPIA or cantidad > LIMITE_ARCHIVOS:
                raise ValueError("El proyecto excede los límites de la copia.")
            salida = copia / ruta.relative_to(origen)
            salida.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ruta, salida)
    return str(copia)


def probar_proyecto(ruta_proyecto=None, timeout=TIMEOUT_PRUEBAS):
    backend = obtener_backend()
    rechazo = _comprobar_backend(backend)
    if rechazo:
        return rechazo
    try:
        with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
            copia = _copiar_proyecto(ruta_proyecto or RUTA_PROYECTO, carpeta)
            return _ejecutar(backend, copia, timeout, "pytest", "pruebas")
    except (OSError, ValueError):
        return _fallo("entrada_invalida", "No se pudo preparar una copia segura del proyecto.")


def probar_cambio_en_proyecto(ruta_archivo, nuevo_codigo,
                              ruta_proyecto=None, timeout=TIMEOUT_PRUEBAS):
    origen = ruta_proyecto or RUTA_PROYECTO
    try:
        relativa = _ruta_proyecto(origen, ruta_archivo)
    except (OSError, ValueError):
        return _fallo("fuera_del_proyecto", "La ruta debe ser un Python dentro del proyecto, sin enlaces.")
    ok, error = verificar_sintaxis(nuevo_codigo)
    if not ok:
        return _fallo("sintaxis", error)
    backend = obtener_backend()
    rechazo = _comprobar_backend(backend)
    if rechazo:
        return rechazo
    try:
        with tempfile.TemporaryDirectory(prefix="bridget_sandbox_") as carpeta:
            copia = _copiar_proyecto(origen, carpeta)
            destino = Path(copia) / relativa
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(nuevo_codigo, encoding="utf-8")
            resultado = _ejecutar(backend, copia, timeout, "pytest", "pruebas")
            resultado["archivo"] = str(relativa)
            return resultado
    except (OSError, ValueError):
        return _fallo("entrada_invalida", "No se pudo preparar una copia segura del cambio.")


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
    rechazo = _comprobar_backend(obtener_backend())
    if rechazo:
        return {"exito": False, "codigo": "", "resultado": rechazo,
                "intentos": 0, "max_intentos": max_intentos}

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

        if resultado["etapa"] == "aislamiento_no_disponible":
            return {"exito": False, "codigo": codigo, "resultado": resultado,
                    "intentos": intento, "max_intentos": max_intentos}

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
    # Una llamada directa tampoco puede etiquetar código sin probarlo.
    resultado = ejecutar_codigo(codigo)
    if not resultado["exito"]:
        raise RuntimeError(resultado["errores"] or "El código no pasó la validación aislada.")
    destino = carpeta or WORKSPACE
    os.makedirs(destino, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ruta = os.path.join(destino, f"script_{timestamp}.py")

    encabezado = (
        f"# Generado por {ASSISTANT_NAME} y probado en el sandbox el {datetime.now().isoformat()}\n"
    )
    if descripcion:
        encabezado += "# Pedido original: " + descripcion.replace("\r", "").replace("\n", "\n# ") + "\n"

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(encabezado + "\n" + codigo + "\n")

    return ruta
