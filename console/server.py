"""Servidor HTTP de la consola (solo librería estándar).

Enruta la API y sirve los estáticos de `console/static/`. El cálculo de los datos vive en los
módulos de al lado (`costs.py` hoy; eventos, cron y tmux según se vayan añadiendo), para que
este fichero siga siendo solo transporte: rutas, JSON, ficheros y autenticación.
"""

from __future__ import annotations

import hmac
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
from .cron import CronManager
from .inbox import Inbox
from .system import SystemInfo
from .terminal import TerminalBridge
from .tmux import TmuxView

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
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
}


def _path_parts(path: str, prefix: str) -> list[str]:
    """Trozos de una ruta bajo `prefix`, o [] si no cuelga de ahí.

    Con la cantidad de rutas que tiene ya la API, comparar cadenas enteras a mano deja de
    leerse; esto permite `/api/cron/jobs/<id>/run` sin montar un enrutador entero.
    """
    if not path.startswith(prefix):
        return []
    return [part for part in path[len(prefix):].split("/") if part]


def _make_handler(config: Config, docker: DockerAPI | None, events: EventStore,
                  system: SystemInfo, inbox: Inbox, cron: CronManager, tmux: TmuxView,
                  terminal: TerminalBridge):
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

            def matches(candidate: str) -> bool:
                return hmac.compare_digest(candidate.encode("utf-8"),
                                           config.token.encode("utf-8"))

            if matches(self.headers.get(TOKEN_HEADER, "")):
                return True, ()
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if TOKEN_COOKIE in cookie and matches(cookie[TOKEN_COOKIE].value):
                return True, ()
            if matches((query.get("token") or [""])[0]):
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

            if parsed.path == "/api/system":
                self._json_or_error(
                    lambda: {**system.snapshot(), "inbox": inbox.stats()}, extra_headers
                )
                return

            if parsed.path == "/api/system/stats":
                self._json_or_error(lambda: {"stats": system.stats()}, extra_headers)
                return

            if parsed.path == "/api/system/disk":
                self._json_or_error(lambda: system.disk(), extra_headers)
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

            if parsed.path == "/api/inbox":
                self._json_or_error(lambda: {
                    "pending": inbox.pending((query.get("agent") or [None])[0]),
                }, extra_headers)
                return

            if parsed.path == "/api/tmux/panes":
                def listing():
                    enabled, reason = terminal.availability()
                    return {"agents": tmux.agents(),
                            "interactive": {"enabled": enabled, "reason": reason}}
                self._json_or_error(listing, extra_headers)
                return

            tmux_attach = _path_parts(parsed.path, "/api/tmux/attach/")
            if len(tmux_attach) == 1:
                terminal.serve(self, tmux_attach[0],
                               lambda status, message: self._send_json(
                                   {"error": message}, status=status))
                return

            tmux_pane = _path_parts(parsed.path, "/api/tmux/panes/")
            if len(tmux_pane) == 1:
                self._json_or_error(lambda: tmux.pane(
                    tmux_pane[0],
                    lines=_int_param(query, "lines") or 60,
                    colors=(query.get("colors") or ["1"])[0] != "0",
                ), extra_headers)
                return

            if parsed.path == "/api/cron/scripts":
                self._json_or_error(lambda: {"scripts": cron.scripts(),
                                             "dir": str(config.scripts_dir)}, extra_headers)
                return

            if parsed.path == "/api/cron/jobs":
                self._json_or_error(lambda: {"jobs": cron.jobs(), "stats": cron.stats()},
                                    extra_headers)
                return

            cron_job = _path_parts(parsed.path, "/api/cron/jobs/")
            if len(cron_job) == 2 and cron_job[1] == "runs":
                self._json_or_error(lambda: {"runs": cron.runs(cron_job[0])}, extra_headers)
                return

            if parsed.path == "/api/cron/runs":
                self._json_or_error(
                    lambda: {"runs": cron.runs(limit=_int_param(query, "limit") or 50)},
                    extra_headers,
                )
                return

            cron_run = _path_parts(parsed.path, "/api/cron/runs/")
            if len(cron_run) == 1:
                self._json_or_key_error(lambda: cron.run_detail(cron_run[0]), extra_headers)
                return

            if parsed.path == "/api/cron/state":
                job = (query.get("job") or [""])[0]
                self._json_or_error(lambda: cron.state(job), extra_headers)
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

            # POST /api/inbox/<id>/ack no lleva cuerpo: se resuelve antes de leerlo.
            if parsed.path.startswith("/api/inbox/") and parsed.path.endswith("/ack"):
                note_id = parsed.path[len("/api/inbox/"):-len("/ack")]
                ok = inbox.ack(note_id)
                self._send_json({"acked": ok}, status=200 if ok else 404,
                                extra_headers=extra_headers)
                return

            # POST /api/cron/jobs/<id>/run tampoco lleva cuerpo.
            cron_run_now = _path_parts(parsed.path, "/api/cron/jobs/")
            if len(cron_run_now) == 2 and cron_run_now[1] == "run":
                self._json_or_key_error(lambda: cron.run_now(cron_run_now[0]), extra_headers)
                return

            if parsed.path not in ("/api/events", "/api/link/send", "/api/inbox/take",
                                   "/api/cron/jobs", "/api/cron/state") \
                    and not (len(cron_run_now) == 1 and parsed.path.startswith("/api/cron/jobs/")):
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

            if parsed.path == "/api/link/send":
                if not isinstance(payload, dict):
                    self._send_json({"error": "se espera un objeto {to, content}"}, status=400)
                    return
                try:
                    result = inbox.send(
                        payload.get("to", ""), payload.get("content", ""), payload.get("job"),
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return
                # 202: la consola acepta el aviso y se encarga; la entrega ocurre cuando el
                # agente pase a recogerlo (ver console/inbox.py).
                self._send_json(result, status=202, extra_headers=extra_headers)
                return

            # La recogida cambia estado (marca lo entregado para poder reentregar), así que es
            # un POST y no un GET: /api/inbox, que sí es de solo lectura, se queda en GET.
            if parsed.path == "/api/inbox/take":
                agent = payload.get("agent", "") if isinstance(payload, dict) else ""
                self._json_or_error(lambda: {"notes": inbox.take(agent)}, extra_headers)
                return

            if parsed.path == "/api/cron/jobs":
                self._json_or_value_error(lambda: cron.create_job(payload or {}),
                                          extra_headers, status=201)
                return

            if len(cron_run_now) == 1 and parsed.path.startswith("/api/cron/jobs/"):
                self._json_or_value_error(
                    lambda: cron.update_job(cron_run_now[0], payload or {}), extra_headers
                )
                return

            if parsed.path == "/api/cron/state":
                self._json_or_value_error(lambda: (
                    cron.set_state(payload["job"], payload["key"], payload.get("value")),
                    {"ok": True},
                )[1], extra_headers)
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

        def do_DELETE(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            authorized, extra_headers = self._authorize(query)
            if not authorized:
                self._send_json({"error": "unauthorized"}, status=401)
                return

            cron_job = _path_parts(parsed.path, "/api/cron/jobs/")
            if len(cron_job) == 1:
                self._json_or_key_error(lambda: {"deleted": cron.delete_job(cron_job[0])},
                                        extra_headers)
                return

            if parsed.path != "/api/events":
                self.send_error(404, "Not found")
                return
            try:
                removed = events.delete(
                    before=_int_param(query, "before"),
                    agent=(query.get("agent") or [None])[0],
                    type_prefix=(query.get("type") or [None])[0],
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json({"deleted": removed}, extra_headers=extra_headers)

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

        def _json_or_key_error(self, build, extra_headers=()):
            """404 cuando lo pedido no existe; el resto, como siempre."""
            try:
                self._send_json(build(), extra_headers=extra_headers)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)

        def _json_or_value_error(self, build, extra_headers=(), status=200):
            """400 cuando lo que manda el cliente no es válido: es culpa suya, no del servidor."""
            try:
                self._send_json(build(), status=status, extra_headers=extra_headers)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)

        def _json_or_error(self, build, extra_headers=()):
            try:
                self._send_json(build(), extra_headers=extra_headers)
            except Exception as exc:  # noqa: BLE001 — la consola no debe caerse por un dato raro
                self._send_json({"error": str(exc)}, status=500)

        def _health(self) -> dict:
            containers = [
                {k: c[k] for k in ("name", "role", "state", "image")}
                for c in system.containers()
            ]
            return {
                "ok": True,
                "project": system.project(),
                "prefix": config.container_prefix,
                "cost_dir": str(config.cost_dir),
                "cost_dir_exists": config.cost_dir.is_dir(),
                "scripts_dir": str(config.scripts_dir),
                "data_dir": str(config.data_dir),
                "docker": bool(docker),
                "containers": containers,
                "auth": bool(config.token),
                "events": events.stats(),
                "inbox": inbox.stats(),
                "cron": cron.stats(),
            }

    return Handler


def _int_param(query: dict, name: str):
    raw = (query.get(name) or [None])[0]
    try:
        return int(raw) if raw not in (None, "") else None
    except ValueError:
        return None


def _start_retention(events: EventStore, inbox: Inbox) -> None:
    """Purga al arrancar y luego a diario. Hilo demonio: no retiene el cierre del proceso.

    Los avisos caducados se miran cada hora y no una vez al día: su TTL se cuenta en horas.
    """
    def loop():
        ticks = 0
        while True:
            try:
                if ticks % 24 == 0:
                    removed = events.purge()
                    if removed:
                        print(f"[console] retención: {removed} eventos borrados "
                              f"(> {events.retention_days} días)")
                expired = inbox.purge()
                if expired:
                    print(f"[console] {expired} aviso(s) caducados sin entregar")
            except Exception as exc:  # noqa: BLE001 — la purga no puede tumbar el servidor
                print(f"[console] aviso: falló la purga: {exc}")
            ticks += 1
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="retention").start()


