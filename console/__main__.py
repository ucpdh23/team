"""Arranque de la consola dentro de su contenedor: `python -m console`.

Toda la configuración llega por entorno (ver `config.py` y el servicio `console` de
docker-compose.yml). Fuera del contenedor, `setup.py --console-local` entra por
`server.serve_local()` en vez de por aquí.
"""

from __future__ import annotations

import sys

from .config import Config
from .server import serve


def main() -> int:
    # Sin esto, la salida del arranque (rutas, avisos) se queda en el buffer hasta que se
    # llene, y `docker logs` no enseña nada durante los primeros minutos. La imagen ya define
    # PYTHONUNBUFFERED, pero esto lo garantiza también si alguien la sobreescribe.
    sys.stdout.reconfigure(line_buffering=True)
    return serve(Config.from_env())


if __name__ == "__main__":
    sys.exit(main())
