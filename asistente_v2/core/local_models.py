"""Cliente Ollama perezoso con endpoint local, deadline y sin proxies del entorno."""
import os
from functools import lru_cache
from urllib.parse import urlsplit


def endpoint():
    value = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("OLLAMA_HOST debe ser HTTP local, sin credenciales ni rutas")
    if parsed.port is None:
        raise ValueError("OLLAMA_HOST requiere puerto explícito")
    return value


@lru_cache(maxsize=4)
def _client(host):
    from ollama import Client
    return Client(host=host, timeout=120, trust_env=False, follow_redirects=False)


class LocalModels:
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(_client(endpoint()), name)


ollama = LocalModels()
