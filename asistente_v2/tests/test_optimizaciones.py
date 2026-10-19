"""Tests que fijan el comportamiento de las rutas optimizadas:
- memoria semántica vectorizada (equivalencia con la versión ingenua)
- cerebro en una sola pasada (ranking por nº de palabras matcheadas)
"""
import os
import tempfile

import core.memoria_semantica as ms
import core.cerebro as cerebro


# ---------- memoria semántica: la versión numpy da el mismo ranking ----------

def _ranking_ingenuo(memoria, q, top_k, umbral):
    scored = []
    for r in memoria:
        s = ms.similitud(q, r["embedding"])
        if s >= umbral:
            scored.append((s, r["texto"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:top_k]]


def test_puntuar_memoria_coincide_con_version_ingenua():
    memoria = [
        {"texto": "a", "embedding": [1.0, 0.0, 0.0]},
        {"texto": "b", "embedding": [0.0, 1.0, 0.0]},
        {"texto": "c", "embedding": [0.9, 0.1, 0.0]},
        {"texto": "d", "embedding": [0.0, 0.0, 1.0]},
    ]
    q = [1.0, 0.05, 0.0]
    esperado = _ranking_ingenuo(memoria, q, top_k=3, umbral=0.3)
    obtenido = [r["texto"] for r in ms.puntuar_memoria(memoria, q, top_k=3, umbral=0.3)]
    assert obtenido == esperado

def test_puntuar_memoria_respeta_umbral():
    memoria = [
        {"texto": "cerca", "embedding": [1.0, 0.0]},
        {"texto": "ortogonal", "embedding": [0.0, 1.0]},
    ]
    q = [1.0, 0.0]
    res = [r["texto"] for r in ms.puntuar_memoria(memoria, q, top_k=5, umbral=0.5)]
    assert res == ["cerca"]  # el ortogonal (score 0) queda afuera

def test_puntuar_memoria_sin_embeddings():
    assert ms.puntuar_memoria([{"texto": "x"}], [1.0, 0.0]) == []


# ---------- memoria semántica: el cache se invalida por mtime ----------

def test_cargar_memoria_usa_cache(monkeypatch, tmp_path):
    archivo = tmp_path / "mem.json"
    archivo.write_text('[{"texto": "hola", "embedding": [1.0, 0.0]}]', encoding="utf-8")
    monkeypatch.setattr(ms, "MEMORIA_FILE", str(archivo))
    ms._cache.update(mtime=None, memoria=[], con_emb=[], matriz=None, normas=None)

    m1 = ms.cargar_memoria()
    assert len(m1) == 1
    assert ms._cache["matriz"] is not None  # se precalculó la matriz
    # segunda llamada sin cambios: mismo objeto cacheado
    assert ms.cargar_memoria() is m1


# ---------- cerebro: una sola pasada, ranking por matches ----------

def test_consultar_cerebro_rankea_por_matches(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="test_vault_")
    with open(os.path.join(tmp, "muchos.md"), "w", encoding="utf-8") as f:
        f.write("python docker async memoria vector")  # 4+ palabras clave
    with open(os.path.join(tmp, "pocos.md"), "w", encoding="utf-8") as f:
        f.write("python solamente")  # 1 palabra clave
    with open(os.path.join(tmp, "nada.md"), "w", encoding="utf-8") as f:
        f.write("texto sin relacion alguna")
    monkeypatch.setenv("VAULT_PATH", tmp)

    res = cerebro.consultar_cerebro("python async memoria vector docker", max_notas=3)
    titulos = [n["titulo"] for n in res]
    assert titulos[0] == "muchos"        # la que más palabras matchea va primera
    assert "nada" not in titulos          # la irrelevante no aparece

def test_consultar_cerebro_vault_invalido_no_rompe(monkeypatch):
    monkeypatch.setenv("VAULT_PATH", "/ruta/que/no/existe/xyz")
    assert cerebro.consultar_cerebro("cualquier cosa larga") == []

def test_consultar_cerebro_sin_palabras_significativas(monkeypatch):
    monkeypatch.setenv("VAULT_PATH", "/tmp")
    assert cerebro.consultar_cerebro("de la que en un") == []


# ---------- brain: el historial no crece sin límite ----------

def test_historial_acotado(monkeypatch):
    import core.brain as brain

    # aislamos consultar_llama de disco/ollama/vault
    monkeypatch.setattr(brain, "leer_recuerdos", lambda: [])
    monkeypatch.setattr(brain, "recordar", lambda *a, **k: [])
    monkeypatch.setattr(brain.cerebro, "consultar_cerebro", lambda *a, **k: [])
    monkeypatch.setattr(brain, "guardar_interaccion", lambda *a, **k: True)

    def fake_chat(**k):
        # consultar_llama ahora usa stream=True e itera los chunks
        if k.get("stream"):
            return iter([{"message": {"content": "ok"}}])
        return {"message": {"content": "ok"}}
    monkeypatch.setattr(brain.ollama, "chat", fake_chat)

    sesion = brain.Sesion()
    for i in range(50):
        brain.consultar_llama(f"mensaje {i}", sesion)

    # nunca supera el tope, aunque se hagan muchísimos turnos
    assert len(sesion.historial) <= brain.MAX_HISTORIAL
