"""Regresión de la API: no se ejecuta NINGUNA entrada, ni siquiera en tests.

El backend de prueba solo devuelve resultados prefijados y lee las entradas
como datos para comprobar el protocolo; no usa exec, subprocess, pytest hijo
ni modelos. La integración con una VM real es una validación separada pendiente.
"""
import builtins
import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import sandbox
from core.sandbox_backends import EstadoBackend, ResultadoBackend
from core.sandbox_backends import SinAislamiento


def estado_disponible():
    return EstadoBackend("doble_de_prueba", archivos_aislados=True, red_bloqueada=True,
                         recursos_limitados=True, procesos_controlados=True,
                         entorno_sin_secretos=True)


@pytest.fixture
def backend(monkeypatch):
    falso = Mock()
    falso.estado.return_value = estado_disponible()
    falso.ejecutar.return_value = ResultadoBackend(
        salida="PRUEBAS SIMULADAS", codigo_retorno=0,
        aislamiento_verificado=True, limpieza_verificada=True,
    )
    monkeypatch.setattr(sandbox, "obtener_backend", lambda: falso)
    return falso


@pytest.fixture(autouse=True)
def sin_procesos_host(monkeypatch):
    # Todos los tests, incluidos los dobles de backend, deben respetar esto.
    import subprocess
    for nombre in ["Popen", "run", "call", "check_call", "check_output"]:
        monkeypatch.setattr(subprocess, nombre, Mock(side_effect=AssertionError("Proceso host prohibido")))


def test_sintaxis_valida():
    assert sandbox.verificar_sintaxis("x = 1 + 1") == (True, None)


def test_sintaxis_invalida():
    assert "Línea" in sandbox.verificar_sintaxis("def rota(:")[1]


@pytest.mark.parametrize("codigo", [None, "x\x00", "x" * (sandbox.LIMITE_ARCHIVO + 1)])
def test_sintaxis_rechaza_entradas_invalidas(codigo):
    assert sandbox.verificar_sintaxis(codigo)[0] is False


def test_extraer_codigo_con_fences():
    assert sandbox.extraer_codigo("texto\n```python\nprint('hola')\n```\nfin") == "print('hola')"


def test_extraer_codigo_sin_fences():
    assert sandbox.extraer_codigo("  x = 1  ") == "x = 1"


@pytest.mark.parametrize("sistema", ["Windows", "Linux", "Darwin", "Desconocido"])
def test_rechazo_sin_backend_en_cualquier_plataforma(monkeypatch, sistema, tmp_path):
    monkeypatch.setattr(sandbox, "obtener_backend", lambda: SinAislamiento(sistema))
    testigo = tmp_path / "NO_DEBE_EXISTIR"
    codigo = f"from pathlib import Path\nPath({str(testigo)!r}).write_text('fallo')"
    resultado = sandbox.ejecutar_codigo(codigo)
    assert resultado["etapa"] == "aislamiento_no_disponible"
    assert resultado["exito"] is False
    assert sistema in resultado["errores"]
    assert not testigo.exists()


def test_backend_directo_tambien_rechaza():
    with pytest.raises(RuntimeError, match="No hay un backend"):
        SinAislamiento("Windows").ejecutar(None)


def test_una_garantia_faltante_bloquea(monkeypatch):
    falso = Mock()
    falso.estado.return_value = EstadoBackend("incompleto", archivos_aislados=True)
    monkeypatch.setattr(sandbox, "obtener_backend", lambda: falso)
    assert not sandbox.ejecutar_codigo("x = 1")["exito"]
    falso.ejecutar.assert_not_called()


def test_fallo_de_inspeccion_bloquea(backend):
    backend.estado.side_effect = OSError("runtime ausente")
    assert sandbox.ejecutar_codigo("x = 1")["etapa"] == "aislamiento_no_disponible"
    backend.ejecutar.assert_not_called()


def test_sin_red_no_es_optativo(backend):
    assert sandbox.ejecutar_codigo("x = 1", bloquear_red=False)["etapa"] == "politica_aislamiento"
    backend.ejecutar.assert_not_called()


def test_ejecutar_codigo_contrato_y_limpieza(backend):
    entradas = []
    def inspeccionar(solicitud):
        entradas.append(solicitud)
        assert solicitud.operacion == "script"
        assert solicitud.carpeta_entrada.joinpath("codigo.py").read_text() == "x = 1"
        assert solicitud.limite_salida == 8000
        assert solicitud.limite_memoria == sandbox.LIMITE_MEMORIA
        return ResultadoBackend(codigo_retorno=0, aislamiento_verificado=True, limpieza_verificada=True)
    backend.ejecutar.side_effect = inspeccionar
    assert sandbox.ejecutar_codigo("x = 1")["exito"]
    assert not entradas[0].carpeta_entrada.exists()


def test_ejecutar_codigo_error_de_sintaxis_no_llega_al_backend(backend):
    assert sandbox.ejecutar_codigo("def rota(:")["etapa"] == "sintaxis"
    backend.ejecutar.assert_not_called()


