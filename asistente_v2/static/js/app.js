// URLs relativas: la página y la API las sirve el MISMO uvicorn, así que
// funcionan igual por LAN, ngrok o localhost. Antes el dominio del túnel
// estaba clavado acá y cambiarlo rompía la app.
const API_URL = "/chat";
const API_AUDIO_URL = "/audio";
const API_UPLOAD_URL = "/upload";
const API_INBOX_URL = "/inbox";
const API_DELETE_URL = "/inbox";
const API_CHAT_ARCHIVO_URL = "/chat-archivo";
const API_SPEAK_URL = "/speak";
const API_HISTORIAL_URL = "/historial";
const API_AGENDA_URL = "/agenda";

// La key ya no viaja hardcodeada en este archivo: cualquiera que llegue a la
// URL puede leer el código fuente servido, así que antes era pública de
// hecho. Ahora se pide una vez por navegador y se guarda local (igual que
// SESSION_ID); si la key guardada deja de valer, cargarHistorial() la
// borra y vuelve a pedirla.
const API_KEY = (() => {
    let k = localStorage.getItem("bridget_api_key");
    if (!k) {
        k = window.prompt("Ingresá la clave de acceso a Bridget:") || "";
        if (k) localStorage.setItem("bridget_api_key", k);
    }
    return k;
})();

// Id de sesión persistente por navegador: la API lo usa para darte tu propia
// conversación (historial + confirmaciones) sin mezclarse con otros clientes.
const SESSION_ID = (() => {
    let s = localStorage.getItem("bridget_session_id");
    if (!s) {
        s = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
            : String(Date.now()) + "-" + Math.random().toString(16).slice(2);
        localStorage.setItem("bridget_session_id", s);
    }
    return s;
})();

const chat = document.getElementById("chat");
const inputArea = document.getElementById("input-area");
const input = document.getElementById("input");
const send = document.getElementById("send");
const mic = document.getElementById("mic");
const handsfree = document.getElementById("handsfree");
const attach = document.getElementById("attach");
const inboxModal = document.getElementById("inbox-modal");
const modalClose = document.getElementById("modal-close");
const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const filesList = document.getElementById("files-list");
const selectedInfo = document.getElementById("selected-info");

let grabando = false;
let mediaRecorder;
let audioChunks = [];
let audioContext;
let stream;
let archivoSeleccionado = null;

