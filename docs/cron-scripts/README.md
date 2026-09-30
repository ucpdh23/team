# Scripts de ejemplo para el cron de la consola

Scripts listos para copiar. **No se ejecutan desde aquí**: el cron de la consola solo ve lo que
hay en `tmp/scripts/` (ver "Scheduled scripts" en el README). Para usar uno:

```bash
cp docs/cron-scripts/despacho_tickets_ai.py tmp/scripts/
```

y prográmalo en la pestaña **Cron**. La API que usan está en
[`console/sdk/README.md`](../../console/sdk/README.md).

| Script | Horario pensado | Qué hace |
|---|---|---|
| [`despacho_tickets_ai.py`](despacho_tickets_ai.py) | `*/5 * * * *` | Si los cinco agentes llevan un rato ociosos, coge el ticket abierto de mayor prioridad con la etiqueta `AI_ANALYSIS` o `AI_DEVELOPMENT`, la cambia a `AI_ANALYSIS_INPROGRESS` / `AI_DEVELOPMENT_INPROGRESS` y le pasa al manager un prompt según el tipo: la etapa 1 de [`work-procedures.md`](../work-procedures.md) para un análisis, o desde la etapa 2 para un desarrollo. Con `--dry-run` enseña el ticket y el prompt sin tocar nada. |

`despacho_tickets_ai.py` modifica tickets, así que `CONSOLE_ADO_PAT` necesita **Work Items —
Read & Write**, no solo lectura.