@pytest.mark.parametrize("resultado,etapa", [
    (ResultadoBackend(codigo_retorno=1, errores="error simulado", aislamiento_verificado=True, limpieza_verificada=True), "ejecucion"),
    (ResultadoBackend(timeout=True, aislamiento_verificado=True, limpieza_verificada=True), "timeout"),
    (ResultadoBackend(codigo_retorno=0), "aislamiento_no_disponible"),
    (ResultadoBackend(codigo_retorno=0, aislamiento_verificado=True), "aislamiento_no_disponible"),
])
def test_no_confunde_codigo_cero_con_seguridad(backend, resultado, etapa):
    backend.ejecutar.return_value = resultado
    assert sandbox.ejecutar_codigo("x = 1")["etapa"] == etapa


def test_fallo_de_runtime_no_reintenta_en_host(backend):
    backend.ejecutar.side_effect = OSError("desconectado")
    assert sandbox.ejecutar_codigo("x = 1")["etapa"] == "aislamiento_no_disponible"
    assert backend.ejecutar.call_count == 1


@pytest.mark.parametrize("timeout", [0, -1, 301, True, "15"])
def test_limites_invalidos_no_se_despachan(backend, timeout):
    assert sandbox.ejecutar_codigo("x = 1", timeout=timeout)["etapa"] == "solicitud_invalida"
    backend.ejecutar.assert_not_called()


def test_probar_codigo_transfiere_tests_como_datos(backend):
    def inspeccionar(solicitud):
        assert solicitud.operacion == "pytest"
        assert (solicitud.carpeta_entrada / "test_solucion.py").read_text() == "assert True"
        return ResultadoBackend(codigo_retorno=0, aislamiento_verificado=True, limpieza_verificada=True)
    backend.ejecutar.side_effect = inspeccionar
    assert sandbox.probar_codigo("x = 1", "assert True")["exito"]


def test_probar_codigo_falla(backend):
    backend.ejecutar.return_value = ResultadoBackend(codigo_retorno=1, aislamiento_verificado=True, limpieza_verificada=True)
    assert sandbox.probar_codigo("x = 1", "assert False")["etapa"] == "pruebas"


def test_suite_y_conftest_se_bloquean_antes_de_copiar(monkeypatch):
    copiar = Mock(side_effect=AssertionError("no debe copiar"))
    monkeypatch.setattr(sandbox, "_copiar_proyecto", copiar)
    assert sandbox.probar_proyecto()["etapa"] == "aislamiento_no_disponible"
    assert sandbox.probar_codigo("x = 1", "assert True")["etapa"] == "aislamiento_no_disponible"
    copiar.assert_not_called()


def test_cambio_bueno_se_prueba_sobre_copia(backend, tmp_path):
    original = tmp_path / "modulo.py"
    original.write_text("x = 1")
    def inspeccionar(solicitud):
        assert (solicitud.carpeta_entrada / "modulo.py").read_text() == "x = 2"
        return ResultadoBackend(codigo_retorno=0, aislamiento_verificado=True, limpieza_verificada=True)
    backend.ejecutar.side_effect = inspeccionar
    assert sandbox.probar_cambio_en_proyecto("modulo.py", "x = 2", str(tmp_path))["exito"]
    assert original.read_text() == "x = 1"


def test_cambio_malo_no_toca_el_original(backend, tmp_path):
    original = tmp_path / "modulo.py"
    original.write_text("x = 1")
    backend.ejecutar.return_value = ResultadoBackend(codigo_retorno=1, aislamiento_verificado=True, limpieza_verificada=True)
    assert not sandbox.probar_cambio_en_proyecto("modulo.py", "x = 2", str(tmp_path))["exito"]
    assert original.read_text() == "x = 1"


def test_cambio_con_sintaxis_rota_no_despacha(backend, tmp_path):
    assert sandbox.probar_cambio_en_proyecto("modulo.py", "def rota(:", str(tmp_path))["etapa"] == "sintaxis"
    backend.ejecutar.assert_not_called()


@pytest.mark.parametrize("archivo", ["../fuera.py", "sub/../../fuera.py", "archivo.txt"])
def test_archivo_fuera_del_proyecto_se_rechaza(tmp_path, archivo):
    assert sandbox.probar_cambio_en_proyecto(archivo, "x = 1", str(tmp_path))["etapa"] == "fuera_del_proyecto"


def test_no_copia_secretos_o_estado(tmp_path):
    origen = tmp_path / "origen"
    origen.mkdir()
    for nombre in ["modulo.py", ".env", ".env.py", "private_key.pem", "memory.json", "dataset.jsonl"]:
        (origen / nombre).write_text("dato sintético")
    (origen / "sesiones").mkdir()
    (origen / "sesiones" / "oculto.py").write_text("x = 1")
    copia = Path(sandbox._copiar_proyecto(origen, tmp_path))
    assert [p.name for p in copia.iterdir()] == ["modulo.py"]


