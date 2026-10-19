"""Dobles del hipervisor: prueban control/límites, no aislamiento de una VM."""
import base64
import io
import json
import struct
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.sandbox_backends import SolicitudEjecucion, obtener_backend
from core.sandbox_backends.qemu import controller
from core.sandbox_backends.qemu.experimental import QemuExperimental
from core.sandbox_backends.qemu.protocol import MAX_CONSOLE, PREFIX


@pytest.fixture
def request_vm(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "codigo.py").write_text("x = 1")
    return SolicitudEjecucion("script", sources, timeout=1, limite_cpu=1, limite_procesos=8,
                             limite_memoria=256 * 1024 ** 2, limite_archivo=1024 ** 2, limite_salida=1000)


class Guard:
    instances = []
    mode = "ok"
    cancellation = None

    def __init__(self, memory, cpu):
        self.memory, self.cpu = memory, cpu
        self.closed = False
        type(self).instances.append(self)

    def start(self, argv, cwd, env):
        self.argv, self.cwd, self.env = argv, cwd, env
        if self.mode == "start_error":
            raise OSError("No se pudo contener el hipervisor")
        if self.mode == "interrupt":
            raise KeyboardInterrupt
        raw = (cwd / "input.bin").read_bytes()
        length = struct.unpack(">I", raw[8:12])[0]
        data = json.loads(raw[12:12 + length])
        reply = dict(version=1, nonce=data["nonce"], returncode=0, stdout="ok", stderr="", timed_out=False)
        if self.mode == "bad_nonce":
            reply["nonce"] = "0" * 32
        output = PREFIX + base64.b64encode(json.dumps(reply).encode()) + b"\n"
        if self.mode == "overflow":
            output = b"x" * (MAX_CONSOLE + 1)
        elif self.mode == "no_result":
            output = b"kernel log\n"
        self.process = SimpleNamespace(stdout=io.BytesIO(output))
        self.process.poll = lambda: (None if not self.closed and self.mode in {"timeout", "cancel"} else
                                     1 if self.mode == "qemu_failure" else 0)
        if self.cancellation is not None:
            self.cancellation.set()
        return self.process

    def close(self):
        self.closed = True
        if self.mode == "close_error":
            raise OSError("Job inaccesible")
        return self.mode != "not_clean"


@pytest.fixture(autouse=True)
def reset_guard(monkeypatch):
    monkeypatch.setattr(Guard, "instances", [])
    monkeypatch.setattr(Guard, "mode", "ok")
    monkeypatch.setattr(Guard, "cancellation", None)


def test_controller_read_only_disk_no_network_or_shares(qemu_bundle, request_vm, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-not-to-share")
    evidence = controller._run_validation_job(qemu_bundle, request_vm, _guard=Guard)
    assert evidence.result["stdout"] == "ok"
    assert evidence.cleaned and not evidence.security_validated
    guard = Guard.instances[0]
    assert guard.memory == request_vm.limite_memoria + 512 * 1024 ** 2
    assert guard.cpu == request_vm.limite_cpu
    assert guard.argv[guard.argv.index("-nic") + 1] == "none"
    assert "q35,accel=tcg" in guard.argv
    assert "-virtfs" not in guard.argv and "-fsdev" not in guard.argv
    blocks = [json.loads(guard.argv[i + 1]) for i, a in enumerate(guard.argv) if a == "-blockdev"]
    assert all(b["read-only"] is True for b in blocks)
    assert set(guard.env) == {"SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"}
    assert not guard.cwd.exists()
    assert guard.closed


@pytest.mark.parametrize("mode", ["bad_nonce", "overflow", "no_result", "not_clean", "close_error", "qemu_failure", "start_error"])
def test_failed_or_incomplete_runs_not_accepted(qemu_bundle, request_vm, monkeypatch, mode):
    monkeypatch.setattr(Guard, "mode", mode)
    evidence = controller._run_validation_job(qemu_bundle, request_vm, _guard=Guard)
    assert evidence.result is None
    assert evidence.error
    assert Guard.instances[0].closed


def test_timeout_kills_and_cleans(qemu_bundle, request_vm, monkeypatch):
    monkeypatch.setattr(Guard, "mode", "timeout")
    times = iter([0, 0.1, 2])
    monkeypatch.setattr(controller.time, "monotonic", lambda: next(times))
    evidence = controller._run_validation_job(qemu_bundle, request_vm, _guard=Guard)
    assert evidence.timed_out and evidence.cleaned and evidence.result is None


def test_cancel_kills_and_cleans(qemu_bundle, request_vm, monkeypatch):
    event = threading.Event()
    monkeypatch.setattr(Guard, "mode", "cancel")
    monkeypatch.setattr(Guard, "cancellation", event)
    evidence = controller._run_validation_job(qemu_bundle, request_vm, event, _guard=Guard)
    assert evidence.cancelled and evidence.cleaned and evidence.result is None


def test_precancel_does_not_read_bundle_or_spawn(request_vm):
    event = threading.Event()
    event.set()
    assert controller._run_validation_job(Path("does-not-exist"), request_vm, event, _guard=Guard).cancelled
    assert not Guard.instances


def test_interrupt_always_destroys_job(qemu_bundle, request_vm, monkeypatch):
    monkeypatch.setattr(Guard, "mode", "interrupt")
    with pytest.raises(KeyboardInterrupt):
        controller._run_validation_job(qemu_bundle, request_vm, _guard=Guard)
    assert Guard.instances[0].closed


def test_backend_cannot_be_enabled_even_with_a_bundle(qemu_bundle):
    backend = QemuExperimental(qemu_bundle)
    assert not backend.estado().disponible
    with pytest.raises(RuntimeError, match="bloqueada"):
        backend.ejecutar(None)
    assert not obtener_backend().estado().disponible