function agregarMensaje(texto, tipo) {
    const div = document.createElement("div");
    div.className = `mensaje ${tipo}`;
    if (tipo === "rick") {
        const nombreDiv = document.createElement("div");
        nombreDiv.className = "nombre";
        nombreDiv.textContent = "RICK //";
        div.appendChild(nombreDiv);

        const textoDiv = document.createElement("div");
        textoDiv.textContent = texto;
        div.appendChild(textoDiv);

        // Agregar contenedor para controles de voz
        const audioDiv = document.createElement("div");
        audioDiv.className = "rick-audio";
        div.appendChild(audioDiv);

        // Crear botón para iniciar reproducción
        const btnVoz = document.createElement("button");
        btnVoz.textContent = "🔊 ESCUCHAR";
        btnVoz.addEventListener("click", () => reproducirRespuesta(texto, audioDiv));
        audioDiv.appendChild(btnVoz);
    } else {
        div.textContent = texto;
    }
    chat.appendChild(div);
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

function agregarMensajeConSincronizar() {
    const div = document.createElement("div");
    div.className = "mensaje rick mensaje-error-sync";

    const nombreDiv = document.createElement("div");
    nombreDiv.className = "nombre";
    nombreDiv.textContent = "RICK //";
    div.appendChild(nombreDiv);

    const textoDiv = document.createElement("div");
    textoDiv.textContent = "Se cortó la conexión, pero es posible que ya haya respondido. Tocá para revisar:";
    div.appendChild(textoDiv);

    const btnSync = document.createElement("button");
    btnSync.textContent = "🔄 Buscar respuesta";
    btnSync.style.marginTop = "8px";
    btnSync.addEventListener("click", async () => {
        btnSync.textContent = "Buscando...";
        btnSync.disabled = true;
        await sincronizarConServidor();
        // si después de sincronizar este mensaje de error sigue en pantalla,
        // es que de verdad no hay nada nuevo: se lo dejamos saber
        if (chat.contains(div)) {
            btnSync.textContent = "No encontré nada nuevo. Reintentar";
            btnSync.disabled = false;
        }
    });
    div.appendChild(btnSync);

    chat.appendChild(div);
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

async function reproducirRespuesta(texto, audioContainer) {
    try {
        // Reutilizar el botón ya existente (creado en agregarMensaje)
        const btn = audioContainer.querySelector("button");
        const audioState = audioContainer.dataset.audioState || "none";

        if (audioState === "none") {
            btn.textContent = "⏳ GENERANDO...";
            btn.disabled = true;
            audioContainer.dataset.audioState = "generating";

            const res = await fetch(API_SPEAK_URL, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "x-api-key": API_KEY
                },
                body: JSON.stringify({ texto })
            });

            if (!res.ok) {
                throw new Error("Error generando audio");
            }

            const audioBlob = await res.blob();
            const audioUrl = URL.createObjectURL(audioBlob);
            const audio = new Audio(audioUrl);
            audioContainer.dataset.audio = audioUrl;
            audioContainer.audio = audio;

            btn.disabled = false;
            btn.textContent = "🔊 ESCUCHAR";
            audioContainer.dataset.audioState = "ready";

            let pauseTimeout = null;

            btn.onclick = (e) => {
                e.stopPropagation();
                const currentState = audioContainer.dataset.audioState;

                if (currentState === "playing") {
                    // Pause
                    audio.pause();
                    btn.textContent = "⏸️ PAUSADO";
                    audioContainer.dataset.audioState = "paused";

                    // Auto-stop después de 15s
                    pauseTimeout = setTimeout(() => {
                        audio.pause();
                        audio.currentTime = 0;
                        btn.textContent = "🔊 ESCUCHAR";
                        btn.classList.remove("activo");
                        audioContainer.dataset.audioState = "ready";
                    }, 15000);

                } else if (currentState === "paused") {
                    // Resume
                    if (pauseTimeout) {
                        clearTimeout(pauseTimeout);
                        pauseTimeout = null;
                    }
                    audio.play();
                    btn.textContent = "⏸️ REPRODUCIENDO";
                    btn.classList.add("activo");
                    audioContainer.dataset.audioState = "playing";

                } else if (currentState === "ready") {
                    // Play
                    audio.play();
                    btn.textContent = "⏸️ REPRODUCIENDO";
                    btn.classList.add("activo");
                    audioContainer.dataset.audioState = "playing";
                }
            };

            audio.onended = () => {
                btn.textContent = "🔊 ESCUCHAR";
                btn.classList.remove("activo");
                audioContainer.dataset.audioState = "ready";
                if (pauseTimeout) clearTimeout(pauseTimeout);
            };

            audio.onerror = () => {
                btn.textContent = "🔊 ERROR";
                btn.disabled = true;
            };
        }

    } catch (e) {
        console.error("Error:", e);
        const btn = audioContainer.querySelector("button");
        if (btn) {
            btn.textContent = "🔊 ESCUCHAR";
            btn.disabled = false;
        }
        audioContainer.dataset.audioState = "none";
    }
}

// ============ MODAL ============
attach.addEventListener("click", () => {
    inboxModal.classList.add("abierto");
    cargarArchivos();
});

modalClose.addEventListener("click", () => {
    inboxModal.classList.remove("abierto");
});

inboxModal.addEventListener("click", (e) => {
    if (e.target === inboxModal) {
        inboxModal.classList.remove("abierto");
    }
});

// ============ AUDIO ============
async function iniciarGrabacion() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
            await enviarAudio(audioBlob);
        };

        mediaRecorder.start();
        grabando = true;
        mic.classList.add("grabando");
        mic.textContent = "⏹️";
    } catch (e) {
        agregarMensaje("Error al acceder al micrófono.", "rick");
    }
}

