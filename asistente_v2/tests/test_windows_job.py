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


def test_job_real_mata_la_carga_si_el_controlador_desaparece(tmp_path):
    # Supervisor y carga FIJOS de prueba; no es una ejecución de snippets host.
    import subprocess
    from pathlib import Path
    root = Path(__file__).parents[1]
    helper = f'''import os,sys
sys.path.insert(0, {str(root)!r})
from core.sandbox_backends.qemu.windows_job import WindowsJob
job = WindowsJob(256 * 1024 ** 2, 10)
child = job.start([sys.executable, "-I", "-c", "import time;time.sleep(30)"], {str(tmp_path)!r}, {{"SystemRoot": os.environ.get("SystemRoot", r"C:\\Windows")}})
print(child.pid, flush=True)
os._exit(0)
'''
    broker = subprocess.Popen([sys.executable, "-I", "-c", helper], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env_minimo())
    try:
        out, error = broker.communicate(timeout=15)
        assert broker.returncode == 0, error.decode("utf-8", "replace")
        pid = int(out.strip())
    finally:
        if broker.poll() is None:
            broker.kill()
            broker.wait(timeout=5)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int32
    handle = api.OpenProcess(0x1000 | 0x100000, False, pid)
    if handle:
        try:
            assert api.WaitForSingleObject(handle, 2000) == 0
        finally:
            api.CloseHandle(handle)
    else:
        assert ctypes.get_last_error() == 87  # El proceso ya no existe.
