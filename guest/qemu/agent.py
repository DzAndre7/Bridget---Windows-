#!/usr/bin/python3
"""Agente del initramfs Linux, NO ejecutar como programa del anfitrión.

Solo biblioteca estándar. Todo código recibido se ejecuta en la VM, como UID
65534, con entorno fijo y límites. La VM completa se destruye después del trabajo.
"""
import base64
import json
import os
import re
import selectors
import signal
import struct
import sys
import time
from pathlib import Path, PurePosixPath

MAGIC = b"BRDGV001"
PREFIX = b"BRIDGET_RESULT_V1:"
MAX_INPUT = 16 * 1024 * 1024
MAX_SOURCE = 10 * 1024 * 1024



def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Clave JSON duplicada")
        result[key] = value
    return result


def parse_input(raw):
    if len(raw) < 12 or raw[:8] != MAGIC:
        raise ValueError("Cabecera de entrada inválida")
    size = struct.unpack(">I", raw[8:12])[0]
    if not 0 < size <= MAX_INPUT or len(raw) < size + 12:
        raise ValueError("Tamaño de entrada inválido")
    data = json.loads(raw[12:12 + size].decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != {"version", "nonce", "operation", "limits", "files"}:
        raise ValueError("Esquema inválido")
    if type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["nonce"], str) or not re.fullmatch(r"[a-f0-9]{32}", data["nonce"]):
        raise ValueError("Protocolo inválido")
    if data["operation"] not in {"script", "pytest"}:
        raise ValueError("Operación inválida")
    limits = data["limits"]
    bounds = {"seconds": (1, 300), "cpu": (1, 300), "memory": (128 * 1024 ** 2, 2 * 1024 ** 3),
              "file": (1, MAX_SOURCE), "processes": (1, 32), "output": (1, 8000)}
    if not isinstance(limits, dict) or set(limits) != set(bounds):
        raise ValueError("Límites inválidos")
    for name, (low, high) in bounds.items():
        if type(limits[name]) is not int or not low <= limits[name] <= high:
            raise ValueError("Límites inválidos")
    files = data["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= 500:
        raise ValueError("Archivos inválidos")
    decoded = {}
    names = set()
    total = 0
    for name, encoded in files.items():
        if not isinstance(name, str) or "\\" in name or ":" in name or "\0" in name:
            raise ValueError("Ruta inválida")
        path = PurePosixPath(name)
        if path.is_absolute() or any(p in {"", ".", ".."} or p.startswith(".") for p in name.split("/")):
            raise ValueError("Ruta inválida")
        if path.suffix.lower() not in {".py", ".html", ".css", ".js", ".png"} and path.name not in {"context.md", "config_presencia.json", "manifest.json"}:
            raise ValueError("Tipo de archivo inválido")
        if name.casefold() in names or not isinstance(encoded, str):
            raise ValueError("Archivo inválido")
        names.add(name.casefold())
        content = base64.b64decode(encoded, validate=True)
        total += len(content)
        if total > MAX_SOURCE:
            raise ValueError("Archivos demasiado grandes")
        decoded[name] = content
    required = "codigo.py" if data["operation"] == "script" else None
    if required and required not in decoded:
        raise ValueError("Falta codigo.py")
    data["files"] = decoded
    return data


def require_guest(*, init=False):
    if sys.platform != "linux" or "bridget_guest=1" not in Path("/proc/cmdline").read_text():
        raise RuntimeError("Solo permitido dentro del invitado Bridget")
    if init and os.getpid() != 1:
        raise RuntimeError("El supervisor debe ser PID 1 del invitado")


def child_limits(limits):
    # POSIX está contenido en el invitado, nunca en el import del backend host.
    require_guest()
    import ctypes
    import resource
    os.setsid()
    for key, value in [(resource.RLIMIT_AS, limits["memory"]),
                       (resource.RLIMIT_CPU, limits["cpu"]),
                       (resource.RLIMIT_FSIZE, limits["file"]),
                       (resource.RLIMIT_NPROC, limits["processes"]),
                       (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)]:
        resource.setrlimit(key, (value, value))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError("No se pudo cerrar privilegios")
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    os.umask(0o077)


def run_guest_job(data):
    require_guest(init=True)
    import subprocess
    work = Path("/work")
    # /work es tmpfs acotado creado por /init. No se reutiliza entre trabajos.
    for name, content in data["files"].items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o600)
        os.chown(path, 65534, 65534)
    for path in sorted(work.rglob("*"), reverse=True):
        if path.is_dir():
            os.chown(path, 65534, 65534)
            path.chmod(0o700)
    os.chown(work, 65534, 65534)
    limits = data["limits"]
    if data["operation"] == "script":
        command = ["/usr/bin/python3", "-I", "-c",
                   "import runpy,sys;sys.path.insert(0,'/work');"
                   "sys.argv=['/work/codigo.py'];runpy.run_path('/work/codigo.py',run_name='__main__')"]
    else:
        command = ["/usr/bin/python3", "-I", "-m", "pytest", "-q"]
        # No ejecutar experimentos legacy si el proyecto tiene tests/.
        if (work / "tests").is_dir():
            command.append("tests")
    proc = subprocess.Popen(
        command, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin", "HOME": "/work",
        "TMPDIR": "/work", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        preexec_fn=lambda: child_limits(limits),
    )
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = False
    deadline = time.monotonic() + limits["seconds"]
    selector = selectors.DefaultSelector()
    for name, stream in [("stdout", proc.stdout), ("stderr", proc.stderr)]:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                timed_out = True
                break
            for key, _ in selector.select(timeout=0.05):
                part = os.read(key.fileobj.fileno(), 4096)
                if not part:
                    selector.unregister(key.fileobj)
                else:
                    target = chunks[key.data]
                    target.extend(part[:max(0, limits["output"] - len(target))])
            if proc.poll() is not None:
                # Hijos que retienen pipes no prolongan la sesión indefinidamente.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
    def text(value):
        # Un corte intermedio UTF-8 no puede expandir el límite al reemplazar.
        return value.decode("utf-8", "ignore")
    return {"version": 1, "nonce": data["nonce"], "returncode": max(-255, min(255, proc.returncode)),
            "stdout": text(chunks["stdout"]), "stderr": text(chunks["stderr"]), "timed_out": timed_out}


def main():
    require_guest(init=True)
    # El script /init monta pseudo-filesystems y scratch antes de exec.
    data = None
    try:
        with open("/dev/vda", "rb", buffering=0) as source:
            header = source.read(12)
            if len(header) != 12 or header[:8] != MAGIC:
                raise ValueError("Disco de entrada inválido")
            length = struct.unpack(">I", header[8:12])[0]
            if not 0 < length <= MAX_INPUT:
                raise ValueError("Disco de entrada demasiado grande")
            data = parse_input(header + source.read(length))
        result = run_guest_job(data)
        message = json.dumps(result, separators=(",", ":")).encode("utf-8")
        sys.stdout.buffer.write(PREFIX + base64.b64encode(message) + b"\n")
        sys.stdout.buffer.flush()
    except Exception:
        # No exponer traceback, rutas del bundle ni contenido arbitrario al host.
        sys.stdout.write("BRIDGET_GUEST_FAILED\n")
        sys.stdout.flush()
    finally:
        import ctypes
        os.sync()
        ctypes.CDLL(None).reboot(0x4321FEDC)  # LINUX_REBOOT_CMD_POWER_OFF
        while True:  # Si apagado falla, el watchdog host destruye QEMU.
            time.sleep(1)


if __name__ == "__main__":
    main()
