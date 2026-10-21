
# Bridget — Asistente personal con IA local

Bridget es un asistente personal de código abierto que corre casi
completamente en tu máquina, sin depender de servicios externos de pago.
Construido desde cero por un programador autodidacta.

## ¿Qué puede hacer hoy?

- Conversación por voz bidireccional (STT + TTS en español)
- Control del sistema: abrir aplicaciones
- Memoria semántica: recuerda cosas por significado, no por palabra exacta
- Revisor de código con modelo experto externo (Groq)
- Auto-auditoría: revisa y mejora su propio código
- Sandbox de código: crea, ejecuta y prueba código en un entorno aislado
  (proceso separado, carpeta temporal, límites de recursos y sin red)
- Auto-mejora: propone mejoras a su propio código, las prueba en el sandbox
  y espera tu aprobación antes de aplicar nada
- Chats persistentes: cada arranque es un chat nuevo que muestra y recuerda
  la conversación de la sesión anterior
- Interfaz web con modo manos libres
- API remota con autenticación

## Dependencias externas opcionales

Bridget es principalmente local, pero tiene dos capacidades que
requieren conexión a internet:

- Búsqueda web: busca en internet si se lo pedís
- Revisor de código: usa Groq (gratuito) para auditar y mejorar código

Todo lo demás — conversación, voz, memoria, control del sistema —
corre completamente offline.

## Sandbox de código

Bridget puede crear y probar su propio código en un entorno controlado
(`core/sandbox.py`). Todo corre en un proceso separado, dentro de una
carpeta temporal descartable, con límites de CPU/memoria/disco y sin
acceso a la red (via `unshare`, si el sistema lo permite).

Comandos que entiende:

- **"Creá y probá un script que ..."** → le pide el código al modelo, lo
  ejecuta en el sandbox y, si falla, le devuelve el error al modelo para
  que lo corrija (hasta 3 intentos). El código que pasa sus pruebas se
  guarda en `asistente_v2/sandbox_workspace/`.
- **"Probá este código: ..."** o **"Probá el archivo /ruta/x.py"** →
  ejecuta ese código en el sandbox y cuenta cómo le fue.
- **"Probá tu código"** / **"Corré tus tests"** → copia el proyecto entero
  a una carpeta temporal y corre la suite de pytest sobre la copia.

Además, cuando le pedís que mejore un archivo del proyecto
("optimizá core/brain.py"), antes de ofrecerte guardar la versión nueva
la prueba en el sandbox: aplica el cambio sobre una copia temporal del
proyecto y corre todas las pruebas ahí. El código real nunca se toca
hasta que vos confirmás.

## Auto-mejora

Sobre el sandbox se monta el ciclo completo de auto-mejora
(\`core/auto_mejora.py\`): detectar → proponer → probar → esperar tu OK.

- **"Mejorate"** o **"proponé una mejora"** → elige el archivo más olvidado
  (o el que le digas), lo pasa por el revisor experto, reescribe el archivo
  con esa guía y corre la suite entera en el sandbox. Si pasa, la propuesta
  queda en \`mejoras_pendientes/\` (código + diff + metadatos) sin tocar nada.
- **"¿Qué mejoras tenés pendientes?"** → lista las propuestas esperando.
- **"Aplicá la mejora"** → re-verifica en el sandbox (y que el archivo no
  haya cambiado desde la propuesta) y recién entonces escribe.
- **"Descartá la mejora"** → la archiva sin aplicar.

## Chats persistentes

Las conversaciones se guardan en \`asistente_v2/sesiones/\` y sobreviven a
los reinicios. Cada arranque (consola o ventana) abre un chat nuevo que:

- muestra la conversación de la sesión anterior al abrir (nunca arrancás
  frente a una ventana vacía), y
- le pasa al modelo un resumen de esa charla, así retoma el hilo sin que
  le repitas nada — recuerda la sesión anterior, no toda la historia.

La API remota persiste una sesión por cliente (header \`X-Session-Id\`).
Preguntale **"¿qué chats guardados hay?"** para ver la lista.

## Stack

- LLM: dolphin3:8b via Ollama (local, sin censura)
- Embeddings: nomic-embed-text-v2-moe (multilingüe)
- STT: Whisper + webrtcvad
- TTS: Coqui TTS
- API: FastAPI + ngrok

## Instalación paso a paso

### Paso 1 — Instalar lo básico
Necesitás tener instalado en tu sistema:
- Python 3.11
- Ollama (https://ollama.com) — el programa que corre los modelos de IA
- Git — para descargar el proyecto

### Paso 2 — Descargar los modelos de IA
Ollama necesita descargar dos modelos. Abrí una terminal y corré:
\`\`\`bash
ollama pull dolphin3:8b
ollama pull nomic-embed-text-v2-moe
\`\`\`
Esto puede tardar un rato la primera vez (son varios GB).

### Paso 3 — Descargar el proyecto
\`\`\`bash
git clone https://github.com/bridget/bridget.git
cd bridget
\`\`\`

### Paso 4 — Crear el entorno de Python
Esto crea un espacio aislado para las dependencias del proyecto:
\`\`\`bash
python -m venv venv311
source venv311/bin/activate
pip install -r requirements.txt
\`\`\`

### Paso 5 — Configurar las claves
Creá un archivo llamado \`.env\` en la carpeta del proyecto con este contenido:
\`\`\`
GROQ_API_KEY=tu_clave_de_groq
RICK_API_KEY=una_clave_que_inventes_para_la_web
\`\`\`
La de Groq se saca gratis en groq.com. La otra la inventás vos.

### Paso 6 — Arrancar
\`\`\`bash
source venv311/bin/activate
python main.py
\`\`\`
¡Listo! Ya podés hablar con tu asistente.


### Cambiar el nombre del asistente
Editá \`asistente_v2/config.py\` y cambiá \`ASSISTANT_NAME\` (y \`ASSISTANT_CREATOR\`)
por lo que quieras. Es el único lugar: prompts, ventana y contexto lo
toman de ahí.

### Cambiar los modelos
También en \`asistente_v2/config.py\`: \`MODELO_CONVERSACION\`, visión,
embeddings, Whisper y el revisor de Groq se eligen ahí, en un solo lugar.
Para probar otro modelo alcanza con \`ollama pull <modelo>\` y cambiar esa
línea. Ojo con la VRAM: en una GPU de 6 GB entra UN solo modelo de
lenguaje a la vez — alternar entre dos cuesta 10-15 segundos de recarga
por turno, por eso todo usa el mismo por defecto.

## Estado del proyecto

Bridget está en desarrollo activo. Funciona y tiene base sólida,
pero hay bugs y limitaciones reales — especialmente en la fluidez
de la conversación, limitada por el modelo de 8B parámetros.
El objetivo a futuro es un asistente que no solo ejecute tareas
sino que acompañe el pensamiento.
EOF