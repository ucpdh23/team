"""Configuración de la consola, resuelta del entorno (dentro del contenedor) o de argumentos.

Todas las rutas que la consola usa viven aquí y en ningún otro sitio: el resto de módulos las
reciben, no las adivinan. Eso es lo que permite que el mismo paquete corra dentro del
contenedor (rutas de /data) y en el host con `setup.py --console-local` (rutas del repo).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 4070
# El servidor local de `setup.py --console-local` usa otro puerto a propósito: así se puede
# inspeccionar un export mientras el contenedor de la consola está levantado, sin chocar.
DEFAULT_LOCAL_PORT = 4080


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, "").strip() or default).expanduser()


@dataclass
class Config:
    port: int
    cost_dir: Path
    data_dir: Path
    scripts_dir: Path
    #: Valor de CONSOLE_BIND con el que el compose publica el puerto. El contenedor no puede
    #: saberlo por sí mismo (solo ve su 0.0.0.0 interno) y se usa únicamente para avisar de
    #: que la consola queda accesible sin autenticación fuera de esta máquina.
    bind: str = "127.0.0.1"
    #: Vacío = sin autenticación (v1). Si se define, se exige en toda petición.
    token: str = ""
    #: Días de eventos que se conservan. Un evento son ~80 bytes (solo metadatos), así que
    #: subirlo no es caro; 0 o menos desactiva la purga.
    event_retention_days: int = 30
    container_prefix: str = "pi"
    docker_socket: str = "/var/run/docker.sock"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            port=int(os.environ.get("CONSOLE_PORT_INTERNAL", "") or DEFAULT_PORT),
            cost_dir=_env_path("CONSOLE_COST_DIR", "/data/cost-tracking"),
            data_dir=_env_path("CONSOLE_DATA_DIR", "/data/console"),
            scripts_dir=_env_path("CONSOLE_SCRIPTS_DIR", "/data/scripts"),
            bind=os.environ.get("CONSOLE_BIND", "").strip() or "127.0.0.1",
            token=os.environ.get("CONSOLE_TOKEN", "").strip(),
            event_retention_days=int(
                os.environ.get("CONSOLE_EVENT_RETENTION_DAYS", "").strip() or 30
            ),
            container_prefix=os.environ.get("CONTAINER_PREFIX", "").strip() or "pi",
            docker_socket=os.environ.get("DOCKER_SOCKET", "").strip() or "/var/run/docker.sock",
        )

    @classmethod
    def local(cls, port: int, cost_dir: Path) -> "Config":
        """Modo `setup.py --console-local`: solo costes, sin Docker ni estado persistente."""
        return cls(
            port=port,
            cost_dir=cost_dir,
            data_dir=cost_dir.parent / ".console-local",
            scripts_dir=cost_dir.parent / ".console-local" / "scripts",
            docker_socket="",
        )

    def publishes_beyond_loopback(self) -> bool:
        return self.bind not in ("127.0.0.1", "localhost", "::1")
