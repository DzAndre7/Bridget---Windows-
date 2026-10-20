"""Adaptadores reales con efectos externos reemplazados; sin abrir aplicaciones."""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from actions import system_actions, agent_actions
from core import app_permissions, runtime_paths, windows_native, notifications, storage
from core.intenciones import extraer_ruta_archivo, extraer_conversion


@pytest.fixture
def allowed_app(tmp_path, monkeypatch):
    app = tmp_path / "Aplicación con espacios.exe"
    app.touch()
    app.chmod(0o755)
    policy = tmp_path / "applications.json"
    policy.write_text(json.dumps({"applications": {"editor": str(app)}, "browser": True}), encoding="utf-8")
    monkeypatch.setenv("BRIDGET_APPS_FILE", str(policy))
    return app


def test_app_needs_explicit_confirmation_and_allowlist(allowed_app, monkeypatch):
    launch = Mock()
    monkeypatch.setattr(system_actions.subprocess, "Popen", launch)
    assert not system_actions.abrir_programa("editor")
    assert not system_actions.abrir_programa("editor", confirmado=1)
    assert not system_actions.abrir_programa("editor --argument", confirmado=True)
    launch.assert_not_called()
    assert system_actions.abrir_programa("EDITOR", confirmado=True)
    launch.assert_called_once_with([str(allowed_app)], shell=False)


def test_app_discovery_only_returns_local_permissions(allowed_app):
    assert agent_actions.buscar_aplicaciones_sistema("edit") == [("editor", "editor")]
    assert not agent_actions.buscar_aplicaciones_sistema("powershell")


def test_changed_policy_revokes_permission(allowed_app, monkeypatch):
    path = Path(os.environ["BRIDGET_APPS_FILE"])
    assert app_permissions.approved_apps()
    path.write_text('{"applications": {}}')
    launch = Mock()
    monkeypatch.setattr(system_actions.subprocess, "Popen", launch)
    assert not system_actions.abrir_programa("editor", confirmado=True)
    launch.assert_not_called()


def test_windows_rejects_batch_file(tmp_path, monkeypatch):
    app = tmp_path / "script.cmd"
    app.touch()
    monkeypatch.setattr(app_permissions, "policy", lambda: {"applications": {"script": str(app)}})
    monkeypatch.setattr(app_permissions, "sys", SimpleNamespace(platform="win32"))
    assert not app_permissions.approved_apps()


def test_browser_is_encoded_and_opt_in(allowed_app, monkeypatch):
    open_url = Mock(return_value=True)
    monkeypatch.setattr(system_actions.webbrowser, "open", open_url)
    text = "hola & calc.exe; ñ"
    assert not system_actions.buscar_en_internet(text)
    assert system_actions.buscar_en_internet(text, confirmado=True)
    assert open_url.call_args.args[0] == "https://www.google.com/search?q=hola+%26+calc.exe%3B+%C3%B1"
    monkeypatch.setattr(system_actions, "policy", lambda: {})
    assert not system_actions.buscar_en_internet(text, confirmado=True)


def test_automation_rejects_before_importing_pyautogui(monkeypatch):
    monkeypatch.setattr(app_permissions, "policy", lambda: {})
    with pytest.raises(PermissionError):
        agent_actions.clickear(1, 2)
    with pytest.raises(PermissionError):
        agent_actions.escribir("data", confirmado=True)


def test_automation_preserves_failsafe(monkeypatch):
    import sys
    desktop = SimpleNamespace(FAILSAFE=False, click=Mock())
    monkeypatch.setitem(sys.modules, "pyautogui", desktop)
    monkeypatch.setattr(app_permissions, "policy", lambda: {"automation": True})
    agent_actions.clickear(2, 3, confirmado=True)
    assert desktop.FAILSAFE is True
    desktop.click.assert_called_once_with(2, 3)


def test_confirmation_clears_session_and_never_executes_model_commands(monkeypatch):
    # Función revisada sin inicializar el resto de brain ni red/modelos.
    source = Path(__file__).parents[1] / "core/brain.py"
    function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "_resolver_confirmacion_tarea")
    launch = Mock(return_value=True)
    scope = {"abrir_programa": launch}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    session = SimpleNamespace(opciones_pendientes=[], plan_pendiente="editor", plan_nombre="Editor", esperando_confirmacion_tarea=True)
    assert "Ejecutando" in scope[function.name]("sí", session)
    launch.assert_called_once_with("editor", confirmado=True)
    assert not session.esperando_confirmacion_tarea and not session.plan_pendiente
    assert scope[function.name]("sí", session) == "Tarea cancelada."
    assert launch.call_count == 1


@pytest.mark.parametrize("text,expected", [
    ('leé "C:\\Mis notas\\Nota Á.md"', 'C:\\Mis notas\\Nota Á.md'),
    ('analiza C:/Notas/test.py', 'C:/Notas/test.py'),
    ('leé /home/user/nota.md', '/home/user/nota.md'),
    ('leé "~/Mis notas/test.md"', '~/Mis notas/test.md'),
])
def test_path_extraction_preserves_case_spaces_and_unicode(text, expected):
    assert extraer_ruta_archivo(text) == expected


