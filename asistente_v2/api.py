
from config import ASSISTANT_NAME
from dotenv import load_dotenv
load_dotenv()
from core import push as push_mod
from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File
from pydantic import BaseModel
from core.brain import procesar_comando, Sesion, _llm_directo
from core.code_analyzer import listar_reportes, obtener_reporte
from core.listen import escuchar_audio
from core.voice import generar_audio
from core import agenda
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

import os
import hmac
import uuid
import tempfile

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


# El server se expone vía ngrok con una sola API key estática (ver
# _autorizar): sin límite de requests, cualquiera con la URL puede golpear
# el LLM sin freno. request.client.host no sirve solo para identificar
# clientes reales porque ngrok reenvía todo desde localhost — usamos el
# X-Forwarded-For que ngrok sí agrega.
def _client_ip(request: Request) -> str:
    reenviado = request.headers.get("x-forwarded-for")
    if reenviado:
        return reenviado.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=["30/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Recordatorios: el hilo avisador habla y notifica en la PC cuando vencen.
# (El frontend además los muestra en el celular consultando GET /agenda.)
agenda.iniciar_avisador()

API_KEY = os.environ.get("BRIDGET_API_KEY", "")


def _autorizar(x_api_key):
    """Valida la API key en tiempo constante (evita timing attacks). Si no hay
    API_KEY configurada, se rechaza todo (fail-closed)."""
    if not API_KEY or not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="No autorizado")


# --- Sesiones por cliente -------------------------------------------------
# Cada cliente (identificado por el header X-Session-Id) tiene su propia
# conversación y su propio estado de confirmación, y ahora PERSISTE en disco
# (core/sesiones.py): un reinicio del servidor no borra la charla. El caché en
# memoria evita releer el JSON en cada request. Sin header, se usa una sesión
# efímera por request (sin estado cruzado, fail-safe).
from core import sesiones as sesiones_mod

_MAX_SESIONES = 200
_sesiones = {}

def _obtener_sesion(x_session_id):
    if not x_session_id:
        return Sesion()
    sesion = _sesiones.get(x_session_id)
    if sesion is None:
        if len(_sesiones) >= _MAX_SESIONES:
            _sesiones.clear()  # tope simple para no crecer sin límite
        sesion = _sesiones[x_session_id] = sesiones_mod.cargar_o_crear(x_session_id)
    # Si la charla quedó vieja (horas sin actividad), se rota: digest +
    # resumen a memoria semántica, historial limpio. Mismo modelo de
    # memoria que la ventana de escritorio.
    sesiones_mod.refrescar_si_vieja(sesion, funcion_llm=_llm_directo, assistant_name=ASSISTANT_NAME)
    return sesion


# --- Inbox: rutas seguras -------------------------------------------------
INBOX_DIR = os.path.join(os.path.dirname(__file__), "inbox")
EXTENSIONES_PERMITIDAS = {".py", ".txt", ".md", ".json"}

def _ruta_inbox(nombre):
    """Devuelve una ruta dentro del inbox a partir de `nombre`, neutralizando
    cualquier intento de path traversal (../, rutas absolutas): nos quedamos solo
    con el nombre base. El inbox es plano, no hay subcarpetas."""
    base = os.path.basename(nombre or "")
    if not base or base.startswith("."):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")
    return base, os.path.join(INBOX_DIR, base)


class Mensaje(BaseModel):
    texto: str


@app.post("/chat")
async def chat(mensaje: Mensaje, x_api_key: str = Header(None), x_session_id: str = Header(None)):
    _autorizar(x_api_key)
    respuesta = procesar_comando(mensaje.texto, ASSISTANT_NAME, _obtener_sesion(x_session_id))
    return {"respuesta": respuesta}


