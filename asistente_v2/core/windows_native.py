"""Herramientas Windows fijas: el contenido del usuario viaja como JSON por stdin.

Estos procesos de confianza NO son un sandbox ni un ejecutor de código generado.
"""
import json
import os
import subprocess
from pathlib import Path

TTS_SCRIPT = '''[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'es' } | Select-Object -First 1
  if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
  $s.SetOutputToWaveFile($p.path)
  $s.Speak([string]$p.text)
} finally { $s.Dispose() }
'''
NOTIFY_SCRIPT = '''[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
try {
  $n.Icon = [System.Drawing.SystemIcons]::Information
  $n.Visible = $true
  $n.ShowBalloonTip(4000, [string]$p.title, [string]$p.text, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Milliseconds 4500
} finally { $n.Dispose() }
'''


def powershell(script, payload, timeout):
    if os.name != "nt" or script not in (TTS_SCRIPT, NOTIFY_SCRIPT):
        raise OSError("Operación Windows no disponible")
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return subprocess.run(
        [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        input=json.dumps(payload, ensure_ascii=False), encoding="utf-8", capture_output=True,
        timeout=timeout, check=True, creationflags=0x08000000,
    )


def synthesize(text, path):
    powershell(TTS_SCRIPT, {"text": text, "path": str(Path(path).resolve())}, 90)
