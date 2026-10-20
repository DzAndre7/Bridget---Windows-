# Ejecutar como usuario normal, desde una copia revisada del repositorio.
[CmdletBinding()]
param(
    [ValidateSet('Text', 'Voice', 'Desktop')][string]$Profile = 'Text',
    [string]$EnvironmentPath = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentPath) { $EnvironmentPath = Join-Path $root '.venv' }
$EnvironmentPath = [IO.Path]::GetFullPath($EnvironmentPath)
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló un paso de instalación (exit $LASTEXITCODE)." }
}
Invoke-Checked 'py' @('-3.11', '-c', 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32, "Se requiere CPython 3.11 x64"')
$python = Join-Path $EnvironmentPath 'Scripts\python.exe'
if (-not (Test-Path $python)) {
    if (Test-Path $EnvironmentPath) { throw 'La ruta existe sin Python válido; elegir un directorio de entorno nuevo.' }
    Invoke-Checked 'py' @('-3.11', '-m', 'venv', $EnvironmentPath)
}
Invoke-Checked $python @('-c', 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32')
Invoke-Checked $python @('-m', 'pip', 'install', 'pip==25.3')
$lock = Join-Path $root 'requirements\windows-text.lock.txt'
if ($Profile -ne 'Text') { $lock = Join-Path $root 'requirements\windows-voice.lock.txt' }
Invoke-Checked $python @('-m', 'pip', 'install', '--only-binary=:all:', '--require-hashes', '-r', $lock)
if ($Profile -eq 'Desktop') {
    # Perfil GUI adicional: su lock incluye paquetes fuente revisables; ver guía.
    Invoke-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $root 'requirements\desktop-preview.txt'))
}
Invoke-Checked $python @('-m', 'pip', 'check')
$receipt = Join-Path $EnvironmentPath 'installed-packages.txt'
& $python -m pip freeze | Out-File -Encoding utf8 $receipt
if ($LASTEXITCODE -ne 0) { throw 'No se pudo guardar inventario.' }
Invoke-Checked $python @((Join-Path $root 'scripts\smoke.py'))
Write-Host 'Instalación y prueba sintética terminadas. Ollama, audio y WebView2 requieren validación aparte.'
Write-Host "Diagnóstico: & '$python' '$(Join-Path $root 'scripts\launch.py')' diagnose --probe-ollama"
