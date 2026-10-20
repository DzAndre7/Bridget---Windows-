# Bridget: instalación y prueba inicial en Windows 11

## Estado de la versión

Vista previa para instalar y probar, no una versión estable acreditada en PC
física. Conversación de texto, memoria, notas, audio y apertura autorizada de
aplicaciones no necesitan el sandbox. La ejecución de snippets/tests generados y
la aplicación de auto-mejoras permanecen bloqueadas. QEMU no se selecciona ni se
activa automáticamente, tampoco durante instalación o diagnóstico.

El CI prueba instalación limpia y componentes en Windows Server; falta ejecutar
la matriz de hardware y escritorio de esta guía en Windows 11. No se descargan
modelos ni se inicia micrófono, reproducción, notificaciones o control de apps
al instalar. Los paquetes de PyPI y los modelos elegidos son dependencias de
confianza que hay que mantener actualizadas.

## 1. Preparar la copia y Python

Usar Windows 11 x64, CPython **3.11 x64** con Python Launcher (`py`) y Git.
No hace falta ser administrador para el entorno Python. Ollama, WebView2 y los
runtimes nativos pueden requerir instalación autorizada aparte. Usar una ruta
corta de trabajo (evita límites de rutas de algunas dependencias), por ejemplo:

```powershell
git clone --branch migration/windows-stage-1 --single-branch https://github.com/DzAndre7/Bridget---Windows-.git C:\Bridget
cd C:\Bridget
py -3.11 -c "import sys; print(sys.version); print(sys.maxsize > 2**32)"
```

Si ya tenés una copia, guardar tus cambios antes de actualizar esa rama. No
trabajar sobre `main` ni copiar un venv Linux. Se conserva el repositorio original.

## 2. Instalar primero texto, después voz/ventana

En PowerShell, revisar y ejecutar el instalador del repositorio:

```powershell
.\scripts\install-windows.ps1 -Profile Text
```

Crea `.venv`, fija pip 25.3, instala las 26 dependencias del lock Text con hashes,
ejecuta `pip check`, guarda `.venv/installed-packages.txt` y realiza la prueba
sintética. No instala servicios, tareas al inicio, modelos ni hipervisores. No
modifica políticas de ejecución de PowerShell. Si tu política impide el script,
seguir el procedimiento Python equivalente; no desactivar una política corporativa:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==25.3
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r requirements/windows-text.lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/smoke.py
```

Para micrófono y reconocimiento local:

```powershell
.\scripts\install-windows.ps1 -Profile Voice
```

El lock Voice incluye texto y 48 dependencias totales, con wheels CPython 3.11
Windows y hashes SHA-256. No usa CUDA ni descarga pesos Whisper. Para la ventana:

```powershell
.\scripts\install-windows.ps1 -Profile Desktop
```

Desktop incluye Voice más `requirements/desktop-preview.txt`. Esa extensión fija
versiones observadas en CI, pero **no tiene un lock con hashes del build**:
`proxy_tools` se construye desde fuente con herramientas de build transitivas.
Para reproducibilidad estricta de artefactos, usar Text/Voice; falta publicar un
wheelhouse revisado de la extensión GUI. WebView2 Runtime y .NET compatibles son
prerrequisitos externos para pywebview: instalar desde Microsoft si faltan.
El script puede repetirse para agregar Voice/Desktop y admite
`-EnvironmentPath C:\Entornos\Bridget`; en ese caso usar el Python de esa ruta.
Para cambiar/reproducir un perfil exacto, preferir un entorno nuevo: pip no quita
paquetes extras de un entorno ya usado. No mezclar el freeze Linux histórico.

## 3. Configurar modelos locales y datos

```powershell
if (-not (Test-Path '.env')) { Copy-Item config/windows.env.example .env }
```

Si `.env` ya existe, editarlo conservando sus valores; no sobrescribirlo con el
ejemplo. Usar rutas `C:/...` en el archivo. Alternativamente definir
`BRIDGET_ENV_FILE` con la ruta absoluta de tu configuración. Variables existentes
del proceso tienen precedencia. No subir `.env`, claves, datos ni diagnósticos
personales al repositorio.

Instalar e iniciar Ollama desde su distribución oficial. Solo se acepta un
endpoint HTTP de loopback con puerto, por defecto `http://127.0.0.1:11434`:
no proxies del entorno, redirects ni endpoints remotos que reciban notas o audio.
El cliente tiene timeout de 120 s. Comprobar y descargar explícitamente los modelos
que decidas usar (pueden ocupar varios GB; revisar licencia, espacio y RAM):

