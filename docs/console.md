# The console

Detail of the web console. Overview and how to open it: [README](../README.md#the-console).

A web console for the team, on **http://localhost:4070**. It's the sixth service in
`docker-compose.yml`, so `python setup.py --start` brings it up with everything else — there's
nothing separate to launch.

```bash
python setup.py --console            # opens this cluster's console in the browser
python setup.py --logs console       # its logs, like any other container
```

It is **not** an agent: no `pi`, no tmux session, no repository of its own, and it does not
register on the pi-link mesh. It observes, it schedules scripts, and — only with a
`CONSOLE_TOKEN`, and only when you ask — it opens a real terminal into one agent.

## The five tabs

| Tab | What it's for |
|---|---|
| **Sistema** | What exists and what's alive: containers with uptime, CPU/memory, image and ports; what's attached to `team-net` (including the siblings `devops` starts); disk usage per volume; and each agent's live state — idle, thinking, running a tool, context consumed — read from the pi-link hub's own `GET /status`, which needs no registration. |
| **Actividad** | Who talks to whom. Each message lights the edge between two agents and fades over ~10 s, a dot travels from sender to recipient, and the list below shows one line per message with how long delivery took. |
| **Costes** | The LLM cost dashboard: total and per agent, over time, by model. Same data as [LLM cost tracking](../README.md#llm-cost-tracking) below, read from `cost-tracking/`. |
| **Cron** | Schedules the team's scripts (below), with history, full output of each run, "run now", and the notices still waiting to be delivered to an agent. |
| **Tmux** | The five agents' panes side by side, **read-only**, refreshed every 5 s. Click one to enlarge it; **Escribir** turns it into a real terminal you can type in (needs `CONSOLE_TOKEN`, see [below](#typing-into-an-agent-tmux-tab)). The `attach` button still copies the `docker exec` command for a terminal of your own. |

## Typing into an agent (Tmux tab)

The mosaic is read-only on purpose: watching five agents at once is cheap, typing into five at
once is not. To act on one, click it and press **Escribir**: the modal becomes a real terminal
([xterm.js](https://xtermjs.org)) attached to that agent's `pi` session, with a red border and
an `ESCRITURA ACTIVA` badge so you can't mistake it for the read-only view. **Solo lectura**,
**Cerrar**, or `Ctrl-b d` bring you back.

```
browser (xterm.js) ──WebSocket──▶ console ──docker.sock, exec with TTY──▶ tmux attach -t pi
```

It is `docker exec -it <container> tmux attach -t pi`, with the browser as the terminal. The
console copies bytes both ways without reading them, and nothing is installed in the agents'
images. Details in [`ARCHITECTURE.md`](../ARCHITECTURE.md#the-tmux-terminal).

**It requires `CONSOLE_TOKEN`.** Typing into an agent means running commands in a container
that holds its own credentials, so without a token the button is disabled and says why — even
with the port on loopback, because a browser lets *any* web page you visit open a WebSocket to
`127.0.0.1` (WebSockets are not subject to CORS). Set the token in `.env`, recreate the console
(`python setup.py --update console`), and open the console **once** with
`http://localhost:4070/?token=<your token>`: that leaves a cookie and the token is not needed
again. On top of the token, the WebSocket only opens from the console's own origin, the
command is fixed by the server (the browser only picks *which agent*, among the containers the
console already lists), at most 5 terminals can be open at once, and every open/close is
logged (`python setup.py --logs console`): which agent, from where and for how long, never
the content.

Some things behave differently from a terminal of your own:

- **`Esc` and `Ctrl+C` go to the agent** (`pi` uses them), so `Esc` does not close the modal
  while the terminal is open. `Ctrl+C` copies instead when you have a selection (and clears
  it, so the next one interrupts). With tmux's mouse mode on, select with **Shift+drag**
  (**Option+drag** on macOS).
- **The size is the tmux window's, not the browser's.** The terminal opens at exactly the
  window's size (220×50 by default) and the font shrinks to fit it, down to a minimum, then
  scrolls. Matching it exactly is what keeps the mosaic and anyone attached from a terminal of
  their own from seeing the window change every time you open one.
- **If someone is attached at the same time you both type into the same session.** That is
  how tmux works, not something the console adds.
- xterm.js is loaded from a CDN (with an integrity hash), like Chart.js: the browser needs
  network access the first time you press **Escribir**.

## What it records, and what it deliberately doesn't

Each agent carries one extra pi extension (`agents/_shared/pi/extensions/team-console`,
mounted into all five) that reports every message the agent sends or receives over pi-link.
What's stored is **only metadata** — sender, recipient, timestamp, size. Never the text:
fragments of the projects the agents work on travel over that mesh, and none of it belongs in
an observability database. The console enforces that at the boundary, dropping any field that
looks like it carries text, so a future emitter cannot smuggle a conversation in by accident.

If the console is down the agents do not notice: the extension queues events with a bounded
buffer, a short timeout and backoff, and delivers them when it comes back.

## Team skills

`pi` can create [skills](https://agentskills.io/specification) for itself on the fly, and
discovers them from two places with no configuration needed, each mounted from its own
directory so they stay versioned in this repo:

| Where it lives | Mounted at | Who sees it |
|---|---|---|
| `agents/<role>/pi/skills/` | `~/.pi/agent/skills` | Only that role — where a skill is born, scoped to whoever identified the need for it. |
| `agents/_shared/pi/skills/` | `~/.agents/skills` (read-only) | All five roles in this cluster. |

Promoting a skill from one to the other is a plain `git mv` — nothing to restart: both paths
are live bind mounts, so a skill that lands in `_shared` becomes visible to the rest of the
team the moment the directory exists, picked up on that agent's next `/reload` (or its next
restart). Sharing a skill with *another* `team` cluster on the same machine is the same idea
one level up — copy it into whatever directory that cluster's own `_shared/pi/skills/` points
at — not something this repo automates on its own.

Every use of a skill — the name only, nothing of what the agent does with it — becomes a
`skill.used` event through the same `team-console` extension and the same `/api/events`
pipeline described above, so it shows up in **Actividad** like any other traffic
(`GET /api/events?type=skill.` to see just these). Caught two ways: `/skill:name` typed
explicitly, and `pi` loading a `SKILL.md` on its own initiative (progressive disclosure) —
either counts.

## Scheduled scripts (Cron tab)

The scripts are **yours, not this project's** — they live in `tmp/scripts/`, which is not
versioned, and are mounted read-only into the console. The web schedules what's in that
catalog; there is no free-form command field, which is what keeps a console without
authentication from meaning arbitrary execution for anyone who reaches the port.

They're Python, and they get an API to talk to the team — `notify()`, `state`, `ado.query()`,
`log()` — documented with a full example in [`console/sdk/README.md`](../console/sdk/README.md).
The case that motivated it: at 20:00 on weekdays, query ADO for the manager's open tickets and
tell it about them. The manager receives it as a message and starts a turn even if it was
idle, because delivery goes through the same mechanism pi-link uses — the console leaves the
notice in a queue and that agent's extension injects it.

Schedules are evaluated in the **container's** timezone (`TZ`, `Europe/Madrid` by default);
the times you see in the page are drawn in your browser's. The Cron tab states which one it's
scheduling in.

## Configuration

Only `CONSOLE_ADO_PAT` is asked by `python setup.py --init` (it's a secret). The rest have
defaults in `docker-compose.yml` and are only needed if you want to change them — add them to
your `.env`:

| Variable | Default | What it does |
|---|---|---|
| `CONSOLE_PORT` | `4070` | Host port. Give each cluster its own if you run several `docker compose` of team on one machine. |
| `CONSOLE_BIND` | `127.0.0.1` | Host interface. Same criterion as `BACKEND_VNC_BIND`; see the warning below before opening it up. |
| `CONSOLE_TOKEN` | *(empty)* | Empty means no authentication. With a value, it's required on every request (`X-Console-Token` header, cookie, or `?token=` once from the browser). **It's also what enables typing into an agent** (see [above](#typing-into-an-agent-tmux-tab)): without it that terminal is disabled. |
| `CONSOLE_SCRIPTS_DIR` | `./tmp/scripts` | Where the cron's scripts are. |
| `CONSOLE_EVENT_RETENTION_DAYS` | `30` | How long message metadata is kept (~80 bytes each). |
| `CONSOLE_INBOX_TTL_HOURS` | `24` | How long an undelivered notice waits for its agent. |
| `CONSOLE_AZ_CLI` | `true` | `false` builds the image without az CLI (830 MB → 222 MB); only the scripts that query ADO need it. |
| `TZ` | `Europe/Madrid` | Timezone the cron thinks in. |

## Publishing it, and several clusters on one machine

By default the port is published on `127.0.0.1` only, so the console is reachable from the
machine running Docker and nowhere else. To reach it from elsewhere, either set
`CONSOLE_BIND=0.0.0.0` in `.env`, or forward it on demand without recreating anything:

```bash
python setup.py --console-publish 0.0.0.0:8080   # temporary forwarder container
python setup.py --console-unpublish
```

With **several clusters of team on the same machine**, give each one its own `CONSOLE_PORT`
(4070, 4071, …) alongside its `CONTAINER_PREFIX`; otherwise the second `docker compose up`
fails because the port is taken. `python setup.py --console` asks Compose where *this*
cluster's console is published, so it always opens the right one.

> **Security, stated plainly.** The console mounts the host's Docker socket — that's what
> makes the container inventory, the network, the disk usage, the tmux panes and the terminal
> possible — and
> that is root-level control of the host, the same trade-off already accepted for `devops`
> (see [`ARCHITECTURE.md`](../ARCHITECTURE.md)). The difference is that here there's a web in
> front. That's why the port is on loopback by default, why the cron can only run scripts you
> placed in the catalog, why typing into an agent requires `CONSOLE_TOKEN`, and why publishing
> it elsewhere without setting one prints a warning at startup.

## Without Docker

`python setup.py --console-local [PORT]` runs only the cost view on the host, reading a
`cost-tracking/` folder from disk (`--cost-dir` to point it at an export from another run).
Everything else — containers, events, cron, tmux — lives in the container.

## Checking it still works

`console/tests/` holds a browser test that drives the real console and fails on any uncaught
page error. It reuses the `cypress` image, adds no dependency, and seeds and cleans up its own
data, so it can run against a working team — see [`console/tests/README.md`](../console/tests/README.md).
