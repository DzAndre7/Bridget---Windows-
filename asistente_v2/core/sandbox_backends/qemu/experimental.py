"""Backend real en desarrollo: solo permite una autoprueba fija de la VM.

No existe opción de habilitar snippets ni configuración por variables de entorno.
La activación futura requiere una revisión de código después de validar Windows.
"""
import tempfile
from pathlib import Path

from ..base import BackendAislado, EstadoBackend, SolicitudEjecucion
from .controller import _run_validation_job

PROBE = '''import json, os, socket
from pathlib import Path
assert os.getuid() == 65534
assert not any(k in os.environ for k in ("USERPROFILE", "GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "GROQ_API_KEY"))
interfaces = set(os.listdir("/sys/class/net"))
assert interfaces <= {"lo"}, interfaces
try:
    socket.create_connection(("192.0.2.1", 443), timeout=0.5)
except OSError:
    pass
else:
    raise AssertionError("Red accesible")
assert not Path("/host").exists()
print("BRIDGET_VM_PROBE_OK")
'''


class QemuExperimental(BackendAislado):
    def __init__(self, bundle_root):
        self.bundle_root = Path(bundle_root)

    def estado(self):
        return EstadoBackend("qemu_experimental", "QEMU experimental: falta validar la frontera completa en Windows 11; ejecución dinámica bloqueada.")

    def ejecutar(self, solicitud):
        raise RuntimeError(self.estado().motivo)

    def autoprueba(self, cancel=None):
        # No acepta código, rutas de fuentes, límites ni argumentos del usuario.
        with tempfile.TemporaryDirectory(prefix="bridget_vm_probe_") as directory:
            Path(directory, "codigo.py").write_text(PROBE, encoding="utf-8")
            request = SolicitudEjecucion(
                "script", Path(directory), timeout=60, limite_cpu=60, limite_procesos=16,
                limite_memoria=512 * 1024 ** 2, limite_archivo=1024 ** 2, limite_salida=2000,
            )
            evidence = _run_validation_job(self.bundle_root, request, cancel)
        ok = bool(evidence.cleaned and evidence.result and not evidence.error
                  and not evidence.timed_out and not evidence.cancelled
                  and evidence.result["returncode"] == 0 and not evidence.result["timed_out"]
                  and evidence.result["stdout"].strip() == "BRIDGET_VM_PROBE_OK")
        return {"autoprueba_correcta": ok, "limpieza_verificada": evidence.cleaned,
                "timeout": evidence.timed_out, "cancelado": evidence.cancelled,
                "error": evidence.error, "ejecucion_dinamica_habilitada": False}
