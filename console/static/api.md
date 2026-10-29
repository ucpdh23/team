# API de la consola de team-pi

Referencia para **agentes y scripts**. Todo lo que hace la web de la consola se puede hacer
con `curl` contra esta API; la web es solo otro cliente. Este mismo documento está en
`/api.md` (Markdown, ideal para un agente) y en `/api.html` (para una persona).

## Conexión

| Desde | URL base |
|---|---|
| Un agente (contenedor de la red `team-net`) | `$CONSOLE_URL` — normalmente `http://console:4070` |
| El host | `http://localhost:4070` (o el `CONSOLE_PORT` del `.env`) |

**Autenticación.** Si la consola tiene `CONSOLE_TOKEN`, toda petición debe llevarlo:

```bash
curl -H "X-Console-Token: $CONSOLE_TOKEN" "$CONSOLE_URL/api/health"
```

Los agentes ya tienen `CONSOLE_URL` y `CONSOLE_TOKEN` en su entorno. Sin token configurado no
hay autenticación. Los ejemplos de abajo omiten la cabecera y usan `$C` como base:

```bash
C=${CONSOLE_URL:-http://localhost:4070}
H=${CONSOLE_TOKEN:+-H "X-Console-Token: $CONSOLE_TOKEN"}   # úsalo como: curl $H "$C/api/..."
```

**Convenciones.** Las respuestas son JSON (salvo la lectura de ficheros, que devuelve el
contenido tal cual). Los errores llevan `{"error": "..."}` y el código HTTP que toca: `400`
petición inválida, `401` sin token, `403` ruta no permitida, `404` no existe, `409` conflicto
(p. ej. el fichero ya existe), `413` demasiado grande. Los tiempos `ts` son milisegundos Unix.
Los **agentes** válidos son `manager`, `backend`, `frontend`, `devops`, `cypress`.

## Qué puedes hacer (índice)

