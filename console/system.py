"""Estado del sistema: contenedores, red, espacio y agentes.

Dos fuentes que se complementan y que a propósito no se mezclan:

- **Docker** (por su socket unix) sabe lo que *existe*: qué contenedores hay, con qué imagen,
  desde cuándo, cuánta CPU y memoria gastan, qué hay colgado de la red del equipo y cuánto
  disco ocupa todo. Es la única fuente que ve un agente **parado**, que es justo el que más
  interesa mirar.
- **pi-link** sabe lo que está *vivo*: el hub expone `GET /status` con el roster (quién está
  conectado, si está ocioso/pensando/ejecutando una herramienta y cuánto contexto lleva
  consumido). Es de solo lectura y no exige registrarse en la malla, así que la consola lo
  consulta sin aparecer en el `link_list` de nadie.

Todo lo de aquí degrada en silencio: si falta el socket, si el hub no responde o si un
contenedor desaparece a mitad de la consulta, se devuelve lo que se tenga y un motivo.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Puerto en el que el broker publica el hub de pi-link hacia la red del equipo
# (docker/pi-link-broker.sh, MESH_PORT). No es el 9900 de pi-link, que es solo loopback.
MESH_PORT = 9901
HUB_ADDR_FILE = "/var/run/pi-link/hub.addr"
HUB_TIMEOUT_S = 2.0

# El estado de los contenedores cambia despacio comparado con el refresco de la web, y
# /system/df tarda cientos de ms: cada cosa con su vida útil.
TTL_CONTAINERS = 3.0
TTL_STATS = 5.0
TTL_DISK = 60.0
TTL_LINK = 3.0


class _Cached:
    """Valor con caducidad. Si el cálculo falla, se conserva el anterior mientras haya."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._value = None
        self._at = 0.0

    def get(self, build):
        with self._lock:
            if self._value is not None and (time.time() - self._at) < self.ttl:
                return self._value
        value = build()
        with self._lock:
            self._value = value
            self._at = time.time()
        return value


def _age(iso: str | None) -> int | None:
    """Segundos desde una marca de tiempo de Docker (RFC3339 con nanosegundos)."""
    if not iso or iso.startswith("0001-01-01"):
        return None
    try:
        text = iso.replace("Z", "+00:00")
        # Docker da 9 decimales y datetime admite 6.
        if "." in text:
            head, _, tail = text.partition(".")
            frac, sign, offset = tail.partition("+")
            text = f"{head}.{frac[:6]}+{offset}" if sign else f"{head}.{frac[:6]}"
        from datetime import datetime, timezone

        started = datetime.fromisoformat(text)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0, int(time.time() - started.timestamp()))
    except ValueError:
        return None


