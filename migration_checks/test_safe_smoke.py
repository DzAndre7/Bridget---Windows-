"""Comprobaciones sin dependencias de terceros, modelos, red ni escritorio.

Ejecutar desde la raíz: python -m unittest discover -s migration_checks -v
"""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "asistente_v2"))

# Imports revisados: estos módulos solo definen funciones, constantes y locks.
from actions import system_actions
from core import memory, preferences


class StaticChecks(unittest.TestCase):
    def test_python_syntax(self):
        for path in sorted(ROOT.rglob("*.py")):
            with self.subTest(path=str(path.relative_to(ROOT))):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_json_syntax(self):
        for path in sorted((ROOT / "asistente_v2").rglob("*.json")):
            with self.subTest(path=str(path.relative_to(ROOT))):
                json.loads(path.read_text(encoding="utf-8"))


class StorageChecks(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="bridget_migration_check_")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for module, name, filename in [
            (preferences, "PREFERENCES_FILE", "preferences.json"),
            (memory, "MEMORY_FILE", "memory.json"),
        ]:
            replacement = patch.object(module, name, str(self.folder / filename))
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_preferences_missing(self):
        self.assertEqual(preferences.cargar_preferencias(), {})

    def test_preferences_unicode_roundtrip_and_update(self):
        self.assertTrue(preferences.guardar_preferencia("editor", "edición de prueba"))
        self.assertEqual(preferences.obtener_preferencia("editor"), "edición de prueba")
        self.assertTrue(preferences.guardar_preferencia("editor", "otro"))
        self.assertEqual(preferences.obtener_preferencia("editor"), "otro")

    def test_preferences_corrupt_json(self):
        Path(preferences.PREFERENCES_FILE).write_text("{invalid", encoding="utf-8")
        self.assertEqual(preferences.cargar_preferencias(), {})

    def test_preferences_unwritable_parent(self):
        with patch.object(preferences, "PREFERENCES_FILE", str(self.folder / "missing" / "file.json")):
            self.assertFalse(preferences.guardar_preferencia("editor", "otro"))

    def test_memory_deduplicates_and_forgets(self):
        self.assertEqual(memory.leer_recuerdos(), [])
        self.assertTrue(memory.guardar_recuerdo("dato sintético"))
        self.assertFalse(memory.guardar_recuerdo("dato sintético"))
        self.assertEqual(memory.leer_recuerdos(), ["dato sintético"])
        self.assertTrue(memory.olvidar_recuerdo("dato sintético"))
        self.assertFalse(memory.olvidar_recuerdo("dato sintético"))

    def test_memory_clear_only_temporary_file(self):
        memory.guardar_recuerdo("dato sintético")
        self.assertTrue(memory.borrar_todos_los_recuerdos())
        self.assertEqual(memory.leer_recuerdos(), [])


class ConversionChecks(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="bridget_migration_conversion_")
        self.addCleanup(folder.cleanup)
        self.input = Path(folder.name) / "documento con espacios.md"
        self.input.write_text("# Documento sintético", encoding="utf-8")
        # Ningún caso puede lanzar un programa real.
        guard = patch.object(subprocess, "Popen", side_effect=AssertionError("Proceso externo no permitido"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_missing_input(self):
        self.assertFalse(system_actions.convertir_documento(str(self.input) + ".missing", "pdf")[0])

    def test_docx_arguments_keep_spaces(self):
        with patch.object(subprocess, "run", return_value=Mock(returncode=0)) as run:
            ok, output = system_actions.convertir_documento(str(self.input), "docx")
        self.assertTrue(ok)
        self.assertEqual(output, str(self.input.with_suffix(".docx")))
        self.assertEqual(run.call_args.args[0], ["pandoc", str(self.input), "-o", output])

    def test_pdf_engine(self):
        with patch.object(subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertTrue(system_actions.convertir_documento(str(self.input), "pdf")[0])
        self.assertIn("--pdf-engine=weasyprint", run.call_args.args[0])

    def test_explicit_output(self):
        output = str(self.input.with_name("otro.docx"))
        with patch.object(subprocess, "run", return_value=Mock(returncode=0)):
            self.assertEqual(system_actions.convertir_documento(str(self.input), "docx", output), (True, output))

    def test_missing_pandoc(self):
        with patch.object(subprocess, "run", side_effect=FileNotFoundError):
            self.assertIn("no está instalado", system_actions.convertir_documento(str(self.input), "pdf")[1])

    def test_timeout(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("pandoc", 60)):
            self.assertIn("canceló", system_actions.convertir_documento(str(self.input), "pdf")[1])

    def test_error_output_is_bounded(self):
        with patch.object(subprocess, "run", return_value=Mock(returncode=1, stderr="x" * 1000)):
            ok, message = system_actions.convertir_documento(str(self.input), "invalid")
        self.assertFalse(ok)
        self.assertEqual(len(message), 500)


if __name__ == "__main__":
    unittest.main()