function detenerGrabacion() {
    if (mediaRecorder && grabando) {
        mediaRecorder.stop();
        grabando = false;
        mic.classList.remove("grabando");
        mic.textContent = "🎙️";
        stream.getTracks().forEach(track => track.stop());
    }
}

async function enviarAudio(audioBlob) {
    const cargando = document.createElement("div");
    cargando.className = "mensaje rick cargando";
    cargando.textContent = "transcribiendo...";
    chat.appendChild(cargando);

    try {
        const formData = new FormData();
        formData.append("file", audioBlob, "audio.wav");

        const res = await fetch(API_AUDIO_URL, {
            method: "POST",
            headers: {
                "x-api-key": API_KEY,
                "x-session-id": SESSION_ID
            },
            body: formData
        });
        const data = await res.json();
        chat.removeChild(cargando);

        if (data.error) {
            agregarMensaje(`Error: ${data.error}`, "rick");
        } else {
            input.value = data.texto_transcrito;
            input.focus();
        }
    } catch (e) {
        if (chat.contains(cargando)) {
            chat.removeChild(cargando);
        }
        agregarMensaje("Error de conexión.", "rick");
    }
}

// ============ MANOS LIBRES ============
let manosLibresActivo = false;
let manosLibresStreamActual = null;
let manosLibresAudioActual = null;

const UMBRAL_VOZ = 12;          // umbral de volumen (0-255) para considerar que hay voz
const SILENCIO_MS = 1600;       // silencio para cortar la grabación
const ESPERA_MAX_MS = 8000;     // tiempo máximo esperando que el usuario empiece a hablar
const GRABACION_MAX_MS = 15000; // tope de seguridad por grabación
const FRASES_SALIDA = ["salir del modo voz", "salir modo voz", "salir manos libres", "salir de manos libres", "modo texto"];

handsfree.addEventListener("click", () => {
    if (manosLibresActivo) {
        detenerManosLibres();
    } else {
        iniciarManosLibres();
    }
});

function agregarEstado(texto) {
    const div = document.createElement("div");
    div.className = "mensaje rick cargando";
    div.textContent = texto;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

function iniciarManosLibres() {
    manosLibresActivo = true;
    handsfree.classList.add("activo");
    agregarEstado("🤚 Modo manos libres activado. Te escucho...");
    cicloManosLibres();
}

function detenerManosLibres() {
    manosLibresActivo = false;
    handsfree.classList.remove("activo", "grabando");

    if (manosLibresAudioActual) {
        manosLibresAudioActual.pause();
        manosLibresAudioActual = null;
    }
    if (manosLibresStreamActual) {
        manosLibresStreamActual.getTracks().forEach(track => track.stop());
        manosLibresStreamActual = null;
    }
    agregarEstado("🤚 Modo manos libres desactivado.");
}

async function cicloManosLibres() {
    while (manosLibresActivo) {
        handsfree.classList.add("grabando");
        const estadoEscucha = agregarEstado("🎙️ escuchando...");
        const audioBlob = await escucharConVAD();
        if (chat.contains(estadoEscucha)) chat.removeChild(estadoEscucha);
        handsfree.classList.remove("grabando");

        if (!manosLibresActivo) break;
        if (!audioBlob) continue; // no se detectó voz, reintentar

        const estadoTranscribe = agregarEstado("🎬 transcribiendo...");
        let texto_transcrito;
        try {
            const formData = new FormData();
            formData.append("file", audioBlob, "audio.wav");
            const res = await fetch(API_AUDIO_URL, {
                method: "POST",
                headers: { "x-api-key": API_KEY, "x-session-id": SESSION_ID },
                body: formData
            });
            const data = await res.json();
            if (chat.contains(estadoTranscribe)) chat.removeChild(estadoTranscribe);

            if (data.error || !data.texto_transcrito) continue;
            texto_transcrito = data.texto_transcrito.trim();
        } catch (e) {
            if (chat.contains(estadoTranscribe)) chat.removeChild(estadoTranscribe);
            continue;
        }

        if (!texto_transcrito) continue;

        const textoLower = texto_transcrito.toLowerCase();
        if (FRASES_SALIDA.some(frase => textoLower.includes(frase))) {
            detenerManosLibres();
            break;
        }

        agregarMensaje(texto_transcrito, "usuario");

        const cargando = document.createElement("div");
        cargando.className = "mensaje rick cargando";
        cargando.textContent = "procesando...";
        chat.appendChild(cargando);

        let respuesta;
        try {
            const res = await fetch(API_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json", "x-api-key": API_KEY, "x-session-id": SESSION_ID },
                body: JSON.stringify({ texto: texto_transcrito })
            });
            const data = await res.json();
            if (chat.contains(cargando)) chat.removeChild(cargando);
            if (data.error) {
                agregarMensaje(`Error: ${data.error}`, "rick");
                continue;
            }
            respuesta = data.respuesta;
            agregarMensaje(respuesta, "rick");
        } catch (e) {
            if (chat.contains(cargando)) chat.removeChild(cargando);
            agregarMensaje("Error de conexión.", "rick");
            continue;
        }

        if (!manosLibresActivo) break;
        await reproducirYesperar(respuesta);
    }
}