def serve(config: Config) -> int:
    docker = None
    if config.docker_socket:
        candidate = DockerAPI(config.docker_socket)
        docker = candidate if candidate.available() else None

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.data_dir / "console.db")
    events = EventStore(db, retention_days=config.event_retention_days)
    inbox = Inbox(db, events, ttl_hours=config.inbox_ttl_hours)
    _start_retention(events, inbox)
    system = SystemInfo(docker, config.container_prefix)
    cron = CronManager(db, events, inbox, config)
    cron.start()
    tmux = TmuxView(docker, system)
    terminal = TerminalBridge(docker, system, config.token)

    handler = _make_handler(config, docker, events, system, inbox, cron, tmux, terminal)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", config.port), handler)
    except OSError as exc:
        print(f"[console] no se pudo abrir el puerto {config.port}: {exc}")
        return 1

    print(f"[console] datos de coste:  {config.cost_dir}")
    print(f"[console] base de datos:    {db.path} ({events.count()} eventos, "
          f"retención {config.event_retention_days} días)")
    pending = inbox.stats()["pending"]
    if pending:
        print(f"[console] avisos pendientes de entregar: {pending}")
    cron_stats = cron.stats()
    print(f"[console] cron:            {cron_stats['scripts']} script(s) en "
          f"{config.scripts_dir}, {cron_stats['enabled']}/{cron_stats['jobs']} "
          "programaciones activas")
    if not config.cost_dir.is_dir():
        print(f"[console] aviso: {config.cost_dir} no existe todavía (dashboard vacío).")
    if config.docker_socket:
        if docker:
            names = [c["name"] for c in system.containers()]
            print(f"[console] docker:          ok, {len(names)} contenedores del proyecto "
                  f"'{system.project() or config.container_prefix}'")
            if len(names) <= 1:
                others = system.other_projects()
                if others:
                    detalle = ", ".join(f"{p} ({n})" for p, n in others.items())
                    print("[console] aviso: no veo más contenedores de este proyecto. En este "
                          f"daemon hay otros: {detalle}. ¿Se levantó el equipo desde otro "
                          "docker-compose o con otro .env?")
        else:
            print(f"[console] aviso: {config.docker_socket} no responde; la información de "
                  "contenedores no estará disponible.")
    if docker:
        enabled, reason = terminal.availability()
        print("[console] terminal tmux:   " + ("interactiva (CONSOLE_TOKEN definido)" if enabled
              else f"solo lectura ({reason})"))
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
        cron.stop()
        httpd.server_close()
        db.close()
    return 0


def serve_local(port: int, cost_dir: Path) -> int:
    """Punto de entrada de `setup.py --console-local`: solo costes, sin Docker."""
    return serve(Config.local(port, cost_dir.resolve()))