@app.post("/audio")
async def audio(file: UploadFile = File(...), x_api_key: str = Header(None), x_session_id: str = Header(None)):
    _autorizar(x_api_key)

    ruta_temp = os.path.join(tempfile.gettempdir(), f"bridget_audio_api_{uuid.uuid4().hex}.wav")
    try:
        contenido = await file.read()

        # archivo único por request: dos audios concurrentes no se pisan
        with open(ruta_temp, "wb") as f:
            f.write(contenido)

        texto_transcrito = escuchar_audio(ruta_temp)

        if not texto_transcrito:
            return {"error": "No se pudo transcribir el audio"}

        respuesta = procesar_comando(texto_transcrito, ASSISTANT_NAME, _obtener_sesion(x_session_id))
        return {
            "texto_transcrito": texto_transcrito,
            "respuesta": respuesta
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(ruta_temp):
            os.remove(ruta_temp)


@app.get("/")
async def root():
    return FileResponse("static/index.html")


# El service worker debe servirse desde la raíz: su alcance (scope) es el
# directorio del que se sirve, y desde /static solo podría cachear /static.
@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/manifest.json")
async def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


@app.get("/historial")
async def historial(x_api_key: str = Header(None), x_session_id: str = Header(None)):
    """Lo que la UI necesita para no arrancar vacía: los mensajes de la
    charla anterior (si la sesión rotó) y los de la charla en curso."""
    _autorizar(x_api_key)
    sesion = _obtener_sesion(x_session_id)
    return {
        "anterior": sesion.historial_anterior,
        "actual": sesion.historial,
    }

class Suscripcion(BaseModel):
    endpoint: str
    keys: dict


@app.post("/push/suscribir")
async def push_suscribir(suscripcion: Suscripcion, x_api_key: str = Header(None)):
    """El celu llama a esto una vez, cuando activás las notificaciones. Guarda
    la suscripción para que el avisador de la agenda pueda mandar push después."""
    _autorizar(x_api_key)
    ok = push_mod.guardar_suscripcion(suscripcion.dict())
    if not ok:
        raise HTTPException(status_code=500, detail="No se pudo guardar la suscripción")
    return {"mensaje": "Suscripción guardada"}


@app.get("/push/vapid-public-key")
async def push_vapid_public_key(x_api_key: str = Header(None)):
    """El celu pide esto para saber con qué clave pública suscribirse."""
    _autorizar(x_api_key)
    return {"clave": os.environ.get("VAPID_PUBLIC_KEY", "")}

@app.get("/agenda")
async def listar_agenda(x_api_key: str = Header(None)):
    """Recordatorios pendientes, para que el celular pueda avisarlos aunque
    la voz suene en la PC."""
    _autorizar(x_api_key)
    return {"pendientes": [
        {"id": r["id"], "texto": r["texto"], "cuando": r["cuando"]}
        for r in agenda.pendientes()
    ]}

@app.get("/reportes")
async def listar_reportes_endpoint(x_api_key: str = Header(None)):
    _autorizar(x_api_key)
    reportes = listar_reportes()
    return {"reportes": reportes}

@app.get("/reportes/{nombre}")
async def obtener_reporte_endpoint(nombre: str, x_api_key: str = Header(None)):
    _autorizar(x_api_key)
    contenido = obtener_reporte(os.path.basename(nombre))
    if not contenido:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    return {"nombre": nombre, "contenido": contenido}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), x_api_key: str = Header(None)):
    _autorizar(x_api_key)

    nombre, ruta_archivo = _ruta_inbox(file.filename)
    ext = os.path.splitext(nombre)[1].lower()
    if ext not in EXTENSIONES_PERMITIDAS:
        raise HTTPException(status_code=400, detail=f"Tipo de archivo no permitido. Soportados: {', '.join(EXTENSIONES_PERMITIDAS)}")

    try:
        contenido = await file.read()
        os.makedirs(INBOX_DIR, exist_ok=True)
        with open(ruta_archivo, "wb") as f:
            f.write(contenido)

        return {
            "nombre": nombre,
            "ruta": ruta_archivo,
            "tamaño": len(contenido)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/inbox")
async def listar_inbox(x_api_key: str = Header(None)):
    _autorizar(x_api_key)

    if not os.path.exists(INBOX_DIR):
        return {"archivos": []}

    archivos = []
    for nombre in os.listdir(INBOX_DIR):
        if nombre.startswith("."):
            continue

        ruta = os.path.join(INBOX_DIR, nombre)
        if os.path.isfile(ruta):
            archivos.append({
                "nombre": nombre,
                "tamaño": os.path.getsize(ruta),
                "modificado": os.path.getmtime(ruta)
            })

    return {"archivos": archivos}

@app.delete("/inbox/{nombre}")
async def delete_archivo(nombre: str, x_api_key: str = Header(None)):
    _autorizar(x_api_key)

    nombre, ruta = _ruta_inbox(nombre)

    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        os.remove(ruta)
        return {"mensaje": f"Archivo '{nombre}' eliminado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat-archivo")
async def chat_archivo(nombre: str, mensaje: Mensaje, x_api_key: str = Header(None), x_session_id: str = Header(None)):
    _autorizar(x_api_key)

    nombre, ruta = _ruta_inbox(nombre)

    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido_archivo = f.read()

        # Crear contexto con el archivo
        prompt_contexto = f"""El usuario está haciendo una pregunta sobre este archivo: {nombre}

CONTENIDO DEL ARCHIVO:
```
{contenido_archivo}
```

PREGUNTA DEL USUARIO:
{mensaje.texto}

Por favor, responde basándote en el contenido del archivo."""

        respuesta = procesar_comando(prompt_contexto, ASSISTANT_NAME, _obtener_sesion(x_session_id))
        return {"respuesta": respuesta}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/speak")
async def speak(mensaje: Mensaje, x_api_key: str = Header(None)):
    _autorizar(x_api_key)

    try:
        ruta_audio = generar_audio(mensaje.texto)

        if not ruta_audio or not os.path.exists(ruta_audio):
            raise HTTPException(status_code=500, detail="Error generando audio")

        # borramos el wav temporal una vez enviado, para no llenar /tmp
        return FileResponse(
            path=ruta_audio,
            media_type="audio/wav",
            filename="respuesta.wav",
            background=BackgroundTask(os.remove, ruta_audio)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
