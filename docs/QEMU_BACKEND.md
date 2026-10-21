# Backend experimental de VM: estado y validación pendiente

## Alcance de esta entrega

Se implementó un controlador real para QEMU x64 sobre Windows Hypervisor Platform
(WHPX), un supervisor Linux invitado y un canal de datos acotado. **No se arrancó
una VM en Codex y no se habilita ejecutar código generado.** La fábrica pública
sigue devolviendo `SinAislamiento`; `QemuExperimental.ejecutar()` rechaza siempre.
La única entrada de QA pública ejecuta una autoprueba fija benigna. Su éxito no
cambia el estado, no equivale a acreditar seguridad y requiere revisión antes de
cualquier integración con Bridget.

## Alternativas evaluadas

| Motor | Evaluación |
| --- | --- |
| Windows Sandbox | Frontera de virtualización adecuada como candidata para código Windows. Requiere edición compatible y virtualización. Desde Windows 11 24H2 tiene CLI, pero `exec` no ofrece actualmente salida estándar del proceso. Faltan canal de resultados sin carpeta host escribible, control por trabajo, límites y teardown comprobados. No implementado. |
| Hyper-V, VM Windows descartable | Opción preferida para comprobar compatibilidad Windows nativa. Requiere edición compatible, imagen Windows/Python mantenida, broker y protocolo sin red ni integración de escritorio. Gestión privilegiada y ciclo de imágenes pendientes. No implementado. |
| QEMU + WHPX, invitado Linux | Primer controlador implementado: hardware virtualizado, entrada como disco RAW de solo lectura y salida serial acotada. Sirve para código Python portable; no acredita APIs Windows. WHPX debe estar habilitado; no se intenta TCG si falta. Motor e imagen todavía sin validar. |
| QEMU + TCG | Descartado para entradas hostiles: QEMU excluye explícitamente la emulación TCG de sus garantías de aislamiento. No existe fallback TCG. |
| Docker Desktop | Depende de VM/daemon y configuración verificables; compartir socket o carpetas rompe el modelo. No se implementó ni ejecutó. |

WHPX por sí solo tampoco acredita la seguridad de este conjunto. Hay que fijar
una versión mantenida de QEMU, revisar su soporte/política de seguridad para esa
combinación exacta, dispositivos y acelerador, aplicar actualizaciones y endurecer
el proceso host. Si esa evaluación no permite confiar en WHPX, continuar sobre
Hyper-V u otro hipervisor validado; nunca sustituirlo por emulación.

## Componentes y controles implementados

- `core/sandbox_backends/qemu/bundle.py`: inventario completo y SHA-256 de
  ejecutable, DLL, firmware, kernel e initramfs; disco local fijo; rechazo de
  enlaces, reparse points, hardlinks de componentes y archivos extra. No descarga
  ni instala herramientas. Los hashes acreditan identidad, no procedencia segura.
- `controller.py`: máquina q35/WHPX, una CPU, memoria explícita, sin NIC, monitor,
  pantalla, carpetas compartidas ni QMP. Solo disco de entrada RAW de lectura y
  consola serial. Cada trabajo usa directorio temporal, nonce e imagen limpia.
  No se copia el entorno host: solo rutas de sistema/runtime y temporales.
- `windows_job.py` y `windows_process.py`: creación con
  `PROC_THREAD_ATTRIBUTE_JOB_LIST`, suspensión inicial y asignación atómica al Job
  antes de reanudar. Lista explícita de handles heredables: stdin nulo y consola.
  Job no heredable con `KILL_ON_JOB_CLOSE`, un proceso host, límite de memoria
  (RAM invitada + 512 MiB) y tiempo CPU. Si el sistema no soporta estos controles
  se rechaza el arranque; no hay lanzamiento alternativo sin Job.
- Deadline de 1–300 s que incluye preparación y arranque, evento de cancelación,
  terminación del Job en `finally`, espera y comprobación de cero procesos
  activos; Ctrl+C también limpia. La comprobación de hashes/lecturas de staging
  es síncrona: cancelación y deadline se comprueban entre fases, no interrumpen
  una lectura de disco bloqueada. Tras el timeout puede haber hasta 5 s de espera
  de proceso y 5 s de cierre de consola, además del tiempo de E/S del sistema.
- Entrada acotada (500 archivos/10 MiB de fuentes/16 MiB de transporte), salida
  serial máxima 256 KiB y texto de resultado máximo 8000 bytes por stream. JSON
  estricto, tipos, rutas, nonce y registros duplicados verificados. La salida de
  la VM siempre es dato no confiable, nunca comando ni prueba de aislamiento.
- `guest/qemu/agent.py`: supervisor PID 1, Python aislado, trabajo uid/gid 65534,
  sin grupos extra, `no_new_privs`, límites POSIX de memoria/CPU/archivos/procesos,
  salida drenada y acotada, timeout y muerte del grupo. `pytest` conserva su
  funcionalidad y ejecuta tests dentro del invitado. Al terminar se apaga la VM;
  el host la destruye incluso si el invitado no coopera.
- `guest/qemu/init`: rootfs no escribible por el usuario de trabajo, `/work`
  tmpfs de 64 MiB, sin dispositivos host ni red. Límites POSIX son defensa dentro
  del invitado, no una sustitución del hipervisor. Los hijos que se separen del
  grupo no sobreviven a la destrucción completa de la VM.

## Bundle e imagen: preparación pendiente

