"""Tests de la matemática de core/memoria_semantica.py (sin llamar a ollama).

Fijan la correctitud de `similitud` para que cualquier reimplementación
(numpy, cache, etc.) siga dando los mismos resultados."""
import math
import core.memoria_semantica as ms


def test_similitud_identicos_es_1():
    v = [0.1, 0.2, 0.3, 0.4]
    assert abs(ms.similitud(v, v) - 1.0) < 1e-9

def test_similitud_ortogonales_es_0():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(ms.similitud(a, b) - 0.0) < 1e-9

def test_similitud_opuestos_es_menos_1():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(ms.similitud(a, b) - (-1.0)) < 1e-9

def test_similitud_valor_conocido():
    # coseno entre (1,1) y (1,0) = 1/sqrt(2)
    a = [1.0, 1.0]
    b = [1.0, 0.0]
    assert abs(ms.similitud(a, b) - (1 / math.sqrt(2))) < 1e-9

def test_recordar_sin_memoria_devuelve_vacio(monkeypatch):
    # si el archivo de memoria no existe, no debe llamar a ollama ni romper
    monkeypatch.setattr(ms, "cargar_memoria", lambda: [])
    assert ms.recordar("cualquier cosa") == []
