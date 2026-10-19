import json
import os
import numpy as np
import ollama
from datetime import datetime

from config import MODELO_EMBEDDINGS, KEEP_ALIVE

MEMORIA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "memoria_semantica.json")

# Caché en memoria: evita releer y reparsear el JSON (cientos de KB con los
# embeddings) en cada turno de conversación, y precalcula la matriz de
# embeddings + sus normas una sola vez. Se invalida solo si cambia el archivo.
_cache = {"mtime": None, "memoria": [], "con_emb": [], "matriz": None, "normas": None}


def obtener_embedding(texto, tipo="document"):
    prefijo = "search_query: " if tipo == "query" else "search_document: "
    # num_gpu=0: el embedder corre SIEMPRE en CPU (mismo criterio que llava
    # en config.py). En los 6 GB de la GPU no entran dolphin3 y nomic a la
    # vez: si el embedder pisa la GPU, desaloja al modelo de conversación y
    # cada turno paga una recarga de 10-15 s (medido: recordar() corre antes
    # de CADA respuesta). En CPU, embeber una consulta corta tarda
    # milisegundos. keep_alive largo para no recargar el embedder tampoco.
    respuesta = ollama.embeddings(
        model=MODELO_EMBEDDINGS,
        prompt=prefijo + texto,
        options={"num_gpu": 0},
        keep_alive=KEEP_ALIVE,
    )
    return respuesta["embedding"]


def similitud(a, b):
    """Similitud coseno entre dos vectores. Se conserva por compatibilidad
    (tests y uso externo); las rutas calientes usan la versión vectorizada."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _refrescar_cache(memoria, mtime):
    con_emb = [r for r in memoria if "embedding" in r]
    if con_emb:
        matriz = np.asarray([r["embedding"] for r in con_emb], dtype=np.float64)
        normas = np.linalg.norm(matriz, axis=1)
        normas[normas == 0] = 1e-12  # evita división por cero
    else:
        matriz, normas = None, None
    _cache.update(mtime=mtime, memoria=memoria, con_emb=con_emb, matriz=matriz, normas=normas)


def cargar_memoria():
    if not os.path.exists(MEMORIA_FILE):
        return []
    try:
        mtime = os.path.getmtime(MEMORIA_FILE)
        if _cache["mtime"] == mtime:
            return _cache["memoria"]
        with open(MEMORIA_FILE, "r", encoding="utf-8") as f:
            memoria = json.load(f)
        _refrescar_cache(memoria, mtime)
        return memoria
    except Exception:
        return []


def _topk(matriz, normas, con_emb, q, top_k, umbral):
    """Top_k recuerdos con score >= umbral, ordenados desc. Todo el scoring
    es una sola multiplicación matriz-vector (numpy)."""
    nq = float(np.linalg.norm(q)) or 1e-12
    scores = (matriz @ q) / (normas * nq)
    orden = np.argsort(scores)[::-1]
    resultado = []
    for i in orden:
        if scores[i] < umbral:
            break
        resultado.append(con_emb[i])
        if len(resultado) >= top_k:
            break
    return resultado


def puntuar_memoria(memoria, embedding_consulta, top_k=3, umbral=0.3):
    """Puntúa una lista de recuerdos contra un embedding ya calculado.
    Función pura (no toca disco ni ollama): usada por el benchmark."""
    con_emb = [r for r in memoria if "embedding" in r]
    if not con_emb:
        return []
    matriz = np.asarray([r["embedding"] for r in con_emb], dtype=np.float64)
    normas = np.linalg.norm(matriz, axis=1)
    normas[normas == 0] = 1e-12
    q = np.asarray(embedding_consulta, dtype=np.float64)
    return _topk(matriz, normas, con_emb, q, top_k, umbral)


def guardar_recuerdo(texto, categoria="general"):
    memoria = cargar_memoria()
    embedding = obtener_embedding(texto)
    recuerdo = {
        "texto": texto,
        "categoria": categoria,
        "embedding": embedding,
        "fecha": datetime.now().isoformat()
    }
    memoria = list(memoria) + [recuerdo]
    with open(MEMORIA_FILE, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)
    # el próximo cargar_memoria detectará el nuevo mtime y refrescará el cache
    return True


def recordar(consulta, top_k=3, umbral=0.3):
    memoria = cargar_memoria()  # llena/reusa el cache (matriz + normas)
    if not memoria or _cache["matriz"] is None:
        return []
    q = np.asarray(obtener_embedding(consulta, tipo="query"), dtype=np.float64)
    return _topk(_cache["matriz"], _cache["normas"], _cache["con_emb"], q, top_k, umbral)
