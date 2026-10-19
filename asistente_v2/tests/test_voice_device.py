"""Selección CPU/GPU del TTS sin imports pesados ni descargar modelos."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("cuda,esperado", [(False, "cpu"), (True, "cuda")])
def test_fallback_coqui_elige_dispositivo_disponible(monkeypatch, cuda, esperado):
    # Solo la definición revisada; no se ejecuta la inicialización de voice.py
    # que modifica builtins.print y carga variables del usuario.
    ruta = Path(__file__).parents[1] / "core" / "voice.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "_cargar_coqui")
    tts = Mock()
    paquete = ModuleType("TTS")
    paquete.__path__ = []
    api = ModuleType("TTS.api")
    api.TTS = tts
    monkeypatch.setitem(__import__('sys').modules, "TTS", paquete)
    monkeypatch.setitem(__import__('sys').modules, "TTS.api", api)
    monkeypatch.setitem(__import__('sys').modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda)))
    espacio = {"_tts_local": None, "silenciar_salida": nullcontext}
    exec(compile(ast.Module(body=[funcion], type_ignores=[]), str(ruta), "exec"), espacio)
    primero = espacio["_cargar_coqui"]()
    assert espacio["_cargar_coqui"]() is primero
    tts.assert_called_once()
    tts.return_value.to.assert_called_once_with(esperado)
