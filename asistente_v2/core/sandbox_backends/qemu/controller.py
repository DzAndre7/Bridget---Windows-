"""Controlador experimental real de QEMU. No se registra como backend habilitado."""
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .bundle import Bundle
from .protocol import MAX_CONSOLE, decode_result, encode_input, read_sources
from .windows_job import WindowsJob


@dataclass(frozen=True)
class Evidence:
    result: dict | None = None
    timed_out: bool = False
    cancelled: bool = False
    cleaned: bool = False
    error: str = ""
    # Evidencia de protocolo/control no habilita una frontera de seguridad.
    security_validated: bool = False


def limits_for(request):
    fields = {"seconds": request.timeout, "cpu": request.limite_cpu,
              "memory": request.limite_memoria, "file": request.limite_archivo,
              "processes": request.limite_procesos, "output": request.limite_salida}
    bounds = {"seconds": (1, 300), "cpu": (1, 300), "memory": (128 * 1024 ** 2, 2 * 1024 ** 3),
              "file": (1, 10 * 1024 ** 2), "processes": (1, 32), "output": (1, 8000)}
    for name, value in fields.items():
        low, high = bounds[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Límites de VM inválidos")
    return fields


def command(bundle, input_disk, memory):
    # JSON evita inyección de opciones con comas en rutas de -drive.
    return [str(bundle.qemu), "-no-user-config", "-nodefaults", "-machine", "q35,accel=whpx",
            "-smp", "1", "-m", str(memory // (1024 ** 2)), "-display", "none",
            "-nic", "none", "-monitor", "none", "-parallel", "none", "-serial", "stdio",
            "-no-reboot", "-L", str(bundle.firmware), "-kernel", str(bundle.kernel),
            "-initrd", str(bundle.initrd), "-append", "console=ttyS0 rdinit=/init panic=-1 quiet loglevel=3 bridget_guest=1",
            "-blockdev", json.dumps({"driver": "file", "filename": str(input_disk),
                                      "node-name": "input-file", "read-only": True}),
            "-blockdev", json.dumps({"driver": "raw", "file": "input-file", "node-name": "input-raw", "read-only": True}),
            "-device", "virtio-blk-pci,drive=input-raw"]


def clean_environment(bundle, staging):
    # No copia os.environ: sin HOME, USERPROFILE, tokens, proxies ni SDKs.
    system = os.environ.get("SystemRoot", r"C:\Windows")
    return {"SystemRoot": system, "WINDIR": system,
            "PATH": str(bundle.qemu.parent) + os.pathsep + str(Path(system) / "System32"),
            "TEMP": str(staging), "TMP": str(staging)}


def _run_validation_job(bundle_root, request, cancel=None, *, _guard=None):
    """Punto interno de QA. Solo la autoprueba fija lo usa en producción.

    No constituye una aprobación del aislamiento. El ejecutor público sigue
    bloqueado aunque el resultado sea correcto y cleaned=True.
    """
    if os.name != "nt" and _guard is None:
        return Evidence(error="La implementación del Job requiere Windows")
    if cancel is not None and cancel.is_set():
        return Evidence(cancelled=True, cleaned=True)
    deadline = time.monotonic() + request.timeout
    guard_factory = _guard or WindowsJob
    bundle = Bundle.load(bundle_root)  # revalida hashes por trabajo, no un cache
    limits = limits_for(request)
    nonce = secrets.token_hex(16)
    data = encode_input(read_sources(request.carpeta_entrada), nonce, request.operacion, limits)
    if cancel is not None and cancel.is_set():
        return Evidence(cancelled=True, cleaned=True)
    guard = None
    reader = None
    process = None
    output = bytearray()
    overflow = threading.Event()
    read_failed = threading.Event()
    timed_out = cancelled = clean = False
    result = None
    error = ""
    # Incluye arranque y ejecución; se reserva tiempo adicional de limpieza.
    with tempfile.TemporaryDirectory(prefix="bridget_vm_") as directory:
        staging = Path(directory)
        disk = staging / "input.bin"
        disk.write_bytes(data)
        if time.monotonic() >= deadline:
            return Evidence(timed_out=True, cleaned=True)
        try:
            guard = guard_factory(limits["memory"] + 512 * 1024 ** 2, limits["cpu"])
            process = guard.start(command(bundle, disk, limits["memory"]), staging, clean_environment(bundle, staging))

            def drain():
                try:
                    while True:
                        chunk = process.stdout.read(4096)
                        if not chunk:
                            return
                        remaining = MAX_CONSOLE - len(output)
                        output.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            overflow.set()
                            return
                except (OSError, ValueError):
                    read_failed.set()

            reader = threading.Thread(target=drain, name="bridget-vm-console", daemon=True)
            reader.start()
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if overflow.is_set() or read_failed.is_set():
                    break
                time.sleep(0.02)
        except (OSError, RuntimeError, ValueError):
            error = "No se pudo iniciar/controlar la VM; no se acepta resultado."
        finally:
            if guard is not None:
                try:
                    clean = guard.close()
                except Exception:
                    error = "No se pudo verificar la limpieza del hipervisor."
            if reader is not None:
                reader.join(timeout=5)
                if reader.is_alive():
                    clean = False
                    error = "La consola no se cerró tras detener la VM."
            if process is not None and process.stdout is not None and (reader is None or not reader.is_alive()):
                process.stdout.close()
        if clean and not (error or cancelled or timed_out or overflow.is_set() or read_failed.is_set()):
            try:
                if process is None or process.poll() != 0:
                    raise ValueError("QEMU no terminó normalmente")
                result = decode_result(bytes(output), nonce, limits["output"])
            except ValueError:
                error = "La VM no devolvió un resultado válido de este trabajo."
        elif not error and not (cancelled or timed_out):
            error = "Salida excedida, lectura fallida o limpieza incompleta."
    return Evidence(result=result, timed_out=timed_out, cancelled=cancelled,
                    cleaned=clean, error=error)