function reproducirYesperar(texto) {
    return new Promise(async (resolve) => {
        try {
            const res = await fetch(API_SPEAK_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json", "x-api-key": API_KEY },
                body: JSON.stringify({ texto })
            });
            if (!res.ok) return resolve();

            const audioBlob = await res.blob();
            const audioUrl = URL.createObjectURL(audioBlob);
            const audio = new Audio(audioUrl);
            manosLibresAudioActual = audio;

            audio.onended = () => { manosLibresAudioActual = null; resolve(); };
            audio.onerror = () => { manosLibresAudioActual = null; resolve(); };
            audio.play();
        } catch (e) {
            resolve();
        }
    });
}

function escucharConVAD() {
    return new Promise(async (resolve) => {
        let stream, audioContext, analyser, recorder, intervalo;
        let chunks = [];
        let hablando = false;
        let ultimaVoz = Date.now();
        const inicio = Date.now();
        let finalizado = false;

        const limpiar = () => {
            if (intervalo) clearInterval(intervalo);
            if (stream) stream.getTracks().forEach(t => t.stop());
            if (audioContext && audioContext.state !== "closed") audioContext.close();
            if (manosLibresStreamActual === stream) manosLibresStreamActual = null;
        };

        const terminar = (resultado) => {
            if (finalizado) return;
            finalizado = true;
            limpiar();
            resolve(resultado);
        };

        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            terminar(null);
            return;
        }

        if (!manosLibresActivo) {
            stream.getTracks().forEach(t => t.stop());
            terminar(null);
            return;
        }

        manosLibresStreamActual = stream;
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const fuente = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        fuente.connect(analyser);
        const datos = new Uint8Array(analyser.frequencyBinCount);

        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (e) => chunks.push(e.data);
        recorder.onstop = () => {
            terminar(hablando ? new Blob(chunks, { type: "audio/wav" }) : null);
        };
        recorder.start();

        intervalo = setInterval(() => {
            if (!manosLibresActivo) {
                if (recorder.state !== "inactive") recorder.stop();
                else terminar(null);
                return;
            }

            analyser.getByteTimeDomainData(datos);
            let suma = 0;
            for (let i = 0; i < datos.length; i++) {
                const valor = datos[i] - 128;
                suma += valor * valor;
            }
            const volumen = Math.sqrt(suma / datos.length);
            const ahora = Date.now();

            if (volumen > UMBRAL_VOZ) {
                hablando = true;
                ultimaVoz = ahora;
            } else if (hablando && ahora - ultimaVoz > SILENCIO_MS) {
                recorder.stop();
                return;
            }

            if (!hablando && ahora - inicio > ESPERA_MAX_MS) {
                recorder.stop();
                return;
            }

            if (ahora - inicio > GRABACION_MAX_MS) {
                recorder.stop();
                return;
            }
        }, 50);
    });
}

