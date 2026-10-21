"""Tests del streaming + TTS por frases (sin audio, sin ollama real).

- `frasear`: agrupación de tokens en frases, limpieza Markdown, salto de código.
- contrato de `consultar_llama`: sigue devolviendo el texto completo, y con un
  sink instalado además entrega las frases a medida que se generan.
"""
import core.brain as brain


# ---------- frasear (función pura) ----------

def test_frasear_divide_en_oraciones():
    assert list(brain.frasear(["Hola mundo. ", "Todo bien?"])) == ["Hola mundo.", "Todo bien?"]

def test_frasear_reensambla_tokens_partidos():
    tokens = ["Un vec", "tor es una lis", "ta. Sirve pa", "ra datos."]
    assert list(brain.frasear(tokens)) == ["Un vector es una lista.", "Sirve para datos."]

def test_frasear_limpia_markdown():
    salida = list(brain.frasear(["**Hola**. ", "- item uno\n"]))
    assert salida == ["Hola.", "item uno"]

def test_frasear_salta_bloques_de_codigo():
    tokens = ["Mirá esto:\n", "```py\n", "print(1)\n", "```", "listo.\n"]
    salida = list(brain.frasear(tokens))
    assert "Revisá el código en pantalla." in salida
    assert "listo." in salida
    # nada del código se cuela como frase
    assert not any("print(1)" in f for f in salida)

def test_frasear_vacio():
    assert list(brain.frasear([])) == []


# ---------- contrato de consultar_llama con streaming ----------

def _stub_entorno(monkeypatch, trozos):
    """Aísla consultar_llama de disco/vault/ollama y hace que el LLM 'genere' `trozos`."""
    monkeypatch.setattr(brain, "leer_recuerdos", lambda: [])
    monkeypatch.setattr(brain, "recordar", lambda *a, **k: [])
    monkeypatch.setattr(brain.cerebro, "consultar_cerebro", lambda *a, **k: [])
    monkeypatch.setattr(brain, "guardar_interaccion", lambda *a, **k: True)

    def fake_chat(model, messages, stream=False, **kw):
        if stream:
            return iter([{"message": {"content": t}} for t in trozos])
        return {"message": {"content": "".join(trozos)}}
    monkeypatch.setattr(brain.ollama, "chat", fake_chat)


def test_consultar_llama_sin_sink_devuelve_texto_completo(monkeypatch):
    _stub_entorno(monkeypatch, ["Hola. ", "Todo ", "bien."])
    brain.usar_sink_de_frases(None)
    sesion = brain.Sesion()

    r = brain.consultar_llama("hola", sesion)
    assert r == "Hola. Todo bien."
    assert brain.ULTIMO_TURNO_STREAMEADO is False
    # el historial de la sesión se actualizó con la respuesta
    assert sesion.historial[-1] == {"role": "assistant", "content": "Hola. Todo bien."}


def test_consultar_llama_con_sink_entrega_frases(monkeypatch):
    _stub_entorno(monkeypatch, ["Hola. ", "Todo ", "bien."])
    recibidas = []

    def sink(frases):
        for f in frases:
            recibidas.append(f)

    brain.usar_sink_de_frases(sink)
    sesion = brain.Sesion()
    try:
        r = brain.consultar_llama("hola", sesion)
    finally:
        brain.usar_sink_de_frases(None)

    assert r == "Hola. Todo bien."                 # contrato: string completo
    assert recibidas == ["Hola.", "Todo bien."]    # frases entregadas en vivo
    assert brain.ULTIMO_TURNO_STREAMEADO is True
    assert sesion.historial[-1]["content"] == "Hola. Todo bien."


def test_consultar_llama_stream_finaliza_historial(monkeypatch):
    _stub_entorno(monkeypatch, ["uno ", "dos ", "tres"])
    sesion = brain.Sesion()
    trozos = list(brain.consultar_llama_stream("contame", sesion))
    assert "".join(trozos) == "uno dos tres"
    assert sesion.historial[-1]["content"] == "uno dos tres"
