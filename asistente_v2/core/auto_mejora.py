"""
Ciclo de auto-mejora: cierra el círculo detectar → proponer → probar → aplicar.

Flujo completo:
1. DETECTAR: se elige un archivo del proyecto (el que hace más tiempo no se
   toca, o el que pida el usuario) y se lo somete al revisor experto
   (Groq, si hay API key) para obtener una guía de qué mejorar.
2. PROPONER: el modelo local reescribe el archivo siguiendo esa guía, con
   instrucciones conservadoras (mantener API pública y comportamiento).
3. PROBAR: la propuesta se prueba en el sandbox (core/sandbox.py): se aplica
   sobre una COPIA temporal del proyecto y se corre la suite entera ahí.
   Si rompe algo, el error vuelve al modelo para que corrija (hasta N vueltas).
4. ESPERAR: si pasa las pruebas, la propuesta queda en mejoras_pendientes/
   (código + diff + metadatos). El archivo real NO se toca.
5. APLICAR: solo cuando el usuario lo pide. Antes de escribir se verifica
   que el archivo no cambió desde la propuesta (hash) y se re-corre la
   suite en el sandbox. Recién entonces se escribe.

La regla de oro es la misma del sandbox: nada se aplica en vivo sin pasar
las pruebas Y sin el visto bueno del usuario.
"""

import difflib
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime

from core import sandbox
from core.code_reviewer import revisar_codigo

RUTA_PROYECTO = sandbox.RUTA_PROYECTO

# Solo se auto-mejora el código propio y activo: nada de tests, legacy ni interfaz web
CARPETAS_CANDIDATAS = ("core", "actions")


def _dir_mejoras(ruta_proyecto=None, estado="pendientes"):
    base = ruta_proyecto or RUTA_PROYECTO
    return os.path.join(base, "mejoras_pendientes" if estado == "pendientes"
                        else f"mejoras_{estado}")


