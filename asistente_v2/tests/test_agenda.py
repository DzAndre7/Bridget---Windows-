"""Tests de la agenda (core/agenda.py): almacenamiento, extracción de
fecha/hora con LLM falso, búsqueda para cancelar y el avisador (una pasada,
sin hilos). Todo contra un archivo temporal.
"""
from datetime import datetime

import pytest

from core import agenda, intenciones


@pytest.fixture(autouse=True)
def agenda_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(agenda, "AGENDA_FILE", str(tmp_path / "agenda.json"))


AHORA = datetime(2026, 7, 13, 15, 0)


# ---------- almacenamiento ----------

def test_agendar_y_listar_pendientes():
    agenda.agendar("llamar al médico", datetime(2026, 7, 14, 9, 0))
    agenda.agendar("comprar pan", datetime(2026, 7, 13, 18, 0))
    textos = [r["texto"] for r in agenda.pendientes()]
    # ordenados del más próximo al más lejano
    assert textos == ["comprar pan", "llamar al médico"]


def test_vencidos_y_marcar_avisado():
    item = agenda.agendar("ya pasó", datetime(2026, 7, 13, 14, 0))
    agenda.agendar("todavía no", datetime(2026, 7, 14, 9, 0))
    vencidos = agenda.vencidos(AHORA)
    assert [r["texto"] for r in vencidos] == ["ya pasó"]

    agenda.marcar_avisado(item["id"])
    assert agenda.vencidos(AHORA) == []
    # el que no venció sigue pendiente
    assert [r["texto"] for r in agenda.pendientes()] == ["todavía no"]


def test_cancelar_por_id():
    item = agenda.agendar("borrable", datetime(2026, 7, 14, 9, 0))
    assert agenda.cancelar(item["id"]) is True
    assert agenda.pendientes() == []
    assert agenda.cancelar("no-existe") is False


def test_buscar_ignora_las_palabras_del_pedido():
    agenda.agendar("llamar al médico", datetime(2026, 7, 14, 9, 0))
    agenda.agendar("comprar pan", datetime(2026, 7, 14, 10, 0))
    resultado = agenda.buscar("cancelá el recordatorio del médico")
    assert [r["texto"] for r in resultado] == ["llamar al médico"]
    # "cancelá el recordatorio" solo, sin tema, no matchea todo
    assert agenda.buscar("cancelá el recordatorio") == []


# ---------- extracción con LLM ----------

def test_extraer_recordatorio_parsea_el_formato():
    respuesta = "FECHA: 2026-07-14 09:00\nTEXTO: llamar al médico"
    que, cuando = agenda.extraer_recordatorio(
        "recordame mañana a las 9 llamar al médico", lambda p: respuesta, ahora=AHORA
    )
    assert que == "llamar al médico"
    assert cuando == datetime(2026, 7, 14, 9, 0)


def test_extraer_recordatorio_sin_fecha():
    que, cuando = agenda.extraer_recordatorio(
        "recordame comprar pan", lambda p: "SIN_FECHA", ahora=AHORA
    )
    assert (que, cuando) == (None, None)


def test_extraer_recordatorio_rechaza_fechas_pasadas():
    respuesta = "FECHA: 2026-07-12 09:00\nTEXTO: algo de ayer"
    que, cuando = agenda.extraer_recordatorio("x", lambda p: respuesta, ahora=AHORA)
    assert (que, cuando) == (None, None)


def test_extraer_recordatorio_llm_roto_no_lanza():
    def llm_roto(p):
        raise ConnectionError("ollama caído")

    assert agenda.extraer_recordatorio("x", llm_roto, ahora=AHORA) == (None, None)


def test_el_prompt_lleva_la_fecha_de_referencia():
    capturado = {}

    def llm_espia(p):
        capturado["prompt"] = p
        return "SIN_FECHA"

    agenda.extraer_recordatorio("recordame algo", llm_espia, ahora=AHORA)
    assert "2026-07-13" in capturado["prompt"]
    assert "15:00" in capturado["prompt"]


# ---------- avisador (una pasada, sin hilos) ----------

def test_revisar_y_avisar_avisa_una_sola_vez():
    agenda.agendar("tomar la pastilla", datetime(2026, 7, 13, 14, 30))
    avisos = []
    assert agenda.revisar_y_avisar(avisar=avisos.append, ahora=AHORA) == 1
    assert avisos == ["Recordatorio: tomar la pastilla"]
    # segunda pasada: ya está avisado, no repite
    assert agenda.revisar_y_avisar(avisar=avisos.append, ahora=AHORA) == 0


# ---------- intenciones de agenda ----------

def test_recordame_es_crear_recordatorio():
    assert intenciones.detectar_intencion("recordame mañana llamar al medico") == "crear_recordatorio"


def test_recorda_que_sigue_siendo_memoria():
    assert intenciones.detectar_intencion("recorda que me gusta el mate") == "guardar_recuerdo"


def test_que_tengo_agendado_lista():
    assert intenciones.detectar_intencion("que tengo agendado para hoy") == "listar_recordatorios"


def test_cancelar_recordatorio():
    assert intenciones.detectar_intencion("cancela el recordatorio del medico") == "cancelar_recordatorio"
