import base64
import ollama
import time
from PIL import ImageGrab

from config import MODELO_VISION

def capturar_pantalla():
    captura = ImageGrab.grab()
    captura.save("/tmp/bridget_pantalla.png")
    with open("/tmp/bridget_pantalla.png", "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def liberar_modelo(modelo):
    """Descarga un modelo de la memoria pidiéndole a Ollama que no lo mantenga."""
    try:
        ollama.generate(model=modelo, prompt="", keep_alive=0)
    except Exception:
        pass

def ver_pantalla(pregunta="¿Qué ves en esta pantalla?"):
    imagen_base64 = capturar_pantalla()

    respuesta = ollama.chat(
        model=MODELO_VISION,
        messages=[{
            "role": "user",
            "content": pregunta,
            "images": [imagen_base64]
        }],
        options={"num_gpu": 0}
    )

    return respuesta["message"]["content"]