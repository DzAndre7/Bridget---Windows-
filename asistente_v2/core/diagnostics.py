"""Diagnóstico sin activar modelos, escritorio, micrófono ni acciones."""
import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from core.local_models import endpoint
from core.runtime_paths import default_data_dir

PACKAGES = {
    "texto": ["ollama", "requests", "python-dotenv", "numpy", "ddgs", "groq", "ruff"],
    "voz": ["sounddevice", "scipy", "faster-whisper", "webrtcvad-wheels"],
    "ventana": ["pywebview", "pillow"],
    "api": ["fastapi", "uvicorn", "python-multipart", "slowapi", "pywebpush"],
    "tts_coqui_opcional": ["coqui-tts", "torch", "torchaudio"],
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ollama_status():
    # No hereda proxies, no sigue redirects, solo endpoint de loopback validado.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(endpoint() + "/api/tags", timeout=3) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Respuesta de Ollama demasiado grande")
    data = json.loads(raw)
    models = data["models"]
    if not isinstance(models, list):
        raise ValueError("Respuesta inválida")
    return [m["name"] for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]


def report(*, probe_ollama=False, audio_devices=False, native_imports=False):
    # El diagnóstico sigue funcionando sin python-dotenv instalado.
    try:
        import config
    except ModuleNotFoundError:
        config = None
    checks = []

    def add(component, status, detail):
        checks.append({"component": component, "status": status, "detail": detail})

    add("python", "ok" if sys.version_info[:2] == (3, 11) else "warning", "Objetivo: CPython 3.11 x64; actual " + sys.version.split()[0])
    add("arquitectura", "ok" if sys.maxsize > 2 ** 32 else "error", "Se requiere Python de 64 bits")
    for group, packages in PACKAGES.items():
        for package in packages:
            try:
                version = importlib.metadata.version(package)
                add(group + "/" + package, "ok", version)
            except importlib.metadata.PackageNotFoundError:
                add(group + "/" + package, "missing", "Componente no instalado")
    data = Path(os.environ.get("BRIDGET_DATA_DIR", default_data_dir())).expanduser()
    parent = data if data.exists() else data.parent
    add("datos", "ok" if parent.is_dir() and os.access(parent, os.W_OK) else "warning", "Directorio de datos disponible" if data.is_dir() else "El launcher debe crear el directorio de datos")
    vault = os.environ.get("VAULT_PATH")
    add("obsidian", "ok" if vault and Path(vault).is_absolute() and Path(vault).is_dir() else "missing", "Vault configurado; no se leen notas" if vault else "VAULT_PATH opcional sin configurar")
    from core.app_permissions import approved_apps
    add("aplicaciones", "ok", f"{len(approved_apps())} aplicaciones autorizadas; cada apertura requiere confirmación")
    from core.sandbox_backends import obtener_backend
    state = obtener_backend().estado()
    add("ejecucion_dinamica", "blocked" if not state.disponible else "error", "Debe permanecer bloqueada; QEMU no se activa")
    if sys.platform == "win32":
        import winreg
        installed = False
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in (r"SOFTWARE\Microsoft\EdgeUpdate\Clients", r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"):
                try:
                    with winreg.OpenKey(hive, subkey) as clients:
                        for i in range(winreg.QueryInfoKey(clients)[0]):
                            with winreg.OpenKey(clients, winreg.EnumKey(clients, i)) as product:
                                try:
                                    name = winreg.QueryValueEx(product, "name")[0]
                                    version = winreg.QueryValueEx(product, "pv")[0]
                                    installed |= "webview2" in name.casefold() and bool(version and version != "0.0.0.0")
                                except OSError:
                                    pass
                except OSError:
                    pass
        add("webview2", "ok" if installed else "warning", "Runtime detectado" if installed else "No detectado; verificar instalación de Edge WebView2 Runtime")
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        add("tts_sapi", "ok" if (system / "System32/WindowsPowerShell/v1.0/powershell.exe").is_file() else "missing", "Requiere System.Speech, voz instalada y PowerShell permitido; ejecutar prueba manual")
    try:
        host = endpoint()
        add("ollama_endpoint", "ok", host)
        if probe_ollama:
            models = ollama_status()
            add("ollama_servicio", "ok", "Servicio local respondió; modelos: " + str(len(models)))
            for role, model in [("chat", getattr(config, "MODELO_CONVERSACION", "dolphin3:8b")),
                                ("embeddings", getattr(config, "MODELO_EMBEDDINGS", "nomic-embed-text-v2-moe")),
                                ("vision", getattr(config, "MODELO_VISION", "llava"))]:
                normalized = model if ":" in model else model + ":latest"
                add("modelo/" + role, "ok" if model in models or normalized in models else "missing", model)
        else:
            add("ollama_servicio", "untested", "Usar --probe-ollama para consultar el servicio local; no descarga modelos")
    except (OSError, ValueError, KeyError, TypeError):
        add("ollama_servicio", "error", "Endpoint inválido, servicio inaccesible o respuesta inválida")
    if native_imports:
        # Solo módulos fijos instalados por el usuario. No modelos ni código LLM.
        for module in ("numpy", "sounddevice", "scipy", "faster_whisper", "webrtcvad", "webview"):
            try:
                process = subprocess.run(
                    [sys.executable, "-I", "-c", "import importlib,sys; importlib.import_module(sys.argv[1])", module],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
                )
                add("import/" + module, "ok" if process.returncode == 0 else "error", "Import verificado" if process.returncode == 0 else "Import falló: dependencia o runtime nativo ausente")
            except (OSError, subprocess.TimeoutExpired):
                add("import/" + module, "error", "Import no terminó o no se pudo iniciar")
    if audio_devices:
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            add("dispositivos_audio", "ok", [{"index": i, "name": d["name"], "input": d["max_input_channels"], "output": d["max_output_channels"]} for i, d in enumerate(devices)])
        except Exception:
            add("dispositivos_audio", "error", "No se pudo consultar PortAudio; no se grabó ni reprodujo audio")
    else:
        add("dispositivos_audio", "untested", "Usar --audio-devices; solo enumera, no graba")
    return {"platform": sys.platform, "checks": checks, "hardware_validated": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-ollama", action="store_true")
    parser.add_argument("--audio-devices", action="store_true")
    parser.add_argument("--native-imports", action="store_true", help="Importa módulos fijos en procesos separados; no activa hardware/modelos")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Devuelve 1 si faltan dependencias de texto o hay errores")
    args = parser.parse_args(argv)
    result = report(probe_ollama=args.probe_ollama, audio_devices=args.audio_devices, native_imports=args.native_imports)
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        for item in result["checks"]:
            print(f"[{item['status']}] {item['component']}: {item['detail']}")
    failed = any(c["status"] == "error" or ((c["component"].startswith("texto/") or c["component"] in {"modelo/chat", "modelo/embeddings"}) and c["status"] == "missing") for c in result["checks"])
    return 1 if args.strict and failed else 0
