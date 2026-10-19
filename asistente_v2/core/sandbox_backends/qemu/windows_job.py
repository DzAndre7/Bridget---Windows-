"""Contención del proceso hipervisor; la frontera de código es la VM, no el Job.

Solo Windows. Se crea suspendido para asignar el Job antes de ejecutar una sola
instrucción. Nunca se usa este módulo como ejecutor de snippets en el anfitrión.
"""
import ctypes as C
import os
import subprocess

U32 = C.c_uint32
I32 = C.c_int32
U64 = C.c_uint64
I64 = C.c_int64
SIZE = C.c_size_t
HANDLE = C.c_void_p


class BasicLimits(C.Structure):
    _fields_ = [("process_time", I64), ("job_time", I64), ("flags", U32),
                ("min_working_set", SIZE), ("max_working_set", SIZE),
                ("active_processes", U32), ("affinity", SIZE),
                ("priority", U32), ("scheduling", U32)]


class IoCounters(C.Structure):
    _fields_ = [(name, U64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(C.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", SIZE),
                ("job_memory", SIZE), ("peak_process_memory", SIZE), ("peak_job_memory", SIZE)]


class Accounting(C.Structure):
    _fields_ = [("user", I64), ("kernel", I64), ("period_user", I64), ("period_kernel", I64),
                ("faults", U32), ("total", U32), ("active", U32), ("terminated", U32)]


class ThreadEntry(C.Structure):
    _fields_ = [("size", U32), ("usage", U32), ("thread_id", U32), ("owner_pid", U32),
                ("base_priority", I32), ("delta_priority", I32), ("flags", U32)]


class WindowsJob:
    def __init__(self, memory_bytes, cpu_seconds):
        if os.name != "nt":
            raise OSError("Este controlador requiere Windows")
        if type(memory_bytes) is not int or not 64 * 1024 ** 2 <= memory_bytes <= 3 * 1024 ** 3:
            raise ValueError("Límite de memoria inválido")
        if type(cpu_seconds) is not int or not 1 <= cpu_seconds <= 300:
            raise ValueError("Límite de CPU inválido")
        self.api = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([HANDLE, C.c_wchar_p], HANDLE),
            "SetInformationJobObject": ([HANDLE, I32, HANDLE, U32], I32),
            "QueryInformationJobObject": ([HANDLE, I32, HANDLE, U32, HANDLE], I32),
            "AssignProcessToJobObject": ([HANDLE, HANDLE], I32),
            "TerminateJobObject": ([HANDLE, U32], I32),
            "CloseHandle": ([HANDLE], I32),
            "OpenProcess": ([U32, I32, U32], HANDLE),
            "CreateToolhelp32Snapshot": ([U32, U32], HANDLE),
            "Thread32First": ([HANDLE, C.POINTER(ThreadEntry)], I32),
            "Thread32Next": ([HANDLE, C.POINTER(ThreadEntry)], I32),
            "OpenThread": ([U32, I32, U32], HANDLE),
            "ResumeThread": ([HANDLE], U32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = args
            function.restype = result
        self.handle = self.api.CreateJobObjectW(None, None)
        self.process = None
        if not self.handle:
            raise C.WinError(C.get_last_error())
        limits = ExtendedLimits()
        # JOB_TIME | ACTIVE_PROCESS | PROCESS_MEMORY | JOB_MEMORY | KILL_ON_JOB_CLOSE
        limits.basic.flags = 0x4 | 0x8 | 0x100 | 0x200 | 0x2000
        limits.basic.active_processes = 1
        limits.basic.job_time = cpu_seconds * 10_000_000
        limits.process_memory = memory_bytes
        limits.job_memory = memory_bytes
        if not self.api.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            error = C.get_last_error()
            self.api.CloseHandle(self.handle)
            self.handle = None
            raise C.WinError(error)

    def start(self, argv, cwd, env):
        if self.process is not None or not self.handle:
            raise RuntimeError("El Job es de un solo uso")
        try:
            self.process = subprocess.Popen(
                argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, shell=False, close_fds=True,
                creationflags=0x4 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW
            )
            process_handle = self.api.OpenProcess(0x100 | 0x1, False, self.process.pid)
            if not process_handle:
                raise C.WinError(C.get_last_error())
            try:
                if not self.api.AssignProcessToJobObject(self.handle, process_handle):
                    raise C.WinError(C.get_last_error())
            finally:
                self.api.CloseHandle(process_handle)
            self._resume_primary_thread()
            return self.process
        except BaseException:
            try:
                if self.process is not None:
                    # Si AssignProcess falló, aún está suspendido y no creó hijos.
                    self.process.kill()
                    self.process.wait(timeout=5)
            finally:
                self.close()
                if self.process is not None and self.process.stdout is not None:
                    self.process.stdout.close()
            raise

    def _resume_primary_thread(self):
        snapshot = self.api.CreateToolhelp32Snapshot(0x4, 0)
        if not snapshot or snapshot == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        ids = []
        try:
            entry = ThreadEntry()
            entry.size = C.sizeof(entry)
            valid = self.api.Thread32First(snapshot, C.byref(entry))
            while valid:
                if entry.owner_pid == self.process.pid:
                    ids.append(entry.thread_id)
                valid = self.api.Thread32Next(snapshot, C.byref(entry))
        finally:
            self.api.CloseHandle(snapshot)
        if len(ids) != 1:
            raise RuntimeError("No se acreditó el hilo inicial suspendido")
        thread = self.api.OpenThread(0x2, False, ids[0])
        if not thread:
            raise C.WinError(C.get_last_error())
        try:
            if self.api.ResumeThread(thread) != 1:
                raise RuntimeError("Estado de suspensión inesperado")
        finally:
            self.api.CloseHandle(thread)

    def close(self):
        if not self.handle:
            return False
        clean = False
        try:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise C.WinError(C.get_last_error())
            if self.process is not None:
                self.process.wait(timeout=5)
            accounting = Accounting()
            if not self.api.QueryInformationJobObject(self.handle, 1, C.byref(accounting), C.sizeof(accounting), None):
                raise C.WinError(C.get_last_error())
            clean = accounting.active == 0
        finally:
            if not self.api.CloseHandle(self.handle):
                clean = False
            self.handle = None
        return clean
