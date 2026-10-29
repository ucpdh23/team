"""Si el cluster completo lleva cinco minutos ocioso, encola una sesión Pi nueva por agente."""

from datetime import datetime
import sys

from console_sdk import ConsoleError, agents, log, new_session, pending_inbox, state

TEAM = ("manager", "backend", "frontend", "devops", "cypress")
MIN_IDLE_S = 5 * 60
STATE_KEY = "daily_new_session"


def idle_problems(roster: dict[str, dict]) -> list[str]:
    problems = []
    for role in TEAM:
        agent = roster.get(role)
        if agent is None:
            problems.append(f"{role}: no conectado")
            continue
        status = agent.get("status")
        if status != "idle":
            problems.append(f"{role}: {status or 'estado desconocido'}")
            continue
        idle_for = agent.get("since_s") or 0
        if idle_for < MIN_IDLE_S:
            problems.append(f"{role}: ocioso solo desde hace {idle_for} s")
    return problems


def main(dry_run: bool) -> int:
    try:
        roster = agents()
    except ConsoleError as exc:
        log("no puedo verificar el estado del cluster; no reinicio sesiones:", exc)
        return 1

    pending_work = [item for item in pending_inbox() if not item.get("command")]
    if pending_work:
        targets = ", ".join(sorted({item["agent"] for item in pending_work}))
        log("hay avisos de trabajo pendientes para", targets, "; no reinicio sesiones")
        return 0

    problems = idle_problems(roster)
    if problems:
        log("cluster no completamente ocioso; no se envía ningún /new:", "; ".join(problems))
        return 0

    if dry_run:
        log("[dry-run] cluster ocioso; encolaría /new para:", ", ".join(TEAM))
        return 0

    today = datetime.now().astimezone().date().isoformat()
    progress = state.get(STATE_KEY, {}) or {}
    if not isinstance(progress, dict):
        progress = {}
    queued = set(progress.get("queued", [])) if progress.get("date") == today else set()
    remaining = [role for role in TEAM if role not in queued]
    if not remaining:
        log(f"las cinco sesiones ya recibieron /new hoy ({today})")
        return 0

    failures = []
    for role in remaining:
        try:
            command_id = new_session(role, key=f"daily-new-{today}-{role}")
        except Exception as exc:  # noqa: BLE001
            log(f"no se pudo encolar /new para {role}: {exc}")
            failures.append(role)
            continue
        queued.add(role)
        # Guardar cada éxito: si el proceso falla a mitad, una reejecución del mismo día
        # continúa con los agentes restantes en lugar de volver a encolar los ya procesados.
        state[STATE_KEY] = {"date": today, "queued": sorted(queued)}
        log(f"orden /new encolada para {role} (id {command_id})")

    if failures:
        log("quedaron agentes sin orden; se puede reintentar hoy:", ", ".join(failures))
        return 1
    log("órdenes encoladas para todo el cluster; la extensión inicia cada sesión nueva")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv[1:]))
