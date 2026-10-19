"""Transporte acotado de datos. Nunca deserializa objetos Python ni extrae ZIPs."""
import base64
import json
import re
import struct
from pathlib import Path, PurePosixPath

MAGIC = b"BRDGV001"
PREFIX = b"BRIDGET_RESULT_V1:"
MAX_INPUT = 16 * 1024 * 1024
MAX_FILES = 500
MAX_SOURCE = 10 * 1024 * 1024
MAX_CONSOLE = 256 * 1024
RESOURCE_NAMES = {"context.md", "config_presencia.json", "manifest.json"}
EXTENSIONS = {".py", ".html", ".css", ".js", ".png"}



def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clave JSON duplicada")
        result[key] = value
    return result


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise ValueError("Nombre de entrada inválido")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in name.split("/")):
        raise ValueError("Ruta de entrada inválida")
    if path.suffix.lower() not in EXTENSIONS and path.name not in RESOURCE_NAMES:
        raise ValueError("Tipo de entrada no permitido")
    return path


def encode_input(files, nonce, operation, limits):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or operation not in {"script", "pytest"}:
        raise ValueError("Solicitud de VM inválida")
    if not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Cantidad de archivos inválida")
    total = 0
    names = set()
    encoded = {}
    for name, data in files.items():
        safe_name(name)
        if name.casefold() in names or not isinstance(data, bytes):
            raise ValueError("Entrada duplicada o inválida")
        names.add(name.casefold())
        total += len(data)
        if total > MAX_SOURCE:
            raise ValueError("Entrada demasiado grande")
        encoded[name] = base64.b64encode(data).decode("ascii")
    data = json.dumps({"version": 1, "nonce": nonce, "operation": operation,
                       "limits": limits, "files": encoded}, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_INPUT:
        raise ValueError("Solicitud demasiado grande")
    blob = MAGIC + struct.pack(">I", len(data)) + data
    # Un dispositivo de bloque debe ser múltiplo del sector de 512 bytes.
    return blob + b"\0" * (-len(blob) % 512)


def read_sources(folder):
    folder = Path(folder)
    if folder.is_symlink() or getattr(folder.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("No se admite una raíz enlazada")
    files = {}
    total = 0
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("No se admiten enlaces ni reparse points")
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            safe_name(name)
            total += path.stat().st_size
            if len(files) >= MAX_FILES or total > MAX_SOURCE or path.stat().st_nlink > 1:
                raise ValueError("Entrada demasiado grande")
            files[name] = path.read_bytes()
    return files


def decode_result(console, nonce, limit):
    """La respuesta es dato no confiable, no una prueba del aislamiento."""
    if len(console) > MAX_CONSOLE:
        raise ValueError("Salida de consola excedida")
    records = [line[len(PREFIX):] for line in console.splitlines() if line.startswith(PREFIX)]
    if len(records) != 1:
        raise ValueError("Falta un único resultado de la VM")
    try:
        result = json.loads(base64.b64decode(records[0], validate=True).decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise ValueError("Resultado de VM inválido") from error
    if not isinstance(result, dict) or set(result) != {"version", "nonce", "returncode", "stdout", "stderr", "timed_out"}:
        raise ValueError("Esquema de resultado inválido")
    if type(result["version"]) is not int or result["version"] != 1 or result["nonce"] != nonce:
        raise ValueError("El resultado no corresponde a este trabajo")
    if type(result["returncode"]) is not int or not -255 <= result["returncode"] <= 255 or type(result["timed_out"]) is not bool:
        raise ValueError("Estado de resultado inválido")
    for key in ("stdout", "stderr"):
        if not isinstance(result[key], str) or len(result[key].encode("utf-8")) > limit:
            raise ValueError("Salida de programa excedida")
    return result
