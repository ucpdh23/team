"""Servidor HTTP de la consola (solo librería estándar).

Enruta la API y sirve los estáticos de `console/static/`. El cálculo de los datos vive en los
módulos de al lado (`costs.py` hoy; eventos, cron y tmux según se vayan añadiendo), para que
este fichero siga siendo solo transporte: rutas, JSON, ficheros y autenticación.
"""

from __future__ import annotations

import json
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import costs
from .config import Config
from .db import Database
from .docker_api import DockerAPI
from .events import MAX_EVENTS_PER_REQUEST, EventStore

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Tope del cuerpo de un POST. La ingesta manda lotes de metadatos (un evento ocupa ~80 bytes),
# así que 1 MiB es holgado y evita que una petición mal formada se coma la memoria.
MAX_BODY_BYTES = 1 << 20

TOKEN_COOKIE = "console_token"
TOKEN_HEADER = "X-Console-Token"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _make_handler(config: Config, docker: DockerAPI | None, events: EventStore):
    class Handler(BaseHTTPRequestHandler):
        # Silencia el log por defecto (una línea por request) para no ensuciar la salida del
        # contenedor, que es donde se ven los avisos que sí importan.
        def log_message(self, *args):
            pass

        # ---------------------------------------------------------------- utilidades

        def _send_json(self, obj, status=200, extra_headers=()):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel: str, extra_headers=()):
            if rel in ("", "/"):
                rel = "index.html"
            target = (STATIC_DIR / rel.lstrip("/")).resolve()
            # Cortafuegos de path traversal: nada fuera de STATIC_DIR.
            if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
                self.send_error(404, "Not found")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                _CONTENT_TYPES.get(target.suffix, "application/octet-stream"),
            )
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        # ------------------------------------------------------------ autenticación

        def _authorize(self, query: dict) -> tuple[bool, tuple]:
            """(autorizado, cabeceras extra a añadir a la respuesta).

            Sin CONSOLE_TOKEN definido no hay autenticación ninguna: es el modo por defecto
            (v1). Con token, vale la cabecera, la cookie o `?token=` en la URL — y en ese
            último caso se deja la cookie puesta, que es lo que permite entrar desde el
            navegador pegando la URL una sola vez.
            """
            if not config.token:
                return True, ()
            if self.headers.get(TOKEN_HEADER, "") == config.token:
                return True, ()
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if TOKEN_COOKIE in cookie and cookie[TOKEN_COOKIE].value == config.token:
                return True, ()
            if (query.get("token") or [""])[0] == config.token:
                return True, ((
                    "Set-Cookie",
                    f"{TOKEN_COOKIE}={config.token}; Path=/; HttpOnly; SameSite=Strict",
                ),)
            return False, ()

        # -------------------------------------------------------------------- rutas

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            authorized, extra_headers = self._authorize(query)
            if not authorized:
                self._send_json({"error": "unauthorized"}, status=401)
                return

            if parsed.path == "/api/consumption":
                range_ = (query.get("range") or ["day"])[0]
                start = (query.get("from") or [None])[0]
                end = (query.get("to") or [None])[0]
                self._json_or_error(
                    lambda: costs.build_payload(config.cost_dir, range_, start, end),
                    extra_headers,
                )
                return

            if parsed.path == "/api/bounds":
                self._json_or_error(
                    lambda: costs.data_bounds(config.cost_dir), extra_headers
                )
                return

            if parsed.path == "/api/health":
                self._json_or_error(lambda: self._health(), extra_headers)
                return

            if parsed.path == "/api/events":
                self._json_or_error(lambda: {
                    "events": events.query(
                        since=_int_param(query, "since"),
                        until=_int_param(query, "until"),
                        agent=(query.get("agent") or [None])[0],
                        type_prefix=(query.get("type") or [None])[0],
                        limit=_int_param(query, "limit") or 200,
                    ),
                }, extra_headers)
                return

            if parsed.path == "/api/events/pulse":
                self._json_or_error(
                    lambda: events.pulse(since=_int_param(query, "since")), extra_headers
                )
                return

            if parsed.path == "/api/events/graph":
                self._json_or_error(lambda: events.graph(
                    window_ms=_int_param(query, "window_ms") or 3_600_000,
                ), extra_headers)
                return

            if parsed.path == "/api/events/stats":
                self._json_or_error(lambda: events.stats(), extra_headers)
                return

            self._send_static(parsed.path, extra_headers)

        def do_POST(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            authorized, extra_headers = self._authorize(query)
            if not authorized:
                self._send_json({"error": "unauthorized"}, status=401)
                return

            if parsed.path != "/api/events":
                self.send_error(404, "Not found")
                return

            body = self._read_body()
            if body is None:
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._send_json({"error": f"json inválido: {exc}"}, status=400)
                return

            batch = payload if isinstance(payload, list) else [payload]
            if len(batch) > MAX_EVENTS_PER_REQUEST:
                self._send_json(
                    {"error": f"máximo {MAX_EVENTS_PER_REQUEST} eventos por petición"},
                    status=400,
                )
                return

            try:
                result = events.ingest(batch)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)
                return
            # 202: la consola confirma recepción, no procesamiento. Quien emite no debe
            # esperar nada más que esto.
            self._send_json(result, status=202, extra_headers=extra_headers)

        def _read_body(self) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                self._send_json({"error": "cuerpo vacío"}, status=400)
                return None
            if length > MAX_BODY_BYTES:
                self._send_json({"error": "cuerpo demasiado grande"}, status=413)
                return None
            return self.rfile.read(length)

        def _json_or_error(self, build, extra_headers=()):
            try:
                self._send_json(build(), extra_headers=extra_headers)
            except Exception as exc:  # noqa: BLE001 — la consola no debe caerse por un dato raro
                self._send_json({"error": str(exc)}, status=500)

        def _health(self) -> dict:
            containers = docker.team_containers(config.container_prefix) if docker else []
            return {
                "ok": True,
                "cost_dir": str(config.cost_dir),
                "cost_dir_exists": config.cost_dir.is_dir(),
                "scripts_dir": str(config.scripts_dir),
                "data_dir": str(config.data_dir),
                "docker": bool(docker),
                "containers": containers,
                "auth": bool(config.token),
                "events": events.stats(),
            }

    return Handler