No se incluye binario QEMU, kernel, initramfs, descarga automática ni instalador.
Antes de la autoprueba, un mantenedor debe preparar y revisar una imagen en una
VM de construcción limpia y desechable, con procedencia/licencias, versiones y
actualizaciones documentadas. **No usar un initramfs del equipo personal:** puede
contener claves de cifrado, configuración de red u otros secretos.

La imagen necesita BusyBox (`/bin/busybox`), Python 3 con biblioteca estándar y
sus dependencias ELF, pytest preinstalado, `/bridget/agent.py`, `/init` ejecutable
(instalar con modo 0755), directorios `/proc`, `/sys`, `/dev`, `/work`; kernel x64
con consola serial, tmpfs, devtmpfs y virtio PCI/block incorporados. El protocolo
espera `/dev/vda`. No incorporar usuarios personales, claves, red, SSH ni agentes
host. Nada se instala desde Internet durante los trabajos. Falta automatizar y
validar una construcción reproducible de esta imagen.

El directorio local dedicado debe contener `bundle.json` con exactamente:

```json
{
  "version": 1,
  "protocol": 1,
  "qemu": "runtime/qemu-system-x86_64.exe",
  "kernel": "guest/bzImage",
  "initrd": "guest/initramfs.cpio.gz",
  "firmware": "runtime/share",
  "files": {
    "runtime/qemu-system-x86_64.exe": "SHA256_REAL_DE_64_HEX",
    "guest/bzImage": "SHA256_REAL_DE_64_HEX",
    "guest/initramfs.cpio.gz": "SHA256_REAL_DE_64_HEX",
    "runtime/share/bios-256k.bin": "SHA256_REAL_DE_64_HEX"
  }
}
```

Es un esquema ilustrativo, no un bundle utilizable: inventariar **todos** los
archivos y DLL reales. Proteger el directorio mediante ACL de mantenimiento;
los hashes no evitan carreras si otro proceso puede reemplazar archivos entre
comprobación y carga. También falta restringir identidad/ACL/red del proceso
QEMU host (por ejemplo un servicio con cuenta dedicada y política revisada).
Un Job limita recursos, pero no impide leer archivos o abrir red tras un escape.
El aislamiento de red del invitado no equivale a restringir la red del broker.

Solo después de revisar la imagen y el runtime, desde PowerShell en una máquina
de QA Windows 11 desechable con WHPX habilitado:

```powershell
cd asistente_v2
python -m core.sandbox_backends.qemu.selftest --bundle C:\BridgetVM\bundle
```

Ejecuta exclusivamente la sonda fija; ni acepta snippets ni habilita ejecución
dinámica. No debe ejecutarse sobre una PC con secretos como prueba de ataques.

## Evidencia automatizada y pruebas Windows 11 pendientes

Las pruebas de protocolo, bundle, supervisor y controlador usan datos y dobles:
no arrancan QEMU ni ejecutan entradas. Las pruebas Windows de Job ejecutan solo
programas Python fijos revisados para inspeccionar límites, bloquear procesos
hijos, terminar un proceso dormido y comprobar su muerte si el broker desaparece.
CI sobre `189ed64`: 163 tests aprobados en Windows Server 2025, 159 aprobados
y 4 omitidos en Ubuntu; Ruff aprobado en ambos
([run](https://github.com/DzAndre7/Bridget---Windows-/actions/runs/39335991340)).
Son pruebas reales de Win32, pero **no de la frontera del hipervisor**. La CI
Windows Server no sustituye validación sobre Windows 11 físico.

Antes de habilitar cualquier código generado, registrar en Windows 11:

1. Versión/edición/build, WHPX y virtualización firmware; runtime e imagen
   fijados. Arranque real y autoprueba; fallo cerrado sin WHPX o con hashes malos.
2. Archivos testigo host inaccesibles; ausencia de perfiles, credenciales,
   portapapeles, shares y dispositivos. Pruebas controladas de enlaces/junctions
   y carreras bajo ACL revisada. No usar datos personales como testigos.
3. Ausencia de NIC/rutas, DNS, acceso al host y servicios de metadatos. Inspección
   desde el host, además de la sonda cooperativa del invitado.
4. Límites efectivos al agotar RAM, CPU, scratch, número de procesos y salida;
   contabilización de memoria WHPX fuera de QEMU/Job. Verificar que el host sigue
   operativo. Las cuotas configuradas no prueban por sí solas su eficacia.
5. Cancelación durante arranque/ejecución, timeout, Ctrl+C, cierre forzado del
   broker, fallo del hipervisor, apagado invitado que falla; cero procesos/VM,
   handles, archivos y trabajos sobrevivientes. Inspección externa repetida.
6. Trabajos consecutivos sin persistencia; consola truncada/manipulada, registros
   múltiples, nonce incorrecto y errores de limpieza nunca aceptan resultados.
7. Revisión de seguridad independiente del hipervisor, dispositivos, canal de
   datos y endurecimiento host; definir criterios de actualización y revocación.

Un resultado correcto de la sonda no completa esta lista. La activación necesita
una modificación revisada de la fábrica y del backend; no existe interruptor de
entorno para saltarla. Compatibilidad nativa Windows sigue necesitando invitado
Windows/Windows Sandbox: una VM Linux no puede acreditarla.

## Fuentes primarias

- [QEMU: modelo y límites de seguridad, exclusión de TCG](https://www.qemu.org/docs/master/system/security.html).
- [QEMU: opciones de arranque](https://www.qemu.org/docs/master/system/qemu-manpage.html).
- [Windows Sandbox CLI y limitación de salida de exec](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli).
- [Configuración Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).
- [Atributos de creación: JOB_LIST y HANDLE_LIST](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).
- [Asignación atómica al Job y riesgo de procesos huérfanos](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812/).
