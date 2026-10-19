"""Contratos de los perfiles; no sustituyen resolver e instalar en Windows."""
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def cargar(path):
    resultado = []
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if linea.startswith("-r "):
            resultado.extend(cargar(path.parent / linea[3:]))
        else:
            resultado.append(Requirement(linea))
    return resultado


def seleccion_windows():
    entorno = default_environment()
    entorno.update(sys_platform="win32", platform_system="Windows",
                   python_version="3.11", python_full_version="3.11.9")
    return {r.name.lower(): r for r in cargar(ROOT / "requirements" / "windows.txt")
            if r.marker is None or r.marker.evaluate(entorno)}


def test_windows_no_arrastra_congelado_linux_o_cuda_fijo():
    seleccion = seleccion_windows()
    assert not {"python3-xlib", "triton", "tts", "pyqt6"} & seleccion.keys()
    assert not any(n.startswith("nvidia-") for n in seleccion)
    assert seleccion["torchaudio"].specifier.contains("2.5.1")
    assert not seleccion["torchaudio"].specifier.contains("2.2.0+cu121")


def test_dependencias_omitidas_ahora_explicitas_y_sin_doble_vad():
    seleccion = seleccion_windows()
    assert {"pywebpush", "faster-whisper", "webrtcvad-wheels", "coqui-tts", "torch", "torchaudio"} <= seleccion.keys()
    assert "webrtcvad" not in seleccion


def test_freeze_historico_conservado():
    congelado = (ROOT / "requirements" / "legacy-linux-freeze.txt").read_text()
    assert "triton==2.2.0" in congelado
    assert "TTS==0.22.0" in congelado


def test_perfil_linux_no_selecciona_windows():
    assert not {"torch", "torchaudio"} & {r.name.lower() for r in cargar(ROOT / "requirements" / "linux.txt")}