def _int_param(query: dict, name: str):
    raw = (query.get(name) or [None])[0]
    try:
        return int(raw) if raw not in (None, "") else None
    except ValueError:
        return None


def _start_retention(events: EventStore) -> None:
    """Purga al arrancar y una vez al día. Un hilo demonio: no retiene el cierre del proceso."""
    def loop():
        while True:
            try:
                removed = events.purge()
                if removed:
                    print(f"[console] retención: {removed} eventos borrados "
                          f"(> {events.retention_days} días)")
            except Exception as exc:  # noqa: BLE001 — la purga no puede tumbar el servidor
                print(f"[console] aviso: falló la purga de eventos: {exc}")
            time.sleep(86_400)

    threading.Thread(target=loop, daemon=True, name="retention").start()


def serve(config: Config) -> int:
    docker = None
    if config.docker_socket:
        candidate = DockerAPI(config.docker_socket)
        docker = candidate if candidate.available() else None

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.data_dir / "console.db")
    events = EventStore(db, retention_days=config.event_retention_days)
    _start_retention(events)

    handler = _make_handler(config, docker, events)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", config.port), handler)
    except OSError as exc:
        print(f"[console] no se pudo abrir el puerto {config.port}: {exc}")
        return 1

    print(f"[console] datos de coste:  {config.cost_dir}")
    print(f"[console] base de datos:    {db.path} ({events.count()} eventos, "
          f"retención {config.event_retention_days} días)")
    if not config.cost_dir.is_dir():
        print(f"[console] aviso: {config.cost_dir} no existe todavía (dashboard vacío).")
    if config.docker_socket:
        if docker:
            names = [c["name"] for c in docker.team_containers(config.container_prefix)]
            print(f"[console] docker:          ok, {len(names)} contenedores del cluster "
                  f"'{config.container_prefix}'")
        else:
            print(f"[console] aviso: {config.docker_socket} no responde; la información de "
                  "contenedores no estará disponible.")
    if config.publishes_beyond_loopback() and not config.token:
        print(f"[console] AVISO: el puerto se publica en {config.bind} y la consola NO pide "
              "autenticación: cualquiera que alcance ese puerto entra. Define CONSOLE_TOKEN "
              "en .env para exigir un token.")
    print(f"[console] escuchando en:   http://0.0.0.0:{config.port}/  (Ctrl-C para parar)")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[console] parado.")
    finally:
        httpd.server_close()
        db.close()
    return 0


def serve_local(port: int, cost_dir: Path) -> int:
    """Punto de entrada de `setup.py --console-local`: solo costes, sin Docker."""
    return serve(Config.local(port, cost_dir.resolve()))
