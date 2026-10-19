"""Tests de actions/system_actions.py: convertir_documento (pandoc).
subprocess se mockea porque no hay pandoc garantizado en CI/sandbox
(sin red, ver core/sandbox.py) — pero sí se ejercita la lógica real de
rutas y manejo de errores.
"""
from unittest.mock import MagicMock

import pytest

from actions import system_actions


def test_archivo_de_entrada_inexistente(tmp_path):
    ok, motivo = system_actions.convertir_documento(str(tmp_path / "no_existe.md"), "pdf")
    assert ok is False
    assert "no encontré" in motivo


def test_convierte_y_arma_la_ruta_de_salida_sola(tmp_path, monkeypatch):
    entrada = tmp_path / "nota.md"
    entrada.write_text("# hola", encoding="utf-8")

    llamado = {}
    def _run_falso(cmd, **kwargs):
        llamado["cmd"] = cmd
        return MagicMock(returncode=0, stderr="")
    monkeypatch.setattr(system_actions.subprocess, "run", _run_falso)

    ok, ruta_salida = system_actions.convertir_documento(str(entrada), "docx")

    assert ok is True
    assert ruta_salida == str(tmp_path / "nota.docx")
    assert llamado["cmd"] == ["pandoc", str(entrada), "-o", str(tmp_path / "nota.docx")]


def test_a_pdf_agrega_el_motor_weasyprint(tmp_path, monkeypatch):
    # pandoc no trae pdflatex (su motor de PDF por defecto): sin esta
    # bandera, cualquier conversión a PDF falla en este sistema.
    entrada = tmp_path / "nota.md"
    entrada.write_text("# hola", encoding="utf-8")

    llamado = {}
    def _run_falso(cmd, **kwargs):
        llamado["cmd"] = cmd
        return MagicMock(returncode=0, stderr="")
    monkeypatch.setattr(system_actions.subprocess, "run", _run_falso)

    system_actions.convertir_documento(str(entrada), "pdf")

    assert "--pdf-engine=weasyprint" in llamado["cmd"]


def test_respeta_ruta_de_salida_explicita(tmp_path, monkeypatch):
    entrada = tmp_path / "nota.md"
    entrada.write_text("# hola", encoding="utf-8")
    salida = tmp_path / "otro_nombre.pdf"

    monkeypatch.setattr(system_actions.subprocess, "run",
                         lambda cmd, **k: MagicMock(returncode=0, stderr=""))

    ok, ruta_salida = system_actions.convertir_documento(str(entrada), "pdf", ruta_salida=str(salida))

    assert ok is True
    assert ruta_salida == str(salida)


def test_pandoc_no_instalado(tmp_path, monkeypatch):
    entrada = tmp_path / "nota.md"
    entrada.write_text("# hola", encoding="utf-8")

    def _sin_pandoc(cmd, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(system_actions.subprocess, "run", _sin_pandoc)

    ok, motivo = system_actions.convertir_documento(str(entrada), "pdf")
    assert ok is False
    assert "no está instalado" in motivo


def test_pandoc_falla_devuelve_el_stderr(tmp_path, monkeypatch):
    entrada = tmp_path / "nota.md"
    entrada.write_text("# hola", encoding="utf-8")

    monkeypatch.setattr(
        system_actions.subprocess, "run",
        lambda cmd, **k: MagicMock(returncode=1, stderr="pandoc: formato desconocido"),
    )

    ok, motivo = system_actions.convertir_documento(str(entrada), "formato-inventado")
    assert ok is False
    assert "formato desconocido" in motivo
