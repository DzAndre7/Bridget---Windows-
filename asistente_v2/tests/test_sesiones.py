"""Tests de la persistencia de sesiones (core/sesiones.py) y de su
integración con procesar_comando. Todo contra un directorio temporal:
no se tocan las sesiones reales.
"""
import json
import os

import pytest

import core.brain as brain
from core import sesiones


@pytest.fixture(autouse=True)
def dir_temporal(tmp_path, monkeypatch):
    """Redirige TODO el módulo de sesiones a tmp_path."""
    monkeypatch.setattr(sesiones, "DIR_SESIONES", str(tmp_path / "sesiones"))
    return tmp_path


def test_guardar_y_cargar_roundtrip():
    sesion = sesiones.abrir_sesion(nombre="prueba")
    sesion.historial.append({"role": "user", "content": "hola"})
    sesion.historial.append({"role": "assistant", "content": "buenas"})
    assert sesiones.guardar(sesion)

    recuperada = sesiones.cargar(sesion.id)
    assert recuperada is not None
    assert recuperada.nombre == "prueba"
    assert recuperada.historial[-1]["content"] == "buenas"


def test_sesion_nueva_recuerda_a_la_anterior():
    primera = sesiones.abrir_sesion()
    primera.historial.append({"role": "user", "content": "hablamos de milanesas"})
    primera.historial.append({"role": "assistant", "content": "ricas las milanesas"})
    sesiones.guardar(primera)

    segunda = sesiones.abrir_sesion(assistant_name="Bridget")
    assert segunda.id != primera.id
    # el modelo recibe el digest de la charla pasada...
    assert "milanesas" in segunda.contexto_anterior
    assert "Bridget:" in segunda.contexto_anterior
    # ...y la UI recibe los mensajes tal cual para mostrarlos
    assert segunda.historial_anterior[-1]["content"] == "ricas las milanesas"
    # pero el historial PROPIO arranca vacío: es un chat nuevo
    assert segunda.historial == []


def test_sesion_vacia_no_cuenta_como_anterior():
    sesiones.abrir_sesion()  # sin mensajes
    segunda = sesiones.abrir_sesion()
    assert segunda.contexto_anterior == ""
    assert segunda.historial_anterior == []


def test_contexto_anterior_entra_al_system_prompt(monkeypatch):
    monkeypatch.setattr(brain, "leer_recuerdos", lambda: [])
    monkeypatch.setattr(brain, "recordar", lambda *a, **k: [])
    monkeypatch.setattr(brain.cerebro, "consultar_cerebro", lambda *a, **k: [])

    sesion = brain.Sesion()
    sesion.contexto_anterior = "Usuario: hablamos de milanesas"
    sistema = brain._preparar_sistema("hola", sesion)
    assert "CONVERSACIÓN ANTERIOR" in sistema
    assert "milanesas" in sistema


def test_procesar_comando_persiste_turnos_deterministicos():
    sesion = sesiones.abrir_sesion()
    respuesta = brain.procesar_comando("qué hora es", "Bridget", sesion)
    assert "Son las" in respuesta

    guardada = sesiones.cargar(sesion.id)
    assert guardada.historial[-2]["content"] == "qué hora es"
    assert "Son las" in guardada.historial[-1]["content"]


def test_sesion_sin_id_no_toca_disco():
    sesion = brain.Sesion()  # efímera, como en los tests de siempre
    brain.procesar_comando("qué hora es", "Bridget", sesion)
    assert sesiones.listar() == []


def test_listar_ordena_por_actualizacion():
    a = sesiones.abrir_sesion(nombre="a")
    a.historial.append({"role": "user", "content": "1"})
    sesiones.guardar(a)
    b = sesiones.abrir_sesion(nombre="b")
    b.historial.append({"role": "user", "content": "2"})
    sesiones.guardar(b)

    listado = sesiones.listar()
    assert listado[0]["nombre"] == "b"  # la más reciente primero
    assert all(s["mensajes"] >= 0 for s in listado)


def test_cargar_o_crear_sanea_ids_peligrosos():
    sesion = sesiones.cargar_o_crear("../../../etc/passwd")
    assert "/" not in sesion.id and ".." not in sesion.id
    # y es persistente: la segunda vez retoma la misma
    sesion.historial.append({"role": "user", "content": "hola"})
    sesiones.guardar(sesion)
    misma = sesiones.cargar_o_crear("../../../etc/passwd")
    assert misma.id == sesion.id
    assert misma.historial[-1]["content"] == "hola"


