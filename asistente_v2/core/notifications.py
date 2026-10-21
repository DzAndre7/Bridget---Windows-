"""Notificaciones de escritorio; sin interpolar texto en comandos."""
import subprocess
import sys


def notify(title, text):
    try:
        if sys.platform == "win32":
            from core.windows_native import NOTIFY_SCRIPT, powershell
            powershell(NOTIFY_SCRIPT, {"title": str(title)[:63], "text": str(text)[:255]}, 8)
        elif sys.platform.startswith("linux"):
            subprocess.run(["notify-send", "-u", "critical", "--", str(title), str(text)],
                           timeout=5, check=True)
        else:
            return False
        return True
    except (OSError, subprocess.SubprocessError):
        return False
