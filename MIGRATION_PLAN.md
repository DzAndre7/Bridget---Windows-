# Migración y estabilización de Bridget para Windows 10/11

## Actualización: cierre seguro del sandbox y perfiles Windows

Trabajo realizado únicamente en `migration/windows-stage-1`, sobre el head
`0c717522692ccc20dbc66a40757eee68b7b9c612`, para actualizar el PR #1.
El original y `main` no son destinos de escritura.

### Estado actual

- **Resuelto:** la capa común del sandbox no importa `resource` ni usa
  `preexec_fn`, `unshare`, variables X11/Wayland ni intérpretes host para ejecutar
  entradas. Se conserva la API y se separa el contrato de backend por plataforma.
- **Resuelto:** código no confiable, tests, `conftest` y propuestas no se ejecutan
  cuando no existe aislamiento acreditado. El resultado distingue
  `aislamiento_no_disponible` de errores del programa. No hay fallback inseguro,
  bandera de entorno para permitirlo ni excepción por tratarse del propio código.
- **Resuelto:** auto-mejora comprueba aislamiento antes de consultar el modelo o
  el revisor y antes de aplicar propuestas. La reescritura antigua tampoco
  permite guardar código tras fallar la validación. El guardado de código
  validado vuelve a comprobarlo antes de etiquetarlo como probado.
- **Resuelto:** las copias para futuras pruebas excluyen secretos/estado,
  restringen tipos y tamaño, y rechazan rutas fuera del proyecto, symlinks,
  hardlinks y reparse points/junctions. No son una barrera de seguridad por sí
  mismas y un backend futuro deberá cerrar carreras de cambios al transferirlas.
- **Adaptado:** perfiles de dependencias por capacidad y plataforma. El freeze
  Linux original se conserva íntegro como referencia, fuera de la instalación
  por defecto. Se añaden push/STT ausentes, wheels VAD y Coqui mantenido con la
  misma API. TTS local selecciona CPU cuando no hay CUDA. Ruff se invoca mediante
  el mismo intérprete y con UTF-8 explícito, sin depender del PATH de Scripts
  ni de la página de códigos de Windows.
- **Pendiente explícito:** no se ha implementado ni habilitado un motor de
  ejecución de producción. Actualmente todas las plataformas rechazan ejecución
  dinámica. Se diseñó la integración sobre VM Windows/Windows Sandbox y la
  alternativa Docker dentro de una VM verificada. No se declara seguro un
  runtime por estar instalado. Las capacidades de sandbox/auto-mejora conservan
  sus APIs, pero requieren completar y verificar ese backend para ejecutarse.

El diseño, modelo de amenaza y todas las dependencias Linux identificadas están
en `docs/SANDBOX.md`. Los perfiles, prerrequisitos e instrucciones de validación
están en `docs/DEPENDENCIES_WINDOWS.md`.

### Evidencia de esta actualización

