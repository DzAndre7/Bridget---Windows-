# Dependencias Windows: perfiles y validación pendiente

Objetivo: Windows 11 x64, Python 3.11. Windows 10 queda como matriz futura.
La vista previa usa locks Text/Voice con versiones y hashes de wheels, y un
instalador comprobado en CI Windows Server. Seguir [WINDOWS11.md](WINDOWS11.md)
para instalación y diagnóstico. Los perfiles completos históricos de abajo
conservan rangos y requieren validación adicional; no son esos locks.

## Perfiles

- `requirements.txt` / `requirements/app.txt`: base, API/push, escritorio, voz
  faster-whisper y conversión de documentos.
- `requirements/windows.txt`: aplicación y voz local Coqui con torch/torchaudio
  de la misma versión para Windows, probando CPU antes de un perfil CUDA.
- `requirements/linux.txt`: aplicación común; no habilita un sandbox inseguro.
- `requirements/voice-local.txt`: Coqui mantenido (`coqui-tts`) y español `gruut`.
  Preserva el import `TTS.api`; no debe coexistir con la distribución antigua `TTS`.
- `requirements/voice-whisper-classic.txt`: respaldo clásico opcional conservado.
- `requirements/test.txt`: herramientas para las pruebas focalizadas, sin modelos.
- `requirements/legacy-linux-freeze.txt`: copia íntegra del requirements original
  como referencia; NO instalar en Windows ni combinar con los perfiles nuevos.

No se copian paquetes transitivos del congelado a ciegas: PyAutoGUI y pywebview
eligen sus dependencias según plataforma. Se retiraron de la selección directa
Windows `python3-xlib`, Qt/X11, `triton` y los paquetes CUDA Linux de distintas
versiones. No se ha eliminado ninguna función para justificar esa separación.
`pywebpush` y `faster-whisper`, antes ausentes, son ahora explícitos.
`webrtcvad-wheels` mantiene el import `webrtcvad` y ofrece wheels Windows;
no instalar simultáneamente la distribución antigua `webrtcvad`.

La carga local de Coqui ahora selecciona CPU si CUDA no está disponible. No se
han probado todavía los modelos ni la compatibilidad del fork con el modelo
`tts_models/es/css10/vits`; esa verificación pertenece a Windows y al perfil
completo de voz. La vista previa reemplaza `paplay` por PortAudio, usa temporales únicos del SO
y notificaciones por plataforma. SAPI permite TTS Windows sin Coqui; Linux
conserva Coqui/Google. El perfil completo Coqui no se acreditó en esta entrega.

## Instalación para validación nativa

En un entorno limpio Windows (sin credenciales ni datos personales), preparar
Python 3.11 x64 y un venv nuevo. Para el perfil CPU instalar primero torch y
torchaudio de la misma versión desde el índice oficial CPU de PyTorch y luego
el perfil Windows. No mezclar índices de CUDA ni un venv del origen Linux.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements/windows.txt
.\.venv\Scripts\python.exe -m pip check
```

Prerrequisitos externos: Ollama y modelos autorizados, Microsoft Visual C++
Runtime según las wheels, WebView2 para el backend Windows de pywebview, acceso
al dispositivo de audio, Pandoc y las DLLs nativas necesarias para WeasyPrint.
El Whisper clásico opcional requiere ffmpeg. No descargar modelos ni arrancar
Bridget dentro de una instalación de dependencias sin revisar esos pasos.

Para las pruebas seguras no hace falta el perfil completo ni GPU:

```powershell
py -3.11 -m venv .venv-tests
.\.venv-tests\Scripts\python.exe -m pip install -r requirements/test.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv-tests\Scripts\python.exe -m pytest -c pytest-safety.ini -q
```

`pytest-safety.ini` selecciona solamente pruebas revisadas. La suite completa
permanece en `asistente_v2/tests/`; requiere revisar sus imports y dependencias
antes de ejecutarla. No incluye automáticamente experimentos de `legacy/`.

## Evidencia de Codex y límites

Se resolvieron desde Linux `base.txt` + `voice.txt` para wheels CPython 3.11
`win_amd64`, con pip `--dry-run --ignore-installed --only-binary=:all:`.
Eso verifica selección/disponibilidad de distribuciones y restricciones en ese
subconjunto; no instala, no carga DLLs ni reproduce exactamente los marcadores
de una instalación nativa en Windows.

La comprobación binaria de API y escritorio no se completó: `http-ece`
(dependencia de pywebpush) y `PyAutoGUI` no ofrecen las wheels requeridas por
`--only-binary=:all:`. Esto no demuestra incompatibilidad de sus distribuciones
fuente, pero obliga a validar construcción/instalación en Windows. No se
relajaron ni ocultaron esos fallos. Coqui y el perfil completo CPU/CUDA tampoco
se declaran validados por ese ensayo parcial.

Tras instalar el perfil completo en Windows, ejecutar `pip check`, imports
controlados sin entrypoints, pruebas del TTS sin GPU y después con GPU, STT,
WebView2 y conversión real en archivos de prueba. Solo entonces generar un lock
transitivo con hashes por perfil y registrar versión de Windows, Python,
controladores y runtimes. No usar `pip freeze` de una máquina personal como lock
multiplataforma.
