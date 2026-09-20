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

    def post(self, path: str, payload=None, timeout: float | None = None):
        """POST a la API. Devuelve (status, cuerpo en bytes), sin interpretar nada.

        El cuerpo se devuelve crudo porque `exec` no contesta JSON, sino el flujo multiplexado
        de la ejecución (ver `exec_capture`).
        """
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        conn = _UnixHTTPConnection(self.socket_path, timeout or self.timeout)
        try:
            conn.request("POST", f"/{API_VERSION}{path}", body=body,
                         headers={"Content-Type": "application/json",
                                  "Content-Length": str(len(body))})
            response = conn.getresponse()
            return response.status, response.read()
        except (OSError, ValueError):
            return 0, b""
        finally:
            conn.close()

    def exec_capture(self, container: str, cmd: list[str], timeout: float = 5.0) -> str | None:
        """Ejecuta un comando dentro de un contenedor y devuelve su salida.

        Es `docker exec` sin cliente `docker`: se crea la ejecución, se arranca sin TTY y la
        respuesta llega multiplexada (ver `_demux`). Sin TTY a propósito: con TTY la salida
        viene en crudo y no se puede separar stdout de stderr, y aquí interesa saber si tmux
        se quejó.
        """
        status, body = self.post(
            f"/containers/{container}/exec",
            {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": cmd},
            timeout=timeout,
        )
        if status != 201:
            return None
        try:
            exec_id = json.loads(body.decode("utf-8"))["Id"]
        except (ValueError, KeyError):
            return None
        status, stream = self.post(f"/exec/{exec_id}/start",
                                   {"Detach": False, "Tty": False}, timeout=timeout)
        if status != 200:
            return None
        return _demux(stream)


def _demux(stream: bytes) -> str:
    """Separa el flujo multiplexado de Docker: cabecera de 8 bytes + carga por trozo.

    Formato: 1 byte de canal (1=stdout, 2=stderr), 3 de relleno y 4 con el tamaño en big
    endian. Se conservan los dos canales: si tmux protesta, esa queja es justo lo que hay que
    enseñar en el panel en vez de un hueco en blanco.
    """
    out = []
    offset = 0
    while offset + 8 <= len(stream):
        size = int.from_bytes(stream[offset + 4:offset + 8], "big")
        offset += 8
        out.append(stream[offset:offset + size].decode("utf-8", errors="replace"))
        offset += size
    return "".join(out)