En Codex/Linux, Python 3.12.14:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -c pytest-safety.ini -q
```

Resultado: **110 pruebas aprobadas**, incluidas las 15 comprobaciones anteriores.
Se prueban rechazo sin backend, garantías incompletas, errores y pérdida del
runtime, prohibición de habilitar red, entradas y límites, rechazo de resultados
sin prueba de aislamiento/limpieza, rutas y copias, protección de archivos
originales, parada de reintentos/LLM y bloqueo de aplicación de mejoras.

Los casos que representan resultados de ejecución usan un doble que NO ejecuta
las entradas. Solo lee el staging y devuelve resultados prefijados. Los handlers
y la selección TTS se prueban cargando definiciones revisadas sin importar el
escritorio, cargar modelos ni inicializar voz. No se ejecutó código generado,
ni snippets, ni pruebas de proyectos recibidos. Ruff analiza estáticamente texto
revisado: no se trata como sandbox ni como prueba dinámica.

La CI Windows detectó y permitió corregir tres incompatibilidades concretas:
la consulta `platform.system()` lanzaba `ver` mediante shell (se reemplazó por
`sys.platform`), Ruff recibía texto con la codificación local en lugar de UTF-8,
y `os.path.relpath` lanzaba una excepción entre unidades distintas. El validador
de rutas real ahora se comparte con la aplicación de propuestas y también
rechaza metadatos que apunten fuera de la raíz. Se limitó además el identificador
de pytest del caso de entrada grande para no desbordar variables de entorno.

Ruff pasó en los módulos de sandbox/auto-mejora y las pruebas nuevas. La sintaxis
Python se comprueba en las fuentes del proyecto, sin recorrer venvs. El workflow
`.github/workflows/safety-tests.yml` ejecuta ese mismo subconjunto en Ubuntu y
Windows con Python 3.11; un runner Windows de GitHub no equivale a una prueba
manual en Windows 11. Su resultado debe revisarse después de publicar la rama.

Se resolvieron **47 distribuciones** para el subconjunto base + voz mediante pip
con destino CPython 3.11 `win_amd64`, `--dry-run` y `--only-binary=:all:`. No es una
instalación nativa. Los ensayos binarios de API/escritorio no completaron porque
`http-ece` y PyAutoGUI requieren distribuciones fuente. No se ocultó ese límite:
la construcción/instalación completa, Coqui y CPU/CUDA quedan por validar en
Windows. No hay todavía un lock completo de ese perfil.

### Orden de trabajo restante

1. Implementar y validar el broker/VM de `docs/SANDBOX.md`: no reactivar ejecución
   antes de demostrar aislamiento de archivos/red, límites y destrucción completa.
2. En Windows 11 x64/Python 3.11 limpio: instalar perfiles CPU, ejecutar
   `pip check`, revisar imports y correr `pytest-safety.ini`; comprobar rutas con
   espacios/Unicode, unidades distintas, UNC y junctions/reparse points reales.
3. Probar la integración de VM con cargas benignas en una VM de ensayo:
   red/archivos host inaccesibles, imagen limpia, falta de secretos, límites,
   salida acotada, cancelación, timeout, procesos descendientes y fallo cerrado
   al perder el runtime. Después probar snippets, suite y propuestas completas.
4. Validar Coqui/faster-whisper y las bibliotecas nativas en Windows sin GPU, y
   después un perfil CUDA coherente. Generar locks con hashes tras esa validación.
5. Seguir con los P1 de la primera entrega: `/tmp`, `paplay`, `notify-send`,
   apertura de apps, `shell=True`/FAILSAFE, parsing de rutas, ciclo de vida API,
   persistencia concurrente y seguridad de exposición remota. No fueron
   corregidos ni declarados seguros por esta actualización.
6. Completar la portada pendiente y la matriz final Windows 10/11 antes de
   considerar la migración estable. No fusionar este PR como versión estable.

`MIGRATION_INVENTORY.json` documenta la instantánea del traslado inicial; sus
hashes y estados no representan los cambios posteriores de desarrollo.

---

## Registro de la primera entrega (histórico)

Los hallazgos y conteos siguientes corresponden al traslado inicial. El estado
actual y las correcciones de sandbox/dependencias se describen arriba.


## Estado de esta entrega

Primera etapa: copia del código con saneamiento de datos, inventario y diagnóstico.
**Todavía no es una versión estable ni ejecutable de forma segura en Windows.**
No se hizo una reescritura ni se eliminaron capacidades para forzar compatibilidad.
Los bloqueos descritos abajo siguen presentes en el código salvo los cambios de
saneamiento enumerados expresamente. No arrancar el asistente para probarlos.

Origen: `DzAndre7/Bridget`, rama `master`, commit
`4289fa36972d7638aab7dcbf7a0186b335aa079e`.
Destino real autorizado en esta conversación: `DzAndre7/Bridget---Windows-`
(no existe un repositorio accesible con el nombre exacto `Bridget-Windows`).
Base del destino: `main`, commit `7409981123f11bf00181f928f9e401f72c48f431`.
Todas las escrituras de GitHub de esta entrega se dirigen al destino.

## Inventario y criterio de traslado

`MIGRATION_INVENTORY.json` enumera los 80 archivos versionados del origen, sus
SHA de blob, tamaño, modo, destino y decisión. El destino contenía solamente
`LICENSE` y `README.md`: ambos se conservan sin cambios. No tenía configuración
adicional que fusionar. No se transfiere el historial Git del origen porque
podría volver a introducir datos excluidos de la copia actual.

| Conjunto | Contenido y tratamiento |
| --- | --- |
| Raíz del origen | `.gitignore`, documentación, `requirements.txt`, dos scripts Bash e imagen de portada |
| `asistente_v2/actions/` | Apertura de programas, conversión y automatización de escritorio |
| `asistente_v2/core/` | Conversación, intenciones, voz, memoria, notas, agenda, sesiones, análisis, sandbox y auto-mejora |
| `asistente_v2/interfaz/` | Ventana pywebview, HTML/CSS/JS y configuración visual |
| `asistente_v2/static/` | Interfaz web/PWA, service worker, manifest e iconos |
| `asistente_v2/tests/` | Suite original y benchmarks conservados, sin ejecución masiva |
| `asistente_v2/legacy/` | Experimentos históricos conservados, no ejecutados |
| `inbox/` y `reports/` | Se conservan únicamente sus `.gitkeep` |

Se trasladan **75 archivos del origen**: 66 idénticos byte por byte y 9 saneados.
Los 53 archivos Python originales se conservan. El README del origen se guarda
como `SOURCE_README.md` para preservar el README existente del destino.

Se excluyen los cuatro informes generados de `asistente_v2/reports/`, por ser
artefactos de ejecución que pueden contener contexto y datos de la máquina.
El inventario registra sus nombres sin reproducir sus contenidos.
No aparecen `.env`, credenciales, entornos virtuales, memorias, conversaciones,
datasets personales ni archivos del vault en el árbol versionado analizado;
no se copian desde fuera de ese árbol.

**Pendiente por limitación de transporte:** `Imagen de Bridget.png` (1.296.095
bytes, blob `7934e2c792ea01468f015cf6d530802c2fa98c3b`). El conector devuelve
contenido vacío para este archivo de más de 1 MB; su lector de blobs solo
decodifica UTF-8 y el acceso Git del entorno falla al conectar al proxy.
No se creó un archivo vacío ni un reemplazo inventado. No hay referencias a esa
imagen en el código trasladado; los dos iconos de la PWA sí se copian íntegros.
Recuperar e inspeccionar esa portada desde el commit fijado y comprobar el SHA
antes de cerrar la migración completa de activos.

### Cambios de saneamiento

- `.gitignore`: añade exclusiones de variantes de `.env`, claves privadas,
  credenciales JSON, entornos, cachés, logs, audio y bases locales. Esto ayuda a
  prevenir nuevas altas accidentales; no sustituye la revisión de secretos.
- `config.py`: el nombre personal del creador se reemplaza por `Usuario`, que
  puede personalizarse después en cada instalación. Se neutraliza una referencia
  a hardware concreto en los comentarios.
- `context.md`: se retiran la biografía, ubicación, edad y perfil de hardware.
  Se conserva la descripción de módulos y sus funciones.
- `static/manifest.json`, un texto de voz de `legacy/prueba_google.py` y una
  muestra de `tests/test_memoria_auto.py`: se usan textos genéricos.
- `OPTIMIZACIONES.md`: se reemplaza la ruta local del entorno por un marcador.
- `rick.sh` y `rick-web.sh`: se reemplaza la ruta fija de la máquina de origen
  por el directorio del script. Siguen siendo lanzadores históricos de Bash,
  no lanzadores Windows. No se ejecutaron.

La licencia preexistente se conserva íntegra, incluida su atribución legal.
La búsqueda por patrones de claves habituales y contactos privados no encontró
coincidencias en los archivos preparados; no demuestra ausencia absoluta de
secretos de formatos desconocidos.

## Problemas encontrados y correcciones priorizadas

### P0 — Bloqueos de arranque y ejecución segura

1. **Sandbox incompatible y aislamiento insuficiente.**
   `core/sandbox.py:26` importa `resource`, inexistente en Windows. `brain.py`
   importa ese módulo, por lo que se afecta también el arranque de consola,
   ventana y API. `_ejecutar_aislado` usa `preexec_fn`, no soportado por Windows;
   `unshare` y los límites `RLIMIT_*` también son POSIX. Si `unshare` falla, el
   código sigue ejecutándose con red disponible. Una carpeta temporal y cambiar
   HOME no impiden acceder al resto del sistema de archivos. No hay un límite
   explícito de CPU aunque la documentación lo sugiera; el timeout tampoco
   garantiza terminar todos los descendientes.
   **Corrección:** separar interfaz de sandbox y backend por plataforma;
   diseñar un backend Windows con aislamiento efectivo (proceso/Job Objects
   para límites y árbol de procesos, más aislamiento de archivos/red mediante
   una opción apropiada como VM o contenedor). Job Objects por sí solo no
   aísla archivos ni red. Fallar de forma cerrada si falta el aislamiento, sin
   fingir éxito ni eliminar la función. Validar primero con código fijo benigno.

2. **Instalación no reproducible para Windows.**
   `requirements.txt` es una lista extensa ligada al entorno Linux: incluye
   `python3-xlib`, `triton==2.2.0`, muchos paquetes CUDA de distintas generaciones
   y `torchaudio==2.2.0+cu121`, que requiere revisar el índice de distribución.
   El soporte de wheels y compatibilidad de versiones debe resolverse en Windows,
   no asumirse. `core/push.py` importa `pywebpush`, ausente de requirements;
   `faster-whisper`, recomendado en `listen.py`, también falta (existe fallback
   a Whisper clásico). Pandoc y las bibliotecas nativas de audio/PDF no quedan
   resueltas por pip. **Corrección:** fijar Python 3.11 como primer objetivo,
   separar dependencias directas/comunes y extras de voz, escritorio, push,
   documentos y GPU; generar un lock probado para Windows x64 con CPU y otro
   perfil GPU compatible. Mantener todas las capacidades mediante sus extras,
   sin borrar arbitrariamente paquetes de la lista original. Probar instalación
   limpia, `pip check` e imports controlados antes de arrancar.

3. **Automatización sin protección suficiente.**
   `actions/agent_actions.py` desactiva `pyautogui.FAILSAFE` al importar.
   `actions/system_actions.py` usa `shell=True` para abrir programas/búsquedas
   en Windows con datos derivados de la petición. **Corrección:** restaurar
   parada de emergencia, validación y confirmación contextual de acciones,
   usar argumentos sin shell para ejecutables y una API de navegador/apertura
   apropiada. Agregar pruebas con metacaracteres, espacios y cancelación.
   No ejecutar automatización real hasta completar esto.

### P1 — Paridad funcional de Windows y robustez

4. **Temporales POSIX y colisiones.** `voice.py`, `listen.py`, `vision.py`,
   `manos_libres.py` y `microfono_ventana.py` contienen rutas `/tmp/...`.
   Varias usan nombres fijos. Sustituirlos por temporales únicos con cierre y
   limpieza compatibles con Windows; probar interrupciones y concurrencia.

5. **Audio y notificaciones.** `voice.py` reproduce con `paplay`; `agenda.py`
   llama a `notify-send`. El fallback Coqui exige `.to("cuda")`, por lo que
   no brinda respaldo en una PC sin CUDA. Añadir backends de reproducción y
   notificación de Windows, detección CPU/GPU y recuperación de errores sin
   retirar voz, streaming, interrupción ni recordatorios. Probar micrófono,
   silencio, permisos y selección de dispositivos en Windows 10 y 11.

6. **Descubrimiento y apertura de aplicaciones.** `agent_actions.py` busca
   `/usr/share/applications/*.desktop`; aliases y prompts presuponen Arch Linux
   (`alacritty`, `google-chrome-stable`). Implementar descubrimiento Windows y
   configuración de aliases, conservar el backend Linux y probar instalaciones
   por usuario, rutas con espacios y aplicaciones que no estén en PATH.

7. **Rutas en lenguaje natural.** `intenciones.extraer_ruta_archivo`,
   `extraer_conversion` y varios handlers de `brain.py` solo reconocen formatos
   de barra POSIX; fallan con unidades (`C:\\...`), UNC, espacios y comillas.
   Separar el parsing de rutas de la normalización de texto para no alterar
   mayúsculas/acentos. Añadir casos Windows sin romper los POSIX actuales.

8. **Rutas y ciclo de vida dependientes del arranque.** `api.py` sirve `static`
   respecto del cwd y arranca el avisador durante el import; `preferences.py`
   usa `preferences.json` relativo, mientras otras memorias usan rutas distintas.
   Anclar recursos a `__file__`, centralizar datos locales en una ubicación
   configurable por usuario, mover hilos al ciclo de vida de la aplicación y
   centralizar la carga de variables. Probar arranque desde cualquier directorio
   sin que importe qué terminal se usa.

9. **Persistencia concurrente.** En `preferences.guardar_preferencia` se lee
   antes de tomar el lock; pueden perderse actualizaciones. Memoria/agenda y
   sesiones también requieren revisar locks, nombres temporales y escrituras
   atómicas. Probar dos requests concurrentes y recuperación de JSON corrupto.

10. **API expuesta y entradas de archivos.** `rick-web.sh` escucha en
    `0.0.0.0`, abre ngrok y limpia procesos usando `fuser`/`pkill`.
    `api.py` lee uploads completos sin límite explícito y permite reemplazar
    nombres; el límite por IP confía en `X-Forwarded-For` sin validar el proxy.
    La clave estática da acceso a operaciones amplias sobre la PC.
    Definir primero arranque en localhost, exposición remota explícita,
    límites de carga, permisos por acción y política de proxy confiable.
    Conservar el acceso remoto, pero validar su autenticación y alcance antes
    de exponerlo. Revisar que nombres HTML del frontend no permitan inyección.

### P2 — Instalación, documentación y validación completa

11. Añadir lanzadores PowerShell con rutas relativas y manejo de procesos
    hijos; no trasladar `fuser`/`pkill` a una simulación insegura. Validar consola
    UTF-8, pywebview y su runtime Windows (incluido WebView2 cuando corresponda),
    audio y bibliotecas nativas de Pandoc/WeasyPrint.
12. Corregir instrucciones del README original: URL de clonación de ejemplo,
    ruta de `main.py`, activación POSIX y `RICK_API_KEY` frente al nombre real
    `BRIDGET_API_KEY`. La descripción «offline» está desactualizada: Google TTS,
    Groq, push y búsquedas usan red. Los prompts/contexto aún dicen Arch Linux.
    Documentar capacidades locales y conectadas, sin prometer voz offline sin
    probar su fallback.
13. Recuperar la imagen de portada pendiente, validar su contenido/metadatos
    y SHA; registrar su copia en el inventario.
14. Crear CI con Windows 10/11 de prueba (o runner disponible más pruebas
    manuales reales en ambos sistemas), Python 3.11, perfiles CPU/GPU y servicios
    externos simulados. Probar `tests/` tras revisar imports; los experimentos
    `legacy/` y benchmarks no deben entrar por descubrimiento indiscriminado.

## Validación realizada en Codex

Entorno Linux, Python 3.12.14. No hay una máquina Windows en esta sesión.
El conector GitHub funciona; Git/HTTP desde la shell no conecta al proxy.
No se instalaron dependencias de la aplicación ni se descargaron modelos.
`pytest` no está instalado; no se informa la suite original como aprobada.

Comando reproducible, sin dependencias de terceros:

```text
python -B -m unittest discover -s migration_checks -v
```

Resultado: **15 comprobaciones aprobadas**. Incluyen sintaxis de los 54
archivos Python de la entrega (53 originales y la comprobación añadida),
validación de los dos JSON de la aplicación, persistencia de recuerdos y
preferencias solo en temporales, y manejo de conversión Pandoc con subprocess
simulado: argumentos con espacios, PDF, salida explícita, errores y timeout.
Son pruebas parciales sobre Linux; no prueban Pandoc real ni compatibilidad
de ejecución con Windows.

Los tres JavaScript pasaron `node --check` sin ejecutarse.
Se verificaron hashes de blobs contra el inventario para los archivos idénticos
y preservación de `README.md`/`LICENSE` del destino. Se revisaron patrones de
credenciales y contactos sin volcar posibles valores en los resultados.

No se ejecutaron los entrypoints (`main.py`, API o ventana), scripts Bash,
experimentos Google, código generado, suite de sandbox/auto-mejora, modelos,
micrófono, capturas, automatización, conversiones reales ni servicios remotos.
Esta restricción evita los efectos secundarios detectados durante la revisión.

## Criterio de finalización de la siguiente etapa

1. Resolver P0: entorno Windows instalable y un backend de ejecución segura;
   sin ellos una prueba de arranque no es representativa ni segura.
2. Arrancar consola, ventana y API local sin efectos secundarios de importación.
3. Probar conversación, memoria, notas, agenda, voz completa, visión, búsqueda,
   documentos, push, sesiones y control de apps con una matriz de pruebas.
4. Probar sandbox y auto-mejora en aislamiento real conservando aprobación
   previa a cambios, cancelación, rollback y trazabilidad.
5. Ejecutar suite revisada, `pip check`, integración y prueba manual en
   Windows 10 y Windows 11, incluyendo una PC sin GPU NVIDIA.
6. Revisar y aprobar los cambios mediante PR. Esta entrega no se fusiona ni
   modifica el original automáticamente.
