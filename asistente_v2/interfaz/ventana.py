# interfaz/ventana.py
import os
import sys
import json

# QtWebEngine (el Chromium embebido que usa pywebview) intenta renderizar por
# GPU; en esta máquina (NVIDIA + X11 sin GBM) cae a Vulkan y termina en
# violación de segmento. Renderizamos por software: estable, y en una ventana
# de chat no se nota. IMPORTANTE: debe setearse ANTES de importar webview,
# que es lo que carga Qt/Chromium. setdefault permite pisarlo desde afuera
# si algún día querés probar la GPU de nuevo.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import webview

DIR = os.path.dirname(__file__)
RUTA_HTML = os.path.join(DIR, "presencia.html")
RUTA_CONFIG = os.path.join(DIR, "config_presencia.json")

# Agregamos la raíz del proyecto al path para poder importar 'core'
RAIZ = os.path.dirname(DIR)  # sube de interfaz/ a asistente_v2/
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from core.brain import procesar_comando, _llm_directo
from core import sesiones
from core import agenda
from config import ASSISTANT_NAME


class API:
    """Puente entre el JavaScript de la ventana y Python."""

    def __init__(self):
        # Sesión persistente: cada apertura de la ventana es un chat nuevo
        # que recuerda el anterior (core/sesiones.py). Con funcion_llm, la
        # charla anterior se resume a memoria semántica en segundo plano.
        self.sesion = sesiones.abrir_sesion(
            assistant_name=ASSISTANT_NAME, funcion_llm=_llm_directo
        )
        # Recordatorios: el hilo avisador habla y notifica cuando vencen.
        agenda.iniciar_avisador()

    def obtener_historial_anterior(self):
        """El frontend llama a esto al abrir, para mostrar la conversación
        de la sesión pasada y que la ventana nunca arranque vacía."""
        mensajes = []
        for mensaje in self.sesion.historial_anterior:
            mensajes.append({
                "quien": "user" if mensaje.get("role") == "user" else "bridget",
                "texto": str(mensaje.get("content", "")),
            })
        return mensajes

    def guardar_config(self, config_json):
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                f.write(config_json)
            return True
        except Exception as e:
            print(f"Error guardando config: {e}")
            return False

    def cargar_config(self):
        if not os.path.exists(RUTA_CONFIG):
            return ""
        try:
            with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Error leyendo config: {e}")
            return ""

    def enviar_mensaje(self, texto):
        """El chat llama a esto. Pasa el mensaje al cerebro y devuelve la respuesta."""
        try:
            respuesta = procesar_comando(texto, ASSISTANT_NAME, self.sesion)
            return respuesta
        except Exception as e:
            print(f"Error procesando mensaje: {e}")
            return "Tuve un problema procesando eso."

    def generar_voz(self, texto):
        """Genera el audio de una respuesta con Enceladus y lo devuelve en base64."""
        import base64
        from core import voice
        try:
            # Reusamos la generación de voice.py: genera el archivo
            ruta = voice.generar_audio(texto)
            if not ruta:
                return ""
            with open(ruta, "rb") as f:
                audio_bytes = f.read()
            # lo codificamos en base64 para pasarlo por el puente
            return base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as e:
            print(f"Error generando voz: {e}")
            return ""

    def iniciar_microfono(self):
        """Empieza a grabar del micrófono."""
        from core import microfono_ventana
        try:
            microfono_ventana.iniciar_grabacion()
            return True
        except Exception as e:
            print(f"Error iniciando micrófono: {e}")
            return False

    def detener_microfono(self):
        """Para de grabar, transcribe, y devuelve el texto."""
        from core import microfono_ventana
        try:
            return microfono_ventana.detener_grabacion()
        except Exception as e:
            print(f"Error deteniendo micrófono: {e}")
            return ""

    def iniciar_manos_libres(self):
        from core import manos_libres
        try:
            manos_libres.iniciar()
            return True
        except Exception as e:
            print(f"Error iniciando manos libres: {e}")
            return False

    def detener_manos_libres(self):
        from core import manos_libres
        try:
            manos_libres.detener()
            return True
        except Exception as e:
            print(f"Error deteniendo manos libres: {e}")
            return False

    def hablar_respuesta(self, texto):
        """Genera y reproduce la voz de una respuesta, pausando la escucha mientras suena."""
        from core import manos_libres, voice
        try:
            manos_libres.pausar()        # dejamos de escuchar mientras habla
            voice.hablar(texto)          # genera (Enceladus) y reproduce, bloquea hasta terminar
            manos_libres.reanudar()      # volvemos a escuchar
            return True
        except Exception as e:
            print(f"Error hablando respuesta: {e}")
            from core import manos_libres
            manos_libres.reanudar()      # por las dudas, reanudamos aunque falle
            return False


def abrir_ventana():
    api = API()
    ventana = webview.create_window(
        title=ASSISTANT_NAME,
        url=RUTA_HTML,
        width=500,
        height=500,
        background_color="#0a0e14",
        resizable=True,
        transparent=True,
        js_api=api
    )
    from core import manos_libres
    manos_libres.configurar_ventana(ventana)
    webview.start()


if __name__ == "__main__":
    abrir_ventana()