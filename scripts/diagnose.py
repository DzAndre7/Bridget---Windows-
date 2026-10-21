"""Se puede ejecutar sin instalar dependencias; no importa la aplicación."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "asistente_v2"))

if __name__ == "__main__":
    from core.diagnostics import main
    raise SystemExit(main())
