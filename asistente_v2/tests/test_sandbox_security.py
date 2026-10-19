"""Rechazos de auto-mejora y handlers sin importar escritorio ni usar modelos."""
import ast
import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import auto_mejora, sandbox
from core.sandbox_backends import EstadoBackend


@pytest.mark.parametrize("funcion,args", [
    (auto_mejora.proponer_mejora, ("core/modulo.py", Mock())),
    (auto_mejora.aplicar_mejora, ("propuesta",)),
])
def test_auto_mejora_no_lee_ni_escribe_sin_aislamiento(monkeypatch, funcion, args, tmp_path):
    leer = Mock(side_effect=AssertionError("No leer propuestas"))
    revisar = Mock(side_effect=AssertionError("No consultar red"))
    monkeypatch.setattr(auto_mejora, "_leer", leer)
    monkeypatch.setattr(auto_mejora, "revisar_codigo", revisar)
    resultado = funcion(*args, ruta_proyecto=str(tmp_path))
    assert resultado["etapa"] == "aislamiento_no_disponible"
    assert not resultado["exito"]
    assert list(tmp_path.iterdir()) == []
    leer.assert_not_called()
    revisar.assert_not_called()


def test_fallo_de_estado_no_autoriza_auto_mejora(monkeypatch):
    # La consulta pública debe también cerrar en caso de error del proveedor.
    falso = Mock()
    falso.estado.side_effect = OSError("motor perdido")
    monkeypatch.setattr(sandbox, "obtener_backend", lambda: falso)
    resultado = auto_mejora.proponer_mejora("core/x.py", Mock())
    assert not resultado["exito"]
    assert resultado["etapa"] == "aislamiento_no_disponible"


def cargar_handler(nombre, **globales):
    """Carga solo la definición revisada, no los imports/efectos de brain.py."""
    ruta = Path(__file__).parents[1] / "core" / "brain.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == nombre)
    espacio = {"os": os, "re": re, **globales}
    exec(compile(ast.Module(body=[funcion], type_ignores=[]), str(ruta), "exec"), espacio)
    return espacio[nombre]


@pytest.mark.parametrize("nombre", [
    "_cmd_crear_y_probar_codigo", "_cmd_probar_proyecto_sandbox",
    "_cmd_probar_codigo_sandbox", "_cmd_auto_mejora",
])
def test_handlers_informan_bloqueo_sin_modelos(nombre):
    handler = cargar_handler(nombre, estado_aislamiento=sandbox.estado_aislamiento)
    assert "No hay un backend" in handler("", "", None, "Bridget")


@pytest.mark.parametrize("etapa", ["pruebas", "fuera_del_proyecto", "aislamiento_no_disponible"])
def test_handler_legacy_no_ofrece_guardar_una_mejora_sin_validar(etapa):
    escribir = Mock(side_effect=AssertionError("No escribir código no probado"))
    preguntar = Mock(side_effect=AssertionError("No ofrecer bypass manual"))
    disponible = EstadoBackend("doble", archivos_aislados=True, red_bloqueada=True,
                              recursos_limitados=True, procesos_controlados=True,
                              entorno_sin_secretos=True)
    handler = cargar_handler(
        "_cmd_mejorar_codigo", DEBUG_MODE=False,
        estado_aislamiento=lambda: disponible, leer_archivo=lambda p: "x = 1",
        consultar_llama=lambda *a: "x = 2", revisar_codigo=lambda *a, **k: None,
        probar_cambio_en_proyecto=lambda *a: {"exito": False, "etapa": etapa, "salida": "", "errores": "rechazado"},
        verificar_sintaxis=lambda *a: (True, None), escribir_archivo=escribir,
        input=preguntar,
    )
    assert "No guardé" in handler("", "mejora /proyecto/x.py", None, "Bridget")
    escribir.assert_not_called()
    preguntar.assert_not_called()


def test_reparse_point_se_detecta_sin_seguirlo():
    ruta = Mock()
    ruta.lstat.return_value = Mock(st_mode=0o100644, st_file_attributes=0x400)
    assert sandbox._es_enlace(ruta)


def test_linter_usa_interprete_actual_y_utf8(monkeypatch):
    import sys
    run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(auto_mejora.subprocess, "run", run)
    assert auto_mejora._lint_ruff("# versión española\nx = 1", "core/modulo.py")["exito"]
    assert run.call_args.args[0][:3] == [sys.executable, "-m", "ruff"]
    assert run.call_args.kwargs["encoding"] == "utf-8"


def test_metadatos_de_propuesta_no_permiten_escribir_fuera(tmp_path, monkeypatch):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    fuera = tmp_path / "fuera.py"
    fuera.write_text("x = 1", encoding="utf-8")
    estado = EstadoBackend("doble", archivos_aislados=True, red_bloqueada=True,
                          recursos_limitados=True, procesos_controlados=True,
                          entorno_sin_secretos=True)
    monkeypatch.setattr(auto_mejora.sandbox, "estado_aislamiento", lambda: estado)
    probar = Mock(side_effect=AssertionError("No transferir una ruta externa"))
    monkeypatch.setattr(auto_mejora.sandbox, "probar_cambio_en_proyecto", probar)
    propuesta, _, _ = auto_mejora._guardar_propuesta("../fuera.py", "x = 1", "x = 2", "", str(proyecto))
    resultado = auto_mejora.aplicar_mejora(propuesta, str(proyecto))
    assert not resultado["exito"]
    assert fuera.read_text() == "x = 1"
    probar.assert_not_called()
