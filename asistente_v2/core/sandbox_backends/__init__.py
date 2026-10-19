"""Selección explícita de backends de aislamiento; sin fallback a procesos host.

No hay aún un backend de ejecución auditado. Tener Docker o Windows Sandbox
instalado no demuestra que una ejecución esté aislada. Ver docs/SANDBOX.md.
"""
import platform

from .base import BackendAislado, EstadoBackend, ResultadoBackend, SolicitudEjecucion

__all__ = [
    "BackendAislado", "EstadoBackend", "ResultadoBackend", "SolicitudEjecucion",
    "obtener_backend",
]


class SinAislamiento(BackendAislado):
    def __init__(self, sistema: str):
        self.sistema = sistema

    def estado(self) -> EstadoBackend:
        return EstadoBackend(
            nombre="no_disponible",
            motivo=(
                f"No hay un backend de aislamiento seguro validado para {self.sistema}. "
                "No se ejecutó código. Windows Sandbox o una VM dedicada requieren "
                "integración y validación; un subprocess, venv o Docker sin "
                "configuración verificada no los reemplaza. Ver docs/SANDBOX.md."
            ),
        )

    def ejecutar(self, solicitud: SolicitudEjecucion) -> ResultadoBackend:
        # Defensa adicional si alguien llama al backend sin consultar estado().
        raise RuntimeError(self.estado().motivo)


def obtener_backend() -> BackendAislado:
    """No acepta módulos, comandos ni banderas de confianza desde el entorno.

    Un futuro backend deberá registrarse en código y acreditar todas las
    garantías del contrato. No se habilita por detectar un ejecutable.
    """
    return SinAislamiento(platform.system())
