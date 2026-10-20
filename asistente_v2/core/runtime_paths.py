"""Rutas portables. El launcher opta por datos separados; no migra datos antiguos."""
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent


def data_file(name, legacy=None):
    configured = os.environ.get("BRIDGET_DATA_DIR")
    return str(Path(configured).expanduser().resolve() / name) if configured else str(legacy or APP_DIR / name)


def default_data_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Bridget"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "bridget"


@contextmanager
def temporary_file(suffix=".wav"):
    descriptor, name = tempfile.mkstemp(prefix="bridget_", suffix=suffix)
    os.close(descriptor)  # Windows: cerrar antes de reabrir con scipy/TTS.
    try:
        yield name
    finally:
        Path(name).unlink(missing_ok=True)
