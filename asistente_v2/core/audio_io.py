"""Audio PCM mediante PortAudio en Windows y Linux; sin paplay ni shell."""
import os
import threading
import wave
from pathlib import Path


def device(kind):
    value = os.environ.get("BRIDGET_" + kind.upper() + "_DEVICE", "").strip()
    return int(value) if value.isdecimal() else value or None


class Playback:
    def __init__(self, path, cleanup=False):
        self.path, self.cleanup = path, cleanup
        self._stop = threading.Event()
        self.returncode = None
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="bridget-audio")
        self._thread.start()

    def _run(self):
        try:
            import sounddevice as sd
            with wave.open(str(self.path), "rb") as source:
                dtype = {1: "uint8", 2: "int16", 3: "int24", 4: "int32"}[source.getsampwidth()]
                with sd.RawOutputStream(samplerate=source.getframerate(), channels=source.getnchannels(),
                                        dtype=dtype, device=device("output")) as stream:
                    while not self._stop.is_set():
                        chunk = source.readframes(1024)
                        if not chunk:
                            break
                        stream.write(chunk)
            self.returncode = 0
        except Exception as error:
            self.error, self.returncode = error, 1
        finally:
            if self.cleanup:
                try:
                    Path(self.path).unlink(missing_ok=True)
                except OSError:
                    pass

    def poll(self):
        return self.returncode if not self._thread.is_alive() else None

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("El dispositivo de audio no respondió")
        if self.error:
            raise RuntimeError("No se pudo reproducir audio; revisar diagnóstico/dispositivo") from self.error
        return self.returncode

    def terminate(self):
        self._stop.set()
        self.wait(timeout=5)


def play_wav(path, *, blocking=True, cleanup=False):
    playback = Playback(path, cleanup)
    if blocking:
        playback.wait()
    return playback
