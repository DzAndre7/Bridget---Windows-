"""Windows real: cargas fijas benignas para verificar el Job, SIN código generado.

No es una prueba de una VM ni acredita el aislamiento del hipervisor.
"""
import ctypes
import os
import sys

import pytest

from core.sandbox_backends.qemu.windows_job import ExtendedLimits, WindowsJob

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requiere Job Objects de Windows")


def env_minimo():
    return {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows")}


def test_job_real_configura_limites_y_ejecuta_carga_benigna(tmp_path):
    job = WindowsJob(256 * 1024 ** 2, 10)
    process = None
    try:
        limits = ExtendedLimits()
        assert job.api.QueryInformationJobObject(job.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None)
        assert limits.basic.active_processes == 1
        assert limits.job_memory == 256 * 1024 ** 2
        assert limits.basic.job_time == 10 * 10_000_000
        process = job.start([sys.executable, "-I", "-c", "print('BRIDGET_JOB_OK', flush=True)"], tmp_path, env_minimo())
        process.wait(timeout=10)
        assert process.stdout.read(1000).strip() == b"BRIDGET_JOB_OK"
        assert process.returncode == 0
    finally:
        assert job.close()
        if process is not None:
            process.stdout.close()


def test_job_real_cancelacion_corta_un_proceso_benigno(tmp_path):
    job = WindowsJob(256 * 1024 ** 2, 10)
    process = None
    try:
        process = job.start([sys.executable, "-I", "-c", "import time;time.sleep(30)"], tmp_path, env_minimo())
    finally:
        assert job.close()
        if process is not None:
            process.stdout.close()
    assert process.poll() is not None


def test_job_real_no_permite_procesos_descendientes(tmp_path):
    job = WindowsJob(256 * 1024 ** 2, 10)
    process = None
    fixed_probe = '''import subprocess,sys
try:
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(5)"])
except OSError:
    print("CHILD_BLOCKED", flush=True)
else:
    child.terminate()
    child.wait()
    print("UNEXPECTED_CHILD", flush=True)
'''
    try:
        process = job.start([sys.executable, "-I", "-c", fixed_probe], tmp_path, env_minimo())
        process.wait(timeout=10)
        assert process.stdout.read(1000).strip() == b"CHILD_BLOCKED"
    finally:
        assert job.close()
        if process is not None:
            process.stdout.close()
