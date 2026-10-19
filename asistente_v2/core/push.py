# core/push.py
# Notificaciones push al celu: guarda la suscripción del navegador y manda avisos
# usando pywebpush + las claves VAPID. Pensado para un solo usuario (vos).

import os
import json
from pywebpush import webpush, WebPushException
from dotenv import load_dotenv

load_dotenv()

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # asistente_v2/
RUTA_SUSCRIPCION = os.path.join(DIR, "push_subscription.json")
RUTA_CLAVE_PRIVADA = os.path.join(DIR, os.getenv("VAPID_PRIVATE_KEY_FILE", "private_key.pem"))
VAPID_CLAIMS = {"sub": os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")}


def guardar_suscripcion(suscripcion):
    """Guarda (o reemplaza) la suscripción push del celu. Como es un solo
    usuario, una suscripción activa es suficiente; una nueva pisa la anterior."""
    try:
        with open(RUTA_SUSCRIPCION, "w", encoding="utf-8") as f:
            json.dump(suscripcion, f)
        return True
    except Exception as e:
        print(f"[Error guardando suscripción push: {e}]")
        return False


def _cargar_suscripcion():
    if not os.path.exists(RUTA_SUSCRIPCION):
        return None
    try:
        with open(RUTA_SUSCRIPCION, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def enviar_notificacion(titulo, cuerpo):
    """Manda una notificación push al celu suscripto. Si no hay suscripción
    (nunca se activaron las notificaciones, o el navegador la invalidó),
    no rompe nada: solo devuelve False."""
    suscripcion = _cargar_suscripcion()
    if not suscripcion:
        return False

    payload = json.dumps({"titulo": titulo, "cuerpo": cuerpo})

    try:
        webpush(
            subscription_info=suscripcion,
            data=payload,
            vapid_private_key=RUTA_CLAVE_PRIVADA,
            vapid_claims=VAPID_CLAIMS.copy(),  # pywebpush le agrega 'exp'; copiamos para no mutar el dict global
        )
        return True
    except WebPushException as e:
        # 410/404 típicamente significa que la suscripción expiró o el
        # usuario desinstaló/revocó permisos: la borramos para no reintentar en vano.
        if "410" in str(e) or "404" in str(e):
            try:
                os.remove(RUTA_SUSCRIPCION)
            except Exception:
                pass
        print(f"[Error enviando push: {e}]")
        return False