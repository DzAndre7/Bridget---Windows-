"""Prueba inicial sintética: no audio, escritorio, vault personal ni código generado."""
import argparse
import os
import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "asistente_v2"))


def run(*, local_models=False):
    # Usar proceso separado: importar almacenamiento solo después de aislar sus rutas.
    with tempfile.TemporaryDirectory(prefix="bridget_smoke_") as directory:
        os.environ["BRIDGET_DATA_DIR"] = directory
        os.environ["BRIDGET_ENV_FILE"] = str(Path(directory) / "no-env")
        os.environ["BRIDGET_APPS_FILE"] = str(Path(directory) / "no-apps.json")
        os.environ["VAULT_PATH"] = str(Path(directory) / "vault")
        Path(os.environ["VAULT_PATH"]).mkdir()
        from core import memory, cerebro, sandbox
        from core.brain import Sesion, procesar_comando
        from actions.system_actions import abrir_programa
        assert procesar_comando("hola", "Bridget", Sesion())
        assert memory.guardar_recuerdo("dato sintético de prueba")
        assert memory.leer_recuerdos() == ["dato sintético de prueba"]
        assert cerebro.guardar_nota("Nota sintética", "Bridget funciona", carpeta="pruebas")
        assert cerebro.leer_nota("Nota sintética")
        assert not sandbox.estado_aislamiento().disponible
        assert sandbox.ejecutar_codigo("print('NO EJECUTAR')")["exito"] is False
        assert abrir_programa("aplicacion-no-autorizada", confirmado=True) is False
        cli_env = dict(os.environ, BRIDGET_VOICE="0")
        cli = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "launch.py"), "text"],
            input="hola\nque hora es\nsalir\n", encoding="utf-8", capture_output=True,
            cwd=directory, env=cli_env, timeout=15, check=True,
        )
        assert "Son las" in cli.stdout and "Nos vemos" in cli.stdout
        if local_models:
            from core.local_models import ollama
            from config import MODELO_CONVERSACION
            from core import memoria_semantica as semantic
            response = ollama.chat(model=MODELO_CONVERSACION, messages=[{"role": "user", "content": "Respondé únicamente: hola"}], options={"num_predict": 12})
            assert response["message"]["content"].strip()
            semantic.guardar_recuerdo("Mi color de prueba es violeta")
            assert semantic.recordar("color violeta", umbral=-1)
        return {"synthetic_smoke": "ok", "cli": "ok", "local_models": "ok" if local_models else "not_tested", "dynamic_execution": "blocked"}


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", action="store_true", help="Consulta chat/embeddings locales con datos sintéticos; no descarga modelos")
    args = parser.parse_args()
    print(json.dumps(run(local_models=args.ollama)))
