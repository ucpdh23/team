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
entrega sus mensajes, así que el agente arranca turno aunque estuviera ocioso. También lleva
órdenes tipadas de control (hoy, iniciar una sesión nueva), que la extensión despacha a un
command handler sin convertirlas en texto del prompt.

Lo que se gana frente a un cliente WebSocket registrado, además de no tener presencia:
confirmación de entrega real (`ack`), y que un aviso para un agente apagado espere en vez de
perderse con un "terminal not found".
"""

from __future__ import annotations

import sqlite3
import time
import uuid

# Si un agente se lleva un aviso y no confirma (se reinició entre la inyección y el ack), se
# le vuelve a dar pasado este tiempo. Lo bastante largo para no duplicar por una confirmación
# lenta, lo bastante corto para que un reinicio no se coma el aviso del día.
REDELIVER_AFTER_MS = 5 * 60 * 1000
MAX_CONTENT_CHARS = 8000
MAX_TAKE = 10
#: Tope de una clave de idempotencia (ver `send`). Generosa de sobra para "job:lo-que-sea"
#: y corta la posibilidad de que un script meta ahí algo que no es una clave.
MAX_ID_CHARS = 200
#: Una orden de sesión no debe quedarse esperando hasta el día siguiente si un agente cayó.
COMMAND_TTL_MS = 15 * 60 * 1000
SUPPORTED_COMMANDS = {"new_session"}


def now_ms() -> int:
    return int(time.time() * 1000)


class Inbox:
    def __init__(self, db, events, ttl_hours: int = 24):
        self.db = db
        self.events = events
        self.ttl_hours = ttl_hours

    # ------------------------------------------------------------------- envío

    def send(self, agent: str, content: str, job: str | None = None,
             note_id: str | None = None) -> dict:
        """Encola un aviso de texto. Con `note_id`, la llamada es idempotente."""
        content = (content or "").strip()
        if not content:
            raise ValueError("el aviso no puede estar vacío")
        if len(content) > MAX_CONTENT_CHARS:
            # Un aviso es un párrafo y una lista, no un volcado: lo que se inyecta se paga en
            # contexto del agente que lo recibe.
            raise ValueError(f"el aviso supera {MAX_CONTENT_CHARS} caracteres")
        return self._enqueue(agent, content, job, note_id, None,
                             self.ttl_hours * 3_600_000)

    def send_command(self, agent: str, command: str, job: str | None = None,
                     note_id: str | None = None) -> dict:
        """Encola una orden tipada de control, nunca texto ejecutable arbitrario."""
        if command not in SUPPORTED_COMMANDS:
            raise ValueError(f"orden no permitida: {command}")
        return self._enqueue(agent, "", job, note_id, command, COMMAND_TTL_MS)

    def _enqueue(self, agent: str, content: str, job: str | None, note_id: str | None,
                 command: str | None, ttl_ms: int) -> dict:
        agent = (agent or "").strip()
        if not agent:
            raise ValueError("falta el destinatario ('to')")

        note_id = (note_id or "").strip()[:MAX_ID_CHARS]
        if note_id:
            existing = self._by_id(note_id)
            if existing:
                if existing.get("command") != command or existing.get("agent") != agent:
                    raise ValueError("la clave ya se usó para otro destinatario o tipo de aviso")
                return existing
        else:
            note_id = str(uuid.uuid4())

        created = now_ms()
        try:
            self.db.execute(
                "INSERT INTO inbox (id, agent, content, command, job, created_ts, expires_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, agent, content, command, job, created, created + ttl_ms),
            )
        except sqlite3.IntegrityError:
            # Otra petición con la misma clave ganó la carrera entre el SELECT de arriba y
            # este INSERT: exactamente lo que la idempotencia debía evitar, no un fallo.
            existing = self._by_id(note_id)
            if existing and existing.get("command") == command and existing.get("agent") == agent:
                return existing
            raise ValueError("la clave ya se usó para otro destinatario o tipo de aviso")
        return {"id": note_id, "queued": True, "agent": agent, "chars": len(content),
                **({"command": command} if command else {})}

    def _by_id(self, note_id: str) -> dict | None:
        rows = self.db.query("SELECT agent, content, command FROM inbox WHERE id = ?", (note_id,))
        if not rows:
            return None
        row = rows[0]
        return {"id": note_id, "queued": True, "agent": row["agent"],
                "chars": len(row["content"]), "deduped": True,
                **({"command": row["command"]} if row["command"] else {})}

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
                **({"command": row["command"]} if row["command"] else {}),
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
                **({"command": row["command"]} if row["command"] else {}),
            },
        }])
        return True

    # ----------------------------------------------------------------- estado

    def pending(self, agent: str | None = None) -> list[dict]:
        """Lo que sigue sin entregarse, para la UI. No toca nada."""
        now = now_ms()
        sql = "SELECT id, agent, job, command, created_ts, expires_ts, taken_ts, attempts, " \
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
            **({"command": r["command"]} if r["command"] else {}),
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
