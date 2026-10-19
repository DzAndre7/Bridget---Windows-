# ÚNICO lugar donde se elige el nombre del asistente y de su creador.
# Todo el proyecto (prompts, ventana, context.md, sandbox) lee de acá:
# cambiá estos valores y el asistente pasa a llamarse así en todos lados.
ASSISTANT_NAME = "Bridget"
ASSISTANT_CREATOR = "Usuario"

# --- Modelos -----------------------------------------------------------------
# También el ÚNICO lugar donde se eligen los modelos.
#
# La GPU (6 GB de VRAM) solo aguanta UN modelo de lenguaje cargado a la vez:
# alternar entre dos cuesta 10-15 segundos de recarga por turno (medido en
# esta máquina). Por eso la clasificación de intenciones y las extracciones
# usan el MISMO modelo que la conversación: caliente responde en ~1 segundo.
# Si algún día hay más VRAM (>8 GB), apuntá MODELO_RAPIDO a un modelo chico
# (ej: "llama3.2") para clasificar más rápido sin desalojar al principal.
MODELO_CONVERSACION = "dolphin3:8b"
MODELO_RAPIDO = MODELO_CONVERSACION  # clasificación de intenciones y extracciones
MODELO_VISION = "llava"              # corre en CPU (num_gpu=0) para no desalojar al principal
MODELO_EMBEDDINGS = "nomic-embed-text-v2-moe"
MODELO_REVISOR = "llama-3.3-70b-versatile"  # revisor externo via Groq
MODELO_STT = "small"                 # tamaño del modelo Whisper (tiny/base/small/...)
                                     # "small" + faster-whisper int8 en CPU:
                                     # mucho más preciso en español que "base"
                                     # y aun así más rápido que el "base" viejo

# Cuánto tiempo mantiene Ollama el modelo cargado después del último uso.
# Con el default (5 minutos), una pausa en la charla costaba una recarga de
# 15-40 segundos al volver; media hora mantiene la conversación fluida.
KEEP_ALIVE = "30m"

# Ventana de contexto que le pedimos a Ollama. Sin esto usaba su default
# (4096 tokens) y el prompt típico (system + 20 mensajes de historial) lo
# DESBORDABA: Ollama truncaba en silencio lo más viejo y el asistente
# "olvidaba" la charla a mitad de conversación (medido: ~4300 tokens de
# demanda típica). 8192 da aire; el costo es más memoria de KV cache
# (~128 KiB por token), que en una GPU compatible puede derramar un poco más a CPU.
NUM_CTX = 8192

# Sampling de la conversación (consultar_llama_stream). Ollama sin esto usa
# su default (temperature 0.8, top_p 0.9, top_k 40, repeat_penalty 1.1),
# que tiende a respuestas correctas pero previsibles. Subido un escalón para
# que suene menos mecánico sin volverse incoherente: más variedad de
# palabras y de qué token sigue (temperature/top_p/top_k arriba), y menos
# muletillas repetidas de turno a turno (repeat_penalty arriba).
# _llm_directo (clasificar intención, extraer datos, auto-mejora) NO usa
# esto: ahí temperature=0 es intencional, la determinística es lo que
# queremos al clasificar.
OPCIONES_CONVERSACION = {
    "temperature": 0.9,
    "top_p": 0.95,
    "top_k": 60,
    "repeat_penalty": 1.15,
}
