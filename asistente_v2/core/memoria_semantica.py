from core.runtime_paths import data_file
import json
import os
import numpy as np
from core.local_models import ollama
from datetime import datetime
import threading
from core.storage import write_json

from config import MODELO_EMBEDDINGS, KEEP_ALIVE

_lock = threading.RLock()

MEMORIA_FILE = data_file("memoria_semantica.json", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "memoria_semantica.json"))

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
    vector = np.asarray(respuesta["embedding"], dtype=np.float64)
    if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all():
        raise ValueError("Embedding inválido del modelo local")
    return vector.tolist()


def _valid_vector(value):
    try:
        vector = np.asarray(value, dtype=np.float64)
        return vector.ndim == 1 and vector.size > 0 and bool(np.isfinite(vector).all())
    except (ValueError, TypeError):
        return False


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
    con_emb = [r for r in memoria if isinstance(r, dict) and _valid_vector(r.get("embedding"))]
    if con_emb:
        size = len(con_emb[0]["embedding"])
        con_emb = [r for r in con_emb if len(r["embedding"]) == size]
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
        metadata = os.stat(MEMORIA_FILE)
        mtime = (os.path.abspath(MEMORIA_FILE), metadata.st_mtime_ns, metadata.st_size)
        if _cache["mtime"] == mtime:
            return _cache["memoria"]
        with open(MEMORIA_FILE, "r", encoding="utf-8") as f:
            memoria = json.load(f)
        if not isinstance(memoria, list):
            raise ValueError("Memoria debe ser una lista")
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
    if top_k <= 0 or not _valid_vector(embedding_consulta):
        return []
    con_emb = [r for r in memoria if isinstance(r, dict) and _valid_vector(r.get("embedding"))
               and len(r["embedding"]) == len(embedding_consulta)]
    if not con_emb:
        return []
    matriz = np.asarray([r["embedding"] for r in con_emb], dtype=np.float64)
    normas = np.linalg.norm(matriz, axis=1)
    normas[normas == 0] = 1e-12
    q = np.asarray(embedding_consulta, dtype=np.float64)
    return _topk(matriz, normas, con_emb, q, top_k, umbral)


def guardar_recuerdo(texto, categoria="general"):
    embedding = obtener_embedding(texto)
    with _lock:
        # No sobrescribir un archivo dañado: requiere recuperación manual.
        if os.path.exists(MEMORIA_FILE):
            with open(MEMORIA_FILE, encoding="utf-8") as stream:
                memoria = json.load(stream)
            if not isinstance(memoria, list):
                raise ValueError("Memoria inválida; recuperar antes de guardar")
        else:
            memoria = []
        recuerdo = {"texto": texto, "categoria": categoria, "embedding": embedding,
                    "embedding_model": MODELO_EMBEDDINGS, "fecha": datetime.now().isoformat()}
        write_json(MEMORIA_FILE, memoria + [recuerdo])
        _cache["mtime"] = None
    return True


def recordar(consulta, top_k=3, umbral=0.3):
    with _lock:
        memoria = list(cargar_memoria())
    if not memoria:
        return []
    candidates = [r for r in memoria if isinstance(r, dict)
                  and r.get("embedding_model", MODELO_EMBEDDINGS) == MODELO_EMBEDDINGS]
    if not candidates:
        return []
    query = obtener_embedding(consulta, tipo="query")
    return puntuar_memoria(candidates, query, top_k, umbral)