def test_symlink_no_se_copia_ni_se_modifica(tmp_path):
    origen = tmp_path / "origen"
    origen.mkdir()
    fuera = tmp_path / "fuera.py"
    fuera.write_text("x = 1")
    try:
        (origen / "enlace.py").symlink_to(fuera)
    except OSError:
        pytest.skip("Requiere privilegio de enlaces o Developer Mode en Windows")
    with pytest.raises(ValueError):
        sandbox._copiar_proyecto(origen, tmp_path)
    assert sandbox.probar_cambio_en_proyecto("enlace.py", "x = 2", str(origen))["etapa"] == "fuera_del_proyecto"
    assert fuera.read_text() == "x = 1"


def test_copia_limita_tamano(tmp_path, monkeypatch):
    origen = tmp_path / "origen"
    origen.mkdir()
    (origen / "grande.py").write_text("x = 1")
    monkeypatch.setattr(sandbox, "LIMITE_COPIA", 1)
    with pytest.raises(ValueError, match="límites"):
        sandbox._copiar_proyecto(origen, tmp_path)


def test_crear_y_probar_no_consulta_llm_sin_aislamiento():
    llm = Mock(side_effect=AssertionError("No consultar modelo"))
    resultado = sandbox.crear_y_probar("sumar", llm)
    assert resultado["resultado"]["etapa"] == "aislamiento_no_disponible"
    assert resultado["intentos"] == 0
    llm.assert_not_called()


def test_crear_y_probar_corrige_tras_un_error(backend):
    backend.ejecutar.side_effect = [
        ResultadoBackend(codigo_retorno=1, aislamiento_verificado=True, limpieza_verificada=True),
        ResultadoBackend(codigo_retorno=0, salida="SIMULADO", aislamiento_verificado=True, limpieza_verificada=True),
    ]
    resultado = sandbox.crear_y_probar("sumar", lambda p: "x = 1")
    assert resultado["exito"]
    assert resultado["intentos"] == 2


def test_crear_y_probar_se_rinde_tras_max_intentos(backend):
    backend.ejecutar.return_value = ResultadoBackend(codigo_retorno=1, aislamiento_verificado=True, limpieza_verificada=True)
    assert sandbox.crear_y_probar("sumar", lambda p: "x = 1", max_intentos=2)["intentos"] == 2


def test_no_insiste_en_llm_si_se_pierde_aislamiento(backend):
    backend.ejecutar.side_effect = OSError("runtime perdido")
    llm = Mock(return_value="x = 1")
    assert sandbox.crear_y_probar("sumar", llm)["intentos"] == 1
    assert llm.call_count == 1


def test_guardar_codigo_validado_rechaza_sin_pruebas(tmp_path):
    with pytest.raises(RuntimeError, match="No hay un backend"):
        sandbox.guardar_codigo_validado("x = 1", carpeta=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_guardar_codigo_validado(backend, tmp_path):
    ruta = sandbox.guardar_codigo_validado("x = 1", descripcion="saludar\nx = 'no inyectar'", carpeta=str(tmp_path))
    assert Path(ruta).read_text().endswith("\nx = 1\n")
    assert "\n# x = 'no inyectar'" in Path(ruta).read_text()
    backend.ejecutar.assert_called_once()


def test_import_portable_no_requiere_resource(monkeypatch):
    importar = builtins.__import__
    def bloquear(nombre, *args, **kwargs):
        if nombre == "resource":
            raise AssertionError("Dependencia POSIX en ruta portable")
        return importar(nombre, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", bloquear)
    importlib.reload(sandbox)
    assert not sandbox.estado_aislamiento().disponible


def test_banderas_de_entorno_no_habilitan_ejecucion(monkeypatch):
    monkeypatch.setenv("BRIDGET_SANDBOX_BACKEND", "subprocess")
    monkeypatch.setenv("BRIDGET_ALLOW_UNSAFE", "1")
    assert not sandbox.estado_aislamiento().disponible


def test_no_acepta_garantias_con_valores_truthy():
    estado = EstadoBackend("incorrecto", archivos_aislados="sí", red_bloqueada=True,
                           recursos_limitados=True, procesos_controlados=True,
                           entorno_sin_secretos=True)
    assert not estado.disponible


def test_aceptar_salida_tambien_requiere_tipos_validos(backend):
    backend.ejecutar.return_value = ResultadoBackend(codigo_retorno=0, salida=None,
                                                    aislamiento_verificado=True, limpieza_verificada=True)
    assert sandbox.ejecutar_codigo("x = 1")["etapa"] == "aislamiento_no_disponible"


def test_recomprueba_disponibilidad_antes_de_despachar(backend):
    backend.estado.side_effect = [estado_disponible(), EstadoBackend("perdido", "runtime detenido")]
    assert sandbox.ejecutar_codigo("x = 1")["etapa"] == "aislamiento_no_disponible"
    backend.ejecutar.assert_not_called()


def test_salida_de_backend_tiene_limite(backend):
    backend.ejecutar.return_value = ResultadoBackend(
        salida="x" * 20000, errores="y" * 20000, codigo_retorno=1,
        aislamiento_verificado=True, limpieza_verificada=True,
    )
    resultado = sandbox.ejecutar_codigo("x = 1")
    assert len(resultado["salida"]) == sandbox.LIMITE_SALIDA
    assert len(resultado["errores"]) == sandbox.LIMITE_SALIDA
