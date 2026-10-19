"""Tests de las funciones puras de core/cerebro.py (parsing y utilidades,
sin tocar el vault real ni el LLM)."""
import core.cerebro as cerebro


def test_limpiar_nombre_archivo_saca_prohibidos():
    assert cerebro._limpiar_nombre_archivo('a/b:c*?"<>|d') == "abcd"

def test_limpiar_nombre_archivo_colapsa_espacios():
    assert cerebro._limpiar_nombre_archivo("hola    mundo") == "hola mundo"

def test_limpiar_nombre_archivo_vacio():
    assert cerebro._limpiar_nombre_archivo('/\\:*?"<>|') == "nota sin titulo"


def test_construir_nota_incluye_titulo_y_tags():
    nota = cerebro._construir_nota("Mi Nota", "contenido", "test", tags=["a", "b"])
    assert "# Mi Nota" in nota
    assert "#a #b" in nota
    assert "contenido" in nota


def test_clasificar_nota_parsea_respuesta_bien_formada():
    def fake_llm(_prompt):
        return "CATEGORIA: personal\nTAGS: cafe, gustos\nTITULO: Le gusta cafe"
    r = cerebro.clasificar_nota("al usuario le gusta el cafe", fake_llm)
    assert r["categoria"] == "personal"
    assert r["tags"] == ["cafe", "gustos"]
    assert r["titulo"] == "Le gusta cafe"

def test_clasificar_nota_categoria_invalida_cae_a_default():
    def fake_llm(_prompt):
        return "CATEGORIA: inventada\nTAGS: x\nTITULO: Algo"
    r = cerebro.clasificar_nota("texto", fake_llm)
    assert r["categoria"] == "conversaciones"  # default seguro

def test_clasificar_nota_llm_falla_devuelve_defaults():
    def fake_llm(_prompt):
        raise RuntimeError("ollama caido")
    r = cerebro.clasificar_nota("texto", fake_llm)
    assert r["categoria"] == "conversaciones"
    assert r["titulo"] == "Nota sin titulo"
    assert r["tags"] == []

def test_clasificar_nota_recorta_titulo_largo():
    def fake_llm(_prompt):
        return "CATEGORIA: conocimiento\nTAGS: a, b\nTITULO: uno dos tres cuatro cinco"
    r = cerebro.clasificar_nota("texto", fake_llm)
    assert len(r["titulo"].split()) <= 3


def test_stopwords_presentes():
    assert "para" in cerebro.STOPWORDS
    assert "que" in cerebro.STOPWORDS