// ============ CHAT ============
let esperandoRespuesta = false;

async function enviar() {
    const texto = input.value.trim();
    if (!texto) return;
    agregarMensaje(texto, "usuario");
    input.value = "";
    const cargando = document.createElement("div");
    cargando.className = "mensaje rick cargando";
    cargando.textContent = "procesando...";
    chat.appendChild(cargando);
    esperandoRespuesta = true;
    try {
        let url = API_URL;
        let body = { texto };
        if (archivoSeleccionado) {
            url = API_CHAT_ARCHIVO_URL + "?nombre=" + encodeURIComponent(archivoSeleccionado);
        }
        const res = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "x-api-key": API_KEY,
                "x-session-id": SESSION_ID
            },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (chat.contains(cargando)) chat.removeChild(cargando);
        if (data.error) {
            agregarMensaje(`Error: ${data.error}`, "rick");
        } else {
            agregarMensaje(data.respuesta, "rick");
        }
        esperandoRespuesta = false;
    } catch (e) {
        if (chat.contains(cargando)) chat.removeChild(cargando);
        agregarMensajeConSincronizar();
        // esperandoRespuesta queda en true: no sabemos si el server llegó a
        // responder. Se apaga recién cuando sincronizarConServidor() resuelve
        // (por botón manual o solo al volver a la pantalla / recuperar red).
    }
}
async function sincronizarConServidor() {
    console.log("sincronizando...");
    try {
        const res = await fetch(API_HISTORIAL_URL, {
            headers: { "x-api-key": API_KEY, "x-session-id": SESSION_ID }
        });
        const data = await res.json();
        console.log("historial recibido:", data);
        const historialServidor = data.actual || [];

        const mensajesRickVisibles = Array.from(chat.querySelectorAll(".mensaje.rick"))
            .filter(el => !el.classList.contains("mensaje-error-sync") && !el.classList.contains("cargando"));
            
        const respuestasServidor = historialServidor.filter(m => m.role === "assistant");
        console.log("respuestas en servidor:", respuestasServidor.length);

        if (respuestasServidor.length > mensajesRickVisibles.length) {
            console.log("¡hay mensajes faltantes! agregando...");
            const faltantes = respuestasServidor.slice(mensajesRickVisibles.length);
            chat.querySelectorAll(".mensaje-error-sync, .cargando").forEach(el => {
                chat.removeChild(el);
            });
            faltantes.forEach(m => agregarMensaje(m.content, "rick"));
            esperandoRespuesta = false;
        }
    } catch (e) {
        console.log("ERROR en sincronización:", e);
    }
}

// Si se corta la conexión justo cuando el usuario cambia de pantalla
// (bloquea el celular, cambia de app), no hay forma de mostrarle un botón:
// apenas vuelve a la pantalla, o el navegador recupera la red, reintentamos solos.
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && esperandoRespuesta) {
        sincronizarConServidor();
    }
});
window.addEventListener("online", () => {
    if (esperandoRespuesta) sincronizarConServidor();
});

// ============ INBOX ============
async function cargarArchivos() {
    try {
        const res = await fetch(API_INBOX_URL, {
            headers: {
                "x-api-key": API_KEY
            }
        });
        const data = await res.json();
        mostrarArchivos(data.archivos);
    } catch (e) {
        console.error("Error cargando archivos:", e);
    }
}

