import json 
import os 

DEBUG_MODE = False
DATASET_MAESTRO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset_maestro.jsonl")

DATASET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset.jsonl")

def guardar_interaccion(pregunta, respuesta):
    try: 
        ejemplo = {
            "messages": [
                {"role": "user", "content": pregunta},
                {"role": "assistant", "content": respuesta}
            ]
        }
        with open(DATASET_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ejemplo, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        if DEBUG_MODE:
             print(f"DEBUG ERROR DATASET: {e}")
        return False

def contar_ejemplos():
    if not os.path.exists(DATASET_FILE):
        return 0 
    try:
        with open(DATASET_FILE, "r", encoding="utf-8") as f:
            return sum(1 for linea in f if linea.strip())
    except Exception:
        return 0

def guardar_par_entrenamiento(codigo_original, propuesta_dolphin, revision_groq):
    try:
        ejemplo = {
            "messages": [
                {"role": "user", "content": f"Mejorá este código Python:\n\n{codigo_original}"},
                {"role": "assistant", "content": revision_groq}
            ],
            "metadata": {
                "propuesta_dolphin": propuesta_dolphin,
                "tipo": "code_improvement"
            }
        }
        with open(DATASET_MAESTRO_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ejemplo, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        if DEBUG_MODE:
            print(f"DEBUG ERROR DATASET MAESTRO: {e}")
        return False