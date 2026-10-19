"""Bundle local de confianza, fijado por hashes; no descarga ni instala nada."""
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_BUNDLE = 2 * 1024 ** 3


def plain_path(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("Ruta de bundle inválida")
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError("Ruta de bundle inválida")
    current = root
    for part in path.parts:
        current /= part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("No se admiten enlaces en el bundle")
    current.resolve(strict=True).relative_to(root)
    return current


@dataclass(frozen=True)
class Bundle:
    root: Path
    qemu: Path
    kernel: Path
    initrd: Path
    firmware: Path

    @classmethod
    def load(cls, root):
        root = Path(root).absolute()
        # No acceder a UNC, otros endpoints ni enlaces de ningún ancestro.
        if str(root).startswith(("\\\\", "//")):
            raise ValueError("El bundle debe estar en disco local")
        for item in (root, *root.parents):
            data = item.lstat()
            if stat.S_ISLNK(data.st_mode) or getattr(data, "st_file_attributes", 0) & 0x400:
                raise ValueError("Bundle a través de enlaces no permitido")
        if os.name == "nt":
            import ctypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW
            drive_type.argtypes = [ctypes.c_wchar_p]
            drive_type.restype = ctypes.c_uint32
            if drive_type(root.anchor) != 3:
                raise ValueError("Se requiere una unidad local fija")
        root = root.resolve(strict=True)
        manifest = plain_path(root, "bundle.json")
        if manifest.stat().st_size > 128 * 1024 or manifest.is_symlink():
            raise ValueError("Manifiesto inválido")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"version", "protocol", "qemu", "kernel", "initrd", "firmware", "files"} or data["version"] != 1 or data["protocol"] != 1:
            raise ValueError("Versión/esquema de bundle no soportado")
        hashes = data["files"]
        if not isinstance(hashes, dict) or not 1 <= len(hashes) <= 2000:
            raise ValueError("Inventario de bundle inválido")
        total = 0
        for name, expected in hashes.items():
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("Hash inválido")
            path = plain_path(root, name)
            if not path.is_file() or path.stat().st_nlink > 1:
                raise ValueError("Se requiere un archivo regular sin hardlinks")
            total += path.stat().st_size
            if total > MAX_BUNDLE:
                raise ValueError("Bundle demasiado grande")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("El bundle no coincide con los hashes fijados")
        for path in root.rglob("*"):
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Enlace no permitido")
            if path.is_file() and path != manifest and path.relative_to(root).as_posix() not in hashes:
                raise ValueError("Archivo no inventariado en el bundle")
        roles = [data[k] for k in ("qemu", "kernel", "initrd")]
        if not all(isinstance(role, str) for role in roles) or len(set(roles)) != 3 or not all(role in hashes for role in roles):
            raise ValueError("Componentes requeridos no inventariados")
        firmware = plain_path(root, data["firmware"])
        if not firmware.is_dir() or not any(name.startswith(data["firmware"] + "/") for name in hashes):
            raise ValueError("Firmware no inventariado")
        return cls(root, *(plain_path(root, name) for name in roles), firmware)
