# Aislamiento: diseño y estado de implementación

Las funciones de conversación, memoria, audio y aplicaciones autorizadas tienen
un camino independiente del sandbox: ver [instalación Windows 11](WINDOWS11.md).
El diagnóstico y sus imports fijos son herramientas de confianza, no ejecutan
código generado ni habilitan el proveedor experimental.

## Qué funciona hoy

La API de sandbox se importa en Windows y Linux usando solo biblioteca estándar.
Conserva `ejecutar_codigo`, `probar_codigo`, `probar_proyecto`,
`probar_cambio_en_proyecto`, `crear_y_probar` y `guardar_codigo_validado`.
La comprobación estática y extracción de código siguen disponibles.

**No hay todavía un backend de ejecución validado.** La fábrica devuelve
`SinAislamiento` en todas las plataformas y las operaciones dinámicas se rechazan
con `exito=False`, `etapa=aislamiento_no_disponible`. No existe una variable de
entorno para omitirlo. Detectar Docker, `unshare` o Windows Sandbox no habilita
nada. Esto es un cierre de la ejecución insegura, no un sandbox Windows operativo.

La auto-mejora no pide propuestas, no consulta al revisor y no aplica cambios
cuando falta el aislamiento. Listar/descartar propuestas sigue disponible.
Un cambio ya propuesto tampoco puede aplicarse sin volver a validarlo. El
handler antiguo de reescritura ya no ofrece guardarlo tras fallar las pruebas,
ni trata sintaxis válida de un archivo externo como una prueba de seguridad.

## Modelo de amenaza

Todo snippet, archivo de usuario, código de LLM, propuesta, test y `conftest.py`
se considera no confiable. Puede intentar leer claves, navegar por el host,
abrir red, agotar memoria/disco/CPU, crear procesos hijos, manipular enlaces o
producir salidas enormes. Los datos de entrada no deben convertirse en comandos
host. Ni `venv`, un cwd temporal, `HOME` distinto, un subprocess, un timeout,
Job Objects ni un namespace de red aislado constituyen por sí solos un sandbox.

El código del coordinador, el runtime/hipervisor y la imagen base son parte de la
base de confianza. Un usuario que modifique Bridget o el hipervisor puede alterar
la política; esto no es una frontera contra administradores del propio host.
La compilación estática tiene límite de tamaño, pero no es una defensa completa
contra denegación de servicio del parser. No exponerla a entradas ilimitadas.

## Dependencias Linux del diseño anterior

| Elemento anterior | Problema y tratamiento actual |
| --- | --- |
| `resource` + `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_CORE` | POSIX; impedía importar en Windows. Se retiraron de la capa común. No se habían fijado límites de CPU. |
| `preexec_fn` | No soportado en Windows; inseguro en procesos con threads. No se usa en el host; el supervisor experimental Linux lo usa solo dentro de la VM. |
| `unshare -r -n true` | Namespaces Linux y herramienta `true`; solo probaba bloqueo de red. Su fallo abría un camino sin aislamiento. Eliminado el fallback. |
| `start_new_session=True` | En POSIX cambia la sesión; no garantiza terminar descendientes ni representa el modelo de procesos Windows. No se usa como aislamiento. |
| `HOME`, `TMPDIR`, `LANG`, `/usr/bin:/bin` | Suposiciones del entorno POSIX; no ofrecían aislamiento de archivos ni preparaban el entorno Windows del invitado. Ya no se fabrica un env host para ejecutar entradas. |
| `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` | Daban a las pruebas acceso al escritorio host. No forman parte del nuevo contrato. |
| `sys.executable` del host y rutas absolutas host | No se pueden usar como ejecutables/rutas dentro de una VM. El contrato expresa operaciones, no comandos host. |
| `capture_output` y recorte posterior | Acumulaba salida ilimitada antes de recortarla. El backend futuro debe limitar durante la lectura. |
| `TimeoutExpired.stdout.decode()` con `text=True` | Podía asumir bytes aunque recibiera texto. El resultado común ya es un tipo explícito; no se depende de ese detalle de subprocess. |
| Copia completa del proyecto | Podía transferir `.env`, claves y memorias. Se reemplazó por una copia reducida con allowlist y límites. No se considera esa copia una barrera de aislamiento. |

## Contrato modular

`core/sandbox.py` prepara entradas y conserva el formato de resultados.
`core/sandbox_backends/base.py` define estados y solicitudes inmutables y la
interfaz `BackendAislado`. `core/sandbox_backends/__init__.py` selecciona el
proveedor. Usa `sys.platform`: `platform.system()` puede iniciar `ver` mediante shell en
Windows/Python 3.11 y no es adecuado para una consulta sin procesos.
No importa módulos POSIX ni hace descubrimiento dinámico desde
comandos, plugins o variables del usuario.

Una solicitud contiene una operación cerrada (`script` o `pytest`), el directorio
staging y límites explícitos. No contiene shell, variables host, credenciales,
permisos de red ni acceso al escritorio. El backend debe verificar, por ejecución:

