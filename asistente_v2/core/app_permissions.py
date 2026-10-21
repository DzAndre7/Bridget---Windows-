"""Allowlist local de aplicaciones. Sin comandos, argumentos ni descubrimiento LLM."""
import json
import os
import sys
from pathlib import Path
from core.runtime_paths import data_file


def policy():
    path = Path(os.environ.get("BRIDGET_APPS_FILE", data_file("applications.json")))
    try:
        if path.stat().st_size > 64 * 1024:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - {"applications", "browser", "automation"}:
            return {}
        apps = data.get("applications", {})
        if not isinstance(apps, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in apps.items()):
            return {}
        return data
    except (OSError, ValueError):
        return {}


def approved_apps():
    result = {}
    for name, value in policy().get("applications", {}).items():
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            continue
        if sys.platform == "win32" and path.suffix.lower() != ".exe":
            continue  # .cmd/.bat/.ps1 no se lanzan mediante shell.
        if sys.platform != "win32" and not os.access(path, os.X_OK):
            continue
        result[name.casefold().strip()] = str(path)
    return result


def find_apps(term):
    term = term.casefold().strip()
    return [(name, name) for name in approved_apps() if term and term in name][:4]


def require_automation(confirmed):
    if confirmed is not True or policy().get("automation") is not True:
        raise PermissionError("Automatización requiere permiso local y confirmación explícita")
