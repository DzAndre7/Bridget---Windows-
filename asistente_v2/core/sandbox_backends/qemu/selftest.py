"""QA manual: python -m core.sandbox_backends.qemu.selftest --bundle RUTA.

Requiere Windows y un bundle íntegro preparado en una máquina limpia. La prueba
NO habilita el backend ni acepta snippets. Ctrl+C cancela la VM y su Job.
"""
import argparse
import json
import threading

from .experimental import QemuExperimental


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()
    cancel = threading.Event()
    backend = QemuExperimental(args.bundle)
    try:
        result = backend.autoprueba(cancel)
    except KeyboardInterrupt:
        cancel.set()
        print(json.dumps({"cancelado": True, "ejecucion_dinamica_habilitada": False}))
        return 130
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"error": "Bundle/runtime no validado; no se habilitó ejecución."}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["autoprueba_correcta"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