- Aislamiento de archivos host, incluida ausencia de sockets del runtime.
- Red bloqueada, incluidos servicios del host y metadatos de nube.
- Límites efectivos de memoria, CPU, disco, procesos y salida.
- Terminación de todo el árbol de procesos al finalizar, cancelar o vencer timeout.
- Entorno e imagen sin secretos; ningún `.env`, vault, historial o perfil del host.
- Destrucción comprobada del entorno y tratamiento de resultados como datos.

Solo entonces puede declarar disponibles todas las garantías. Un código de
retorno cero no basta: cada resultado debe confirmar aislamiento y limpieza. Los
errores de inspección o ejecución cierran la operación sin intentar un proceso
normal en el host. Estos flags son obligaciones del proveedor de confianza, no
una verificación de virtualización por sí mismos; por eso no se habilita un
proveedor de producción en esta entrega.

La preparación de proyectos excluye entornos, Git, sesiones, informes, inbox,
memorias y claves; solo admite código y recursos concretos. Rechaza enlaces,
junctions/reparse points, rutas fuera de la raíz y otros volúmenes; limita tamaño
y cantidad de archivos. No resuelve por sí sola carreras de cambios del host:
un backend real deberá volver a validar una instantánea cerrada antes de
transferirla y nunca montarla como proyecto host escribible.

## Implementación prevista para Windows 11

El controlador experimental QEMU/WHPX, su alcance y validaciones pendientes se
detallan en [QEMU_BACKEND.md](QEMU_BACKEND.md). Solo permite una sonda fija; no
está registrado en la fábrica y no se ha arrancado una VM en esta entrega.

### Primera opción para compatibilidad nativa: VM Windows descartable

Usar una VM dedicada Hyper-V con imagen limpia de Python 3.11 x64 y herramientas
preinstaladas, sin red ni credenciales, restaurada para cada trabajo. Un broker
host de confianza entrega un manifiesto de archivos y recoge únicamente salida
textual limitada. No deben exponerse perfil, proyecto original, carpetas de
usuario, dispositivos, portapapeles ni sockets de administración al invitado.
El broker tiene que verificar el estado del hipervisor, las restricciones y la
identidad de la imagen antes de ejecutar. La imagen se prepara fuera de la
petición y no se instala nada desde red mientras se procesa código no confiable.

Requiere virtualización activada en firmware, recursos de VM y una edición y
configuración de Windows que soporte Hyper-V. Windows 11 Home necesita una
alternativa de virtualización compatible; no se debe bajar la seguridad para
hacerlo funcionar. Job Objects puede complementar la gestión de procesos, pero
no sustituye esta frontera de aislamiento.

### Alternativa: Windows Sandbox

Windows 11 Pro/Enterprise/Education, característica opcional Windows Sandbox y
virtualización habilitadas; no está disponible de forma estándar en Home.
Desactivar red, portapapeles, audio/video de entrada, impresoras y GPU compartida;
usar solo entrada de staging de lectura, sin exponer archivos personales.
Desde Windows 11 24H2 existe CLI de Windows Sandbox, pero `exec` no devuelve
actualmente stdout del proceso. Un `.wsb` y `LogonCommand` por sí solos no dan un protocolo fiable de resultado,
recursos y teardown. Hace falta diseñar y probar el broker y el canal de salida.
No abrir una carpeta host escribible general para obtener resultados. No se ha
implementado ni habilitado esta alternativa.

### Docker y futura compatibilidad Linux

Docker Desktop con contenedores Linux puede alojar pruebas portables dentro de
su VM, pero no prueba comportamiento nativo Windows. Exigir motor/contexto local
verificados, imagen fijada por digest, usuario no privilegiado, sin bind mounts
host ni socket Docker, sin capacidades adicionales, sin red, filesystem de solo
lectura con scratch acotado, política seccomp y límites de recursos/procesos.
El daemon es parte de confianza y nunca se comparte con las entradas.

Un Docker convencional sobre el kernel del host no se considera aquí suficiente
para código hostil. Para Linux se prevé el mismo contrato sobre microVM/Kata u
otra frontera validada. `unshare` solo, rootless Docker solo o un contenedor con
`--privileged` no habilitarán ejecución. No hay un backend Docker implementado;
no se construyeron ni arrancaron contenedores en estas pruebas.

## Verificación necesaria antes de habilitar un proveedor

En una VM de ensayo desechable y con cargas fijas benignas comprobar: acceso
negado a archivos testigo del host, red y servicios locales inaccesibles,
entrada de solo lectura, ausencia de credenciales, límites de memoria/disco/CPU,
salida acotada, cancelación y eliminación de procesos hijos, reinicio limpio por
trabajo, fallo cerrado cuando el runtime se detiene y rechazo de resultados
manipulados, links y junctions. No probar payloads peligrosos sobre la PC de uso.

Las pruebas automatizadas del PR no acreditan esas garantías: usan resultados
simulados para comprobar el contrato y ejecutan rechazos reales sin backend.
