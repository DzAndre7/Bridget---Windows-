"""WAV real y controladores simulados: sin hardware, red ni descargas de modelos."""
import importlib
import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from core import audio_io, voice


@pytest.fixture
def fake_audio(monkeypatch):
    stream = Mock()
    stream.__enter__ = Mock(return_value=stream)
    stream.__exit__ = Mock(return_value=False)
    sound = SimpleNamespace(RawOutputStream=Mock(return_value=stream), InputStream=Mock(return_value=stream),
                            rec=Mock(return_value=np.zeros((160, 1), dtype=np.int16)), wait=Mock(), sleep=Mock())
    monkeypatch.setitem(sys.modules, "sounddevice", sound)
    # scipy/VAD reemplazados: no se importa ningún runtime nativo de audio en CI unitario.
    def write(path, rate, data):
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", ""))
            output.writeframes(np.asarray(data, dtype=np.int16).tobytes())
    scipy = ModuleType("scipy")
    io = ModuleType("scipy.io")
    wav = ModuleType("scipy.io.wavfile")
    wav.write = write
    scipy.io, io.wavfile = io, wav
    monkeypatch.setitem(sys.modules, "scipy", scipy)
    monkeypatch.setitem(sys.modules, "scipy.io", io)
    monkeypatch.setitem(sys.modules, "scipy.io.wavfile", wav)
    monkeypatch.setitem(sys.modules, "webrtcvad", SimpleNamespace(Vad=lambda mode: SimpleNamespace(is_speech=lambda *a: False)))
    yield sound, stream, write
    for name in ("core.listen", "core.microfono_ventana", "core.manos_libres"):
        # No conservar módulos ligados a drivers simulados entre tests.
        monkeypatch.delitem(sys.modules, name, raising=False)


def load_module(monkeypatch, name):
    monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(name)


def test_playback_uses_portaudio_and_cleans_wav(fake_audio, tmp_path, monkeypatch):
    sound, stream, write = fake_audio
    path = tmp_path / "voz.wav"
    write(path, 16000, np.ones((2048, 1), dtype=np.int16))
    monkeypatch.setenv("BRIDGET_OUTPUT_DEVICE", "3")
    playback = audio_io.play_wav(path, cleanup=True)
    assert playback.poll() == 0 and not path.exists()
    sound.RawOutputStream.assert_called_once_with(samplerate=16000, channels=1, dtype="int16", device=3)
    assert stream.write.call_count == 2


def test_playback_error_still_cleans_file(fake_audio, tmp_path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"invalid")
    with pytest.raises(RuntimeError):
        audio_io.play_wav(path, cleanup=True)
    assert not path.exists()


def test_playback_cancel_stops_stream(fake_audio, tmp_path):
    import threading
    sound, stream, write = fake_audio
    entered, release = threading.Event(), threading.Event()
    path = tmp_path / "long.wav"
    write(path, 16000, np.ones((4096, 1), dtype=np.int16))
    def output(chunk):
        entered.set()
        assert release.wait(2)
    stream.write.side_effect = output
    playback = audio_io.play_wav(path, blocking=False, cleanup=True)
    assert entered.wait(2)
    playback._stop.set()
    release.set()
    playback.terminate()
    assert playback.poll() == 0 and stream.write.call_count == 1
    assert not path.exists()


@pytest.mark.parametrize("value,expected", [("", None), ("2", 2), ("Micrófono USB", "Micrófono USB")])
def test_select_audio_device(value, expected, monkeypatch):
    monkeypatch.setenv("BRIDGET_INPUT_DEVICE", value)
    assert audio_io.device("input") == expected


def test_tts_windows_provider_no_coqui_download(monkeypatch, tmp_path):
    from core import windows_native
    monkeypatch.setenv("BRIDGET_TTS", "windows")
    fallback = Mock(side_effect=AssertionError("No Coqui"))
    monkeypatch.setattr(voice, "_generar_coqui", fallback)
    monkeypatch.setattr(windows_native, "synthesize", lambda text, path: Path(path).write_bytes(b"x" * 45))
    assert voice._generar("hola", str(tmp_path / "voice.wav"))
    fallback.assert_not_called()


def test_tts_failure_deletes_temp_and_does_not_play(monkeypatch):
    observed = []
    def fail(text, path):
        observed.append(path)
        return False
    monkeypatch.setattr(voice, "_generar", fail)
    monkeypatch.setattr(voice, "play_wav", Mock(side_effect=AssertionError("No playback")))
    assert voice.generar_audio("hola") is None
    assert voice.hablar_interrumpible("hola") is None
    voice.hablar("hola")
    assert len(set(observed)) == 3
    assert not any(Path(p).exists() for p in observed)


