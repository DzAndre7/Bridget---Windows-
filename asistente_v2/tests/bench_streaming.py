"""Mide el beneficio real del streaming por frases a través del camino de
producción `brain.consultar_llama` (con dolphin3:8b, vault y embeddings reales).

Usa un sink que sólo cronometra cuándo llega cada frase (no reproduce audio),
para aislar la ganancia de latencia percibida:

    python tests/bench_streaming.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.brain as brain


def bench(prompt):
    tiempos = []
    frases = []
    t0 = time.perf_counter()

    def sink(iterable_frases):
        for f in iterable_frases:
            tiempos.append(time.perf_counter() - t0)
            frases.append(f)

    brain.usar_sink_de_frases(sink)
    try:
        completo = brain.consultar_llama(prompt)
    finally:
        brain.usar_sink_de_frases(None)
    total = time.perf_counter() - t0

    print(f"prompt: {prompt!r}")
    print(f"  frases habladas        : {len(frases)}")
    if tiempos:
        print(f"  1ª frase lista a       : {tiempos[0]:6.2f}s  <- cuándo Bridget empieza a hablar")
        print(f"  última frase lista a   : {tiempos[-1]:6.2f}s")
    print(f"  respuesta completa a   : {total:6.2f}s")
    if tiempos:
        print(f"  silencio inicial evitado: {total - tiempos[0]:6.2f}s  (antes se esperaba TODO)")
    print()
    print("  Primeras frases:")
    for t, f in list(zip(tiempos, frases))[:3]:
        print(f"    [{t:5.2f}s] {f}")


if __name__ == "__main__":
    print("=" * 60)
    print("BENCHMARK STREAMING (camino real consultar_llama)")
    print("=" * 60)
    bench("Explicame en 3 o 4 frases qué es un vector y para qué sirve en programación.")
