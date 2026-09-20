"""Acceso a la base de datos de la consola (SQLite, librería estándar).

Una sola base (`console.db`, en el volumen `console-data`) para todo lo que la consola tiene
que recordar: hoy los eventos entre agentes; más adelante los jobs de cron, sus ejecuciones y
la cola de avisos. SQLite y no ficheros JSONL como `cost-tracking/` porque aquí escribe **un
solo proceso** —el JSONL de pi-cost-counter existe porque ahí escriben cinco contenedores a la
vez— y porque hay que filtrar y agregar por agente, por par emisor-receptor y por ventana
temporal en cada refresco de la web.

`ThreadingHTTPServer` atiende cada petición en su propio hilo, así que la conexión se comparte
con `check_same_thread=False` y las escrituras van serializadas por un lock. Es el patrón más
simple que no acaba en `database is locked`: las escrituras son cortas y poco frecuentes
(un puñado de eventos por minuto), y las lecturas en WAL no bloquean a nadie.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# Se sube cuando cambia el esquema; `migrate()` aplica lo que falte. PRAGMA user_version viene
# en el propio fichero, así que no hace falta una tabla de versiones.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id          TEXT PRIMARY KEY,
  ts          INTEGER NOT NULL,   -- epoch ms del emisor: el instante que de verdad interesa
  received_ts INTEGER NOT NULL,   -- epoch ms de la consola: delata relojes desfasados
  type        TEXT NOT NULL,
  agent       TEXT NOT NULL,
  peer        TEXT,
  payload     TEXT NOT NULL       -- JSON con metadatos (nunca texto de mensajes)
);
CREATE INDEX IF NOT EXISTS events_ts       ON events(ts DESC);
CREATE INDEX IF NOT EXISTS events_agent_ts ON events(agent, ts DESC);
CREATE INDEX IF NOT EXISTS events_pair_ts  ON events(agent, peer, ts DESC);
CREATE INDEX IF NOT EXISTS events_type_ts  ON events(type, ts DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL: lectores y escritor no se bloquean entre sí, que es justo el patrón de la
        # consola (una web leyendo mientras los agentes escriben eventos).
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current >= SCHEMA_VERSION:
                return
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._conn.commit()

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params=()) -> int:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor.rowcount

    def executemany(self, sql: str, seq) -> int:
        with self._lock:
            cursor = self._conn.executemany(sql, seq)
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