class SystemInfo:
    def __init__(self, docker, container_prefix: str, hub_addr_file: str = HUB_ADDR_FILE):
        self.docker = docker
        self.prefix = container_prefix
        self.hub_addr_file = Path(hub_addr_file)
        self._project = _Cached(60.0)
        self._containers = _Cached(TTL_CONTAINERS)
        self._stats = _Cached(TTL_STATS)
        self._disk = _Cached(TTL_DISK)
        self._link = _Cached(TTL_LINK)

    # ------------------------------------------------------------- contenedores

    def project(self) -> str | None:
        """Proyecto de Compose al que pertenece esta consola, según su propia etiqueta.

        Compose etiqueta cada contenedor que crea con `com.docker.compose.project`, y la
        consola se inspecciona a sí misma (su hostname es su id) para leerla.
        """
        return self._project.get(self._build_project)

    def _build_project(self) -> str | None:
        if not self.docker:
            return None
        detail = self.docker.get(f"/containers/{socket.gethostname()}/json")
        labels = ((detail or {}).get("Config") or {}).get("Labels") or {}
        return labels.get("com.docker.compose.project")

    def _by_project(self, project: str) -> list[dict]:
        query = urllib.parse.quote(json.dumps({"label": [f"com.docker.compose.project={project}"]}))
        return self.docker.get(f"/containers/json?all=1&filters={query}") or []

    def containers(self) -> list[dict]:
        return self._containers.get(self._build_containers)

    def _list_raw(self) -> list[dict]:
        """Los contenedores del equipo, por los DOS criterios a la vez.

        - El proyecto de Compose de la propia consola (etiqueta `com.docker.compose.project`).
        - El prefijo de nombre (`CONTAINER_PREFIX`), que es el criterio original.

        Se unen en vez de elegir uno porque cada uno falla en un caso distinto: si el equipo se
        levantó desde otro directorio (otro proyecto de Compose) solo lo encuentra el prefijo,
        y si alguien cambió CONTAINER_PREFIX después de crear los contenedores solo lo
        encuentra el proyecto. Ver un contenedor de más que casualmente comparta prefijo es
        barato; no ver a tus agentes, no.
        """
        found: dict[str, dict] = {}
        project = self.project()
        if project:
            for container in self._by_project(project):
                found[container["Id"]] = container
        for container in self.docker.containers():
            names = [n.lstrip("/") for n in container.get("Names") or []]
            if any(n.startswith(f"{self.prefix}-") for n in names):
                found[container["Id"]] = container
        # Los contenedores de `docker compose run` son de usar y tirar: no forman parte del
        # equipo aunque lleven la etiqueta del proyecto.
        return [c for c in found.values()
                if (c.get("Labels") or {}).get("com.docker.compose.oneoff") != "True"]

    def _build_containers(self) -> list[dict]:
        if not self.docker:
            return []
        out = []
        for container in self._list_raw():
            names = [n.lstrip("/") for n in container.get("Names") or []]
            name = names[0] if names else ""
            labels = container.get("Labels") or {}
            detail = self.docker.get(f"/containers/{container['Id']}/json") or {}
            state = detail.get("State") or {}
            out.append({
                "id": container["Id"][:12],
                # El rol es el nombre del servicio en el compose, no un trozo del nombre del
                # contenedor: es lo que de verdad dice qué pieza del equipo es esta.
                "name": name,
                "role": labels.get("com.docker.compose.service")
                        or (name[len(self.prefix) + 1:] if name.startswith(f"{self.prefix}-") else name),
                "image": container.get("Image", ""),
                "state": container.get("State", ""),
                "status": container.get("Status", ""),
                "uptime_s": _age(state.get("StartedAt")) if state.get("Running") else None,
                "exit_code": state.get("ExitCode") if not state.get("Running") else None,
                "restarts": state.get("RestartCount", 0),
                "health": ((state.get("Health") or {}).get("Status")),
                "ports": self._ports(container.get("Ports") or []),
            })
        return sorted(out, key=lambda c: c["name"])

    @staticmethod
    def _ports(ports: list[dict]) -> list[str]:
        out = []
        for port in ports:
            public = port.get("PublicPort")
            private = port.get("PrivatePort")
            if public:
                out.append(f"{port.get('IP', '')}:{public}->{private}".lstrip(":"))
            elif private:
                out.append(str(private))
        return sorted(set(out))

    # ------------------------------------------------------------------- stats

    def stats(self) -> dict:
        return self._stats.get(self._build_stats)

    def _build_stats(self) -> dict:
        """CPU y memoria por contenedor.

        `/stats?stream=false` tarda ~1 s por contenedor porque necesita dos muestras para
        calcular el porcentaje de CPU, así que se piden en paralelo: seis en el tiempo de uno.
        Va en su propia ruta para que la tabla de contenedores aparezca sin esperar a esto.
        """
        if not self.docker:
            return {}
        running = [c for c in self.containers() if c["state"] == "running"]
        if not running:
            return {}

        def one(container):
            raw = self.docker.get(f"/containers/{container['id']}/stats?stream=false")
            return container["name"], _summarize_stats(raw)

        with ThreadPoolExecutor(max_workers=min(8, len(running))) as pool:
            return {name: data for name, data in pool.map(one, running) if data}

    # --------------------------------------------------------------------- red

    def network(self) -> dict:
        if not self.docker:
            return {"name": f"{self.prefix}-net", "available": False, "members": []}
        net = self.docker.get(f"/networks/{self.prefix}-net")
        if not net:
            return {"name": f"{self.prefix}-net", "available": False, "members": []}
        members = []
        for _id, info in (net.get("Containers") or {}).items():
            name = info.get("Name", "")
            members.append({
                "name": name,
                "ipv4": (info.get("IPv4Address") or "").split("/")[0],
                # Lo que `devops` levanta (una BBDD de desarrollo, p. ej.) vive en esta misma
                # red pero no es del equipo: se marca para poder enseñarlo aparte.
                "team": name.startswith(f"{self.prefix}-"),
            })
        return {
            "name": net.get("Name", f"{self.prefix}-net"),
            "available": True,
            "driver": net.get("Driver"),
            "members": sorted(members, key=lambda m: (not m["team"], m["name"])),
        }

    # ------------------------------------------------------------------ espacio

    def disk(self) -> dict:
        return self._disk.get(self._build_disk)

    def _build_disk(self) -> dict:
        if not self.docker:
            return {"available": False}
        df = self.docker.get("/system/df")
        if not df:
            return {"available": False}

        volumes = []
        for volume in df.get("Volumes") or []:
            usage = volume.get("UsageData") or {}
            size = usage.get("Size", -1)
            name = volume.get("Name", "")
            volumes.append({
                "name": name,
                "size": size if size and size > 0 else 0,
                # Los volúmenes del cluster llevan el prefijo en el nombre (ver
                # docker-compose.yml): así se separan de los del resto de la máquina.
                "team": self.prefix in name,
            })
        volumes.sort(key=lambda v: v["size"], reverse=True)

        images = df.get("Images") or []
        containers = df.get("Containers") or []
        return {
            "available": True,
            "images_size": sum(i.get("Size", 0) for i in images),
            "images_reclaimable": sum(
                i.get("Size", 0) for i in images if not i.get("Containers")
            ),
            "containers_size": sum(c.get("SizeRw", 0) or 0 for c in containers),
            "volumes_size": sum(v["size"] for v in volumes),
            "volumes": volumes[:12],
        }

    # ------------------------------------------------------------------ pi-link

    def link(self) -> dict:
        return self._link.get(self._build_link)

    def _build_link(self) -> dict:
        """Roster de la malla, preguntando al hub por HTTP.

        `hub.addr` lo escribe el broker del contenedor que ganó el flock y contiene su nombre
        de servicio, que es resoluble por DNS dentro de la red del equipo. Si el hub cambia
        (failover), el fichero cambia y la siguiente consulta ya va al nuevo: no hay nada que
        mantener por aquí.
        """
        try:
            hub = self.hub_addr_file.read_text(encoding="utf-8").strip()
        except OSError:
            return {"available": False, "reason": "sin volumen pi-link-coord"}
        if not hub:
            return {"available": False, "reason": "ningún contenedor ejerce de hub todavía"}

        url = f"http://{hub}:{MESH_PORT}/status"
        try:
            with urllib.request.urlopen(url, timeout=HUB_TIMEOUT_S) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # El caso corriente no es un fallo raro: es que el contenedor que fue hub está
            # parado y su nombre ya no resuelve. Merece decirse en ese idioma, porque la
            # pestaña Sistema lo enseña tal cual.
            text = str(getattr(exc, "reason", exc))
            if "Name or service not known" in text or "Temporary failure" in text:
                reason = f"el último hub anotado ({hub}) no está levantado"
            else:
                reason = f"el hub {hub} no responde: {text}"
            return {"available": False, "hub": hub, "reason": reason}

        terminals = {}
        for terminal in payload.get("terminals") or []:
            name = terminal.get("name")
            if not name:
                continue
            context = terminal.get("context") or {}
            terminals[name] = {
                "role": terminal.get("role"),
                "status": terminal.get("status"),
                "since_s": terminal.get("sinceSeconds"),
                "cwd": terminal.get("cwd"),
                "tokens": context.get("tokens"),
                "context_window": context.get("window"),
            }
        return {"available": True, "hub": payload.get("hub", hub), "terminals": terminals}

    # ------------------------------------------------------------------ resumen

    def other_projects(self) -> dict[str, int]:
        """Contenedores de OTROS proyectos de Compose visibles en este daemon.

        Solo se usa cuando la consola no encuentra a nadie de su equipo: si ahí aparece un
        proyecto con cinco contenedores, la respuesta a "¿por qué no veo a mis agentes?" está
        justo delante (se levantaron desde otro sitio, no desde este compose).
        """
        if not self.docker:
            return {}
        mine = self.project()
        counts: dict[str, int] = {}
        for container in self.docker.containers():
            project = (container.get("Labels") or {}).get("com.docker.compose.project")
            if project and project != mine:
                counts[project] = counts.get(project, 0) + 1
        return counts

    def snapshot(self) -> dict:
        """Lo que pinta la pestaña Sistema de un tirón (sin stats ni disco, que van aparte)."""
        containers = self.containers()
        data = {
            "prefix": self.prefix,
            "project": self.project(),
            "docker": bool(self.docker),
            "containers": containers,
            "network": self.network(),
            "link": self.link(),
        }
        # Un solo contenedor (la propia consola) casi siempre significa que el resto del equipo
        # se levantó con otra configuración, no que no exista.
        if len(containers) <= 1:
            data["other_projects"] = self.other_projects()
        return data


def _summarize_stats(raw) -> dict | None:
    """Porcentaje de CPU y memoria a partir de la muestra cruda de Docker.

    La fórmula es la misma que usa `docker stats`: incremento de uso de CPU del contenedor
    sobre el incremento del sistema, multiplicado por el número de CPUs. Si faltan las
    muestras previas (contenedor recién arrancado) se devuelve 0 en vez de inventar nada.
    """
    if not isinstance(raw, dict):
        return None
    cpu = raw.get("cpu_stats") or {}
    precpu = raw.get("precpu_stats") or {}
    cpu_delta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - \
                (precpu.get("cpu_usage") or {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    cpus = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    cpu_percent = (cpu_delta / system_delta) * cpus * 100 if cpu_delta > 0 and system_delta > 0 else 0.0

    memory = raw.get("memory_stats") or {}
    used = memory.get("usage", 0) - (memory.get("stats") or {}).get("inactive_file", 0)
    return {
        "cpu_percent": round(cpu_percent, 1),
        "memory_bytes": max(0, used),
        "memory_limit": memory.get("limit", 0),
    }
