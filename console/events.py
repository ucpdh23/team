"""Eventos entre agentes: ingesta, consulta y agregación.

Cada vez que un agente manda un mensaje a otro por pi-link, la extensión `team-console`
(agents/_shared/pi/extensions/) manda aquí un evento. Lo que se guarda es **solo el
metadato**: quién, a quién, cuándo y cuánto ocupaba — nunca el texto del mensaje, que puede
llevar código, rutas o credenciales del proyecto en el que trabajan los agentes.

Esa promesa no se delega en quien emite: `_clean_payload()` tira cualquier campo con pinta de
llevar texto y recorta el resto, así que un emisor mal programado no puede colar una
conversación en la base ni por error.
"""

from __future__ import annotations

import json
import time
import uuid

# Campos que nunca se guardan, aunque un emisor los mande: son los que llevarían el contenido
# del mensaje. Ver la promesa de arriba.
_TEXT_KEYS = {"content", "message", "text", "body", "preview", "prompt", "output", "args"}
# Tope por si algún día un metadato legítimo (un nombre de job, un error) llega enorme.
_MAX_VALUE_CHARS = 200
_MAX_PAYLOAD_KEYS = 20

MAX_EVENTS_PER_REQUEST = 100
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

# Tipos que la consola entiende hoy. No se valida contra esta lista (un tipo nuevo no debe
# perderse por no estar aquí), pero documenta lo que existe.
TYPE_SENT = "link.message.sent"
TYPE_RECEIVED = "link.message.received"


def now_ms() -> int:
    return int(time.time() * 1000)


def _clean_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    clean = {}
    for key, value in payload.items():
        if len(clean) >= _MAX_PAYLOAD_KEYS:
            break
        if not isinstance(key, str) or key.lower() in _TEXT_KEYS:
            continue
        if isinstance(value, str):
            clean[key] = value[:_MAX_VALUE_CHARS]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        # Listas y objetos anidados se descartan: no hay ningún metadato que los necesite y
        # son la vía fácil para colar texto.
    return clean


def normalize(raw: dict, received_ts: int) -> dict | None:
    """Convierte lo que llega por la API en una fila, o None si no es un evento válido.

    Solo `type` y `agent` son obligatorios: el resto se completa. El `id` lo pone el emisor
    para que un reintento tras un timeout no duplique la fila; si no viene, se genera aquí.
    """
    if not isinstance(raw, dict):
        return None
    type_ = str(raw.get("type") or "").strip()
    agent = str(raw.get("agent") or "").strip()
    if not type_ or not agent:
        return None

    ts = raw.get("ts")
    ts = int(ts) if isinstance(ts, (int, float)) else received_ts
    peer = raw.get("peer")
    peer = str(peer).strip() or None if isinstance(peer, str) else None

    return {
        "id": str(raw.get("id") or uuid.uuid4()),
        "ts": ts,
        "received_ts": received_ts,
        "type": type_[:100],
        "agent": agent[:64],
        "peer": peer[:64] if peer else None,
        "payload": json.dumps(_clean_payload(raw.get("payload"))),
    }


