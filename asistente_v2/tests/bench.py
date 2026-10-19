"""Benchmark reproducible de las dos rutas calientes del asistente,
las que corren en CADA turno de conversación dentro de consultar_llama:

  A) Puntuación de memoria semántica  (core/memoria_semantica.py)
  B) Búsqueda de notas en el cerebro  (core/cerebro.py)

Se corre igual antes y después de optimizar para comparar números:
    python tests/bench.py

Usa datos sintéticos deterministas (semilla fija) para que las corridas
sean comparables. No llama a ollama ni a la red.
"""
import os
import sys
import time
import random
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.memoria_semantica as ms
import core.cerebro as cerebro


def _similitud_pura(a, b):
    """Copia de la implementación ORIGINAL (Python puro), para que la
    comparación 'antes' sea honesta aunque el módulo ya esté optimizado."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb)


def _cronometrar(fn, repeticiones):
    inicio = time.perf_counter()
    for _ in range(repeticiones):
        fn()
    return (time.perf_counter() - inicio) / repeticiones


# ---------------------------------------------------------------------------
# A) Memoria semántica: puntuar N recuerdos contra una consulta
# ---------------------------------------------------------------------------
def bench_memoria(n_recuerdos=2000, dim=768, repeticiones=20):
    random.seed(42)
    memoria = [
        {"texto": f"recuerdo {i}", "embedding": [random.gauss(0, 1) for _ in range(dim)]}
        for i in range(n_recuerdos)
    ]
    consulta = [random.gauss(0, 1) for _ in range(dim)]
    umbral = 0.3

    # --- ANTES: bucle en Python puro (implementación original) ---
    def viejo():
        scored = []
        for r in memoria:
            score = _similitud_pura(consulta, r["embedding"])
            if score >= umbral:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:3]

    t_viejo = _cronometrar(viejo, repeticiones)

    # --- DESPUÉS (sin cache): numpy reconstruyendo la matriz en cada consulta ---
    def nuevo_sin_cache():
        return ms.puntuar_memoria(memoria, consulta, top_k=3, umbral=umbral)
    t_nuevo = _cronometrar(nuevo_sin_cache, repeticiones)

    # --- DESPUÉS (con cache): matriz precalculada, solo matmul (como recordar) ---
    matriz = np.asarray([r["embedding"] for r in memoria], dtype=np.float64)
    normas = np.linalg.norm(matriz, axis=1)
    normas[normas == 0] = 1e-12
    q = np.asarray(consulta, dtype=np.float64)

    def nuevo_con_cache():
        return ms._topk(matriz, normas, memoria, q, 3, umbral)
    t_cache = _cronometrar(nuevo_con_cache, repeticiones)

    print(f"[A] Memoria semántica ({n_recuerdos} recuerdos x {dim} dims)")
    print(f"    bucle Python puro (original)  : {t_viejo*1000:8.2f} ms/consulta")
    print(f"    numpy sin cache               : {t_nuevo*1000:8.2f} ms/consulta   ({t_viejo/t_nuevo:5.1f}x)")
    print(f"    numpy + cache (como recordar) : {t_cache*1000:8.2f} ms/consulta   ({t_viejo/t_cache:5.1f}x)")
    print()


# ---------------------------------------------------------------------------
# B) Cerebro: buscar notas relevantes para una consulta de varias palabras
# ---------------------------------------------------------------------------
def bench_cerebro(n_notas=300, repeticiones=15):
    tmp = tempfile.mkdtemp(prefix="bench_vault_")
    random.seed(7)
    palabras = ["python", "docker", "async", "memoria", "vector", "modelo",
                "cerebro", "nota", "proyecto", "codigo", "audio", "whisper"]
    for i in range(n_notas):
        cuerpo = " ".join(random.choices(palabras, k=60))
        with open(os.path.join(tmp, f"nota_{i}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Nota {i}\n\n{cuerpo}\n")

    os.environ["VAULT_PATH"] = tmp
    consulta = "que sabes sobre python async y el modelo de memoria vector"

    def correr():
        return cerebro.consultar_cerebro(consulta, max_notas=3)

    # warm-up (cache de FS)
    correr()
    t = _cronometrar(correr, repeticiones)
    print(f"[B] Cerebro ({n_notas} notas, consulta de varias palabras)")
    print(f"    consultar_cerebro : {t*1000:8.2f} ms/consulta")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("BENCHMARK Bridget2")
    print("=" * 60)
    bench_memoria()
    bench_cerebro()