```powershell
ollama list
ollama pull dolphin3:8b
ollama pull nomic-embed-text-v2-moe
# Solo si vas a usar visión:
ollama pull llava
```

No iniciar otro `ollama serve` si la aplicación Ollama ya está escuchando. Si hay
poca RAM, podés elegir un modelo conversacional menor, por ejemplo instalar
`llama3.2:3b` y cambiar `BRIDGET_MODELO_CONVERSACION` en `.env`; no es una garantía
sobre velocidad o calidad. Embeddings y visión piden CPU para no desalojar al
modelo principal de la GPU. CPU/GPU, carga simultánea y consumo real requieren
pruebas locales; no se necesita CUDA para la vista previa.

El launcher crea los datos bajo `%LOCALAPPDATA%\Bridget`, o `BRIDGET_DATA_DIR` si
se configura: recuerdos, preferencias, agenda, sesiones, datasets y reportes.
No los mueve ni borra automáticamente. Sin launcher ni override se conservan las
rutas históricas (preferencias ancladas al directorio de la app). Para recuperar
datos antiguos, cerrar todas las instancias, hacer backup y copiarlos manualmente
al directorio elegido antes de abrir. No ejecutar dos instancias sobre el mismo
estado: los locks serializan hilos, no procesos. Algunos estados auxiliares de
API/auto-mejora conservan rutas históricas; esa extensión no está empaquetada aquí.

Para Obsidian, crear un vault de **prueba**, y configurar, por ejemplo:

```text
VAULT_PATH=C:/Notas/BridgetPrueba
```

No requiere Obsidian abierto ni plugins: se leen/escriben notas Markdown. Rutas
con espacios/Unicode y nombres reservados de Windows están cubiertos por tests;
se excluyen `.obsidian`/`.trash` y notas enlazadas fuera del vault. La escritura
puede crear categorías e `_inbox`; probar sobre notas sintéticas antes de dar
acceso a un vault personal. Su contenido puede formar parte del contexto enviado
al modelo local; proveedores cloud opcionales mantienen sus propios requisitos
de consentimiento y claves. Escrituras JSON principales son atómicas. Embeddings
nuevos incluyen la identidad del modelo; no se comparan dimensiones incompatibles. Los
recuerdos históricos sin modelo asumen el configurado: al cambiarlo, respaldar y
reindexar explícitamente; no existe todavía migración automática del índice.

## 4. Diagnóstico y primera prueba

Desde cualquier directorio, usando rutas absolutas si hace falta:

```powershell
.\.venv\Scripts\python.exe scripts/launch.py diagnose --probe-ollama --strict
.\.venv\Scripts\python.exe scripts/launch.py diagnose --audio-devices --native-imports --json
.\.venv\Scripts\python.exe scripts/smoke.py
# Prueba adicional con chat y embeddings REALES, sobre datos sintéticos temporales:
.\.venv\Scripts\python.exe scripts/smoke.py --ollama
```

También existe `py -3.11 scripts/diagnose.py` sin instalar dependencias: informa
faltantes sin importar modelos o escritorio. `--probe-ollama` hace solo GET local
`/api/tags` con 3 s y respuesta acotada, no genera texto ni descarga modelos.
`--audio-devices` enumera PortAudio, no graba/reproduce. `--native-imports`
comprueba módulos fijos en procesos separados con timeout, detectando DLLs
faltantes sin iniciar modelos ni dispositivos. El diagnóstico verifica
versiones de paquetes, endpoint/modelos, directorio de datos, vault (sin leer
notas), aplicaciones autorizadas, WebView2 y disponibilidad de PowerShell;
los checks de presencia no acreditan que el componente funcione. `--strict`
falla por faltantes de texto, modelos chat/embeddings consultados o errores;
los opcionales ausentes no son un fallo de la instalación Text.

La prueba sintética crea y borra sus propios recuerdos y vault temporal,
comprueba saludo, lectura/escritura de notas, arranque real de la CLI desde otro
cwd (saludo/hora/salir con voz desactivada), bloqueo de aplicaciones no
permitidas y bloqueo del sandbox. No ejecuta el snippet de prueba.
`--ollama` comprueba además una respuesta y recuperación semántica reales;
no usa notas personales ni necesita GPU. Su salida debe incluir
`synthetic_smoke: ok`, `local_models: ok` y `dynamic_execution: blocked`.
Sin el flag, `local_models: not_tested` es lo esperado.

```powershell
.\.venv\Scripts\python.exe scripts/launch.py text
```

