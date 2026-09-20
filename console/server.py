"""Servidor HTTP de la consola (solo librería estándar).

Enruta la API y sirve los estáticos de `console/static/`. El cálculo de los datos vive en los
módulos de al lado (`costs.py` hoy; eventos, cron y tmux según se vayan añadiendo), para que
este fichero siga siendo solo transporte: rutas, JSON, ficheros y autenticación.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import costs
from .config import Config
from .docker_api import DockerAPI

STATIC_DIR = Path(__file__).resolve().parent / "static"

TOKEN_COOKIE = "console_token"
TOKEN_HEADER = "X-Console-Token"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _make_handler(config: Config, docker: DockerAPI | None):
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

            self._send_static(parsed.path, extra_headers)

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
            }

    return Handler


def serve(config: Config) -> int:
    docker = None
    if config.docker_socket:
        candidate = DockerAPI(config.docker_socket)
        docker = candidate if candidate.available() else None

    config.data_dir.mkdir(parents=True, exist_ok=True)

    handler = _make_handler(config, docker)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", config.port), handler)
    except OSError as exc:
        print(f"[console] no se pudo abrir el puerto {config.port}: {exc}")
        return 1

    print(f"[console] datos de coste:  {config.cost_dir}")
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
    return 0


def serve_local(port: int, cost_dir: Path) -> int:
    """Punto de entrada de `setup.py --console-local`: solo costes, sin Docker."""
    return serve(Config.local(port, cost_dir.resolve()))