function mostrarArchivos(archivos) {
    filesList.innerHTML = "";

    if (archivos.length === 0) {
        filesList.innerHTML = '<div style="color: #00ff8866; font-size: 11px; text-align: center; padding: 20px;">Sin archivos subidos</div>';
        return;
    }

    archivos.forEach(archivo => {
        const div = document.createElement("div");
        div.className = "file-item";
        if (archivoSeleccionado === archivo.nombre) {
            div.classList.add("seleccionado");
        }

        div.innerHTML = `
            <span class="file-name">${archivo.nombre}</span>
            <button class="file-delete">✕</button>
        `;

        div.querySelector(".file-delete").addEventListener("click", (e) => {
            e.stopPropagation();
            eliminarArchivo(archivo.nombre);
        });

        div.addEventListener("click", () => {
            document.querySelectorAll(".file-item").forEach(f => f.classList.remove("seleccionado"));
            div.classList.add("seleccionado");
            archivoSeleccionado = archivo.nombre;
            attach.classList.add("activo");
            selectedInfo.textContent = `✓ ${archivo.nombre} seleccionado`;
            selectedInfo.classList.add("activo");
        });

        filesList.appendChild(div);
    });
}

async function subirArchivo(file) {
    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch(API_UPLOAD_URL, {
            method: "POST",
            headers: {
                "x-api-key": API_KEY
            },
            body: formData
        });

        if (res.ok) {
            cargarArchivos();
        } else {
            const data = await res.json();
            agregarMensaje(`Error: ${data.detail}`, "rick");
        }
    } catch (e) {
        agregarMensaje("Error al subir archivo.", "rick");
    }
}

async function eliminarArchivo(nombre) {
    try {
        const res = await fetch(API_DELETE_URL + "/" + encodeURIComponent(nombre), {
            method: "DELETE",
            headers: {
                "x-api-key": API_KEY
            }
        });

        if (res.ok) {
            if (archivoSeleccionado === nombre) {
                archivoSeleccionado = null;
                attach.classList.remove("activo");
                selectedInfo.textContent = "Sin archivo seleccionado";
                selectedInfo.classList.remove("activo");
            }
            cargarArchivos();
        }
    } catch (e) {
        console.error("Error eliminando archivo:", e);
    }
}

// ============ EVENT LISTENERS ============
send.addEventListener("click", enviar);
input.addEventListener("keypress", e => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        enviar();
    }
});

// Auto-ajustar altura del textarea
input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 100) + "px";
});

// La barra de entrada crece con texto multilinea; como ya no es "fixed"
// sino un elemento normal del flex-column, el chat se reajusta solo y
// nunca queda tapado. Solo hace falta mantener el scroll abajo si el
// usuario ya estaba viendo el final.
const cercaDelFondo = () => chat.scrollHeight - chat.scrollTop - chat.clientHeight < 40;
new ResizeObserver(() => {
    if (cercaDelFondo()) chat.scrollTop = chat.scrollHeight;
}).observe(inputArea);

mic.addEventListener("mousedown", iniciarGrabacion);
mic.addEventListener("mouseup", detenerGrabacion);
mic.addEventListener("mouseleave", detenerGrabacion);

mic.addEventListener("touchstart", (e) => {
    e.preventDefault();
    iniciarGrabacion();
});
mic.addEventListener("touchend", (e) => {
    e.preventDefault();
    detenerGrabacion();
});

// Mantener el último mensaje visible cuando aparece el teclado virtual
input.addEventListener("focus", () => {
    setTimeout(() => { chat.scrollTop = chat.scrollHeight; }, 300);
});
if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {
        chat.scrollTop = chat.scrollHeight;
    });
}

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");

    const files = e.dataTransfer.files;
    for (let file of files) {
        subirArchivo(file);
    }
});

fileInput.addEventListener("change", (e) => {
    const files = e.target.files;
    for (let file of files) {
        subirArchivo(file);
    }
    fileInput.value = "";
});

