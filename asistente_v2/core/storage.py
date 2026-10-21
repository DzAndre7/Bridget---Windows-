"""Escritura JSON atómica, también en Windows (cerrar antes de os.replace)."""
import json
import os
import tempfile
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".bridget_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
