"""CreateProcessW atómico dentro de un Job (Windows 10+).

Solo recibe el ejecutable de confianza del hipervisor y sus argumentos; nunca
snippets. PROC_THREAD_ATTRIBUTE_JOB_LIST cierra la ventana de procesos huérfanos.
"""
import ctypes as C
import os
import subprocess

HANDLE = C.c_void_p
U32 = C.c_uint32
U16 = C.c_uint16
SIZE = C.c_size_t


class StartupInfo(C.Structure):
    _fields_ = [("cb", U32), ("reserved", C.c_wchar_p), ("desktop", C.c_wchar_p),
                ("title", C.c_wchar_p), ("x", U32), ("y", U32), ("x_size", U32),
                ("y_size", U32), ("x_count", U32), ("y_count", U32),
                ("fill", U32), ("flags", U32), ("show", U16), ("reserved_size", U16),
                ("reserved_data", HANDLE), ("stdin", HANDLE), ("stdout", HANDLE), ("stderr", HANDLE)]


class StartupInfoEx(C.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", HANDLE), ("thread", HANDLE), ("pid", U32), ("tid", U32)]


class NativeProcess:
    def __init__(self, api, info, output):
        self.api, self.handle, self.pid = api, info.process, info.pid
        self.stdout = output
        self.returncode = None

    @classmethod
    def create(cls, api, job, argv, cwd, env):
        if not argv or not os.path.isabs(argv[0]) or not os.path.isabs(str(cwd)):
            raise ValueError("Se requieren rutas absolutas")
        if any(not isinstance(k, str) or not isinstance(v, str) or "=" in k or "\0" in k + v for k, v in env.items()):
            raise ValueError("Entorno inválido")
        signatures = {
            "InitializeProcThreadAttributeList": ([HANDLE, U32, U32, C.POINTER(SIZE)], C.c_int32),
            "UpdateProcThreadAttribute": ([HANDLE, U32, SIZE, HANDLE, SIZE, HANDLE, HANDLE], C.c_int32),
            "DeleteProcThreadAttributeList": ([HANDLE], None),
            "CreateProcessW": ([C.c_wchar_p, C.c_wchar_p, HANDLE, HANDLE, C.c_int32,
                                U32, HANDLE, C.c_wchar_p, HANDLE, C.POINTER(ProcessInfo)], C.c_int32),
            "ResumeThread": ([HANDLE], U32),
            "WaitForSingleObject": ([HANDLE, U32], U32),
            "GetExitCodeProcess": ([HANDLE, C.POINTER(U32)], C.c_int32),
            "TerminateProcess": ([HANDLE, U32], C.c_int32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = args, result
        import msvcrt
        read_fd, write_fd = os.pipe()
        null_fd = None
        attributes = None
        initialized = False
        info = ProcessInfo()
        process = None
        try:
            null_fd = os.open(os.devnull, os.O_RDONLY)
            os.set_inheritable(write_fd, True)
            os.set_inheritable(null_fd, True)
            stdout = msvcrt.get_osfhandle(write_fd)
            stdin = msvcrt.get_osfhandle(null_fd)
            size = SIZE()
            api.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
            if not size.value:
                raise C.WinError(C.get_last_error())
            attributes = C.create_string_buffer(size.value)
            if not api.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)):
                raise C.WinError(C.get_last_error())
            initialized = True
            jobs = (HANDLE * 1)(job)
            inherited = (HANDLE * 2)(stdout, stdin)
            # Los valores deben vivir hasta DeleteProcThreadAttributeList.
            for key, value in [(0x2000D, jobs), (0x20002, inherited)]:
                if not api.UpdateProcThreadAttribute(attributes, 0, key, C.byref(value), C.sizeof(value), None, None):
                    raise C.WinError(C.get_last_error())
            startup = StartupInfoEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdin, stdout, stdout
            startup.attributes = C.cast(attributes, HANDLE)
            environment = C.create_unicode_buffer("\0".join(k + "=" + env[k] for k in sorted(env, key=str.casefold)) + "\0\0")
            command_line = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            # SUSPENDED | NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | UNICODE_ENVIRONMENT
            flags = 0x4 | 0x08000000 | 0x00080000 | 0x400
            if not api.CreateProcessW(argv[0], command_line, None, None, True, flags,
                                      environment, str(cwd), C.byref(startup), C.byref(info)):
                raise C.WinError(C.get_last_error())
            output = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = None
            process = cls(api, info, output)
            if api.ResumeThread(info.thread) != 1:
                raise RuntimeError("Estado de suspensión inesperado")
            return process
        except BaseException:
            if info.process:
                api.TerminateProcess(info.process, 1)
                api.WaitForSingleObject(info.process, 5000)
                api.CloseHandle(info.process)
                if process is not None:
                    process.handle = None
                    process.stdout.close()
            raise
        finally:
            if info.thread:
                api.CloseHandle(info.thread)
            if initialized:
                api.DeleteProcThreadAttributeList(attributes)
            for fd in (read_fd, write_fd, null_fd):
                if fd is not None:
                    os.close(fd)

    def poll(self):
        if self.handle is None:
            return self.returncode
        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 258:  # WAIT_TIMEOUT
            return None
        if status != 0:
            raise C.WinError(C.get_last_error())
        code = U32()
        if not self.api.GetExitCodeProcess(self.handle, C.byref(code)):
            raise C.WinError(C.get_last_error())
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=5):
        if self.handle is None:
            return self.returncode
        status = self.api.WaitForSingleObject(self.handle, max(1, int(timeout * 1000)))
        if status == 258:
            raise subprocess.TimeoutExpired("trusted-hypervisor", timeout)
        if status != 0:
            raise C.WinError(C.get_last_error())
        return self.poll()

    def close_handle(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise C.WinError(C.get_last_error())
