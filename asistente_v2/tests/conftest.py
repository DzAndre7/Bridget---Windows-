"""Pone el directorio asistente_v2/ en sys.path para que
`config`, `core` y `actions` sean importables desde los tests,
igual que cuando la app corre desde asistente_v2/.
"""
import hashlib
import json
import os
import sys

import pytest

ASISTENTE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ASISTENTE_DIR not in sys.path:
    sys.path.insert(0, ASISTENTE_DIR)



@pytest.fixture
def qemu_bundle(tmp_path):
    tmp_path = tmp_path / "bundle"
    tmp_path.mkdir()
    files = {"runtime/qemu.exe": b"trusted executable fixture", "kernel": b"kernel",
             "initrd": b"initrd", "runtime/firmware/bios.bin": b"bios"}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {"version": 1, "protocol": 1, "qemu": "runtime/qemu.exe", "kernel": "kernel",
                "initrd": "initrd", "firmware": "runtime/firmware",
                "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}}
    (tmp_path / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path
