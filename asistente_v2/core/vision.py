import base64
from core.local_models import ollama
from io import BytesIO

from config import MODELO_VISION

def capturar_pantalla():
    from PIL import ImageGrab
    captura = ImageGrab.grab()
    with BytesIO() as output:
        captura.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("utf-8")

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