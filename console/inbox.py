"""Cola de avisos de la consola hacia los agentes.

Es la respuesta a una pregunta concreta: ¿cómo le dice la consola algo a un agente a una hora
determinada (el cron de la fase siguiente) sin convertirse en un miembro más del equipo?

Por pi-link no puede: el hub descarta lo que venga de un socket sin registrar y sobrescribe el
campo `from` con el nombre registrado, así que enviar obliga a registrarse, y registrarse
obliga a aparecer en el `link_list` de los cinco agentes (los grupos aíslan el enrutado, así
que esconderse en otro grupo deja a la consola invisible *y* muda).

La salida es no usar pi-link: la extensión `team-console`, que ya vive dentro del proceso `pi`
de cada agente, pregunta cada pocos segundos si hay algo para él y lo inyecta con
`pi.sendMessage(..., { triggerTurn: true })` — el mismo mecanismo exacto con el que pi-link
entrega sus mensajes, así que el agente arranca turno aunque estuviera ocioso.

Lo que se gana frente a un cliente WebSocket registrado, además de no tener presencia:
confirmación de entrega real (`ack`), y que un aviso para un agente apagado espere en vez de
perderse con un "terminal not found".
"""

from __future__ import annotations

import json
import time
import uuid

# Si un agente se lleva un aviso y no confirma (se reinició entre la inyección y el ack), se
# le vuelve a dar pasado este tiempo. Lo bastante largo para no duplicar por una confirmación
# lenta, lo bastante corto para que un reinicio no se coma el aviso del día.
REDELIVER_AFTER_MS = 5 * 60 * 1000
MAX_CONTENT_CHARS = 8000
MAX_TAKE = 10


def now_ms() -> int:
    return int(time.time() * 1000)


class Inbox:
    def __init__(self, db, events, ttl_hours: int = 24):
        self.db = db
        self.events = events
        self.ttl_hours = ttl_hours

    # ------------------------------------------------------------------- envío

    def send(self, agent: str, content: str, job: str | None = None) -> dict:
        agent = (agent or "").strip()
        content = (content or "").strip()
        if not agent:
            raise ValueError("falta el destinatario ('to')")
        if not content:
            raise ValueError("el aviso no puede estar vacío")
        if len(content) > MAX_CONTENT_CHARS:
            # Un aviso es un párrafo y una lista, no un volcado: lo que se inyecta se paga en
            # contexto del agente que lo recibe.
            raise ValueError(f"el aviso supera {MAX_CONTENT_CHARS} caracteres")

        note_id = str(uuid.uuid4())
        created = now_ms()
        self.db.execute(
            "INSERT INTO inbox (id, agent, content, job, created_ts, expires_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (note_id, agent, content, job, created, created + self.ttl_hours * 3_600_000),
        )
        return {"id": note_id, "queued": True, "agent": agent, "chars": len(content)}

    # ---------------------------------------------------------------- entrega

    def take(self, agent: str, limit: int = MAX_TAKE) -> list[dict]:
        """Avisos que ese agente debe entregarse a sí mismo ahora.

        Marca lo entregado para poder detectar una reentrega, pero **no borra**: la fila vive
        hasta el `ack`, que es lo que convierte "se lo llevó" en "llegó".
        """
        agent = (agent or "").strip()
        if not agent:
            return []
        now = now_ms()
        rows = self.db.query(
            "SELECT * FROM inbox WHERE agent = ? AND expires_ts > ? "
            "  AND (taken_ts IS NULL OR taken_ts < ?) "
            "ORDER BY created_ts LIMIT ?",
            (agent, now, now - REDELIVER_AFTER_MS, max(1, min(int(limit), MAX_TAKE))),
        )
        out = []
        for row in rows:
            self.db.execute(
                "UPDATE inbox SET taken_ts = ?, attempts = attempts + 1 WHERE id = ?",
                (now, row["id"]),
            )
            out.append({
                "id": row["id"],
                "content": row["content"],
                "job": row["job"],
                "created_ts": row["created_ts"],
                # El agente lo enseña como tal: un aviso repetido confunde si no se avisa.
                "redelivered": row["attempts"] > 0,
            })
        return out

    def ack(self, note_id: str) -> bool:
        """Confirma la entrega: borra el aviso y deja solo su metadato en `events`."""
        rows = self.db.query("SELECT * FROM inbox WHERE id = ?", (note_id,))
        if not rows:
            return False
        row = rows[0]
        self.db.execute("DELETE FROM inbox WHERE id = ?", (note_id,))
        # La flecha `console → agente` del grafo de Actividad sale de aquí. El texto del aviso
        # se va con la fila: en `events` solo queda cuánto ocupaba, como con todo lo demás.
        self.events.ingest([{
            "ts": now_ms(),
            "type": "link.message.sent",
            "agent": "console",
            "peer": row["agent"],
            "payload": {
                "chars": len(row["content"]),
                "ok": True,
                "attempts": row["attempts"],
                **({"job": row["job"]} if row["job"] else {}),
            },
        }])
        return True

    # ----------------------------------------------------------------- estado

    def pending(self, agent: str | None = None) -> list[dict]:
        """Lo que sigue sin entregarse, para la UI. No toca nada."""
        now = now_ms()
        sql = "SELECT id, agent, job, created_ts, expires_ts, taken_ts, attempts, " \
              "LENGTH(content) AS chars FROM inbox"
        params: tuple = ()
        if agent:
            sql += " WHERE agent = ?"
            params = (agent,)
        sql += " ORDER BY created_ts"
        return [{
            "id": r["id"],
            "agent": r["agent"],
            "job": r["job"],
            "chars": r["chars"],
            "age_s": max(0, (now - r["created_ts"]) // 1000),
            "expires_in_s": max(0, (r["expires_ts"] - now) // 1000),
            "attempts": r["attempts"],
            "taken": r["taken_ts"] is not None,
        } for r in self.db.query(sql, params)]

    def purge(self) -> int:
        """Tira los avisos caducados. Un 'revisa los tickets de hoy' de hace tres días es ruido."""
        return self.db.execute("DELETE FROM inbox WHERE expires_ts <= ?", (now_ms(),))

    def stats(self) -> dict:
        rows = self.db.query(
            "SELECT agent, COUNT(*) AS n FROM inbox WHERE expires_ts > ? GROUP BY agent",
            (now_ms(),),
        )
        return {"pending": sum(r["n"] for r in rows), "by_agent": {r["agent"]: r["n"] for r in rows}}