Probar `hola`, `qué hora es`, una consulta breve, `recordá que mi color de prueba
es violeta` y `qué sabés de mi color de prueba`. La conversación requiere Ollama;
el saludo/hora y apertura de un alias autorizado no requieren el LLM. La voz
arranca desactivada; `activar voz` la activa si instalaste sus dependencias.
El cierre del proceso conserva datos; `scripts/smoke.py` solo conserva resultados
en pantalla. No habilitar auto-mejora para resolver fallos de instalación.

## 5. Audio, voz y notificaciones

`BRIDGET_INPUT_DEVICE` y `BRIDGET_OUTPUT_DEVICE` aceptan índice PortAudio o parte
del nombre del dispositivo. Dejar sin configurar para los predeterminados.
En Windows permitir acceso al micrófono a aplicaciones de escritorio desde
Configuración > Privacidad y seguridad > Micrófono. Probar auriculares primero
para evitar que Bridget transcriba su propia salida.

- Captura mono 16 kHz/int16; fragmentos y WAV temporales únicos cerrados antes de
  reabrirlos (compatible Windows). Capturas continuas y por botón acotan buffers
  a 60 s; falta validar latencia/permisos y cambios de dispositivo en PC física.
- faster-whisper usa CPU/int8 y carga perezosa. La primera activación de voz puede
  descargar el modelo `BRIDGET_MODELO_STT` (por defecto `small`) desde Hugging Face.
  Para trabajo offline prepararlo previamente y configurar una ruta local del
  modelo CTranslate2. El instalador/diagnóstico no lo descargan. El respaldo
  Whisper clásico se conserva en perfil opcional y requiere ffmpeg.
- `BRIDGET_TTS=windows` usa voz instalada de System.Speech/SAPI: prefiere español
  si está instalado; si no, usa la voz predeterminada. Agregar una voz española
  de Windows si hace falta. No necesita claves, CUDA ni modelo Coqui.
- `BRIDGET_TTS=auto` conserva Google si hay clave; en Windows intenta luego SAPI,
  después Coqui. `google`/`coqui` fuerzan el proveedor. Google envía texto al
  servicio externo; no configurarlo si querés un ensayo enteramente local.
  Coqui/CPU-CUDA siguen disponibles mediante el perfil opcional histórico y
  requieren instalación, descarga/licencia y pruebas específicas de modelos.
- Reproducción WAV mediante PortAudio en ambas plataformas, sin `paplay`.
  La reproducción interrumpible tiene `poll/terminate/wait`; se limpia su WAV.
  Un driver que bloquee una escritura puede retrasar la interrupción: comprobar
  drivers reales. Nunca se considera este proceso/audio un sandbox.
- Recordatorios usan notificación WinForms en Windows y `notify-send` en Linux,
  más voz/push si están configurados. Texto transportado por JSON/stdin hacia un
  script fijo, sin interpolarlo como PowerShell. Windows puede suprimir globos
  por No molestar, sesión no interactiva o política; eso requiere prueba visual.
  No se ejecuta notificación real en CI.

