"""Tests de los arreglos de aislamiento de sesión y robustez/limpieza:
- Sesiones no comparten estado de confirmación (aislamiento multi-cliente).
- detectar_intencion es robusto a tildes y ya no produce la intención muerta 'abrir'.
- escribir_archivo devuelve True/False correctamente.
"""
import core.brain as brain


# ---------- aislamiento de sesión ----------

def test_sesiones_no_comparten_confirmacion(monkeypatch):
    # no tocamos memoria real aunque se confirme
    monkeypatch.setattr(brain, "borrar_todos_los_recuerdos", lambda: True)

    s1 = brain.Sesion()
    s2 = brain.Sesion()

    r1 = brain.procesar_comando("borra todos mis recuerdos", "Bridget", s1)
    assert "seguro" in r1.lower()
    assert s1.esperando_confirmacion_borrado is True
    assert s2.esperando_confirmacion_borrado is False  # <- aislada

    # confirmar en s2 no dispara nada: no tiene borrado pendiente
    r2 = brain.procesar_comando("s", "Bridget", s2)
    assert "no hay" in r2.lower()

    # confirmar en s1 resuelve su propia confirmación
    r3 = brain.procesar_comando("s", "Bridget", s1)
    assert "borrado" in r3.lower()
    assert s1.esperando_confirmacion_borrado is False


def test_sesion_default_existe():
    assert isinstance(brain._sesion_default, brain.Sesion)


# ---------- detectar_intencion: robustez a tildes y sin código muerto ----------

def test_detectar_intencion_robusta_a_tildes():
    assert brain.detectar_intencion(brain.normalizar_texto("mirá la pantalla")) == "ver_pantalla"
    assert brain.detectar_intencion(brain.normalizar_texto("analizá mi proyecto")) == "analizar_proyecto"
    assert brain.detectar_intencion(brain.normalizar_texto("qué hora es")) == "consultar_hora"

def test_no_existe_intencion_abrir_muerta():
    # 'abrir' nunca se produce (su handler muerto fue removido de procesar_comando)
    intenciones = {
        brain.detectar_intencion(brain.normalizar_texto(t))
        for t in ["abrí firefox", "abrí opera", "abrime el editor"]
    }
    assert "abrir" not in intenciones

def test_contiene_ignora_tildes():
    assert brain._contiene("analiza el proyecto", ["analizá"]) is True
    assert brain._contiene("hola mundo", ["chau"]) is False


# ---------- escribir_archivo ----------

def test_escribir_archivo_ok(tmp_path):
    ruta = tmp_path / "salida.txt"
    assert brain.escribir_archivo(str(ruta), "contenido") is True
    assert ruta.read_text(encoding="utf-8") == "contenido"

def test_escribir_archivo_error_devuelve_false():
    # ruta imposible de escribir -> False, sin lanzar excepción
    assert brain.escribir_archivo("/proc/no/se/puede/x.txt", "x") is False