def _hash_codigo(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _leer(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _lint_ruff(codigo, rel):
    """Chequeo estático rápido, antes del sandbox: pesca nombres indefinidos
    e imports que faltan (F821/F401) en un segundo. Existe porque un módulo
    sin tests puede pasar la suite entera del sandbox con un NameError
    adentro si nada ejercita esa línea (así se coló una propuesta real que
    usaba `urllib` sin importarlo)."""
    try:
        resultado = subprocess.run(
            ["ruff", "check", "--quiet", "--select", "F821,F401,F811",
             "--stdin-filename", rel, "-"],
            input=codigo, capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # sin ruff instalado no bloqueamos la propuesta por esto: el sandbox
        # sigue siendo la validación real
        return {"exito": True, "salida": ""}
    return {"exito": resultado.returncode == 0, "salida": resultado.stdout}


def elegir_archivo(ruta_proyecto=None):
    """DETECTAR: elige el candidato a mejorar. Criterio simple y justo: el
    archivo activo que hace MÁS tiempo no se modifica (el más 'olvidado'),
    salteando los que ya tienen una mejora pendiente sin revisar."""
    base = ruta_proyecto or RUTA_PROYECTO
    pendientes = {m["archivo"] for m in listar_mejoras(ruta_proyecto)}

    candidatos = []
    for carpeta in CARPETAS_CANDIDATAS:
        ruta_carpeta = os.path.join(base, carpeta)
        if not os.path.isdir(ruta_carpeta):
            continue
        for nombre in os.listdir(ruta_carpeta):
            if not nombre.endswith(".py") or nombre.startswith("__"):
                continue
            rel = os.path.join(carpeta, nombre)
            if rel in pendientes:
                continue
            candidatos.append((os.path.getmtime(os.path.join(base, rel)), rel))

    if not candidatos:
        return None
    candidatos.sort()  # mtime más viejo primero
    return candidatos[0][1]


def proponer_mejora(ruta_archivo, funcion_llm, ruta_proyecto=None, max_intentos=2):
    """PROPONER + PROBAR: genera una versión mejorada del archivo y solo la
    acepta si la suite entera pasa en el sandbox. Devuelve un dict con
    exito/motivo y, si salió bien, el id de la propuesta y su diff.
    El archivo real nunca se modifica acá."""
    base = os.path.abspath(ruta_proyecto or RUTA_PROYECTO)
    absoluta = os.path.abspath(
        ruta_archivo if os.path.isabs(ruta_archivo)
        else os.path.join(base, ruta_archivo)
    )
    rel = os.path.relpath(absoluta, base)
    if rel.startswith(".."):
        return {"exito": False, "motivo": f"{ruta_archivo} no pertenece al proyecto."}

    original = _leer(absoluta)
    if original is None:
        return {"exito": False, "motivo": f"No pude leer {rel}."}

    # 1. la guía del revisor experto (si Groq no está, se sigue sin guía)
    revision = revisar_codigo(
        original,
        objetivo="señalar los 3 problemas o mejoras más importantes de este archivo, concretos y accionables",
    ) or ""

    guia = f"\nGUÍA DEL REVISOR (priorizá esto):\n{revision[:2000]}\n" if revision else ""
    prompt = (
        f"Estás mejorando un archivo de tu propio proyecto: {rel}\n"
        f"{guia}\n"
        f"CÓDIGO ACTUAL:\n{original}\n\n"
        "Reescribí el archivo COMPLETO aplicando solo mejoras seguras y "
        "conservadoras. Reglas estrictas:\n"
        "- Mantené la API pública: mismos nombres de funciones/clases y firmas.\n"
        "- No elimines funcionalidad ni cambies el comportamiento observable.\n"
        "- Mantené los comentarios que explican decisiones.\n"
        "- Respondé SOLO con el código completo, sin explicaciones."
    )

    ultimo_motivo = "el modelo no devolvió código"
    for intento in range(1, max_intentos + 1):
        respuesta = funcion_llm(prompt)
        codigo = sandbox.extraer_codigo(respuesta)
        # extraer_codigo hace strip(): reponemos el salto de línea final
        # para escribir archivos bien formados
        if codigo and not codigo.endswith("\n"):
            codigo += "\n"

        # sanidad: una "mejora" que recorta la mitad del archivo casi seguro
        # borró funcionalidad, por más que las pruebas pasen
        if len(codigo) < len(original) * 0.5:
            ultimo_motivo = "la propuesta recorta demasiado el archivo (posible pérdida de funcionalidad)"
            prompt = (
                f"Tu versión quedó sospechosamente corta ({len(codigo)} caracteres "
                f"contra {len(original)} del original): probablemente borraste "
                "funcionalidad. Reescribí el archivo COMPLETO de nuevo, conservando "
                "todas las funciones. Respondé SOLO con el código:\n\n" + original
            )
            continue

        lint = _lint_ruff(codigo, rel)
        if not lint["exito"]:
            ultimo_motivo = "el linter encontró errores (nombres indefinidos o imports rotos)"
            prompt = (
                f"Tu versión de {rel} tiene errores que ruff detectó (nombres "
                f"indefinidos, imports que faltan, etc.):\n\n{lint['salida']}\n\n"
                "Corregí eso y devolvé el archivo COMPLETO de nuevo. "
                "Respondé SOLO con el código."
            )
            continue

        prueba = sandbox.probar_cambio_en_proyecto(rel, codigo, ruta_proyecto=base)
        if prueba["exito"]:
            id_mejora, ruta_diff, diff = _guardar_propuesta(
                rel, original, codigo, revision, ruta_proyecto=base
            )
            return {
                "exito": True, "id": id_mejora, "archivo": rel,
                "diff": diff, "ruta_diff": ruta_diff,
                "intentos": intento, "revision": revision,
            }

        ultimo_motivo = f"las pruebas fallaron en el sandbox (etapa: {prueba['etapa']})"
        prompt = (
            f"Tu versión de {rel} ROMPE las pruebas del proyecto.\n\n"
            f"ERROR:\n{prueba['salida'][-1500:]}\n{prueba['errores'][-500:]}\n\n"
            "Corregí el problema y devolvé el archivo COMPLETO de nuevo. "
            "Respondé SOLO con el código."
        )

    return {"exito": False, "motivo": ultimo_motivo, "archivo": rel,
            "intentos": max_intentos}


def _guardar_propuesta(rel, original, codigo, revision, ruta_proyecto=None):
    """Deja la propuesta esperando revisión humana: código, diff y metadatos."""
    carpeta = _dir_mejoras(ruta_proyecto)
    os.makedirs(carpeta, exist_ok=True)

    id_mejora = datetime.now().strftime("%Y%m%d_%H%M%S")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        codigo.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}",
    ))

    with open(os.path.join(carpeta, f"{id_mejora}.py"), "w", encoding="utf-8") as f:
        f.write(codigo)
    ruta_diff = os.path.join(carpeta, f"{id_mejora}.diff")
    with open(ruta_diff, "w", encoding="utf-8") as f:
        f.write(diff)
    with open(os.path.join(carpeta, f"{id_mejora}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "id": id_mejora,
            "archivo": rel,
            "fecha": datetime.now().isoformat(),
            "hash_original": _hash_codigo(original),
            "revision": revision[:1000],
        }, f, ensure_ascii=False, indent=2)

    return id_mejora, ruta_diff, diff


