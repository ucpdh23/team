"""Mosaico de las sesiones tmux de los agentes, en solo lectura.

Cada agente corre `pi` dentro de una sesión tmux llamada `pi` (ver docker/entrypoint.sh). Este
módulo pide a cada contenedor el contenido actual de ese panel con `tmux capture-pane`, que
devuelve exactamente lo que se vería al engancharse — sin engancharse, sin teclear y sin poder
interferir.

Por qué solo lectura: para trabajar de verdad con un agente ya está
`docker exec -it <contenedor> tmux attach -t pi` (o `python setup.py --tmux <rol>`), que da una
terminal completa. Lo que no había era poder ver los cinco a la vez, y eso es lo que resuelve
esto.

El coste es un `exec` por agente y refresco, así que hay una caché corta: varias pestañas
abiertas del navegador no multiplican el trabajo del daemon.
"""

from __future__ import annotations

import threading
import time

SESSION = "pi"
DEFAULT_LINES = 60
MAX_LINES = 400
CACHE_TTL_S = 2.0
EXEC_TIMEOUT_S = 5.0


class TmuxView:
    def __init__(self, docker, system):
        self.docker = docker
        self.system = system
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def agents(self) -> list[dict]:
        """Los contenedores que pueden tener sesión: todos menos la propia consola.

        Los que están en marcha van primero: un mosaico es para mirar lo que está vivo, y los
        parados solo tienen que estar ahí para que se note que faltan.
        """
        agents = [
            {"agent": c["role"], "container": c["name"], "state": c["state"],
             "status": c["status"]}
            for c in self.system.containers()
            if c["role"] != "console"
        ]
        return sorted(agents, key=lambda a: (a["state"] != "running", a["agent"]))

    def pane(self, agent: str, lines: int = DEFAULT_LINES, colors: bool = True) -> dict:
        lines = max(5, min(int(lines), MAX_LINES))
        key = f"{agent}:{lines}:{int(colors)}"
        with self._lock:
            cached = self._cache.get(key)
            if cached and (time.time() - cached[0]) < CACHE_TTL_S:
                return cached[1]

        result = self._capture(agent, lines, colors)
        with self._lock:
            self._cache[key] = (time.time(), result)
        return result

    def _capture(self, agent: str, lines: int, colors: bool) -> dict:
        target = next((c for c in self.system.containers() if c["role"] == agent), None)
        if target is None:
            return {"agent": agent, "error": "no hay ningún contenedor para ese agente"}
        if target["state"] != "running":
            return {"agent": agent, "container": target["name"], "state": target["state"],
                    "error": f"el contenedor está {target['state']}"}
        if not self.docker:
            return {"agent": agent, "error": "sin acceso al socket de Docker"}

        # -p a stdout, -e conserva los colores ANSI, -S -<n> incluye las últimas n líneas del
        # historial además de lo visible: si el agente acaba de imprimir algo largo, se ve.
        cmd = ["tmux", "capture-pane", "-p", "-t", SESSION, "-S", f"-{lines}"]
        if colors:
            cmd.insert(2, "-e")
        output = self.docker.exec_capture(target["id"], cmd, timeout=EXEC_TIMEOUT_S)

        if output is None:
            return {"agent": agent, "container": target["name"],
                    "error": "no se pudo ejecutar tmux en el contenedor"}
        if "no server running" in output or "can't find session" in output:
            # El contenedor está arriba pero la sesión no: el watchdog del entrypoint la
            # relanza sola, así que esto es información, no un fallo de la consola.
            return {"agent": agent, "container": target["name"],
                    "error": "la sesión tmux 'pi' no está activa todavía"}
        return {
            "agent": agent,
            "container": target["name"],
            "state": target["state"],
            "text": output.rstrip("\n"),
            "ts": int(time.time() * 1000),
        }