Pruebas manuales explícitas tras instalar Voice:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'asistente_v2'); from core.voice import hablar; hablar('Prueba de voz de Bridget')"
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'asistente_v2'); from core.listen import escuchar_fragmento; print(escuchar_fragmento(3))"
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'asistente_v2'); from core.notifications import notify; print(notify('Bridget','Recordatorio de prueba'))"
.\.venv\Scripts\python.exe scripts/launch.py desktop
```

Ventana: enviar texto, mantener botón micrófono/soltar, probar manos libres,
pausa mientras habla y detener/reanudar sin duplicar escuchas. Captura de pantalla
usa memoria, no un PNG persistente en `/tmp`; comprobar múltiples monitores/DPI
con datos no sensibles antes de usar visión.

## 6. Permisos para abrir aplicaciones

Por defecto ninguna aplicación, navegador o automatización está autorizada.
Crear `%LOCALAPPDATA%\Bridget\applications.json` (o `BRIDGET_APPS_FILE`) con los
alias y **rutas absolutas de ejecutables existentes** que quieras permitir:

```json
{
  "applications": {
    "notepad": "C:/Windows/System32/notepad.exe"
  },
  "browser": false,
  "automation": false
}
```

Escribir `abrí notepad`, comprobar el alias propuesto y confirmar `sí` o una
opción `a`–`d`. La confirmación pertenece a esa sesión, se consume una vez y se
vuelve a comprobar el archivo de permisos al lanzar. La salida del LLM no puede
agregar permisos. No se admiten argumentos, `.cmd`, `.bat`, `.ps1` ni shell. Si la
app necesita argumentos o un protocolo de Windows Store, falta un adaptador
específico; no habilitar un intérprete como alternativa automática.

`browser: true` permite abrir búsquedas HTTPS solicitadas con el navegador
predeterminado; la consulta se codifica como URL. `automation: true` por sí solo
no ejecuta nada: click/teclas requieren además confirmación explícita del caller;
se mantiene `PyAutoGUI.FAILSAFE=True`. La interfaz no concede ese permiso mediante
texto del modelo. Para automatización opcional instalar el perfil original de
escritorio/PyAutoGUI aparte y revisarlo. No dar acceso de escritura al archivo de
permisos a otro usuario. Una aplicación permitida conserva los permisos normales
del usuario del sistema; no está aislada.

## 7. Linux y componentes opcionales

Linux conserva cliente Ollama, captura/reproducción PortAudio, Coqui/Google,
notificaciones `notify-send`, Obsidian y aliases autorizados (rutas absolutas de
binarios ejecutables). Crear venv e instalar `requirements/base.txt`, agregar
`requirements/voice.txt` y otros perfiles según capacidades. El launcher usa
`$XDG_DATA_HOME/bridget` o `~/.local/share/bridget`; los locks Windows no se usan
en Linux. Según distribución, instalar PortAudio, `libnotify`, backend Qt/GTK de
pywebview y motor de voz local. No se probó hardware Linux en Codex.

API/push/documentos siguen en los perfiles existentes, fuera del instalador de
vista previa. Para API, instalar `requirements/api.txt`, definir una clave propia
`BRIDGET_API_KEY` y ejecutar `scripts/launch.py api`: escucha solo `127.0.0.1:8000`.
No exponer por ngrok/red hasta revisar autenticación, proxy y permisos de acciones.
Pandoc/WeasyPrint requieren sus runtimes externos para convertir PDF; no están
validados en esta entrega. No confundir esos perfiles con Text/Voice bloqueados
por hashes.

## Evidencia automatizada

CI sobre `0f99cd4`: 260 pruebas aprobadas en Windows Server 2025, 255 aprobadas y
5 omitidas en Ubuntu; Ruff aprobado, instalación limpia Text/Voice+GUI Windows
y texto Linux con `pip check` y smoke aprobados
([ejecución](https://github.com/DzAndre7/Bridget---Windows-/actions/runs/39348483658)).
Incluye síntesis SAPI real de una frase fija a WAV, sin reproducirla; los tests
restantes de audio/escritorio usan controladores simulados. En Codex pasaron
además 71 regresiones revisadas de conversación/streaming, memoria y agenda con
LLM simulado. El smoke añade arranque real de CLI desde otro cwd en la revisión
siguiente. Estos resultados no prueban modelos ni hardware Windows 11.

## Matriz pendiente en Windows 11 físico

| Prueba | Resultado esperado y evidencia a registrar |
| --- | --- |
| Text/Voice/Desktop en usuario estándar | Instalación limpia, `pip check`, smoke y diagnóstico; conservar inventario sin claves |
| Ollama CPU/GPU | Chat normal/streaming, recuperación semántica, servicio detenido/modelo ausente sin cerrar CLI; RAM/VRAM y latencia |
| Micrófono integrado/USB/Bluetooth | Permiso concedido/denegado, silencio, 60 s, cambiar dispositivo, español y limpieza WAV |
| Parlantes/auriculares | SAPI español, streaming, interrupción y ausencia de WAV huérfanos; sesión sin audio |
| Ventana/WebView2 | Apertura, botones, manos libres, DPI, múltiples monitores, captura autorizada |
| Recordatorio | Globo visible/No molestar, voz desactivada/activada y cierre del hilo al salir |
| Aplicaciones | Alias permitido + confirmar; cancelar/revocar; metacaracteres nunca son comando; FAILSAFE |
| Obsidian | Vault de prueba con espacios/acentos, guardar/buscar, notas internas/enlaces excluidos, backup antes de cambiar embeddings |
| Reinstalación/actualización | Estado fuera del checkout conservado; no lanzar dos instancias; Linux como regresión |

No están probados en hardware real: precisión de STT, drivers WASAPI/MME,
barge-in/eco, voces españolas, comportamiento visual de notificaciones/WebView2,
CUDA/Coqui ni capacidad de los modelos. La ejecución dinámica continúa rechazada
aunque todas estas pruebas funcionen; es una línea de trabajo independiente.
