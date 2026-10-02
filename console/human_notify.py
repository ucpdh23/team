"""Avisos de un agente para el humano, mostrados como notificación del navegador.

Es el `inbox` al revés: `inbox.py` lleva avisos de la consola *a* un agente; esto lleva un
aviso de un agente *al navegador*, para que `console/static/app.js` lo convierta en una
`Notification` del sistema operativo. Quien lo crea hoy es la tool `notify_human` de la
extensión del manager (`agents/manager/pi/extensions/notify-human/`), pero el endpoint no
asume quién llama — cualquier agente podría usarlo si algún día le hace falta.

Sin ack ni reentrega, a propósito: un toast que no has visto no tiene sentido repetirlo más
tarde fuera de contexto — lo máximo que hace esto es esperar a que el navegador sondee.
"""

from __future__ import annotations

import time
import uuid

MAX_CONTENT_CHARS = 500
#: Cuánto se conserva un aviso ya mostrado. Es ruido pasado este tiempo, no historial: a
#: diferencia de `events`, aquí no hay pestaña que lo liste.
RETENTION_MS = 24 * 3_600_000


def now_ms() -> int:
    return int(time.time() * 1000)


class HumanNotify:
    def __init__(self, db):
        self.db = db

    def create(self, agent: str, content: str) -> dict:
        agent = (agent or "").strip()
        content = (content or "").strip()
        if not agent:
            raise ValueError("falta quién lo pide ('agent')")
        if not content:
            raise ValueError("el aviso no puede estar vacío")
        if len(content) > MAX_CONTENT_CHARS:
            # Una notificación del sistema operativo es una frase, no un informe: lo que no
            # cabe en un toast no pertenece aquí.
            raise ValueError(f"el aviso supera {MAX_CONTENT_CHARS} caracteres")

        note_id = str(uuid.uuid4())
        created = now_ms()
        self.db.execute(
            "INSERT INTO human_notices (id, agent, content, created_ts) VALUES (?, ?, ?, ?)",
            (note_id, agent, content, created),
        )
        return {"id": note_id, "agent": agent, "ts": created}

    def pending(self, since: int | None = None, limit: int = 50) -> dict:
        """Avisos desde `since`, con el cursor para la próxima vez.

        Mismo patrón que `events.pulse()`: sin `since`, los últimos 10 s (un primer sondeo no
        debe disparar un toast por cada aviso de las últimas 24 h), y el cursor avanza aunque
        no haya nada nuevo, para que el navegador no repita una ventana cada vez más ancha.
        """
        now = now_ms()
        if since is None:
            since = now - 10_000
        rows = self.db.query(
            "SELECT id, agent, content, created_ts FROM human_notices "
            "WHERE created_ts > ? ORDER BY created_ts ASC LIMIT ?",
            (int(since), max(1, min(int(limit), 50))),
        )
        notices = [{"id": r["id"], "agent": r["agent"], "content": r["content"],
                   "ts": r["created_ts"]} for r in rows]
        cursor = notices[-1]["ts"] if notices else max(int(since), now - 60_000)
        return {"notices": notices, "cursor": cursor}

    def purge(self) -> int:
        return self.db.execute(
            "DELETE FROM human_notices WHERE created_ts < ?", (now_ms() - RETENTION_MS,)
        )
