"""Si el equipo entero está ocioso, le da al manager el siguiente ticket AI_ANALYSIS / AI_DEVELOPMENT."""

# Pensado para `*/5 * * * *`. En cada pasada:
#
#   1. Comprueba que los cinco agentes están conectados y ociosos desde hace un rato.
#      Si falta alguno o alguno está trabajando, no hace nada.
#   2. Busca en ADO el ticket abierto de mayor prioridad con la etiqueta AI_ANALYSIS o
#      AI_DEVELOPMENT.
#   3. Cambia esa etiqueta por su versión _INPROGRESS, para que la siguiente pasada no lo coja.
#   4. Solo entonces avisa al manager con un prompt que depende del tipo de trabajo. Si el
#      aviso falla, devuelve la etiqueta original para que el ticket no se quede huérfano.
#
# Con el argumento `--dry-run` dice lo que haría sin tocar ADO ni avisar a nadie.

import sys

from console_sdk import ado, agents, log, notify

TEAM = ("manager", "backend", "frontend", "devops", "cypress")

# Segundos que cada agente tiene que llevar ocioso. Entre dos mensajes de pi-link un agente
# puede quedarse ocioso un instante sin haber terminado nada; esto evita confundirlo con
# "el equipo no tiene trabajo".
MIN_IDLE_S = 60

# Etiqueta que se busca → etiqueta que se pone al despacharlo. El orden decide qué gana si un
# ticket tiene las dos: no se desarrolla lo que no se ha analizado.
TAGS = {
    "AI_ANALYSIS": "AI_ANALYSIS_INPROGRESS",
    "AI_DEVELOPMENT": "AI_DEVELOPMENT_INPROGRESS",
}

PRIORITY = "Microsoft.VSTS.Common.Priority"

WIQL = (
    f"SELECT [System.Id], [System.Title], [System.WorkItemType], [System.Tags], [{PRIORITY}] "
    "FROM WorkItems WHERE ("
    + " OR ".join(f"[System.Tags] CONTAINS '{tag}'" for tag in TAGS)
    + ") AND [System.State] NOT IN ('Closed', 'Done', 'Removed') "
    f"ORDER BY [{PRIORITY}] ASC, [System.Id] ASC"
)

PROMPTS = {
    "AI_ANALYSIS": """\
Ticket para ANALIZAR: #{id} [{type}] {title} (prioridad {priority}).

Venía etiquetado AI_ANALYSIS; ya lo he cambiado a AI_ANALYSIS_INPROGRESS.

Haz con él la etapa 1 (Analysis) de /docs/work-procedures.md. Lee el ticket en ADO, consulta \
con link_prompt a los roles afectados, junta sus preguntas abiertas en una sola lista y \
publícala como comentario en el ticket. En esta etapa no se implementa nada ni se crean Tasks.""",
    "AI_DEVELOPMENT": """\
Ticket para DESARROLLAR: #{id} [{type}] {title} (prioridad {priority}).

Venía etiquetado AI_DEVELOPMENT; ya lo he cambiado a AI_DEVELOPMENT_INPROGRESS. Esa \
etiqueta es el visto bueno humano: el alcance está aprobado.

Llévalo desde la etapa 2 (Approved) de /docs/work-procedures.md: crea las Tasks por rol como \
hijas del ticket, reparte el trabajo por pi-link y sigue las etapas hasta merge-ready. Si al \
leerlo quedan preguntas sin resolver, no empieces: publícalas como comentario en el ticket.""",
}


def team_is_idle() -> bool:
    roster = agents()
    busy = []
    for name in TEAM:
        agent = roster.get(name)
        if agent is None:
            busy.append(f"{name}: no conectado")
        elif agent.get("status") != "idle":
            busy.append(f"{name}: {agent.get('status')}")
        elif (agent.get("since_s") or 0) < MIN_IDLE_S:
            busy.append(f"{name}: ocioso solo desde hace {agent.get('since_s')} s")
    if busy:
        log("el equipo no está libre →", "; ".join(busy))
        return False
    return True


def kind_of(item) -> str | None:
    """Qué etiqueta de TAGS lleva el ticket, sin importar cómo esté escrita (AI_Analysis,
    ai_analysis... todas cuentan; lo que se escribe de vuelta siempre es la forma canónica)."""
    upper = {tag.upper() for tag in item.tags}
    return next((tag for tag in TAGS if tag in upper), None)


def _priority_key(item):
    # `or 99` trataría una prioridad 0 real como "sin prioridad" (0 es falsy); solo la
    # ausencia del campo (None) debe ir al final.
    priority = item.fields.get(PRIORITY)
    return (99 if priority is None else priority, item.id)


def next_ticket():
    # WIQL ya ordena, pero se vuelve a ordenar aquí para no depender de que az conserve el
    # orden.
    candidates = [item for item in ado.query(WIQL) if kind_of(item)]
    candidates.sort(key=_priority_key)
    return candidates[0] if candidates else None


def main(dry_run: bool) -> int:
    if not team_is_idle():
        return 0

    ticket = next_ticket()
    if ticket is None:
        log("equipo ocioso, pero no hay tickets con", " ni ".join(TAGS))
        return 0

    # Se vuelve a leer justo antes de tocarlo: entre la consulta y este momento alguien ha
    # podido cambiarle las etiquetas.
    ticket = ado.work_item(ticket.id)
    kind = kind_of(ticket)
    if kind is None:
        log(f"#{ticket.id} ya no lleva ninguna etiqueta de despacho; lo dejo para la próxima")
        return 0

    original = "; ".join(ticket.tags)
    updated = "; ".join(TAGS[kind] if tag.upper() == kind else tag for tag in ticket.tags)
    prompt = PROMPTS[kind].format(
        id=ticket.id, type=ticket.type, title=ticket.title,
        priority=ticket.fields.get(PRIORITY, "sin prioridad"),
    )

    if dry_run:
        log(f"[dry-run] #{ticket.id}: etiquetas «{original}» → «{updated}»")
        log("[dry-run] aviso para el manager:\n" + prompt)
        return 0

    ado.update(ticket.id, {"System.Tags": updated})
    log(f"#{ticket.id}: {kind} → {TAGS[kind]}")
    try:
        # key: si esto se reintenta (p. ej. tras una excepción de red de la que no se sabe
        # si la consola llegó a procesar la primera llamada) sin que la revert-ada de abajo
        # llegue a ejecutarse, la consola ya tiene un aviso con este id y no manda otro — el
        # manager no se entera dos veces del mismo ticket.
        notify("manager", prompt, key=f"despacho-{ticket.id}-{kind}")
    except Exception as notify_exc:
        log(f"no se pudo avisar al manager de #{ticket.id}: {notify_exc}")
        try:
            ado.update(ticket.id, {"System.Tags": original})
        except Exception as revert_exc:
            # Si esto también falla, el ticket se queda en «updated» sin que nadie lo sepa
            # a menos que se diga aquí: ni se avisó al manager ni volverá a ser candidato.
            log(f"TAMPOCO se pudo devolver la etiqueta de #{ticket.id} a «{original}»: "
                f"{revert_exc}. Se queda en «{updated}»: revísalo a mano.")
        else:
            log(f"#{ticket.id} vuelve a «{original}»")
        raise notify_exc
    log(f"manager avisado: #{ticket.id} ({kind}) «{ticket.title}»")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv[1:]))