def test_windows_conversion_path():
    assert extraer_conversion('convertí "C:\\Notas grandes\\Hola.md" a pdf') == ('C:\\Notas grandes\\Hola.md', 'pdf')


def test_temp_file_can_be_reopened_and_is_cleaned_after_error():
    path = None
    with pytest.raises(RuntimeError):
        with runtime_paths.temporary_file() as path:
            Path(path).write_bytes(b"closed handle")
            raise RuntimeError()
    assert not Path(path).exists()


def test_data_override_and_legacy_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("BRIDGET_DATA_DIR", raising=False)
    assert runtime_paths.data_file("memory.json", "legacy.json") == "legacy.json"
    monkeypatch.setenv("BRIDGET_DATA_DIR", str(tmp_path))
    assert runtime_paths.data_file("memory.json", "legacy.json") == str(tmp_path / "memory.json")


def test_atomic_json_failure_keeps_old_data(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('["anterior"]')
    monkeypatch.setattr(storage.os, "replace", Mock(side_effect=PermissionError))
    with pytest.raises(PermissionError):
        storage.write_json(path, ["nuevo"])
    assert json.loads(path.read_text()) == ["anterior"]
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("script,payload", [
    (windows_native.TTS_SCRIPT, {"text": "'; calc.exe; $env:HOME", "path": "C:/audio.wav"}),
    (windows_native.NOTIFY_SCRIPT, {"title": "`$(bad)", "text": "'; Start-Process evil"}),
])
def test_windows_native_payload_is_data_not_script(script, payload, monkeypatch):
    monkeypatch.setattr(windows_native, "os", SimpleNamespace(name="nt", environ={"SystemRoot": "C:/Windows"}))
    run = Mock()
    monkeypatch.setattr(windows_native.subprocess, "run", run)
    windows_native.powershell(script, payload, 5)
    args, kwargs = run.call_args
    assert args[0][-1] == script
    assert "-NoProfile" in args[0]
    assert json.loads(kwargs["input"]) == payload
    assert not kwargs.get("shell", False)
    assert kwargs["timeout"] == 5 and kwargs["check"] is True


def test_notifications_linux_and_windows(monkeypatch):
    run = Mock()
    monkeypatch.setattr(notifications.subprocess, "run", run)
    monkeypatch.setattr(notifications, "sys", SimpleNamespace(platform="linux"))
    assert notifications.notify("Bridget", "--not-option")
    assert run.call_args.args[0][-3:] == ["--", "Bridget", "--not-option"]
    native = Mock()
    monkeypatch.setattr(windows_native, "powershell", native)
    monkeypatch.setattr(notifications, "sys", SimpleNamespace(platform="win32"))
    assert notifications.notify("Bridget", "recordatorio")
    assert native.call_args.args[0] == windows_native.NOTIFY_SCRIPT


def test_authorized_app_proposal_does_not_need_ollama():
    source = Path(__file__).parents[1] / "core/brain.py"
    function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "_cmd_ejecutar_tarea")
    llm = Mock(side_effect=AssertionError("No Ollama required"))
    scope = {"normalizar_nombre_programa": lambda name: name,
             "extraer_objeto_apertura": lambda text: "editor",
             "buscar_aplicaciones_sistema": lambda term: [("editor", "editor")],
             "extraer_programa_con_llama": llm}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    session = SimpleNamespace(esperando_confirmacion_tarea=False, plan_pendiente="", plan_nombre="")
    assert "¿Lo abro?" in scope[function.name]("abri editor", "abrí editor", session, "Bridget")
    assert session.esperando_confirmacion_tarea and session.plan_pendiente == "editor"
    llm.assert_not_called()


@pytest.mark.parametrize("command", ["hola", "escuchame", "modo voz"])
def test_cli_keeps_running_after_component_failure(command, monkeypatch, capsys):
    from core import agenda
    source = Path(__file__).parents[1] / "main.py"
    function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    session = SimpleNamespace(historial_anterior=[])
    failure = Mock(side_effect=OSError("unavailable"))
    scope = {"sesiones": SimpleNamespace(abrir_sesion=lambda **k: session),
             "ASSISTANT_NAME": "Bridget", "ASSISTANT_CREATOR": "Usuario",
             "brain": SimpleNamespace(_llm_directo=Mock()), "usar_sink_de_frases": Mock(),
             "obtener_saludo": lambda: "Hola", "obtener_nombre_preferido": lambda: None,
             "procesar_comando": failure, "escuchar": failure,
             "modo_voz_interrumpible": failure, "VOZ_ACTIVADA": False,
             "hablar_por_frases": Mock()}
    monkeypatch.setattr(agenda, "iniciar_avisador", Mock())
    monkeypatch.setattr("builtins.input", Mock(side_effect=[command, "salir"]))
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    scope[function.name]()
    output = capsys.readouterr().out
    assert "Revisá" in output or "revisá" in output
    assert "Nos vemos" in output
    failure.assert_called_once()
