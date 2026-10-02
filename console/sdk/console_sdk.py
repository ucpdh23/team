"""API que la consola ofrece a los scripts del cron.

Los **scripts** son del equipo de desarrollo y viven fuera de este repositorio; lo que team
versiona es esto: la forma de hablar con el equipo. Así, si mañana cambia cómo se entregan los
avisos o dónde se guarda el estado, los scripts no se enteran.

Se importa sin instalar nada: la imagen de la consola copia este módulo en `/opt/console-sdk`
y lo pone en `PYTHONPATH` al ejecutar cada script.

    \"\"\"Avisa al manager de sus tickets pendientes.\"\"\"   # ← la descripción que sale en la UI
    from console_sdk import ado, notify, state

    tickets = ado.query("SELECT [System.Id], [System.Title] FROM WorkItems "
                        "WHERE [System.AssignedTo] = @Me AND [System.State] <> 'Closed'")
    if tickets and state.get("ultimo_aviso") != sorted(t.id for t in tickets):
        notify("manager", "Tickets pendientes:\\n" + "\\n".join(f"- #{t.id} {t.title}" for t in tickets))
        state["ultimo_aviso"] = sorted(t.id for t in tickets)

Todo es librería estándar. Si un script necesita dependencias, basta con dejar un
`requirements.txt` junto a los scripts: la consola prepara un venv con ellas.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

__all__ = ["notify", "log", "state", "agents", "ado", "job_name", "run_id", "ConsoleError"]

CONSOLE_URL = (os.environ.get("CONSOLE_URL") or "http://127.0.0.1:4070").rstrip("/")
TIMEOUT_S = 10

#: Nombre del job que está ejecutando este script (lo pone la consola). Vacío si se ejecuta a mano.
job_name = os.environ.get("CONSOLE_JOB_NAME", "")
run_id = os.environ.get("CONSOLE_RUN_ID", "")


class ConsoleError(RuntimeError):
    pass


def _request(method: str, path: str, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{CONSOLE_URL}{path}", data=data, method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    token = os.environ.get("CONSOLE_TOKEN", "").strip()
    if token:
        request.add_header("X-Console-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ConsoleError(f"{method} {path} → {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ConsoleError(f"no se pudo hablar con la consola: {exc}") from exc


def log(*parts) -> None:
    """Escribe en el log de esta ejecución, con marca de tiempo.

    Es un `print` con hora: la salida del script se guarda entera y se ve en la pestaña Cron.
    """
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}]", *parts, flush=True)


def notify(to: str, content: str, key: str | None = None) -> str:
    """Deja un aviso para un agente y devuelve su id.

    No se entrega en el momento: se encola y la extensión de ese agente lo recoge (en ≤15 s) y
    se lo inyecta, arrancándole turno aunque estuviera ocioso. Si el agente está apagado, el
    aviso espera a que vuelva, hasta su caducidad.

    `key`, si se da, hace la llamada idempotente: si no se sabe si un envío anterior llegó a
    procesarse (p. ej. una excepción de red leyendo la respuesta, que no dice si la petición
    llegó a la consola o no) y se reintenta con la misma `key`, el agente no recibe el aviso
    dos veces — la consola ya tenía uno con ese id y devuelve el que ya había. Basta con que
    `key` sea única dentro de este script (se guarda como `job_name:key`); no hace falta
    coordinarla con los demás.
    """
    note_id = f"{job_name}:{key}" if key and job_name else key
    payload = {"to": to, "content": content, "job": job_name or None}
    if note_id:
        payload["id"] = note_id
    result = _request("POST", "/api/link/send", payload)
    return (result or {}).get("id", "")


def agents() -> dict[str, dict]:
    """Estado de cada agente conectado a la malla, tal como lo ve el hub de pi-link.

    Devuelve `{nombre: {"status", "since_s", "tokens", "context_window", ...}}`. `status` es
    uno de `idle`, `thinking`, `tool` o `compacting` según lo reporta el hub de pi-link — pero
    trátalo con `==  "idle"` o `!= "idle"`, no asumas que el resto son exactamente esas cuatro
    cadenas (`tool` puede traer sufijo, p. ej. qué herramienta). Un agente apagado o
    desconectado simplemente no aparece. Si el hub no responde se lanza `ConsoleError`: "no sé
    cómo está el equipo" no es lo mismo que "están todos ociosos".
    """
    link = (_request("GET", "/api/system") or {}).get("link") or {}
    if not link.get("available"):
        raise ConsoleError(f"no se sabe el estado de los agentes: {link.get('reason', '?')}")
    return link.get("terminals") or {}


class _State:
    """Memoria del job entre ejecuciones.

    Vive en la base de datos de la consola y no en un fichero, porque el directorio de scripts
    está montado en solo lectura a propósito. Sirve para lo de siempre: "ya avisé de esto hoy,
    no lo repitas".
    """

    def _job(self) -> str:
        if not job_name:
            raise ConsoleError("state solo está disponible dentro de un job del cron")
        return job_name

    def all(self) -> dict:
        return _request("GET", f"/api/cron/state?job={urllib.parse.quote(self._job())}") or {}

    def get(self, key: str, default=None):
        return self.all().get(key, default)

    def __getitem__(self, key: str):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value) -> None:
        _request("POST", "/api/cron/state", {"job": self._job(), "key": key, "value": value})

    def __delitem__(self, key: str) -> None:
        _request("POST", "/api/cron/state", {"job": self._job(), "key": key, "value": None})

    def __contains__(self, key: str) -> bool:
        return key in self.all()


_MISSING = object()
state = _State()


class _WorkItem:
    """Un work item de ADO con los campos de uso diario a mano y el resto en `fields`."""

    def __init__(self, raw: dict):
        self.raw = raw
        fields = raw.get("fields") or {}
        self.fields = fields
        self.id = raw.get("id")
        self.title = fields.get("System.Title", "")
        self.state = fields.get("System.State", "")
        self.type = fields.get("System.WorkItemType", "")
        assigned = fields.get("System.AssignedTo") or {}
        self.assigned_to = assigned.get("displayName") if isinstance(assigned, dict) else assigned
        #: ADO guarda las etiquetas como una sola cadena separada por "; ".
        self.tags = [t.strip() for t in (fields.get("System.Tags") or "").split(";") if t.strip()]

    def __repr__(self) -> str:
        return f"<WorkItem #{self.id} {self.state}: {self.title[:40]}>"


class _Ado:
    """Consultas a Azure DevOps con el PAT y la organización ya resueltos del entorno.

    Por debajo es `az boards`, la misma herramienta y la misma sintaxis que usan los agentes
    (ver docs/work-procedures.md), para que un WIQL que funciona en un sitio funcione en el
    otro. El PAT es el de la consola (CONSOLE_ADO_PAT), independiente del de cada agente.
    """

    def _az(self, *args: str) -> object:
        if not os.environ.get("AZURE_DEVOPS_EXT_PAT"):
            raise ConsoleError(
                "no hay PAT de Azure DevOps en el entorno: define CONSOLE_ADO_PAT en .env"
            )
        command = ["az", *args, "--output", "json"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as exc:
            raise ConsoleError(
                "az CLI no está en esta imagen (¿se construyó con CONSOLE_AZ_CLI=false?)"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConsoleError("la consulta a ADO tardó más de 120 s") from exc
        if result.returncode != 0:
            raise ConsoleError(f"az falló: {result.stderr.strip()[:500]}")
        return json.loads(result.stdout or "null")

    def query(self, wiql: str) -> list[_WorkItem]:
        """Ejecuta un WIQL y devuelve los work items resultantes."""
        raw = self._az("boards", "query", "--wiql", wiql)
        return [_WorkItem(item) for item in (raw or [])]

    def work_item(self, item_id: int | str) -> _WorkItem:
        return _WorkItem(self._az("boards", "work-item", "show", "--id", str(item_id)))

    def update(self, item_id: int | str, fields: dict[str, str]) -> _WorkItem:
        """Cambia campos de un work item y devuelve cómo ha quedado.

        `fields` usa los nombres de referencia de ADO (`{"System.Tags": "a; b"}`). Ojo con
        `System.Tags`: se sustituye entera, así que para cambiar una etiqueta hay que mandar
        la lista completa (ver `_WorkItem.tags`).
        """
        pairs = [f"{name}={value}" for name, value in fields.items()]
        return _WorkItem(self._az("boards", "work-item", "update", "--id", str(item_id),
                                  "--fields", *pairs))


ado = _Ado()