"""Tests de la capa de comprensión (core/intenciones.py), en especial del
clasificador LLM de nivel 2. Sin modelo real: el LLM entra como función
falsa, igual que en los tests del sandbox.
"""
import pytest

from core import intenciones


# ---------- detectar: combinación reglas + LLM ----------

def test_reglas_tienen_prioridad_y_no_gastan_llm():
    def llm_que_no_debe_llamarse(prompt):
        raise AssertionError("no debería consultarse el LLM si las reglas matchean")

    assert intenciones.detectar("que hora es", funcion_llm=llm_que_no_debe_llamarse) == "consultar_hora"


def test_sin_funcion_llm_se_comporta_como_las_reglas():
    assert intenciones.detectar("contame un chiste") == "desconocida"


def test_llm_clasifica_cuando_las_reglas_no_reconocen():
    resultado = intenciones.detectar(
        "fijate que hay en mi monitor",
        funcion_llm=lambda p: "ver_pantalla",
    )
    assert resultado == "ver_pantalla"


def test_una_sola_palabra_no_consulta_al_llm():
    def llm_que_no_debe_llamarse(prompt):
        raise AssertionError("una palabra no amerita clasificación")

    assert intenciones.detectar("dale", funcion_llm=llm_que_no_debe_llamarse) == "desconocida"


# ---------- clasificar_con_llm: robustez del parseo ----------

def test_respuesta_exacta():
    assert intenciones.clasificar_con_llm("x", lambda p: "consultar_hora") == "consultar_hora"


def test_respuesta_con_texto_alrededor():
    respuesta = "La intención es: ver_pantalla."
    assert intenciones.clasificar_con_llm("x", lambda p: respuesta) == "ver_pantalla"


def test_conversar_se_traduce_a_desconocida():
    assert intenciones.clasificar_con_llm("x", lambda p: "conversar") == "desconocida"


def test_respuesta_basura_da_desconocida():
    assert intenciones.clasificar_con_llm("x", lambda p: "ni idea flaco") == "desconocida"


def test_llm_caido_da_desconocida_sin_lanzar():
    def llm_roto(prompt):
        raise ConnectionError("ollama caído")

    assert intenciones.clasificar_con_llm("x", llm_roto) == "desconocida"


def test_solo_acepta_intenciones_del_catalogo():
    # aunque el modelo "invente" algo parecido a una intención real del
    # sistema pero que no está en el catálogo, no se acepta
    assert intenciones.clasificar_con_llm("x", lambda p: "borrar_todo_el_disco") == "desconocida"


def test_el_prompt_incluye_el_catalogo_y_el_mensaje():
    capturado = {}

    def llm_espia(prompt):
        capturado["prompt"] = prompt
        return "conversar"

    intenciones.clasificar_con_llm("quiero milanesas", llm_espia)
    assert "quiero milanesas" in capturado["prompt"]
    for nombre in intenciones.INTENCIONES_LLM:
        assert nombre in capturado["prompt"]


# ---------- reglas: límites de palabra (antes matcheaban por substring) ----------
# El bug emblema: "ahora" contenía "hora" y cualquier frase con "ahora"
# respondía la hora. Lo mismo pasaba con "confuso"/"uso", "borrador"/"borra",
# "récord"/"record". Estas pruebas fijan que la charla común ya no se
# desvía a comandos.

def test_ahora_no_dispara_la_hora():
    texto = intenciones.normalizar_texto("ahora que lo pienso, contame más de eso")
    assert intenciones.detectar_intencion(texto) == "desconocida"


def test_que_hora_es_sigue_funcionando():
    assert intenciones.detectar_intencion("que hora es") == "consultar_hora"


def test_confuso_no_guarda_preferencia():
    assert intenciones.detectar_intencion("estoy confuso con este tema") == "desconocida"


def test_uso_con_herramienta_si_guarda_preferencia():
    assert intenciones.detectar_intencion("uso opera como navegador") == "guardar_preferencia"


def test_borrador_no_borra_recuerdos():
    assert intenciones.detectar_intencion("te paso el borrador del texto") == "desconocida"


def test_record_deportivo_no_toca_la_memoria():
    texto = intenciones.normalizar_texto("messi rompió otro récord mundial")
    assert intenciones.detectar_intencion(texto) == "desconocida"


def test_mejorar_sin_codigo_es_charla():
    assert intenciones.detectar_intencion("me gustaria mejorar mi ingles") == "desconocida"


def test_mejorar_con_codigo_sigue_siendo_comando():
    assert intenciones.detectar_intencion("mejora el codigo de este archivo") == "mejorar_codigo"


def test_recorda_que_guarda_aunque_diga_mi():
    # antes leer_recuerdos se evaluaba primero y "mi" desviaba el guardado
    assert intenciones.detectar_intencion("recorda que mi hermana se llama ana") == "guardar_recuerdo"


def test_que_sabes_de_mi_lee_recuerdos():
    assert intenciones.detectar_intencion("que sabes de mi") == "leer_recuerdos"


# ---------- convertir_documento / extraer_conversion ----------

def test_intencion_convertir_documento():
    texto = intenciones.normalizar_texto("convertí /home/bridget/nota.md a pdf")
    assert intenciones.detectar_intencion(texto) == "convertir_documento"


def test_convertir_va_antes_que_leer_archivo():
    # sin la regla de conversión, esto caería en leer_archivo (tiene ".md")
    assert intenciones.detectar_intencion("pasame /home/bridget/nota.md a pdf") == "convertir_documento"


def test_extraer_conversion_ruta_y_formato():
    ruta, extension = intenciones.extraer_conversion("convertí /home/bridget/nota.md a pdf")
    assert ruta == "/home/bridget/nota.md"
    assert extension == "pdf"


def test_extraer_conversion_no_confunde_extension_de_entrada_con_destino():
    # el archivo de entrada ya es .md: el formato de destino pedido es html,
    # no debería "detectar" markdown por la propia extensión de la ruta.
    ruta, extension = intenciones.extraer_conversion("convertí /home/bridget/nota.md a html")
    assert extension == "html"


def test_extraer_conversion_word_y_powerpoint_son_alias():
    _, extension_word = intenciones.extraer_conversion("pasá /tmp/x.md a word")
    _, extension_ppt = intenciones.extraer_conversion("pasá /tmp/x.md a powerpoint")
    assert extension_word == "docx"
    assert extension_ppt == "pptx"


def test_extraer_conversion_sin_ruta_devuelve_nada():
    assert intenciones.extraer_conversion("convertime esto a pdf") == (None, None)


def test_extraer_conversion_sin_formato_reconocido():
    ruta, extension = intenciones.extraer_conversion("convertí /tmp/x.md a algo raro")
    assert ruta == "/tmp/x.md"
    assert extension is None
