"""Cliente mínimo de la API del daemon de Docker, por su socket unix.

El contenedor de la consola monta `/var/run/docker.sock` para poder enseñar el inventario de
contenedores, la red y el espacio (y, más adelante, leer las sesiones tmux con `exec`) — ver
ARCHITECTURE.md. No se instala el cliente `docker` en la imagen: la API es HTTP normal sobre
un socket unix, así que `http.client` con un socket AF_UNIX basta y la imagen se ahorra el
paquete entero.

Todo lo de aquí es de solo lectura y degrada con elegancia: si el socket no está montado o el
daemon no contesta, `available()` devuelve False y el resto devuelve listas vacías en vez de
reventar. La consola tiene que poder arrancar sin Docker (p. ej. `setup.py --console-local`).
"""

from __future__ import annotations

import http.client
import json
import socket

DEFAULT_SOCKET = "/var/run/docker.sock"
# La API de Docker versiona por ruta; 1.41 es la de Docker 20.10, suficientemente antigua para
# no exigir un daemon reciente y suficientemente moderna para todo lo que pedimos.
API_VERSION = "v1.41"


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection que habla por un socket unix en vez de por TCP."""

    def __init__(self, socket_path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


class DockerAPI:
    def __init__(self, socket_path: str = DEFAULT_SOCKET, timeout: float = 5.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def get(self, path: str):
        """GET a la API. Devuelve el JSON parseado, o None si algo falla."""
        conn = _UnixHTTPConnection(self.socket_path, self.timeout)
        try:
            conn.request("GET", f"/{API_VERSION}{path}")
            response = conn.getresponse()
            body = response.read()
            if response.status >= 400:
                return None
            return json.loads(body.decode("utf-8")) if body else None
        except (OSError, ValueError):
            return None
        finally:
            conn.close()

    def available(self) -> bool:
        return self.get("/version") is not None

    def containers(self) -> list[dict]:
        return self.get("/containers/json?all=1") or []

    def team_containers(self, prefix: str) -> list[dict]:
        """Contenedores de *este* cluster, resumidos.

        Se filtran por el prefijo de nombre (CONTAINER_PREFIX) en vez de por la etiqueta de
        proyecto de Compose: el prefijo es lo que ya distingue un cluster de otro en este
        repositorio, y no obliga a saber con qué nombre de proyecto se levantó.
        """
        out = []
        for container in self.containers():
            names = [n.lstrip("/") for n in container.get("Names") or []]
            name = names[0] if names else ""
            if not name.startswith(f"{prefix}-"):
                continue
            out.append({
                "name": name,
                "role": name[len(prefix) + 1:],
                "image": container.get("Image", ""),
                "state": container.get("State", ""),
                "status": container.get("Status", ""),
            })
        return sorted(out, key=lambda c: c["name"])
