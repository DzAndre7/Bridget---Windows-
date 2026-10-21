"""Modelos y datos sintéticos. Nunca se contacta Ollama ni un vault personal."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import local_models, memoria_semantica as semantic, cerebro, diagnostics


@pytest.mark.parametrize("value", ["https://example.com:443", "http://127.0.0.1:11434/path", "http://user:secret@localhost:11434", "http://localhost:11434?token=x", "http://localhost", "http://localhost:99999"])
def test_ollama_rejects_nonlocal_or_credential_endpoints(value, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", value)
    with pytest.raises(ValueError):
        local_models.endpoint()


def test_ollama_client_is_lazy_bounded_and_no_proxy(monkeypatch):
    import sys
    local_models._client.cache_clear()
    client = Mock()
    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=client))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    local_models.ollama.chat(model="synthetic")
    local_models.ollama.embeddings(model="synthetic")
    client.assert_called_once_with(host="http://127.0.0.1:11434", timeout=120, trust_env=False, follow_redirects=False)
    local_models._client.cache_clear()


@pytest.fixture
def memory_file(tmp_path, monkeypatch):
    path = tmp_path / "memoria_semantica.json"
    monkeypatch.setattr(semantic, "MEMORIA_FILE", str(path))
    monkeypatch.setattr(semantic, "_cache", {"mtime": None, "memoria": [], "con_emb": [], "matriz": None, "normas": None})
    monkeypatch.setattr(semantic, "obtener_embedding", lambda text, tipo="document": [1., 0., 0.])
    return path


def test_semantic_roundtrip_unicode_and_model(memory_file):
    assert semantic.guardar_recuerdo("Me gusta la música", "personal")
    assert semantic.recordar("música")[0]["texto"] == "Me gusta la música"
    record = json.loads(memory_file.read_text(encoding="utf-8"))[0]
    assert record["embedding_model"] == semantic.MODELO_EMBEDDINGS
    assert not list(memory_file.parent.glob("*.tmp"))


def test_semantic_bad_dimensions_and_other_model_do_not_crash(memory_file):
    memory_file.write_text(json.dumps([
        {"texto": "correcto", "embedding": [1, 0, 0]},
        {"texto": "dimensión distinta", "embedding": [1, 0]},
        {"texto": "otro modelo", "embedding_model": "other", "embedding": [1, 0, 0]},
        {"texto": "inválido", "embedding": ["NaN", 0, 0]},
    ]), encoding="utf-8")
    assert [r["texto"] for r in semantic.recordar("x")] == ["correcto"]
    assert semantic.puntuar_memoria([], [1], top_k=0) == []


def test_semantic_corrupt_file_is_not_overwritten(memory_file):
    memory_file.write_text("{broken")
    assert semantic.recordar("x") == []
    with pytest.raises(ValueError):
        semantic.guardar_recuerdo("new")
    assert memory_file.read_text() == "{broken"


def test_semantic_write_invalidates_cache(memory_file):
    semantic.guardar_recuerdo("uno")
    assert len(semantic.cargar_memoria()) == 1
    semantic.guardar_recuerdo("dos")
    assert len(semantic.cargar_memoria()) == 2


def test_invalid_embedding_response_rejected(monkeypatch):
    monkeypatch.setattr(semantic, "ollama", SimpleNamespace(embeddings=lambda **kw: {"embedding": [float("nan")]}))
    with pytest.raises(ValueError):
        semantic.obtener_embedding("test")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    path = tmp_path / "Vault con espacios á"
    path.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(path))
    return path


def test_obsidian_unicode_roundtrip_excludes_internal_notes(vault):
    result = cerebro.guardar_nota('Idea: música?', 'Música sintética', carpeta="proyectos")
    assert Path(result).name == 'Idea música.md'
    assert "Música sintética" in cerebro.leer_nota("Idea música")
    internal = vault / ".obsidian"
    internal.mkdir()
    (internal / "secret.md").write_text("Música interna")
    assert len(cerebro.listar_notas()) == 1
    assert len(cerebro.consultar_cerebro("música")) == 1


@pytest.mark.parametrize("name", ["CON", "nul.txt", "LPT1", "COM9", "nombre. ", "\x00"])
def test_obsidian_portable_windows_names(name):
    safe = cerebro._limpiar_nombre_archivo(name)
    assert safe and not safe.endswith((".", " ")) and "\x00" not in safe
    assert safe.split(".")[0].upper() not in {"CON", "NUL", "LPT1", "COM9"}


def test_obsidian_no_traversal_or_internal_write(vault):
    for category in ["../outside", ".obsidian", ".TRASH"]:
        with pytest.raises(ValueError):
            cerebro.guardar_nota("nota", "dato", carpeta=category)
    assert not (vault.parent / "outside").exists()


def test_obsidian_links_outside_vault_are_not_read(vault, tmp_path):
    outside = tmp_path / "private.md"
    outside.write_text("dato externo")
    link = vault / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Sin permisos para symlinks")
    assert cerebro.leer_nota("link") is None


def test_diagnostic_default_never_contacts_services(monkeypatch):
    monkeypatch.setattr(diagnostics, "ollama_status", Mock(side_effect=AssertionError("No service probe")))
    monkeypatch.setattr(diagnostics.importlib.metadata, "version", lambda name: "test")
    result = diagnostics.report()
    assert result["hardware_validated"] is False
    assert next(c for c in result["checks"] if c["component"] == "ejecucion_dinamica")["status"] == "blocked"


def test_diagnostic_reports_missing_models_and_service_errors(monkeypatch):
    from config import MODELO_CONVERSACION
    monkeypatch.setattr(diagnostics, "ollama_status", lambda: [MODELO_CONVERSACION])
    checks = diagnostics.report(probe_ollama=True)["checks"]
    assert next(c for c in checks if c["component"] == "modelo/chat")["status"] == "ok"
    monkeypatch.setattr(diagnostics, "ollama_status", Mock(side_effect=OSError))
    checks = diagnostics.report(probe_ollama=True)["checks"]
    assert next(c for c in checks if c["component"] == "ollama_servicio")["status"] == "error"


def test_ollama_probe_no_proxy_no_redirect_bounded(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"models":[{"name":"test:latest"}]}'
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(diagnostics.urllib.request, "build_opener", factory)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    assert diagnostics.ollama_status() == ["test:latest"]
    assert factory.call_args.args[0].proxies == {}
    assert isinstance(factory.call_args.args[1], diagnostics.NoRedirect)
    opener.open.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=3)
    response.read.return_value = b"x" * (1024 * 1024 + 1)
    with pytest.raises(ValueError):
        diagnostics.ollama_status()


def test_native_diagnostic_uses_only_fixed_imports_and_timeout(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(diagnostics.subprocess, "run", run)
    checks = diagnostics.report(native_imports=True)["checks"]
    assert len([c for c in checks if c["component"].startswith("import/") and c["status"] == "ok"]) == 6
    for call in run.call_args_list:
        assert call.args[0][-1] in {"numpy", "sounddevice", "scipy", "faster_whisper", "webrtcvad", "webview"}
        assert call.kwargs["timeout"] == 15
        assert call.kwargs["stderr"] == diagnostics.subprocess.DEVNULL
        assert "-I" in call.args[0] and not call.kwargs.get("shell", False)
    run.side_effect = diagnostics.subprocess.TimeoutExpired("python", 15)
    checks = diagnostics.report(native_imports=True)["checks"]
    assert all(c["status"] == "error" for c in checks if c["component"].startswith("import/"))


def test_diagnostic_runs_with_only_stdlib_and_fails_strict_for_missing_packages():
    # -I -S elimina site-packages y PYTHONPATH: funciona antes del instalador.
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[2] / "scripts/diagnose.py"
    result = subprocess.run([sys.executable, "-I", "-S", str(script), "--json", "--strict"],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert any(c["component"] == "texto/ollama" and c["status"] == "missing" for c in data["checks"])
    assert next(c for c in data["checks"] if c["component"] == "ejecucion_dinamica")["status"] == "blocked"
