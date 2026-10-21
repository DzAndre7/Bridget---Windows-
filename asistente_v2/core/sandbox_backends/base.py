"""Contrato portable para ejecutar exclusivamente dentro de aislamiento real."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class EstadoBackend:
    nombre: str
    motivo: str = ""
    archivos_aislados: bool = False
    red_bloqueada: bool = False
    recursos_limitados: bool = False
    procesos_controlados: bool = False
    entorno_sin_secretos: bool = False

    @property
    def disponible(self) -> bool:
        return all(valor is True for valor in (
            self.archivos_aislados, self.red_bloqueada, self.recursos_limitados,
            self.procesos_controlados, self.entorno_sin_secretos,
        ))


@dataclass(frozen=True)
class SolicitudEjecucion:
    # No hay un comando shell, env host, DISPLAY ni opción de permitir red.
    operacion: Literal["script", "pytest"]
    carpeta_entrada: Path
    timeout: int
    limite_cpu: int
    limite_procesos: int
    limite_memoria: int
    limite_archivo: int
    limite_salida: int


@dataclass(frozen=True)
class ResultadoBackend:
    salida: str = ""
    errores: str = ""
    codigo_retorno: int = -1
    timeout: bool = False
    # El backend solo puede dar resultado válido tras destruir TODO el entorno.
    aislamiento_verificado: bool = False
    limpieza_verificada: bool = False


class BackendAislado(ABC):
    @abstractmethod
    def estado(self) -> EstadoBackend:
        """Verifica las garantías, no solo la presencia de un runtime."""

    @abstractmethod
    def ejecutar(self, solicitud: SolicitudEjecucion) -> ResultadoBackend:
        """Transporta entradas sin secretos y limita la salida durante la lectura.

        Nunca importa ni ejecuta las entradas dentro de Python o procesos del
        host. Debe impedir red/escrituras host y terminar todos los descendientes
        aun al vencer timeout o cancelar. Los límites no se aplican opcionalmente.
        """
