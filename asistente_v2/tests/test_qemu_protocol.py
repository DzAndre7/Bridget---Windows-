"""Solo codificación/datos: nunca arranca una VM ni ejecuta fuentes recibidas."""
import base64
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from core.sandbox_backends.qemu import protocol

NONCE = "a" * 32
LIMITS = {"seconds": 15, "cpu": 15, "memory": 256 * 1024 ** 2,
          "file": 1024 ** 2, "processes": 16, "output": 1000}


@pytest.fixture
def agent():
    path = Path(__file__).parents[2] / "guest" / "qemu" / "agent.py"
    spec = importlib.util.spec_from_file_location("bridget_guest_data_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # definiciones, sin main() ni ejecución de entradas
    return module


def record(**changes):
    data = dict(version=1, nonce=NONCE, returncode=0, stdout="ok", stderr="", timed_out=False)
    data.update(changes)
    return protocol.PREFIX + base64.b64encode(json.dumps(data).encode()) + b"\n"


def test_input_roundtrip_and_sector_alignment(agent):
    raw = protocol.encode_input({"codigo.py": "print('sí')".encode()}, NONCE, "script", LIMITS)
    assert len(raw) % 512 == 0
    decoded = agent.parse_input(raw)
    assert decoded["files"] == {"codigo.py": "print('sí')".encode()}
    assert decoded["limits"] == LIMITS


@pytest.mark.parametrize("name", ["../a.py", "/a.py", "C:/a.py", "a\\b.py", ".env", "x/.env.py", "a//b.py", "a/./b.py", "private.key"])
def test_host_rejects_paths_and_credentials(name):
    with pytest.raises(ValueError):
        protocol.encode_input({name: b"x"}, NONCE, "script", LIMITS)


def test_case_collisions_rejected():
    with pytest.raises(ValueError):
        protocol.encode_input({"A.py": b"x", "a.py": b"y"}, NONCE, "script", LIMITS)


def test_read_sources_stops_at_total_limit(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_bytes(b"aaa")
    (tmp_path / "b.py").write_bytes(b"bbb")
    monkeypatch.setattr(protocol, "MAX_SOURCE", 5)
    with pytest.raises(ValueError):
        protocol.read_sources(tmp_path)


def test_result_boot_noise_and_nonce():
    assert protocol.decode_result(b"boot log\n" + record(), NONCE, 1000)["stdout"] == "ok"
    with pytest.raises(ValueError):
        protocol.decode_result(record(), "b" * 32, 1000)


@pytest.mark.parametrize("data", [b"", b"BRIDGET_RESULT_V1:bad\n", record() + record(), record(returncode=True),
                                   record(version=True), record(stdout="x" * 1001), record(timed_out="false")],
                         ids=["missing", "bad_base64", "duplicate_record", "bad_code", "bad_version", "long_output", "bad_timeout"])
def test_bad_results_are_not_accepted(data):
    with pytest.raises(ValueError):
        protocol.decode_result(data, NONCE, 1000)


def test_console_bounded():
    with pytest.raises(ValueError):
        protocol.decode_result(b"x" * (protocol.MAX_CONSOLE + 1), NONCE, 1000)


def test_guest_independently_validates_input(agent):
    data = {"version": 1, "nonce": NONCE, "operation": "script", "limits": LIMITS,
            "files": {"../bad.py": base64.b64encode(b"x").decode()}}
    payload = json.dumps(data).encode()
    raw = protocol.MAGIC + struct.pack(">I", len(payload)) + payload
    with pytest.raises(ValueError):
        agent.parse_input(raw)


def test_guest_refuses_to_execute_on_host(agent):
    with pytest.raises((OSError, RuntimeError)):
        agent.run_guest_job({})


def test_input_size_header_checked_before_read(agent):
    with pytest.raises(ValueError):
        agent.parse_input(protocol.MAGIC + struct.pack(">I", protocol.MAX_INPUT + 1))


def test_duplicate_json_keys_rejected():
    raw = b'{"version":1,"version":1,"nonce":"' + NONCE.encode() + b'","returncode":0,"stdout":"ok","stderr":"","timed_out":false}'
    with pytest.raises(ValueError, match="inválido"):
        protocol.decode_result(protocol.PREFIX + base64.b64encode(raw), NONCE, 1000)