def listar_mejoras(ruta_proyecto=None):
    """Mejoras propuestas que esperan tu decisión, la más nueva primero."""
    carpeta = _dir_mejoras(ruta_proyecto)
    if not os.path.isdir(carpeta):
        return []

    mejoras = []
    for nombre in os.listdir(carpeta):
        if nombre.endswith(".json"):
            datos = _leer(os.path.join(carpeta, nombre))
            if datos:
                try:
                    mejoras.append(json.loads(datos))
                except ValueError:
                    continue
    mejoras.sort(key=lambda m: m.get("fecha", ""), reverse=True)
    return mejoras


def obtener_diff(id_mejora, ruta_proyecto=None):
    return _leer(os.path.join(_dir_mejoras(ruta_proyecto), f"{id_mejora}.diff"))


def _mover_propuesta(id_mejora, destino_estado, ruta_proyecto=None):
    origen = _dir_mejoras(ruta_proyecto)
    destino = _dir_mejoras(ruta_proyecto, destino_estado)
    os.makedirs(destino, exist_ok=True)
    for extension in (".py", ".diff", ".json"):
        ruta = os.path.join(origen, f"{id_mejora}{extension}")
        if os.path.exists(ruta):
            shutil.move(ruta, os.path.join(destino, f"{id_mejora}{extension}"))


def aplicar_mejora(id_mejora, ruta_proyecto=None):
    """APLICAR: escribe la mejora en el archivo real, con doble protección:
    - si el archivo cambió desde que se propuso (hash distinto), se niega;
    - re-corre la suite en el sandbox por si el resto del proyecto cambió.
    Si todo pasa, escribe y archiva la propuesta en mejoras_aplicadas/."""
    base = os.path.abspath(ruta_proyecto or RUTA_PROYECTO)
    carpeta = _dir_mejoras(base)

    datos = _leer(os.path.join(carpeta, f"{id_mejora}.json"))
    if not datos:
        return {"exito": False, "motivo": f"No encontré la mejora {id_mejora}."}
    meta = json.loads(datos)

    codigo = _leer(os.path.join(carpeta, f"{id_mejora}.py"))
    if codigo is None:
        return {"exito": False, "motivo": "La propuesta no tiene código guardado."}

    ruta_real = os.path.join(base, meta["archivo"])
    actual = _leer(ruta_real)
    if actual is None:
        return {"exito": False, "motivo": f"Ya no existe {meta['archivo']}."}
    if _hash_codigo(actual) != meta["hash_original"]:
        return {
            "exito": False,
            "motivo": (f"{meta['archivo']} cambió después de la propuesta: "
                       "la mejora quedó desactualizada. Descartala y pedí una nueva."),
        }

    prueba = sandbox.probar_cambio_en_proyecto(meta["archivo"], codigo, ruta_proyecto=base)
    if not prueba["exito"]:
        return {
            "exito": False,
            "motivo": (f"La re-verificación en el sandbox falló (etapa: {prueba['etapa']}); "
                       "no aplico nada."),
        }

    with open(ruta_real, "w", encoding="utf-8") as f:
        f.write(codigo)
    _mover_propuesta(id_mejora, "aplicadas", base)
    return {"exito": True, "archivo": meta["archivo"], "id": id_mejora}


def descartar_mejora(id_mejora, ruta_proyecto=None):
    """Archiva la propuesta en mejoras_descartadas/ sin tocar nada."""
    carpeta = _dir_mejoras(ruta_proyecto)
    if not os.path.exists(os.path.join(carpeta, f"{id_mejora}.json")):
        return {"exito": False, "motivo": f"No encontré la mejora {id_mejora}."}
    _mover_propuesta(id_mejora, "descartadas", ruta_proyecto)
    return {"exito": True, "id": id_mejora}
