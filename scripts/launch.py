"""Arranque estable desde cualquier cwd, datos separados y API solo loopback."""
import argparse
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "asistente_v2"))


def prepare():
    from core.runtime_paths import default_data_dir
    # Cargar configuración antes de elegir datos e importar módulos de estado.
    from config import ASSISTANT_NAME
    data = Path(os.environ.get("BRIDGET_DATA_DIR", default_data_dir())).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ["BRIDGET_DATA_DIR"] = str(data)
    return ASSISTANT_NAME


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["text", "desktop", "api", "diagnose"], default="text", nargs="?")
    args, extra = parser.parse_known_args(argv)
    prepare()
    if args.mode == "diagnose":
        from core.diagnostics import main as diagnose
        return diagnose(extra)
    if extra:
        parser.error("Opciones desconocidas: " + " ".join(extra))
    if args.mode == "api":
        if not os.environ.get("BRIDGET_API_KEY"):
            parser.error("Configurar BRIDGET_API_KEY antes de iniciar API")
        import uvicorn
        uvicorn.run("api:app", host="127.0.0.1", port=8000)
    else:
        target = "main.py" if args.mode == "text" else "interfaz/ventana.py"
        runpy.run_path(str(ROOT / "asistente_v2" / target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
