"""Terminal interactiva de un agente, en el navegador.

Es lo que haces con `docker exec -it <contenedor> tmux attach -t pi`, con el navegador de
terminal: el navegador (xterm.js) habla WebSocket con la consola, y la consola reenvía los
bytes, sin mirarlos, a un `exec` con TTY dentro del contenedor del agente. Ver
`docker_api.exec_attach` y `websocket.py`.

Aquí se decide **quién puede escribir y dónde**, porque teclear en un agente es ejecutar
comandos en un contenedor con sus credenciales:

- Exige `CONSOLE_TOKEN`. Sin token no hay terminal, aunque el puerto esté en loopback: el
  navegador deja abrir un WebSocket a `127.0.0.1` desde cualquier web que estés visitando
  (los WebSockets no pasan por CORS), y con la consola sin autenticación eso sería dar
  escritura a esa web.
- Exige que `Origin` sea la propia consola, y que llegue: un navegador siempre lo manda.
- El comando lo fija este módulo. El cliente solo elige el agente, y solo entre los
  contenedores que la consola ya lista; nunca manda un comando.
- No cambia el tamaño de la ventana de tmux, que es el que ven el mosaico y quien esté
  enganchado por terminal: el navegador se adapta a la ventana, no al revés. Para eso la
  terminal se abre con el tamaño de la ventana MÁS su barra de estado (con una fila menos,
  tmux encoge la ventana en cada conexión), y con `ignore-size`, que hace que un cliente no
  mande sobre el tamaño cuando hay otro enganchado. Ojo: si el navegador está solo, tmux sí
  sigue su tamaño; por eso el ajuste exacto es lo que de verdad evita el encogimiento.
"""

from __future__ import annotations

import json
import re
import secrets
import select
import threading
import time
from urllib.parse import urlparse

from .tmux import SESSION
from .websocket import (
    CLOSE_INTERNAL, CLOSE_NORMAL, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG, OP_TEXT,
    FrameParser, ProtocolError, accept_key, encode_close, encode_frame,
)

MAX_TERMINALS = 5
DEFAULT_SIZE = (220, 51)      # ventana de docker/entrypoint.sh (220x50) + barra de estado
PING_EVERY_S = 20
DEAD_AFTER_S = 60
IO_TIMEOUT_S = 15

ATTACH_CMD = ["tmux", "attach-session", "-f", "ignore-size", "-t", SESSION]

# Cerrar la conexión NO termina el `tmux attach`: Docker deja el exec vivo y el cliente
# quedaría enganchado para siempre. Cada terminal lleva una variable de entorno única; al
# cerrar se busca en /proc el proceso que la tiene y se le manda SIGHUP, que tmux entiende como
# "desengánchate". No deja ficheros en el contenedor ni toca a otros clientes.
_KILL = (
    'for e in /proc/[0-9]*/environ; do '
    'if tr "\\0" "\\n" < "$e" 2>/dev/null | grep -qx "CONSOLE_ATTACH=$1"; then '
    'p=${e%/environ}; kill -HUP "${p#/proc/}"; fi; done'
)


def same_origin(origin: str | None, host: str | None) -> bool:
    if not origin or not host:
        return False
    return urlparse(origin).netloc.lower() == host.lower()


