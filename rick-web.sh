#!/bin/bash
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source venv311/bin/activate
cd asistente_v2

uvicorn api:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

cleanup() {
    echo "Cerrando Rick web..."
    kill "$UVICORN_PID" 2>/dev/null
    fuser -k 8000/tcp 2>/dev/null
    # antes hacía `pkill $NGROK_PID`, pero NGROK_PID nunca se seteaba a tiempo
    # (ngrok corre en foreground): el ngrok quedaba huérfano al hacer Ctrl-C.
    pkill -f "ngrok http 8000" 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# ngrok en foreground: al salir (Ctrl-C) dispara el trap y limpia todo
ngrok http 8000
cleanup