// ============ PRESENCIA (motor de partículas) ============
(function(){
  var canvas = document.getElementById('bcanvas');
  if(!canvas) return;
  var ctx = canvas.getContext('2d');
  var W, H, cx, cy;

  function resize(){
    var dpr = window.devicePixelRatio || 1;
    var w = window.innerWidth;
    var h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(1, 0, 0, 1, 0, 0); // resetea cualquier transform previo
    ctx.scale(dpr, dpr);
    W = w; H = h;
    cx = W/2; cy = H/2;
  }
  window.addEventListener('resize', resize);

  var t = 0;
  window.bridgetModo = 'reposo';  // global, para que el chat pueda cambiarlo
  var sacudida = 0;

  var cfg = {
    col: '40,140,150', cant: 140, disp: 100, vel: 100, sz: 100,
    react: 100, core: 100, flat: 78, opac: 65
  };
  window.bridgetCfg = cfg;  // global para el editor

  var P = [];
  function rebuild(n){
    P = [];
    for(var i=0;i<n;i++){
      P.push({ a: Math.random()*Math.PI*2, r: 30+Math.random()*95, s: 0.25+Math.random()*0.9, sz: 0.6+Math.random()*1.8, tw: Math.random()*Math.PI*2 });
    }
  }
  rebuild(cfg.cant);
  window.bridgetRebuild = rebuild;

  function voz(){
    var base = (window.bridgetModo==='reposo')
      ? (0.12 + 0.06*Math.sin(t*0.04))
      : (0.45 + 0.55*Math.abs(Math.sin(t*0.07))*(0.55+0.45*Math.sin(t*0.21)));
    return base * (cfg.react/100) + sacudida;
  }

  function loop(){
    t += cfg.vel/100;
    if(sacudida > 0) sacudida *= 0.92;
    ctx.clearRect(0,0,W,H);
    var v = voz();
    var col = cfg.col;
    var flat = cfg.flat/100;

    if(cfg.core > 0){
      var coreR = (5 + v*5) * (cfg.core/100);
      var g = ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(1,coreR*4));
      g.addColorStop(0,'rgba('+col+','+(0.5+v*0.4)+')');
      g.addColorStop(1,'rgba('+col+',0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx,cy,Math.max(1,coreR*4),0,Math.PI*2); ctx.fill();
      ctx.beginPath(); ctx.arc(cx,cy,coreR,0,Math.PI*2);
      ctx.fillStyle = 'rgba(235,250,252,'+(0.7+v*0.3)+')'; ctx.fill();
    }

    for(var i=0;i<P.length;i++){
      var p = P[i];
      p.a += 0.0016*p.s*(0.5+v);
      p.tw += 0.05;
      var rr = (p.r*(cfg.disp/100)) + v*55*p.s*(cfg.disp/100);
      var x = cx + Math.cos(p.a)*rr;
      var y = cy + Math.sin(p.a)*rr*flat;
      var alpha = (0.15 + v*0.55)*(0.6+0.4*Math.sin(p.tw));
      var size = p.sz*(0.5+v*0.9)*(cfg.sz/100);
      ctx.beginPath();
      ctx.arc(x,y,Math.max(0.2,size),0,Math.PI*2);
      ctx.fillStyle = 'rgba('+col+','+alpha+')';
      ctx.fill();
    }
    requestAnimationFrame(loop);
  }
  resize();
  loop();

  window.bridgetSacudir = function(){ sacudida = 0.35; setTimeout(resize, 360); };
})();

// ============ ARRANQUE: PWA + HISTORIAL + RECORDATORIOS ============

// Service worker: cachea el caparazón para abrir al instante y permite
// instalar Bridget como app ("Agregar a pantalla de inicio").
if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// Al abrir, la ventana nunca arranca vacía: mostramos la charla anterior
// (si la sesión rotó por inactividad) y lo que va de la charla actual.
// Mismo comportamiento que la ventana de escritorio.
async function cargarHistorial() {
    try {
        const res = await fetch(API_HISTORIAL_URL, {
            headers: { "x-api-key": API_KEY, "x-session-id": SESSION_ID }
        });
        if (res.status === 401) {
            localStorage.removeItem("bridget_api_key");
            alert("Clave incorrecta. Volvé a intentar.");
            location.reload();
            return;
        }
        if (!res.ok) return;
        const data = await res.json();

        const render = (mensajes) => {
            for (const m of mensajes) {
                agregarMensaje(String(m.content || ""), m.role === "user" ? "usuario" : "rick");
            }
        };

        if (data.anterior && data.anterior.length) {
            const div = document.createElement("div");
            div.className = "mensaje rick cargando";
            div.textContent = "— de la charla anterior —";
            chat.appendChild(div);
            render(data.anterior);
            if (data.actual && data.actual.length) {
                const hoy = document.createElement("div");
                hoy.className = "mensaje rick cargando";
                hoy.textContent = "— hoy —";
                chat.appendChild(hoy);
            }
        }
        render(data.actual || []);
        chat.scrollTop = chat.scrollHeight;
    } catch (e) { /* sin red no hay historial, no es fatal */ }
}
cargarHistorial();