class TerminalBridge:
    def __init__(self, docker, system, token: str):
        self.docker = docker
        self.system = system
        self.token = token
        self._lock = threading.Lock()
        self._open = 0

    def availability(self) -> tuple[bool, str]:
        """Si la terminal puede usarse y, si no, por qué (el navegador lo enseña tal cual)."""
        if not self.docker:
            return False, "sin acceso al socket de Docker"
        if not self.token:
            return False, ("para escribir en un agente hay que definir CONSOLE_TOKEN en .env "
                           "y recrear la consola")
        return True, ""

    # ------------------------------------------------------------------ entrada HTTP

    def serve(self, handler, agent: str, reject) -> None:
        """Atiende `GET /api/tmux/attach/<agente>`.

        Lo que no es un uso legítimo (sin token, otro origen, no es un WebSocket) se rechaza con
        un error HTTP normal, vía `reject(status, mensaje)`. Todo lo demás (el agente está
        parado, ya hay demasiadas terminales...) se acepta primero y se cuenta después por el
        propio WebSocket: la API del navegador no deja leer el código de un rechazo HTTP, y sin
        eso el usuario solo vería "falló".
        """
        ok, reason = self.availability()
        if not ok:
            return reject(403, reason)
        if not same_origin(handler.headers.get("Origin"), handler.headers.get("Host")):
            return reject(403, "origen no permitido: la terminal solo se abre desde la propia "
                               "consola")
        key = handler.headers.get("Sec-WebSocket-Key", "")
        if ("websocket" not in handler.headers.get("Upgrade", "").lower() or not key
                or handler.headers.get("Sec-WebSocket-Version") != "13"):
            return reject(400, "esto es un WebSocket: hay que abrirlo con new WebSocket(...)")

        handler.close_connection = True
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept_key(key))
        handler.end_headers()

        conn = handler.connection
        conn.settimeout(IO_TIMEOUT_S)
        try:
            self._session(conn, handler.client_address[0], agent)
        except OSError:
            pass    # el navegador se fue: no hay a quién contárselo

    def _session(self, conn, peer: str, agent: str) -> None:
        target = next((c for c in self.system.containers() if c["role"] == agent
                       and c["role"] != "console"), None)
        if target is None:
            return self._fail(conn, "no hay ningún contenedor para ese agente")
        if target["state"] != "running":
            return self._fail(conn, f"el contenedor está {target['state']}")
        size = self._window_size(target["id"])
        if size is None:
            return self._fail(conn, "la sesión tmux 'pi' no está activa todavía")
        cols, rows = size

        with self._lock:
            if self._open >= MAX_TERMINALS:
                return self._fail(conn, f"ya hay {MAX_TERMINALS} terminales abiertas")
            self._open += 1
        try:
            marker = secrets.token_hex(8)
            stream = self.docker.exec_attach(
                target["id"], ATTACH_CMD,
                ["TERM=xterm-256color", "COLORTERM=truecolor", f"CONSOLE_ATTACH={marker}"],
            )
            if stream is None:
                return self._fail(conn, "no se pudo abrir la terminal en el contenedor")

            started = time.monotonic()
            print(f"[console] terminal: {agent} abierta desde {peer}")
            try:
                # Docker solo acepta el cambio de tamaño con el proceso ya en marcha.
                for _ in range(5):
                    if stream.resize(rows, cols):
                        break
                    time.sleep(0.1)
                stream.sock.settimeout(IO_TIMEOUT_S)
                conn.sendall(encode_frame(OP_TEXT, json.dumps(
                    {"type": "ready", "agent": agent, "cols": cols, "rows": rows}).encode()))
                self._pump(conn, stream)
            finally:
                self._reap(target["id"], stream, marker)
                print(f"[console] terminal: {agent} cerrada tras "
                      f"{int(time.monotonic() - started)} s")
        finally:
            with self._lock:
                self._open -= 1

    @staticmethod
    def _fail(conn, message: str) -> None:
        conn.sendall(encode_frame(OP_TEXT, json.dumps(
            {"type": "error", "message": message}).encode()))
        conn.sendall(encode_close(CLOSE_NORMAL, "no disponible"))

    # ---------------------------------------------------------------------- piezas

    def _window_size(self, container: str) -> tuple[int, int] | None:
        """(columnas, filas) que debe tener la terminal, o None si la sesión no existe.

        Son las de la ventana de tmux más las filas de su barra de estado, que tmux dibuja en
        el cliente y no cuenta dentro de la ventana.
        """
        out = self.docker.exec_capture(
            container,
            ["tmux", "display-message", "-p", "-t", SESSION,
             "#{window_width} #{window_height} #{status}"],
            timeout=5.0,
        )
        if out is None:
            return DEFAULT_SIZE
        match = re.fullmatch(r"(\d+) (\d+) (on|off|\d)\s*", out)
        if match:
            # `status` es "on" (una fila), "off" (ninguna) o el número de filas (2 a 5).
            raw_status = match.group(3)
            status_rows = int(raw_status) if raw_status.isdigit() else int(raw_status == "on")
            cols, rows = int(match.group(1)), int(match.group(2)) + status_rows
            if 20 <= cols <= 500 and 5 <= rows <= 200:
                return cols, rows
            return DEFAULT_SIZE
        if "no server running" in out or "can't find" in out:
            return None
        return DEFAULT_SIZE

    def _pump(self, conn, stream) -> None:
        """Copia bytes en los dos sentidos hasta que uno de los dos lados se cierre."""
        parser = FrameParser()
        if stream.pending:
            conn.sendall(encode_frame(OP_BINARY, stream.pending))
        now = time.monotonic()
        last_rx = last_ping = now

        while True:
            readable, _, _ = select.select([conn, stream.sock], [], [], 1.0)
            now = time.monotonic()

            if conn in readable:
                data = conn.recv(65536)
                if not data:
                    return
                last_rx = now
                try:
                    messages = parser.feed(data)
                except ProtocolError as exc:
                    conn.sendall(encode_close(exc.code, str(exc)))
                    return
                for opcode, payload in messages:
                    if opcode in (OP_TEXT, OP_BINARY):
                        stream.sock.sendall(payload)
                    elif opcode == OP_PING:
                        conn.sendall(encode_frame(OP_PONG, payload))
                    elif opcode == OP_CLOSE:
                        conn.sendall(encode_close(CLOSE_NORMAL))
                        return

            if stream.sock in readable:
                data = stream.sock.recv(65536)
                if not data:
                    # El exec terminó (Ctrl-b d, o la sesión se cerró): se avisa y se cierra.
                    conn.sendall(encode_frame(OP_TEXT, json.dumps(
                        {"type": "ended"}).encode()))
                    conn.sendall(encode_close(CLOSE_NORMAL, "sesión terminada"))
                    return
                conn.sendall(encode_frame(OP_BINARY, data))

            if now - last_rx > DEAD_AFTER_S:
                conn.sendall(encode_close(CLOSE_INTERNAL, "sin respuesta"))
                return
            if now - last_ping > PING_EVERY_S:
                conn.sendall(encode_frame(OP_PING))
                last_ping = now

    def _reap(self, container: str, stream, marker: str) -> None:
        stream.close()
        if stream.running():
            self.docker.exec_capture(container, ["sh", "-c", _KILL, "sh", marker], timeout=5.0)
