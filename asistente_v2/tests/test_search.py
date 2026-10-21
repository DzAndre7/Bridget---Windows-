"""Tests de la búsqueda web (core/search.py). DDGS se reemplaza por un doble
falso porque no hay red en el sandbox ni en CI — pero el motivo real de
estos tests es de cobertura: la propuesta descartada 20260714_214417
(usaba `urllib` sin importarlo) pasó los 154 tests existentes sin
problema porque ninguno llamaba a buscar_web() ni a formatear_resultados()
con una ejecución real.
"""
from core import search


class _DDGSFalso:
    """Copia el protocolo de contexto de ddgs.DDGS: `with DDGS() as ddgs`."""

    def __init__(self, resultados=None, excepcion=None):
        self._resultados = resultados or []
        self._excepcion = excepcion

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def text(self, consulta, region, max_results):
        if self._excepcion:
            raise self._excepcion
        return self._resultados[:max_results]


def test_buscar_web_devuelve_resultados_normalizados(monkeypatch):
    crudos = [
        {"title": "Título 1", "href": "http://a.com", "body": "resumen 1"},
        {"title": "Título 2", "href": "http://b.com", "body": "resumen 2"},
    ]
    monkeypatch.setattr(search, "DDGS", lambda: _DDGSFalso(crudos))

    resultados = search.buscar_web("clima en buenos aires")

    assert resultados == [
        {"titulo": "Título 1", "url": "http://a.com", "snippet": "resumen 1"},
        {"titulo": "Título 2", "url": "http://b.com", "snippet": "resumen 2"},
    ]


def test_buscar_web_respeta_max_resultados(monkeypatch):
    crudos = [{"title": f"t{i}", "href": "", "body": ""} for i in range(5)]
    monkeypatch.setattr(search, "DDGS", lambda: _DDGSFalso(crudos))

    resultados = search.buscar_web("algo", max_resultados=2)

    assert len(resultados) == 2


def test_buscar_web_si_falla_devuelve_lista_vacia_no_string(monkeypatch):
    monkeypatch.setattr(search, "DDGS", lambda: _DDGSFalso(excepcion=RuntimeError("sin red")))

    resultados = search.buscar_web("algo")

    # tiene que ser lista: formatear_resultados() la itera asumiendo dicts
    assert resultados == []


def test_formatear_resultados_vacio():
    assert search.formatear_resultados([]) == "No encontré información en internet."


def test_formatear_resultados_con_datos():
    resultados = [
        {"titulo": "Uno", "url": "http://a", "snippet": "primer resumen"},
        {"titulo": "Dos", "url": "http://b", "snippet": "segundo resumen"},
    ]

    texto = search.formatear_resultados(resultados)

    assert "1. Uno" in texto
    assert "primer resumen" in texto
    assert "2. Dos" in texto


def test_pipeline_completo_ante_un_fallo_no_rompe(monkeypatch):
    """El caso que rompía la propuesta descartada: buscar_web() falla, y su
    resultado se le pasa directo a formatear_resultados() en
    core/brain.py::_cmd_buscar_web. El pipeline completo no debe explotar."""
    monkeypatch.setattr(search, "DDGS", lambda: _DDGSFalso(excepcion=RuntimeError("sin red")))

    resultados = search.buscar_web("algo")
    texto = search.formatear_resultados(resultados)

    assert texto == "No encontré información en internet."
