"""Tests de la memoria proactiva (core/memoria_auto.py). Sin modelo real ni
embeddings: el LLM entra como función falsa (mismo patrón que los tests de
intenciones) y la memoria semántica se monkeypatchea.
"""
import pytest

from core import memoria_auto


# ---------- nivel 1: heurística ----------

def test_heuristica_detecta_datos_personales():
    assert memoria_auto.parece_dato_personal("me llamo usuario de prueba")
    assert memoria_auto.parece_dato_personal("Me gusta el mate amargo")
    assert memoria_auto.parece_dato_personal("tengo 20 años")
    assert memoria_auto.parece_dato_personal("mi hermana se llama ana")


def test_heuristica_ignora_charla_neutra():
    assert not memoria_auto.parece_dato_personal("qué hora es")
    assert not memoria_auto.parece_dato_personal("contame un chiste")
    assert not memoria_auto.parece_dato_personal("buscá el clima en internet")


def test_me_gustaria_no_es_me_gusta():
    # "me gustaría mejorar mi inglés" es un deseo pasajero, no un gusto:
    # el límite de palabra evita que "gusta" matchee adentro de "gustaría"
    assert not memoria_auto.parece_dato_personal("me gustaría salir más temprano")


# ---------- nivel 2: extracción con LLM ----------

def test_extraer_dato_devuelve_el_dato():
    dato = memoria_auto.extraer_dato(
        "me gusta el mate", lambda p: "El usuario toma mate amargo"
    )
    assert dato == "El usuario toma mate amargo"


def test_extraer_dato_nada_devuelve_none():
    assert memoria_auto.extraer_dato("tengo una duda", lambda p: "NADA") is None


def test_extraer_dato_respuesta_larga_se_descarta():
    assert memoria_auto.extraer_dato("tengo sueño", lambda p: "bla " * 100) is None


# ---------- pipeline completo con dedupe ----------

def test_procesar_turno_guarda_dato_nuevo(monkeypatch):
    guardados = []
    monkeypatch.setattr(memoria_auto.memoria_semantica, "cargar_memoria", lambda: [])
    monkeypatch.setattr(
        memoria_auto.memoria_semantica, "guardar_recuerdo",
        lambda texto, categoria="auto": guardados.append(texto) or True,
    )
    assert memoria_auto.procesar_turno(
        "me gusta el mate", lambda p: "El usuario toma mate"
    )
    assert guardados == ["El usuario toma mate"]


def test_procesar_turno_no_duplica(monkeypatch):
    memoria_falsa = [{"texto": "El usuario toma mate", "embedding": [1.0, 0.0]}]
    monkeypatch.setattr(
        memoria_auto.memoria_semantica, "cargar_memoria", lambda: memoria_falsa
    )
    monkeypatch.setattr(
        memoria_auto.memoria_semantica, "obtener_embedding",
        lambda texto, tipo="document": [1.0, 0.0],
    )
    guardados = []
    monkeypatch.setattr(
        memoria_auto.memoria_semantica, "guardar_recuerdo",
        lambda texto, categoria="auto": guardados.append(texto) or True,
    )
    assert not memoria_auto.procesar_turno(
        "me gusta el mate", lambda p: "El usuario toma mate"
    )
    assert guardados == []


def test_procesar_turno_charla_neutra_no_llama_al_llm():
    def llm_que_no_debe_llamarse(prompt):
        raise AssertionError("charla neutra no debería llegar al modelo")

    assert memoria_auto.procesar_turno("qué hora es", llm_que_no_debe_llamarse) is False


def test_procesar_turno_nunca_lanza():
    def llm_roto(prompt):
        raise ConnectionError("ollama caído")

    assert memoria_auto.procesar_turno("me gusta el mate", llm_roto) is False