def test_digest_trunca_mensajes_largos():
    historial = [{"role": "assistant", "content": "x" * 1000}]
    digest = sesiones._digest(historial, "Bridget")
    assert len(digest) <= sesiones.MAX_CHARS_DIGEST
    assert "…" in digest


# ---------- indexado de charlas a memoria semántica ----------

def test_indexar_charla_resume_y_guarda(monkeypatch):
    guardados = []
    monkeypatch.setattr(
        sesiones.memoria_semantica, "guardar_recuerdo",
        lambda texto, categoria="charla": guardados.append((texto, categoria)) or True,
    )
    previa = sesiones.abrir_sesion(nombre="a indexar")
    previa.creada = "2026-07-12T20:00:00"
    for i in range(3):
        previa.historial.append({"role": "user", "content": f"hablemos de milanesas {i}"})
        previa.historial.append({"role": "assistant", "content": "ricas"})
    sesiones.guardar(previa)

    ok = sesiones.indexar_charla(previa, lambda p: "Hablaron de milanesas.", "Bridget")
    assert ok
    texto, categoria = guardados[0]
    assert categoria == "charla"
    assert "2026-07-12" in texto and "milanesas" in texto
    # quedó marcada: no se vuelve a indexar en el próximo arranque
    assert sesiones._ya_indexada(previa.id)


def test_charlas_cortas_no_se_indexan(monkeypatch):
    def no_debe_llamarse(p):
        raise AssertionError("dos intercambios no ameritan resumen")

    previa = sesiones.abrir_sesion()
    previa.historial.append({"role": "user", "content": "hola"})
    previa.historial.append({"role": "assistant", "content": "buenas"})
    sesiones.guardar(previa)
    assert sesiones.indexar_charla(previa, no_debe_llamarse) is False


def test_abrir_sesion_sin_funcion_llm_no_indexa(monkeypatch):
    def no_debe_llamarse(*a, **k):
        raise AssertionError("sin funcion_llm no hay indexado")

    monkeypatch.setattr(sesiones, "indexar_charla", no_debe_llamarse)
    previa = sesiones.abrir_sesion()
    for i in range(3):
        previa.historial.append({"role": "user", "content": f"tema {i}"})
        previa.historial.append({"role": "assistant", "content": "ok"})
    sesiones.guardar(previa)
    sesiones.abrir_sesion()  # sin funcion_llm: no debe tocar el indexador


# ---------- rotación de sesiones de la API (refrescar_si_vieja) ----------

class _HiloInmediato:
    """Reemplazo de threading.Thread que corre el target en el acto:
    los tests no quieren carreras con hilos de fondo."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_refrescar_si_vieja_rota_e_indexa(monkeypatch):
    monkeypatch.setattr(sesiones.threading, "Thread", _HiloInmediato)
    guardados = []
    monkeypatch.setattr(
        sesiones.memoria_semantica, "guardar_recuerdo",
        lambda texto, categoria="charla": guardados.append(texto) or True,
    )

    sesion = sesiones.abrir_sesion(nombre="remota")
    for i in range(3):
        sesion.historial.append({"role": "user", "content": f"hablamos de asado {i}"})
        sesion.historial.append({"role": "assistant", "content": "rico el asado"})
    sesiones.guardar(sesion)
    sesion.actualizada = "2026-07-01T10:00:00"  # quedó vieja hace días

    roto = sesiones.refrescar_si_vieja(sesion, funcion_llm=lambda p: "Charlaron de asado.")
    assert roto is True
    # la charla vieja quedó como memoria...
    assert "asado" in sesion.contexto_anterior
    assert sesion.historial_anterior[-1]["content"] == "rico el asado"
    assert guardados and "asado" in guardados[0]
    # ...y el historial arranca de cero
    assert sesion.historial == []


def test_refrescar_si_vieja_respeta_charlas_recientes():
    sesion = sesiones.abrir_sesion(nombre="remota-activa")
    sesion.historial.append({"role": "user", "content": "hola"})
    sesiones.guardar(sesion)  # actualizada = ahora

    assert sesiones.refrescar_si_vieja(sesion) is False
    assert sesion.historial  # intacto


def test_memoria_de_charla_anterior_sobrevive_al_reinicio():
    sesion = sesiones.abrir_sesion(nombre="con-memoria")
    sesion.contexto_anterior = "Usuario: hablamos de milanesas"
    sesion.historial_anterior = [{"role": "user", "content": "hablamos de milanesas"}]
    sesiones.guardar(sesion)

    recargada = sesiones.cargar(sesion.id)
    assert "milanesas" in recargada.contexto_anterior
    assert recargada.historial_anterior[0]["content"] == "hablamos de milanesas"