// Vigía de recordatorios: consulta la agenda y avisa EN EL CELULAR cuando
// vence uno (la voz de la PC suena allá; esto cubre cuando estás afuera).
// Los ya avisados se recuerdan en localStorage para no repetir.
const AVISADOS_KEY = "bridget_avisados";
let agendaPendientes = [];

function yaAvisado(id) {
    try { return JSON.parse(localStorage.getItem(AVISADOS_KEY) || "[]").includes(id); }
    catch (e) { return false; }
}

function marcarAvisadoLocal(id) {
    try {
        const lista = JSON.parse(localStorage.getItem(AVISADOS_KEY) || "[]");
        lista.push(id);
        localStorage.setItem(AVISADOS_KEY, JSON.stringify(lista.slice(-100)));
    } catch (e) { /* localStorage lleno o bloqueado: solo repetiría el aviso */ }
}

async function refrescarAgenda() {
    try {
        const res = await fetch(API_AGENDA_URL, { headers: { "x-api-key": API_KEY } });
        if (res.ok) agendaPendientes = (await res.json()).pendientes || [];
    } catch (e) { /* sin red: seguimos con la última lista conocida */ }
}

function revisarVencidos() {
    const ahora = Date.now();
    for (const r of agendaPendientes) {
        // 25 s de margen: aunque el servidor lo marque avisado justo antes
        // del próximo refresco, el celular no se lo pierde
        if (new Date(r.cuando).getTime() > ahora + 25000 || yaAvisado(r.id)) continue;
        marcarAvisadoLocal(r.id);
        agregarMensaje(`⏰ Recordatorio: ${r.texto}`, "rick");
        if ("Notification" in window && Notification.permission === "granted") {
            try { new Notification("Bridget ⏰", { body: r.texto, icon: "/static/icono-192.png" }); }
            catch (e) { /* algunos navegadores móviles lo bloquean fuera de SW */ }
        }
    }
}

setInterval(refrescarAgenda, 60000);
setInterval(revisarVencidos, 15000);
refrescarAgenda();

// El permiso de notificaciones se pide en el primer gesto del usuario
// (los navegadores ignoran el pedido si no viene de una interacción).
function pedirPermisoNotificaciones() {
    if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
    }
}
send.addEventListener("click", pedirPermisoNotificaciones, { once: true });
input.addEventListener("focus", pedirPermisoNotificaciones, { once: true });

// --- Notificaciones push ---
async function activarNotificaciones() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        alert("Este navegador no soporta notificaciones push.");
        return;
    }

    const permiso = await Notification.requestPermission();
    if (permiso !== "granted") {
        alert("No diste permiso para notificaciones.");
        return;
    }

    const registro = await navigator.serviceWorker.ready;

    const resClave = await fetch("/push/vapid-public-key", {
        headers: { "x-api-key": API_KEY },
    });
    const { clave } = await resClave.json();

    const suscripcion = await registro.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(clave),
    });

    await fetch("/push/suscribir", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": API_KEY },
        body: JSON.stringify(suscripcion.toJSON()),
    });

    alert("Notificaciones activadas.");
}

document.getElementById("btn-notificaciones")?.addEventListener("click", activarNotificaciones);

function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i++) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

// --- Panel del editor: abrir/cerrar ---
const btnPanel = document.getElementById('btn-panel');
const panelEditor = document.getElementById('panel');
const escenario = document.getElementById('escenario');

btnPanel.addEventListener('click', () => {
    const abierto = panelEditor.classList.toggle('abierto');
    escenario.classList.toggle('empujado', abierto);
});