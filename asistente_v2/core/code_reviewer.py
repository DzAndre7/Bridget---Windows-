import os
from groq import Groq
from dotenv import load_dotenv

from config import MODELO_REVISOR

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def revisar_codigo(codigo, objetivo="mejorar y detectar errores"):
    if not GROQ_API_KEY:
        return None

    try:
        cliente = Groq(api_key=GROQ_API_KEY)
        respuesta = cliente.chat.completions.create(
            model=MODELO_REVISOR,
            messages=[
                {"role": "system", "content": "Sos un revisor experto de código Python. Analizás código y das mejoras concretas, claras y justificadas. Respondés en español."},
                {"role": "user", "content": f"Objetivo: {objetivo}\n\nRevisá este código y dame mejoras concretas:\n\n{codigo}"}
            ]
        )
        return respuesta.choices[0].message.content
    except Exception as e:
        print(f"DEBUG GROQ ERROR: {e}")
        return None