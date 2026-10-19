"""Tests del ciclo de auto-mejora (core/auto_mejora.py). Sin LLM ni Groq
reales: el modelo entra como función falsa y el revisor se anula, igual que
en los tests del sandbox. El proyecto a mejorar es uno chiquito en tmp_path.
"""
import os
import textwrap

import pytest

from core import auto_mejora


MODULO_ORIGINAL = textwrap.dedent("""
    def sumar(a, b):
        # suma simple
        resultado = a + b
        return resultado
""").lstrip()

MODULO_MEJORADO = textwrap.dedent("""
    def sumar(a, b):
        # suma simple, versión mejorada
        return a + b
""").lstrip()

MODULO_ROTO = textwrap.dedent("""
    def sumar(a, b):
        # esta version esta rota a proposito para el test
        resultado = a - b
        return resultado
""").lstrip()

# sumar() sigue andando bien (la única función que testea test_modulo.py),
# pero formatear() usa un nombre que nunca se importó. La suite pasa igual
# porque nada llama a formatear() — exactamente el hueco que dejó pasar la
# propuesta real de core/search.py. Ruff lo detecta sin ejecutar nada.
MODULO_CON_NOMBRE_INDEFINIDO = textwrap.dedent("""
    def sumar(a, b):
        return a + b

    def formatear(resultado):
        return nombre_que_no_existe.strip()
""").lstrip()


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Proyecto mínimo con core/, tests/ y revisor externo anulado."""
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "core" / "modulo.py").write_text(MODULO_ORIGINAL, encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(textwrap.dedent("""
        import os, sys
        RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if RAIZ not in sys.path:
            sys.path.insert(0, RAIZ)
    """), encoding="utf-8")
    (tests / "test_modulo.py").write_text(textwrap.dedent("""
        from core.modulo import sumar

        def test_sumar():
            assert sumar(2, 3) == 5
    """), encoding="utf-8")

    # sin Groq en los tests: la propuesta se genera sin guía externa
    monkeypatch.setattr(auto_mejora, "revisar_codigo", lambda *a, **k: None)
    return tmp_path


def test_proponer_mejora_buena_queda_pendiente_sin_tocar_el_original(proyecto):
    resultado = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_MEJORADO, ruta_proyecto=str(proyecto)
    )
    assert resultado["exito"], resultado
    assert resultado["archivo"] == "core/modulo.py"
    assert "resultado = a + b" in resultado["diff"]  # el diff refleja el cambio

    # regla de oro: el archivo real sigue intacto
    original = (proyecto / "core" / "modulo.py").read_text(encoding="utf-8")
    assert original == MODULO_ORIGINAL

    # y la propuesta quedó esperando revisión
    mejoras = auto_mejora.listar_mejoras(str(proyecto))
    assert len(mejoras) == 1
    assert mejoras[0]["id"] == resultado["id"]


def test_propuesta_que_rompe_las_pruebas_se_rechaza(proyecto):
    resultado = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_ROTO,
        ruta_proyecto=str(proyecto), max_intentos=1,
    )
    assert not resultado["exito"]
    assert "sandbox" in resultado["motivo"]
    assert auto_mejora.listar_mejoras(str(proyecto)) == []


def test_propuesta_que_recorta_demasiado_se_rechaza(proyecto):
    resultado = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: "x = 1",
        ruta_proyecto=str(proyecto), max_intentos=1,
    )
    assert not resultado["exito"]
    assert "recorta" in resultado["motivo"]


def test_propuesta_con_nombre_indefinido_se_rechaza(proyecto):
    resultado = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_CON_NOMBRE_INDEFINIDO,
        ruta_proyecto=str(proyecto), max_intentos=1,
    )
    assert not resultado["exito"]
    assert "linter" in resultado["motivo"]
    assert auto_mejora.listar_mejoras(str(proyecto)) == []


def test_archivo_fuera_del_proyecto_se_rechaza(proyecto):
    resultado = auto_mejora.proponer_mejora(
        "/etc/hostname", lambda p: "x", ruta_proyecto=str(proyecto)
    )
    assert not resultado["exito"]


def test_aplicar_mejora_escribe_y_archiva(proyecto):
    propuesta = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_MEJORADO, ruta_proyecto=str(proyecto)
    )
    resultado = auto_mejora.aplicar_mejora(propuesta["id"], ruta_proyecto=str(proyecto))
    assert resultado["exito"], resultado

    contenido = (proyecto / "core" / "modulo.py").read_text(encoding="utf-8")
    assert contenido == MODULO_MEJORADO
    # ya no está pendiente: quedó archivada en aplicadas/
    assert auto_mejora.listar_mejoras(str(proyecto)) == []
    assert os.path.isdir(proyecto / "mejoras_aplicadas")


def test_aplicar_se_niega_si_el_archivo_cambio_despues(proyecto):
    propuesta = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_MEJORADO, ruta_proyecto=str(proyecto)
    )
    # alguien tocó el archivo después de la propuesta
    (proyecto / "core" / "modulo.py").write_text(
        MODULO_ORIGINAL + "\n# cambio posterior\n", encoding="utf-8"
    )
    resultado = auto_mejora.aplicar_mejora(propuesta["id"], ruta_proyecto=str(proyecto))
    assert not resultado["exito"]
    assert "cambió" in resultado["motivo"]


def test_descartar_mejora_archiva_sin_tocar_nada(proyecto):
    propuesta = auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_MEJORADO, ruta_proyecto=str(proyecto)
    )
    resultado = auto_mejora.descartar_mejora(propuesta["id"], ruta_proyecto=str(proyecto))
    assert resultado["exito"]
    assert auto_mejora.listar_mejoras(str(proyecto)) == []
    original = (proyecto / "core" / "modulo.py").read_text(encoding="utf-8")
    assert original == MODULO_ORIGINAL


def test_elegir_archivo_saltea_los_que_tienen_mejora_pendiente(proyecto):
    assert auto_mejora.elegir_archivo(str(proyecto)) == os.path.join("core", "modulo.py")

    auto_mejora.proponer_mejora(
        "core/modulo.py", lambda p: MODULO_MEJORADO, ruta_proyecto=str(proyecto)
    )
    # el único candidato ya tiene propuesta pendiente
    assert auto_mejora.elegir_archivo(str(proyecto)) is None
