"""Tests de core/preferences.py: guardado/lectura de preferencias en disco.

Existen porque el único caller real (core.brain._cmd_guardar_preferencia,
vía core.intenciones.extraer_preferencia) pasa `valor` como STRING, no
como dict — sin un test que ejercite esto, una mejora que exigiera dict
se hubiera colado igual que pasó con la propuesta descartada
20260712_161207.
"""
import json

import pytest

from core import preferences


@pytest.fixture(autouse=True)
def archivo_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "PREFERENCES_FILE", str(tmp_path / "preferences.json"))


def test_cargar_preferencias_sin_archivo_devuelve_vacio():
    assert preferences.cargar_preferencias() == {}


def test_guardar_y_obtener_preferencia_con_string():
    # así la llama brain.py de verdad: "uso opera como navegador"
    assert preferences.guardar_preferencia("navegador", "opera") is True
    assert preferences.obtener_preferencia("navegador") == "opera"


def test_guardar_preferencia_persiste_en_disco():
    preferences.guardar_preferencia("editor", "vim")
    with open(preferences.PREFERENCES_FILE, encoding="utf-8") as f:
        datos = json.load(f)
    assert datos == {"editor": "vim"}


def test_obtener_preferencia_inexistente_devuelve_none():
    assert preferences.obtener_preferencia("algo_que_no_existe") is None


def test_guardar_preferencia_sobrescribe_el_mismo_tipo():
    preferences.guardar_preferencia("navegador", "opera")
    preferences.guardar_preferencia("navegador", "firefox")
    assert preferences.obtener_preferencia("navegador") == "firefox"


def test_cargar_preferencias_con_json_corrupto_no_explota(tmp_path, monkeypatch):
    archivo = tmp_path / "otro.json"
    archivo.write_text("{esto no es json valido", encoding="utf-8")
    monkeypatch.setattr(preferences, "PREFERENCES_FILE", str(archivo))
    assert preferences.cargar_preferencias() == {}


def test_guardar_preferencia_si_falla_la_escritura_devuelve_false(tmp_path, monkeypatch):
    ruta_invalida = tmp_path / "carpeta_que_no_existe" / "preferences.json"
    monkeypatch.setattr(preferences, "PREFERENCES_FILE", str(ruta_invalida))
    assert preferences.guardar_preferencia("navegador", "opera") is False
