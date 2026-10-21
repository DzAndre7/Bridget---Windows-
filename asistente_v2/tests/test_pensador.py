"""Tests de la ruta híbrida de pensamiento (core/pensador.py y su manejador
en brain). Sin red ni Groq real: se monkeypatchea la consulta.
"""
import pytest

import core.brain as brain
from core import pensador, intenciones


# ---------- intención ----------

def test_pensalo_bien_va_al_modelo_grande():
    assert intenciones.detectar_intencion("pensalo bien antes de responder") == "pensar_profundo"


def test_pensar_comun_no_dispara_la_ruta():
    assert intenciones.detectar_intencion("estaba pensando en vos") == "desconocida"


# ---------- pensador ----------

def test_sin_api_key_devuelve_none(monkeypatch):
    monkeypatch.setattr(pensador, "GROQ_API_KEY", None)
    assert pensador.pensar_profundo("¿qué es la conciencia?") is None


def test_mensajes_llevan_contexto_reciente():
    historial = [{"role": "user", "content": "hola"},
                 {"role": "assistant", "content": "buenas"},
                 {"role": "sistema-raro", "content": "esto no va"}]
    mensajes = pensador._mensajes("¿y entonces?", historial)
    assert mensajes[0]["role"] == "system"
    assert mensajes[-1] == {"role": "user", "content": "¿y entonces?"}
    roles = [m["role"] for m in mensajes]
    assert "sistema-raro" not in roles  # solo user/assistant del historial


# ---------- manejador: explícito vs derivación automática ----------

def test_respuesta_del_grande_entra_al_historial(monkeypatch):
    monkeypatch.setattr(brain.pensador, "pensar_profundo",
                        lambda pregunta, historial=None, extenso=True: "respuesta profunda")
    sesion = brain.Sesion()
    r = brain._cmd_pensar_profundo("pensalo bien x", "pensalo bien x", sesion, "Bridget")
    assert r == "respuesta profunda"
    assert sesion.historial[-1] == {"role": "assistant", "content": "respuesta profunda"}
    assert sesion.historial[-2]["role"] == "user"


def test_pedido_explicito_va_extenso_y_automatico_corto(monkeypatch):
    capturado = {}

    def espia(pregunta, historial=None, extenso=True):
        capturado["extenso"] = extenso
        return "ok"

    monkeypatch.setattr(brain.pensador, "pensar_profundo", espia)
    sesion = brain.Sesion()

    brain._cmd_pensar_profundo("pensalo bien x", "pensalo bien x", sesion, "Bridget")
    assert capturado["extenso"] is True  # lo pidió: que se explaye

    brain._cmd_pensar_profundo(
        "que conviene estudiar primero", "qué conviene estudiar primero", sesion, "Bridget"
    )
    assert capturado["extenso"] is False  # derivación automática: formato charla


def test_sin_revisor_explicito_avisa(monkeypatch):
    monkeypatch.setattr(brain.pensador, "pensar_profundo",
                        lambda pregunta, historial=None, extenso=True: None)
    monkeypatch.setattr(brain, "consultar_llama",
                        lambda texto, sesion=None: "respuesta local")
    sesion = brain.Sesion()
    r = brain._cmd_pensar_profundo("pensalo bien x", "pensalo bien x", sesion, "Bridget")
    assert "respuesta local" in r
    assert "revisor" in r  # avisa que no llegó al modelo grande


def test_sin_revisor_automatico_no_avisa(monkeypatch):
    # si Bridget derivó sola y no hay internet, responde local sin drama:
    # el usuario nunca pidió el modelo grande
    monkeypatch.setattr(brain.pensador, "pensar_profundo",
                        lambda pregunta, historial=None, extenso=True: None)
    monkeypatch.setattr(brain, "consultar_llama",
                        lambda texto, sesion=None: "respuesta local")
    sesion = brain.Sesion()
    r = brain._cmd_pensar_profundo(
        "que conviene estudiar primero", "qué conviene estudiar primero", sesion, "Bridget"
    )
    assert r == "respuesta local"


# ---------- formato según el modo ----------

def test_sistema_extenso_vs_charla():
    extenso = pensador._mensajes("x", [], extenso=True)[0]["content"]
    corto = pensador._mensajes("x", [], extenso=False)[0]["content"]
    assert "extenderte" in extenso
    assert "párrafos cortos" in corto