class EventStore:
    def __init__(self, db, retention_days: int = 30):
        self.db = db
        self.retention_days = retention_days

    # ------------------------------------------------------------------ ingesta

    def ingest(self, raw_events: list) -> dict:
        received_ts = now_ms()
        rows = [e for e in (normalize(r, received_ts) for r in raw_events) if e]
        if not rows:
            return {"accepted": 0, "duplicated": 0, "rejected": len(raw_events)}

        before = self.count()
        # INSERT OR IGNORE + id del emisor = idempotencia: reintentar tras un timeout no
        # duplica nada, que es lo que permite a la extensión reintentar sin pensar.
        self.db.executemany(
            "INSERT OR IGNORE INTO events (id, ts, received_ts, type, agent, peer, payload) "
            "VALUES (:id, :ts, :received_ts, :type, :agent, :peer, :payload)",
            rows,
        )
        accepted = self.count() - before
        return {
            "accepted": accepted,
            "duplicated": len(rows) - accepted,
            "rejected": len(raw_events) - len(rows),
        }

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM events")[0]["n"]

    # ----------------------------------------------------------------- consulta

    def query(self, since=None, until=None, agent=None, type_prefix=None,
              limit=DEFAULT_LIMIT) -> list[dict]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list = []
        if since is not None:
            sql += " AND ts > ?"
            params.append(int(since))
        if until is not None:
            sql += " AND ts <= ?"
            params.append(int(until))
        if agent:
            # Un evento "toca" a un agente tanto si lo emite como si es el otro extremo.
            sql += " AND (agent = ? OR peer = ?)"
            params += [agent, agent]
        if type_prefix:
            sql += " AND type LIKE ?"
            params.append(f"{type_prefix}%")
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(max(1, min(int(limit), MAX_LIMIT)))
        return [self._row_to_dict(r) for r in self.db.query(sql, tuple(params))]

    def pulse(self, since=None, limit=DEFAULT_LIMIT) -> dict:
        """Lo ocurrido desde `since`, en orden cronológico, con el cursor para la próxima vez.

        Es lo que sondea la pestaña Actividad cada pocos segundos para encender las aristas
        del grafo. Devuelve `cursor` aunque no haya eventos, para que el cliente avance igual
        y no vuelva a pedir una ventana cada vez más grande.
        """
        now = now_ms()
        if since is None:
            since = now - 10_000
        events = list(reversed(self.query(since=since, limit=limit)))
        cursor = events[-1]["ts"] if events else max(int(since), now - 60_000)
        return {"events": events, "cursor": cursor, "now": now}

    def graph(self, window_ms: int = 3_600_000) -> dict:
        """Aristas emisor→receptor agregadas de la ventana pedida.

        Se construye con los eventos de **envío**, que son los que traen el destinatario
        exacto y el instante real. Si en la ventana no hay ninguno (p. ej. porque a un agente
        le falta la extensión) se cae a los de recepción, invirtiendo la dirección, y se dice
        en la respuesta en vez de devolver un grafo vacío sin explicación.
        """
        since = now_ms() - max(1000, int(window_ms))
        edges = self._edges(TYPE_SENT, since, invert=False)
        source = "sent"
        if not edges:
            edges = self._edges(TYPE_RECEIVED, since, invert=True)
            source = "received" if edges else "sent"
        return {"edges": edges, "source": source, "window_ms": window_ms, "since": since}

    def _edges(self, type_: str, since: int, invert: bool) -> list[dict]:
        rows = self.db.query(
            "SELECT agent, peer, COUNT(*) AS count, MAX(ts) AS last_ts, "
            "       SUM(COALESCE(json_extract(payload, '$.chars'), 0)) AS chars "
            "FROM events WHERE type = ? AND ts > ? AND peer IS NOT NULL "
            "GROUP BY agent, peer ORDER BY count DESC",
            (type_, since),
        )
        edges = []
        for row in rows:
            source, target = (row["peer"], row["agent"]) if invert else (row["agent"], row["peer"])
            edges.append({
                "from": source,
                "to": target,
                "count": row["count"],
                "chars": row["chars"] or 0,
                "last_ts": row["last_ts"],
            })
        return edges

    def stats(self) -> dict:
        row = self.db.query(
            "SELECT COUNT(*) AS total, MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM events"
        )[0]
        by_type = {
            r["type"]: r["n"]
            for r in self.db.query("SELECT type, COUNT(*) AS n FROM events GROUP BY type")
        }
        return {
            "total": row["total"],
            "first_ts": row["first_ts"],
            "last_ts": row["last_ts"],
            "by_type": by_type,
            "retention_days": self.retention_days,
        }

    # ---------------------------------------------------------------- retención

    def delete(self, before=None, agent=None, type_prefix=None) -> int:
        """Borrado manual, siempre acotado.

        Exige al menos un filtro a propósito: un `DELETE /api/events` desnudo que se llevara
        el histórico entero por descuido no es una función, es una trampa.
        """
        clauses, params = [], []
        if before is not None:
            clauses.append("ts < ?")
            params.append(int(before))
        if agent:
            clauses.append("(agent = ? OR peer = ?)")
            params += [agent, agent]
        if type_prefix:
            clauses.append("type LIKE ?")
            params.append(f"{type_prefix}%")
        if not clauses:
            raise ValueError("hay que acotar el borrado con before, agent o type")
        return self.db.execute(
            f"DELETE FROM events WHERE {' AND '.join(clauses)}", tuple(params)
        )

    def purge(self) -> int:
        """Borra lo más viejo que la retención configurada. Devuelve cuántas filas cayeron."""
        if self.retention_days <= 0:
            return 0
        cutoff = now_ms() - self.retention_days * 86_400_000
        return self.db.execute("DELETE FROM events WHERE ts < ?", (cutoff,))

    @staticmethod
    def _row_to_dict(row) -> dict:
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError):
            payload = {}
        return {
            "id": row["id"],
            "ts": row["ts"],
            "received_ts": row["received_ts"],
            "type": row["type"],
            "agent": row["agent"],
            "peer": row["peer"],
            "payload": payload,
        }
