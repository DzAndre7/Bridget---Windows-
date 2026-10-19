"""Tests del sandbox (core/sandbox.py): ejecución aislada de código.
No usan LLM ni red real: el sandbox se prueba con código fijo y, para el
ciclo crear→probar→corregir, con un LLM falso que devuelve respuestas
preparadas.
"""
import os
import sys
import textwrap

from core import sandbox


# ---------- verificar_sintaxis ----------

def test_sintaxis_valida():
    ok, error = sandbox.verificar_sintaxis("x = 1 + 1\nprint(x)")
    assert ok
    assert error is None


def test_sintaxis_invalida():
    ok, error = sandbox.verificar_sintaxis("def rota(:\n    pass")
    assert not ok
    assert "Línea" in error


# ---------- extraer_codigo ----------

def test_extraer_codigo_con_fences():
    respuesta = "Acá va:\n```python\nprint('hola')\n```\n¡Espero que sirva!"
    assert sandbox.extraer_codigo(respuesta) == "print('hola')"


def test_extraer_codigo_sin_fences():
    assert sandbox.extraer_codigo("  print('hola')  ") == "print('hola')"


# ---------- ejecutar_codigo ----------

def test_ejecutar_codigo_ok():
    resultado = sandbox.ejecutar_codigo("print('hola sandbox')")
    assert resultado["exito"]
    assert resultado["etapa"] == "ok"
    assert "hola sandbox" in resultado["salida"]


def test_ejecutar_codigo_error_de_ejecucion():
    resultado = sandbox.ejecutar_codigo("1 / 0")
    assert not resultado["exito"]
    assert resultado["etapa"] == "ejecucion"
    assert "ZeroDivisionError" in resultado["errores"]


def test_ejecutar_codigo_error_de_sintaxis_no_llega_a_correr():
    resultado = sandbox.ejecutar_codigo("def rota(:")
    assert not resultado["exito"]
    assert resultado["etapa"] == "sintaxis"


def test_ejecutar_codigo_timeout():
    resultado = sandbox.ejecutar_codigo("while True: pass", timeout=2)
    assert not resultado["exito"]
    assert resultado["etapa"] == "timeout"


def test_ejecutar_codigo_corre_fuera_del_proyecto():
    # el cwd del código probado debe ser una carpeta temporal descartable
    # y propia, nunca el proyecto mismo. (Se compara por nombre y no por
    # 'no contiene la ruta del proyecto' para que también valga cuando la
    # suite entera corre dentro de una copia sandbox: ahí el TMPDIR queda
    # debajo de la copia y las rutas se anidan.)
    resultado = sandbox.ejecutar_codigo("import os; print(os.getcwd())")
    assert resultado["exito"]
    cwd = resultado["salida"].strip()
    assert cwd != sandbox.RUTA_PROYECTO
    assert os.path.basename(cwd).startswith("bridget_sandbox_")


def test_ejecutar_codigo_home_aislado():
    # HOME apunta al sandbox: un descuido tipo open(~/archivo) no toca el real
    resultado = sandbox.ejecutar_codigo(
        "import os; print(os.path.expanduser('~'))"
    )
    assert resultado["exito"]
    home = resultado["salida"].strip()
    assert home != os.path.expanduser("~")
    assert os.path.basename(home).startswith("bridget_sandbox_")


# ---------- probar_codigo ----------

def test_probar_codigo_pasa():
    codigo = "def sumar(a, b):\n    return a + b\n"
    pruebas = textwrap.dedent("""
        from solucion import sumar

        def test_sumar():
            assert sumar(2, 3) == 5
    """)
    resultado = sandbox.probar_codigo(codigo, pruebas)
    assert resultado["exito"]
    assert resultado["etapa"] == "ok"


def test_probar_codigo_falla():
    codigo = "def sumar(a, b):\n    return a - b\n"  # bug a propósito
    pruebas = textwrap.dedent("""
        from solucion import sumar

        def test_sumar():
            assert sumar(2, 3) == 5
    """)
    resultado = sandbox.probar_codigo(codigo, pruebas)
    assert not resultado["exito"]
    assert resultado["etapa"] == "pruebas"


