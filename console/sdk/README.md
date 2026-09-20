# `console_sdk` — la API de los scripts del cron

Los **scripts** son del equipo de desarrollo y no se versionan en team: viven en el directorio
que la consola monta en `/data/scripts` (por defecto `tmp/scripts/`, fuera del control de
versiones). Lo que team versiona es **esto**: la forma en que esos scripts hablan con el
equipo. Así, si mañana cambia cómo se entregan los avisos o dónde se guarda el estado, los
scripts no se enteran.

No hay que instalar nada: la imagen de la consola copia el módulo en `/opt/console-sdk` y lo
pone en `PYTHONPATH` al ejecutar cada script.

## Qué ofrece

| | Para qué |
|---|---|
| `notify(to, content)` | Deja un aviso para un agente. Lo recoge su extensión en ≤15 s y se lo inyecta, arrancándole turno aunque esté ocioso. Si está apagado, espera. |
| `log(...)` | Como `print`, con hora. La salida se guarda entera y se ve en la pestaña Cron. |
| `state` | Memoria del job entre ejecuciones (`state["ultimo_aviso"] = [...]`). Vive en la base de datos de la consola, porque el directorio de scripts está montado en solo lectura. |
| `ado.query(wiql)` / `ado.work_item(id)` | Consulta a Azure DevOps con el PAT (`CONSOLE_ADO_PAT`) y la organización ya resueltos. Por debajo es `az boards`, la misma sintaxis que usan los agentes. |
| `job_name`, `run_id` | Qué job y qué ejecución son ésta. |

## El ejemplo que motivó todo esto

`tmp/scripts/aviso_tickets_manager.py`, programado con `0 20 * * 1-5`:

```python
"""Avisa al manager de sus tickets pendientes."""   # ← la descripción que sale en la UI

from console_sdk import ado, log, notify, state

tickets = ado.query(
    "SELECT [System.Id], [System.Title] FROM WorkItems "
    "WHERE [System.AssignedTo] = @Me AND [System.State] <> 'Closed'"
)
if not tickets:
    log("sin tickets pendientes, no hay nada que avisar")
    raise SystemExit(0)

ids = sorted(t.id for t in tickets)
if state.get("ultimo_aviso") == ids:
    log("los mismos tickets que la última vez; no repito el aviso")
    raise SystemExit(0)

notify("manager",
       "Revisión de fin de jornada. Tickets pendientes:\n"
       + "\n".join(f"- #{t.id} {t.title}" for t in tickets))
state["ultimo_aviso"] = ids
log("avisado el manager de", len(ids), "tickets")
```

El manager lo recibe como un mensaje con encabezado propio
(`[Consola del equipo · aviso programado "…"]`) y, si estaba ocioso, arranca turno: nadie tiene
que estar mirando la pantalla a las ocho de la tarde.

## Reglas de la casa

- **Stdlib por defecto.** `urllib` y `json` bastan para hablar con la consola y con la API de
  ADO. Si un script necesita más, basta con dejar un `requirements.txt` junto a los scripts: la
  consola prepara un venv con ellas y solo lo rehace cuando ese fichero cambia.
- **Un aviso es un párrafo y una lista**, no un volcado: lo que se inyecta se paga en contexto
  del agente que lo recibe. El límite son 8.000 caracteres.
- **Salir con código distinto de 0 marca la ejecución como fallida**, y se ve en rojo en la
  pestaña Cron con su salida completa.
- **Las horas se evalúan en el huso del contenedor** (`TZ`, `Europe/Madrid` por defecto), no en
  el del navegador desde el que se programa.