def test_streaming_tts_playback_failure_drains_and_removes_files(monkeypatch):
    paths = []
    def generate(text, path):
        Path(path).write_bytes(b"synthetic")
        paths.append(path)
        return True
    monkeypatch.setattr(voice, "_generar", generate)
    monkeypatch.setattr(voice, "play_wav", Mock(side_effect=RuntimeError))
    assert voice.hablar_por_frases(["uno", "dos"]) == "uno dos"
    assert not any(Path(p).exists() for p in paths)


def test_fragment_recording_uses_selected_input_and_cleans(fake_audio, monkeypatch):
    sound, stream, write = fake_audio
    listen = load_module(monkeypatch, "core.listen")
    monkeypatch.setenv("BRIDGET_INPUT_DEVICE", "Micrófono USB")
    paths = []
    def transcribe(path):
        assert Path(path).exists()
        paths.append(path)
        return "Hola"
    monkeypatch.setattr(listen, "_transcribir", transcribe)
    assert listen.escuchar_fragmento(.01) == "hola"
    assert sound.rec.call_args.kwargs["device"] == "Micrófono USB"
    assert not Path(paths[0]).exists()


def test_microphone_start_error_releases_device_and_state(fake_audio, monkeypatch):
    sound, stream, write = fake_audio
    mic = load_module(monkeypatch, "core.microfono_ventana")
    stream.start.side_effect = OSError("device denied")
    with pytest.raises(OSError):
        mic.iniciar_grabacion()
    assert mic._grabando is False and mic._stream is None
    stream.close.assert_called_once()


def test_microphone_button_roundtrip_and_limit(fake_audio, monkeypatch):
    sound, stream, write = fake_audio
    mic = load_module(monkeypatch, "core.microfono_ventana")
    monkeypatch.setenv("BRIDGET_INPUT_DEVICE", "4")
    paths = []
    monkeypatch.setattr(mic, "escuchar_audio", lambda p: paths.append(p) or "hola")
    assert mic.iniciar_grabacion()
    callback = sound.InputStream.call_args.kwargs["callback"]
    assert sound.InputStream.call_args.kwargs["device"] == 4
    callback(np.ones((160, 1), dtype=np.int16), 160, None, None)
    assert mic.detener_grabacion() == "hola"
    assert not Path(paths[0]).exists()
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    assert mic.detener_grabacion() == ""


def test_faster_whisper_lazy_cpu_and_cached(fake_audio, monkeypatch):
    listen = load_module(monkeypatch, "core.listen")
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(text=" Hola ")], None)
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    assert listen._transcribir("synthetic.wav") == "Hola"
    assert listen._transcribir("synthetic.wav") == "Hola"
    factory.assert_called_once_with(listen.MODELO_STT, device="cpu", compute_type="int8")
    assert model.transcribe.call_args.kwargs["language"] == "es"


def test_hands_free_unique_file_and_json_callback(fake_audio, monkeypatch):
    sound, stream, write = fake_audio
    hands = load_module(monkeypatch, "core.manos_libres")
    hands._activo = True
    hands._pausado = False
    hands._ventana = SimpleNamespace(evaluate_js=Mock())
    # Una frase termina al silenciar; al transcribir se desactiva el bucle.
    calls = iter([True] + [False] * 100)
    hands.webrtcvad = SimpleNamespace(Vad=lambda mode: SimpleNamespace(is_speech=lambda *a: next(calls)))
    stream.read.return_value = (np.zeros((320, 1), dtype=np.int16), False)
    paths = []
    def transcribe(path):
        paths.append(path)
        hands._activo = False
        return "'linea\\\nsegura"
    monkeypatch.setattr(hands, "escuchar_audio", transcribe)
    hands._ciclo()
    assert paths and not Path(paths[0]).exists()
    js = hands._ventana.evaluate_js.call_args.args[0]
    assert js.startswith('window.recibirVozManosLibres("')


@pytest.mark.skipif(sys.platform != "win32", reason="Síntesis SAPI nativa de Windows")
def test_native_sapi_fixed_phrase_to_wav_without_playing(tmp_path):
    # Programa fijo de confianza; sintetiza a disco y no abre dispositivo de audio.
    from core.windows_native import synthesize
    path = tmp_path / "prueba á.wav"
    synthesize("Prueba de Bridget", path)
    with wave.open(str(path), "rb") as source:
        assert source.getnframes() > 0
        assert source.getnchannels() in (1, 2)
        assert source.getsampwidth() in (1, 2, 3, 4)