# ---------- probar_cambio_en_proyecto ----------

def _mini_proyecto(tmp_path):
    """Arma un proyecto chiquito con la misma forma que asistente_v2:
    un módulo en la raíz y una carpeta tests/ con conftest que agrega
    la raíz al sys.path."""
    (tmp_path / "modulo.py").write_text(
        "def sumar(a, b):\n    return a + b\n", encoding="utf-8"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(
        textwrap.dedent("""
            import os, sys
            RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if RAIZ not in sys.path:
                sys.path.insert(0, RAIZ)
        """),
        encoding="utf-8",
    )
    (tests / "test_modulo.py").write_text(
        textwrap.dedent("""
            from modulo import sumar

            def test_sumar():
                assert sumar(2, 3) == 5
        """),
        encoding="utf-8",
    )
    return tmp_path


def test_cambio_bueno_pasa_las_pruebas(tmp_path):
    proyecto = _mini_proyecto(tmp_path)
    resultado = sandbox.probar_cambio_en_proyecto(
        "modulo.py",
        "def sumar(a, b):\n    resultado = a + b\n    return resultado\n",
        ruta_proyecto=str(proyecto),
    )
    assert resultado["exito"], resultado["salida"] + resultado["errores"]
    assert resultado["etapa"] == "ok"


def test_cambio_malo_falla_y_no_toca_el_original(tmp_path):
    proyecto = _mini_proyecto(tmp_path)
    original = (proyecto / "modulo.py").read_text(encoding="utf-8")

    resultado = sandbox.probar_cambio_en_proyecto(
        "modulo.py",
        "def sumar(a, b):\n    return a - b\n",  # rompe la suite
        ruta_proyecto=str(proyecto),
    )
    assert not resultado["exito"]
    assert resultado["etapa"] == "pruebas"
    # la regla de oro: el archivo real quedó intacto
    assert (proyecto / "modulo.py").read_text(encoding="utf-8") == original


def test_cambio_con_sintaxis_rota_no_corre_la_suite(tmp_path):
    proyecto = _mini_proyecto(tmp_path)
    resultado = sandbox.probar_cambio_en_proyecto(
        "modulo.py", "def sumar(a, b:\n", ruta_proyecto=str(proyecto)
    )
    assert not resultado["exito"]
    assert resultado["etapa"] == "sintaxis"


def test_archivo_fuera_del_proyecto_se_rechaza(tmp_path):
    proyecto = _mini_proyecto(tmp_path)
    resultado = sandbox.probar_cambio_en_proyecto(
        "/etc/hostname", "print('no')", ruta_proyecto=str(proyecto)
    )
    assert not resultado["exito"]
    assert resultado["etapa"] == "fuera_del_proyecto"


# ---------- crear_y_probar ----------

def test_crear_y_probar_corrige_tras_un_error():
    """LLM falso: primero devuelve código roto, después la corrección."""
    respuestas = iter([
        "```python\n1 / 0\n```",
        "```python\nassert 2 + 2 == 4\nprint('PRUEBAS OK')\n```",
    ])
    resultado = sandbox.crear_y_probar(
        "sumar dos números", lambda prompt: next(respuestas), max_intentos=3
    )
    assert resultado["exito"]
    assert resultado["intentos"] == 2
    assert "PRUEBAS OK" in resultado["resultado"]["salida"]


def test_crear_y_probar_se_rinde_tras_max_intentos():
    resultado = sandbox.crear_y_probar(
        "algo imposible", lambda prompt: "```python\n1 / 0\n```", max_intentos=2
    )
    assert not resultado["exito"]
    assert resultado["intentos"] == 2
    assert resultado["resultado"]["etapa"] == "ejecucion"


# ---------- guardar_codigo_validado ----------

def test_guardar_codigo_validado(tmp_path):
    ruta = sandbox.guardar_codigo_validado(
        "print('hola')", descripcion="saludar", carpeta=str(tmp_path)
    )
    assert os.path.exists(ruta)
    contenido = open(ruta, encoding="utf-8").read()
    assert "print('hola')" in contenido
    assert "saludar" in contenido
    assert "sandbox" in contenido