| Capacidad | Endpoints | Para qué |
|---|---|---|
| [Workitems](#workitems) | `GET/PUT/POST /api/workitems/…` | Leer, subir y organizar lo que cada agente tiene en `/workspace/workitems`. |
| [Skills y AGENTS.md](#skills-y-agentsmd) | `GET/PUT/POST /api/skills/…` | Leer, revisar y **reescribir** los skills (propios y compartidos) y el `AGENTS.md` de cada agente. |
| [Docs compartidos](#documentación-compartida) | `GET/PUT/POST /api/docs/…` | Revisar y editar la carpeta `docs/` compartida por los agentes. |
| [Costes](#costes) | `GET /api/costs` | Gasto en LLM por agente, modelo y día/hora. |
| [Sistema](#sistema) | `GET /api/system…`, `/api/health` | Contenedores, red, disco y estado vivo de cada agente. |
| [Actividad](#actividad-eventos) | `GET/POST/DELETE /api/events…` | Quién habló con quién (solo metadatos) y uso de skills. |
| [Avisos a un agente](#avisos-a-un-agente-inbox) | `POST /api/link/send`, `/api/inbox…` | Dejar un mensaje que el agente recibe aunque esté inactivo. |
| [Avisos al humano](#avisos-al-humano) | `POST /api/human-notify` | Notificación del navegador a la persona. |
| [Cron](#cron) | `/api/cron/…` | Programar scripts del catálogo, ver su historial y estado. |
| [Tmux](#tmux) | `GET /api/tmux/panes…` | Leer lo que hay en pantalla en la sesión de un agente. |

---

## Workitems

`/workspace/workitems` de cada agente: una carpeta por funcionalidad solicitada al equipo.
Solo se ve esa carpeta (nada del resto del workspace).

| Petición | Resultado |
|---|---|
| `GET /api/workitems` | `{"agents":[{"agent","exists","items"}]}` — qué agentes tienen `workitems/` y cuántas carpetas. |
| `GET /api/workitems/<agente>[/<ruta>]` sobre un **directorio** | `{"agent","path","entries":[{"name","path","type":"dir"\|"file","size","modified"}],"truncated"}` |
| `GET …?recursive=1` sobre un directorio | Todos los ficheros de debajo, en plano (máx. 5000, `truncated` lo indica). |
| `GET /api/workitems/<agente>/<ruta>` sobre un **fichero** | El contenido tal cual. `?download=1` añade `Content-Disposition: attachment`. |
| `PUT /api/workitems/<agente>/<ruta>` con el contenido como cuerpo | Sube un fichero (crea las carpetas que falten). `201 {"saved","size","replaced"}`. |
| `POST /api/workitems/<agente>/<ruta-directorio>` | Crea una carpeta y los directorios padres que falten. `201 {"created","type":"dir"}`. |

```bash
curl $H "$C/api/workitems"                                   # ¿qué hay?
curl $H "$C/api/workitems/backend"                           # funcionalidades del backend
curl $H "$C/api/workitems/backend?recursive=1"               # todos los ficheros, para analizar
curl $H "$C/api/workitems/backend/login/spec.md"             # leer un documento
curl $H -T informe.md "$C/api/workitems/backend/login/informe.md"          # subir
curl $H -T informe.md "$C/api/workitems/backend/login/informe.md?overwrite=1"   # sustituir
```

- `path` de cada entrada se puede pegar tal cual tras `/api/workitems/<agente>/`.
- Subir **no sustituye** por defecto: si existe, `409`; añade `?overwrite=1`.
- No hay borrado. Máximo 50 MiB por fichero (`CONSOLE_MAX_UPLOAD_MB`).
- Las carpetas también se crean automáticamente al subir un fichero en una ruta nueva; usa `POST` para crear una carpeta vacía desde la API o el botón **Nueva carpeta** de la web. Si ya existe, devuelve `409`.
- HTML, SVG y JS se devuelven como `text/plain`; las imágenes con su tipo real.

## Skills y AGENTS.md

El contexto de equipo que vive en el repositorio (`agents/`) y que el compose monta en los
agentes. Pensado para que un agente **revise y mejore** skills y `AGENTS.md`. Cada ámbito
(`<agente>` o `shared`) tiene una raíz virtual con:

| Ámbito | `AGENTS.md` | `skills/` |
|---|---|---|
| `manager`, `devops`, `cypress` | `agents/<rol>/AGENTS.md` | skills propios de ese rol |
| `backend` | `AGENTS.<BACKEND_STACK>.md` | skills propios de backend |
| `frontend` | `AGENTS.<FRONTEND_STACK>.md` | skills propios de frontend |
| `shared` | — | skills genéricos, de todo el equipo |

El nombre `AGENTS.md` es siempre el mismo en la API; la consola lo traduce al fichero del
stack activo (por ejemplo `AGENTS.kotlin.md`). La respuesta de `GET /api/skills` dice cuál es
en `agents_md`.

| Petición | Resultado |
|---|---|
| `GET /api/skills` | `{"scopes":[{"scope","exists","items","agents_md","agents_md_exists"}]}` (`items` = nº de skills). |
| `GET /api/skills/<ámbito>` | Raíz virtual: `AGENTS.md` y `skills/`. |
| `GET /api/skills/<ámbito>?recursive=1` | Todos los ficheros de ese ámbito, en plano. |
| `GET /api/skills/<ámbito>/skills/<skill>/SKILL.md` | Contenido del fichero. |
| `PUT /api/skills/<ámbito>/<ruta>` | Crea o **sustituye** un fichero. |
| `POST /api/skills/<ámbito>/<ruta-directorio>` | Crea una carpeta y los directorios padres que falten. |

```bash
curl $H "$C/api/skills"                                          # panorama
curl $H "$C/api/skills/backend?recursive=1"                      # todo lo del backend
curl $H "$C/api/skills/backend/AGENTS.md"                        # su contexto de equipo
curl $H "$C/api/skills/shared/skills/revision/SKILL.md"          # un skill genérico
curl $H -T SKILL.md "$C/api/skills/backend/skills/revision/SKILL.md"   # crear/mejorar un skill
curl $H -T AGENTS.md "$C/api/skills/devops/AGENTS.md"            # reescribir su AGENTS.md
curl -X POST "$C/api/skills/backend/skills/nuevo-skill"         # crear carpeta
```

- También puedes crear carpetas vacías con `POST` o con el botón **Nueva carpeta** en la web;
  los directorios padres que falten se crean automáticamente. Si la ruta ya existe, devuelve `409`.
- A diferencia de workitems, **`PUT` sustituye por defecto** (`?overwrite=0` lo impide). Los
  ficheros están en git, así que se pueden revertir con `git checkout`.
- Solo existen `AGENTS.md` y `skills/` en cada ámbito. Extensiones, scripts de arranque y el
  resto de `agents/` no son accesibles (`404`).
- Máximo 2 MiB por fichero. No hay borrado.
- **Un skill o `AGENTS.md` es el prompt de un agente.** Escribir aquí cambia cómo se comporta;
  el agente lo ve en su siguiente `/reload` o reinicio.
- Un skill es una carpeta con un `SKILL.md` (cabecera YAML con `name` y `description`,
  después las instrucciones).

## Documentación compartida

`./docs/` del repositorio, el mismo directorio que los agentes ven montado como `/docs`. La API
expone directamente su raíz en `/api/docs` (sin ámbito de agente):

| Petición | Resultado |
|---|---|
| `GET /api/docs` | Lista la raíz de `docs/`. |
| `GET /api/docs/<ruta>` | Lista una carpeta o devuelve el contenido de un fichero. `?recursive=1` aplana el árbol. |
| `PUT /api/docs/<ruta>` | Crea un fichero; crea los directorios padres que falten. Si ya existe, añade `?overwrite=1` para sustituirlo. |
| `POST /api/docs/<ruta-directorio>` | Crea una carpeta (y los directorios padres que falten). Devuelve `201`; si ya existe, `409`. |

```bash
curl $H "$C/api/docs"                                         # índice de la documentación
curl $H "$C/api/docs/console.md"                              # leer un documento
curl $H -T nueva-guia.md "$C/api/docs/guia/nueva-guia.md"      # subir, creando guia/ si falta
curl -X POST "$C/api/docs/guia/referencias"                    # crear una carpeta vacía
```

La pestaña **Docs** ofrece el mismo explorador que Workitems y Skills: vista previa, edición de
texto, subida y creación explícita de carpetas. La subida no sustituye un fichero existente por
defecto (`?overwrite=1` lo permite). Los cambios se escriben directamente en el
repositorio y los agentes los ven en `/docs`. El límite de subida es `CONSOLE_MAX_UPLOAD_MB`
(50 MiB por defecto); no hay borrado.

## Costes

Gasto en LLM leído de `cost-tracking/`. Para análisis, usa **`/api/costs`**.

`GET /api/costs` — parámetros (todos opcionales):

| Parámetro | Significado |
|---|---|
| `from`, `to` | Fechas `AAAA-MM-DD`, inclusivas, en la zona horaria de la consola. Sin ellas, todo el histórico. |
| `agent` | Solo ese agente. |
| `model` | Solo modelos cuyo nombre contenga esa subcadena (sin distinguir mayúsculas), p. ej. `opus`. |
| `by` | Granularidad de `series`: `day` (por defecto) o `hour`. |

```bash
curl $H "$C/api/costs"                                              # todo el histórico
curl $H "$C/api/costs?from=2026-10-01&to=2026-10-31"                # un mes
curl $H "$C/api/costs?agent=backend&from=2026-10-27&to=2026-10-27&by=hour"   # un agente, un día, por horas
curl $H "$C/api/costs?model=opus"                                   # cuánto se gasta en un modelo
```

Respuesta (`cost` en la moneda que reporte el proveedor, normalmente USD; `tokens` suma
entrada, salida y caché; `calls` = nº de llamadas al modelo):

```json
{
  "from": null, "to": null, "agent": null, "model": null, "by": "day",
  "total": {"cost": 1.75, "tokens": 330, "calls": 3},
  "by_agent": {"backend": {"cost": 1.5, "tokens": 220, "calls": 2}},
  "by_model": {"github-copilot/gpt-5.4": {"cost": 0.5, "tokens": 110, "calls": 1}},
  "by_agent_model": {"backend": {"github-copilot/gpt-5.4": {"cost": 0.5, "tokens": 110, "calls": 1}}},
  "series": [{"bucket": "2026-10-26", "cost": 1.25, "tokens": 220, "calls": 2,
              "by_agent": {"manager": 0.25, "backend": 1.0}}]
}
```

Solo aparecen agentes y modelos con actividad en la ventana. Un filtro inválido da `400`.

Otros dos endpoints existen para la gráfica de la web y no son cómodos para analizar:
`GET /api/consumption?range=day|week` (o `from`/`to`) devuelve series alineadas para dibujar,
y `GET /api/bounds` la primera y última fecha con datos (`{"min","max","empty"}`) — útil para
saber qué rango tiene sentido preguntar.

## Sistema

| Petición | Resultado |
|---|---|
| `GET /api/health` | Estado de la consola: prefijo del cluster, si hay Docker, contenedores, nº de eventos, avisos y jobs. Sirve de comprobación rápida. |
| `GET /api/system` | Contenedores del cluster (rol, estado, imagen, puertos), red, y el **roster de pi-link** con el estado de cada agente (inactivo, pensando, ejecutando una herramienta, contexto consumido). |
| `GET /api/system/stats` | CPU y memoria por contenedor. |
| `GET /api/system/disk` | Uso de disco: imágenes, volúmenes, contenedores. |

```bash
curl $H "$C/api/system" | jq '.link'      # ¿qué está haciendo cada agente ahora?
```

## Actividad (eventos)

Quién habló con quién por pi-link. **Solo metadatos** (emisor, receptor, hora, tamaño): el
texto de los mensajes nunca se guarda. También registra el uso de skills (`skill.used`).
Un evento: `{"id","ts","type","agent","peer","payload"}`.

| Petición | Resultado |
|---|---|
| `GET /api/events` | `{"events":[…]}` más recientes primero. Filtros: `agent` (como emisor **o** receptor), `type` (prefijo, p. ej. `link.` o `skill.`), `since`/`until` (ms), `limit` (máx. 1000, por defecto 200). |
| `GET /api/events/pulse?since=<ms>` | Lo ocurrido desde `since` en orden cronológico, con `cursor` para la siguiente consulta. Pensado para sondeo. |
| `GET /api/events/graph?window_ms=3600000` | Aristas emisor→receptor agregadas en la ventana. |
| `GET /api/events/stats` | Total, primero/último, recuento por tipo y retención. |
| `POST /api/events` | Ingesta: un objeto o una lista (máx. 100) con `type` y `agent` obligatorios. Lo usa la extensión `team-console`; devuelve `202`. |
| `DELETE /api/events?before=<ms>&agent=…&type=…` | Borrado manual. Exige al menos un filtro. |

```bash
curl $H "$C/api/events?type=skill.&limit=50"            # qué skills se están usando
curl $H "$C/api/events?agent=backend&since=$(( ($(date +%s)-3600)*1000 ))"   # última hora
```

## Avisos a un agente (inbox)

Dejar un mensaje a un agente. Lo recibe **aunque esté inactivo** (arranca un turno), porque
la extensión del agente recoge su cola.

| Petición | Resultado |
|---|---|
| `POST /api/link/send` `{"to","content","job"?,"id"?}` | Encola un aviso (`202`). `content` ≤ 8000 caracteres. Con `id`, el reintento es idempotente: no se entrega dos veces. |
| `GET /api/inbox[?agent=<a>]` | Avisos pendientes (sin el texto, solo tamaño y estado). |
| `POST /api/inbox/take` `{"agent"}` | Lo que recoge el agente (cambia estado: marca entregado). Uso de la extensión. |
| `POST /api/inbox/<id>/ack` | Confirma la entrega. Uso de la extensión. |

```bash
curl $H -X POST "$C/api/link/send" -H 'Content-Type: application/json' \
     -d '{"to":"manager","content":"Revisa los tickets abiertos de hoy","id":"tickets-2026-10-27"}'
```

Los avisos caducan sin entregar pasadas `CONSOLE_INBOX_TTL_HOURS` (24 por defecto).

## Avisos al humano

`POST /api/human-notify` `{"agent","content"}` (`content` ≤ 500 caracteres) → `202`. La
persona lo ve como notificación del navegador si tiene la consola abierta y los avisos
activados. Para algo que requiere atención humana, no para el flujo entre agentes.
`GET /api/human-notify?since=<ms>` devuelve los avisos desde `since` y un `cursor`.

## Cron

Programa **scripts del catálogo** (los `.py` de `tmp/scripts/`; no hay comando libre). Hora
local de la consola. Expresión cron de 5 campos (`min hora díaMes mes díaSemana`; admite `*`,
`a-b`, `*/n`, listas).

| Petición | Resultado |
|---|---|
| `GET /api/cron/scripts` | Scripts disponibles con su descripción. |
| `GET /api/cron/jobs` | Programaciones y estadísticas. |
| `POST /api/cron/jobs` `{"name","schedule","script","args"?,"enabled"?,"timeout_s"?}` | Crea (`201`). `args`: lista de cadenas; `timeout_s` 1–3600 (300 por defecto). |
| `POST /api/cron/jobs/<id>` (mismo cuerpo, parcial) | Modifica. |
| `DELETE /api/cron/jobs/<id>` | Elimina. |
| `POST /api/cron/jobs/<id>/run` | Ejecuta ya (en segundo plano). |
| `GET /api/cron/jobs/<id>/runs` · `GET /api/cron/runs?limit=` | Historial. |
| `GET /api/cron/runs/<runId>` | Una ejecución con su salida completa. |
| `GET /api/cron/state?job=<nombre>` · `POST /api/cron/state` `{"job","key","value"}` | Estado clave/valor que un script conserva entre ejecuciones (`value: null` lo borra). |

```bash
curl $H -X POST "$C/api/cron/jobs" -H 'Content-Type: application/json' \
     -d '{"name":"tickets","schedule":"0 20 * * 1-5","script":"tickets.py"}'
```

## Tmux

Lee lo que se ve en pantalla en la sesión de `pi` de un agente (solo lectura).

| Petición | Resultado |
|---|---|
| `GET /api/tmux/panes` | Agentes disponibles y si la terminal interactiva está habilitada. |
| `GET /api/tmux/panes/<agente>?lines=60&colors=0` | Contenido actual (`lines` 5–400). `colors=0` quita los códigos ANSI: úsalo si vas a leerlo un agente. |

```bash
curl $H "$C/api/tmux/panes/backend?lines=80&colors=0"   # ¿en qué está el backend?
```

Escribir en una terminal de un agente solo se puede desde la web (WebSocket, requiere
`CONSOLE_TOKEN`); no forma parte de esta API.

## Receta: un agente que mejora skills

1. `GET /api/skills` para ver ámbitos y `AGENTS.md` activos.
2. `GET /api/skills/<ámbito>?recursive=1` y leer cada fichero con `GET /api/skills/<ámbito>/<path>`.
3. Cruzar con uso real: `GET /api/events?type=skill.used` (qué skills se invocan y quién).
4. Cruzar con coste: `GET /api/costs?agent=<a>` para ver dónde se gasta.
5. Proponer el cambio y aplicarlo con `PUT /api/skills/<ámbito>/<path>`; el humano lo revisa con
   `git diff` en el repositorio.
