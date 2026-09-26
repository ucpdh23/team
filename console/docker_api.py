"""Cliente mínimo de la API del daemon de Docker, por su socket unix.

El contenedor de la consola monta `/var/run/docker.sock` para poder enseñar el inventario de
contenedores, la red y el espacio (y, más adelante, leer las sesiones tmux con `exec`) — ver
ARCHITECTURE.md. No se instala el cliente `docker` en la imagen: la API es HTTP normal sobre
un socket unix, así que `http.client` con un socket AF_UNIX basta y la imagen se ahorra el
paquete entero.

Las consultas degradan con elegancia: si el socket no está montado o el daemon no contesta,
`available()` devuelve False y el resto devuelve listas vacías en vez de reventar. La consola
tiene que poder arrancar sin Docker (p. ej. `setup.py --console-local`).

`exec_attach` es la excepción a "solo mirar": abre una terminal interactiva dentro de un
contenedor (la usa `terminal.py`), así que quien la llame es quien responde de que solo se
ejecute lo que debe.
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


    def exec_attach(self, container: str, cmd: list[str],
                    env: list[str] | None = None) -> "ExecStream | None":
        """Como `docker exec -it`: arranca `cmd` con una pseudo-terminal y devuelve el canal.

        A diferencia de `exec_capture` (una petición, una respuesta), aquí se pide a Docker
        que convierta la conexión HTTP en un canal de bytes crudo y bidireccional
        (`Upgrade: tcp`). Con TTY no hay flujo multiplexado que separar: lo que llega es lo que
        la aplicación dibujó, y lo que se escribe es lo que ella lee del teclado.
        """
        status, body = self.post(
            f"/containers/{container}/exec",
            {"AttachStdin": True, "AttachStdout": True, "AttachStderr": True, "Tty": True,
             "Cmd": cmd, "Env": env or []},
        )
        if status != 201:
            return None
        try:
            exec_id = json.loads(body.decode("utf-8"))["Id"]
        except (ValueError, KeyError):
            return None

        payload = b'{"Detach":false,"Tty":true}'
        request = (
            f"POST /{API_VERSION}/exec/{exec_id}/start HTTP/1.1\r\n"
            "Host: docker\r\n"
            "Content-Type: application/json\r\n"
            "Connection: Upgrade\r\n"
            "Upgrade: tcp\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        ).encode("ascii") + payload

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
            sock.sendall(request)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = sock.recv(4096)
                if not chunk or len(head) > 65536:
                    raise OSError("respuesta de Docker incompleta")
                head += chunk
            head, _, pending = head.partition(b"\r\n\r\n")
            code = int(head.split(b"\r\n", 1)[0].split()[1])
        except (OSError, ValueError, IndexError):
            sock.close()
            return None
        # Docker contesta 101 al `Upgrade`; algunas versiones contestan 200 y siguen igual.
        if code not in (101, 200):
            sock.close()
            return None
        return ExecStream(self, exec_id, sock, pending)


class ExecStream:
    """Un exec con TTY ya arrancado: `sock` es el canal crudo, `pending` lo que llegó pegado
    a la cabecera y todavía no se ha entregado."""

    def __init__(self, api: DockerAPI, exec_id: str, sock: socket.socket, pending: bytes):
        self.api = api
        self.exec_id = exec_id
        self.sock = sock
        self.pending = pending

    def resize(self, rows: int, cols: int) -> bool:
        status, _ = self.api.post(f"/exec/{self.exec_id}/resize?h={rows}&w={cols}")
        return status in (200, 201)

    def running(self) -> bool:
        info = self.api.get(f"/exec/{self.exec_id}/json") or {}
        return bool(info.get("Running"))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


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
