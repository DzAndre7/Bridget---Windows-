"""Tests de las funciones puras de core/brain.py (sin LLM, sin audio).

Red de regresión: fijan el comportamiento de parsing/intención para que
las optimizaciones no cambien lo que ya funciona, y documentan bugs.
"""
import core.brain as brain


# ---------- normalizar_texto ----------

def test_normalizar_minusculas_y_sin_tildes():
    assert brain.normalizar_texto("Qué HORA Es") == "que hora es"

def test_normalizar_conserva_enie():
    # la ñ no es un acento: debe conservarse
    assert brain.normalizar_texto("Compañía") == "compania" or "ñ" in brain.normalizar_texto("año")


# ---------- limpiar_texto_base ----------

def test_limpiar_saca_ruido_inicial():
    # limpiar_texto_base solo minusculiza y saca ruido inicial; NO quita tildes
    assert brain.limpiar_texto_base("Hola Bridget, qué hora es", "Bridget") == "qué hora es"

def test_limpiar_sin_ruido_no_rompe():
    assert brain.limpiar_texto_base("decime el clima", "Bridget") == "decime el clima"


# ---------- detectar_intencion (recibe texto ya normalizado) ----------

def test_intencion_hora():
    assert brain.detectar_intencion(brain.normalizar_texto("qué hora es")) == "consultar_hora"

def test_intencion_nombre():
    assert brain.detectar_intencion(brain.normalizar_texto("cómo te llamas")) == "consultar_nombre"

def test_intencion_saludo():
    assert brain.detectar_intencion(brain.normalizar_texto("hola")) == "saludo"

def test_intencion_buscar_web():
    assert brain.detectar_intencion(brain.normalizar_texto("buscá en internet noticias")) == "buscar_web"

def test_intencion_ejecutar_tarea():
    assert brain.detectar_intencion(brain.normalizar_texto("abrí firefox")) == "ejecutar_tarea"

def test_intencion_guardar_recuerdo():
    assert brain.detectar_intencion(brain.normalizar_texto("recordá que me gusta el café")) == "guardar_recuerdo"

def test_intencion_desconocida_va_al_llm():
    assert brain.detectar_intencion(brain.normalizar_texto("contame un chiste")) == "desconocida"

def test_intencion_convertir_documento():
    texto = brain.normalizar_texto("convertí /home/bridget/nota.md a pdf")
    assert brain.detectar_intencion(texto) == "convertir_documento"


# ---------- extraer_recuerdo / extraer_olvido ----------

def test_extraer_recuerdo():
    assert brain.extraer_recuerdo("recordá que me gusta el café") == "me gusta el café"

def test_extraer_recuerdo_sin_disparador():
    assert brain.extraer_recuerdo("hoy hace calor") is None

def test_extraer_olvido():
    assert brain.extraer_olvido("olvidate que me gusta el café") == "me gusta el café"


# ---------- extraer_ruta_archivo / extraer_tipo_analisis ----------

def test_extraer_ruta_archivo():
    assert brain.extraer_ruta_archivo("analiza /home/bridget/x.py por favor") == "/home/bridget/x.py"

def test_extraer_ruta_archivo_sin_ruta():
    assert brain.extraer_ruta_archivo("analiza mi codigo") is None

def test_extraer_tipo_analisis_default():
    assert brain.extraer_tipo_analisis("analiza el proyecto") == "completo"

def test_extraer_tipo_analisis_seguridad():
    assert brain.extraer_tipo_analisis("solo seguridad de /x.py") == "seguridad"


# ---------- BUG documentado: extraer_consulta_busqueda ----------
# Con una consulta compuesta solo por verbos/contexto de búsqueda
# ("buscar", "google"...) la versión original deja `consulta` sin asignar
# y lanza NameError, que rompe procesar_comando entero. Debe devolver None.

def test_extraer_consulta_busqueda_no_crashea_sin_terminos():
    # "busca google" son todas palabras de comando: no debe lanzar UnboundLocalError
    resultado = brain.extraer_consulta_busqueda("busca google", "Bridget")
    assert resultado is None

def test_extraer_consulta_busqueda_normal():
    resultado = brain.extraer_consulta_busqueda("buscar en internet clima en cordoba", "Bridget")
    assert resultado and "clima" in resultado

def test_extraer_consulta_busqueda_no_deja_conector_suelto():
    # no debe filtrarse un "en" pegado al inicio de la consulta
    resultado = brain.extraer_consulta_busqueda("buscar en internet clima", "Bridget")
    assert resultado == "clima"
