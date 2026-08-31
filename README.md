# team-pi

Docker Compose infrastructure that spins up a **team of 5 [pi](https://pi.dev) agents**
(`@earendil-works/pi-coding-agent`), each in its own container with its own role,
coordinating with each other in real time through **[pi-link](https://pi.dev/packages/pi-link)**.

## Goal

Simulate a software development team made of specialized autonomous agents:

| Role | Container | Responsibility |
|---|---|---|
| **manager** | `pi-manager` | Coordinates the team, breaks down and prioritizes tasks, synthesizes results, main point of contact for the human in charge. |
| **backend** | `pi-backend` | Backend service/API development (stack TBD). |
| **frontend** | `pi-frontend` | User interface development (stack TBD, likely Angular). |
| **devops** | `pi-devops` | Infrastructure, CI/CD, deployment and observability — including this very infrastructure. |
| **cypress** | `pi-cypress` | End-to-end testing of backend + frontend together. |

Each agent has its own plugin/package configuration and its own team context
(`AGENTS.md`), and they all talk to each other by prompt via pi-link, with no human in the
communication loop.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  pi-manager │     │  pi-backend │     │ pi-frontend │     │  pi-devops  │     │  pi-cypress │
│             │     │             │     │             │     │             │     │             │
│  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │     │  pi + tmux  │
│  + broker   │     │  + broker   │     │  + broker   │     │  + broker   │     │  + broker   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │                   │
       └───────────────────┴─────────┬─────────┴───────────────────┴───────────────────┘
                                      │  regular docker-compose bridge network
                                      │  (each container keeps its own IP and ports)
                                      ▼
                    shared "pi-link-coord" volume (hub election via flock)
```

Every container is independent at the network level — there is no "special" container at
the infrastructure level. The 3 components running inside each one:

- **`pi`** — the agent itself, inside a **persistent tmux session** (stays alive even if
  nobody is connected; auto-relaunches if it crashes).
- **`pi-link`** (pi extension) — the communication channel between agents. It only ever
  talks to `127.0.0.1:9900` (hardcoded, no auth, loopback-only — see
  [pi-link docs](https://github.com/alvivar/pi-link)).
- **`pi-link-broker.sh`** — a script of this project that solves the problem of `pi-link`
  being tied to loopback: it lets 5 network-independent containers discover each other all
  the same, with automatic failover. See below.

### How the 5 agents connect without sharing a network

`pi-link` uses a fixed hub-spoke topology on `127.0.0.1:9900`: the first one to start acts as
the hub (WebSocket server) and the rest connect as clients. That works out of the box on a
single machine with several terminals, but not across containers with different IPs — and
the port isn't configurable via environment variable, flag, or config file.

Instead of merging the network of all 5 containers (which would blow up any port each stack
needs on its own — 8080, 4200, etc. — by sharing it across all 5), every container runs a
**broker** (`docker/pi-link-broker.sh`) that:

1. Competes for an exclusive, non-blocking **`flock`** on a file in the shared
   `pi-link-coord` volume. Whoever gets it becomes the hub; the lock is released
   automatically (at the host kernel level) if that container dies, so the rest compete for
   the role again on their own.
2. **The hub container** exposes its `127.0.0.1:9900` (where `pi-link` has actually bound)
   to the rest of the network on a port of its own for this mesh, `0.0.0.0:9901`, via
   `socat`.
3. **The rest (spokes)** keep a local `socat` relay forwarding their own `127.0.0.1:9900`
   to `<hub>:9901`.

`pi-link` never knows any of this exists — it only ever sees its local `127.0.0.1:9900`
working or not, and reacts with its own reconnection logic (2-5s randomized backoff). If the
hub container dies, the rest reconnect on their own, following pi-link's own procedure,
without any external script ever telling the `pi` process anything directly.

## Documentation

- [`docs/introduction.md`](docs/introduction.md) — a human-oriented introduction to the
  team, written for someone joining the project (what this is, who's on the team, how to
  work with it).
- [`docs/work-procedures.md`](docs/work-procedures.md) — the detailed workflow: the eight
  stages a piece of work moves through, each role's objectives, and exactly what changes in
  Azure DevOps and in each role's own `workitems/` folder along the way.

## Folder structure

```
.
├── docker-compose.yml
├── .env.example              # copy to .env — ANTHROPIC_API_KEY is optional (see Authentication)
├── docs/
│   ├── introduction.md         # human-oriented intro to the team
│   └── work-procedures.md      # detailed workflow: stages, roles, ADO/local workitem changes
├── docker/
│   ├── Dockerfile.pi           # base image: manager, backend, frontend, devops
│   ├── Dockerfile.cypress      # variant on top of cypress/included (TODO: pin version)
│   ├── entrypoint.sh           # installs pi packages, starts broker + tmux session, watchdogs
│   ├── pi-link-broker.sh       # hub election (flock) + socat relays (see Architecture)
│   └── generate-tmux-conf.sh   # generates /etc/tmux.conf at build time (colors + extended-keys)
├── agents/
│   └── <role>/
│       ├── AGENTS.md           # team context: who this agent is, who the rest of the team is
│       └── pi/                 # mounted at /workspace/.pi in the container
│           └── extensions/     # local pi extensions specific to this role
└── workspace/
    └── <role>/                  # source code for that role, mounted at /workspace in the container
        └── workitems/           # created by the agent itself inside its own project (private to
                                  # this role, not shared — see docs/work-procedures.md)
```

`<role>` is one of: `manager`, `backend`, `frontend`, `devops`, `cypress`.

## Requirements

- Docker and Docker Compose v2 (`docker compose ...`, not `docker-compose`).
- Python 3 (stdlib only) to run `setup.py` — works the same on Windows and Linux.
- A machine with internet access for the build (pulls the base Node/Cypress image and
  installs `pi` and `pi-link` via npm).

## Getting started

```bash
python setup.py --init    # interactively builds .env from .env.example (Enter keeps the default)
python setup.py --start   # docker compose up -d --build
```

## Configuration (`.env`)

`setup.py --init` walks through every variable in `.env.example`, proposing its value as
the default (Enter accepts it); it writes the result to `.env` (backing up any existing one
to `.env.bak` first). You can also skip it and copy/edit `.env.example` by hand. Variables:

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Optional — see [Authentication](#authentication) below. |
| `CONTAINER_PREFIX` | Prefix for the 5 container names (default `pi`, i.e. `pi-manager`, ...). Change it to run several instances of this project on the same machine without name clashes. |
| `<ROLE>_REPO_URL` | Git remote (origin) URL for that role's real repository — SSH or HTTPS. Exposed inside each container as `REPO_URL`. Empty until each role's repo/stack is decided. |
| `ADO_ORGANIZATION_URL`, `ADO_PROJECT` | Shared Azure DevOps organization/project (see `docs/work-procedures.md`). Exposed as-is inside every container, ready for `az devops configure --defaults organization=$ADO_ORGANIZATION_URL project=$ADO_PROJECT`. |

To rebuild after changing any Dockerfile/script and pick up the changes without losing
existing sessions or logins:

```bash
python setup.py --start   # same as docker compose up -d --build
```

To stop the 5 containers without touching their volumes (each agent's login/state is kept
for next time):

```bash
python setup.py --stop   # same as docker compose down
```

> **Do not run `docker compose down -v` / `--volumes`** unless you actually want to wipe the
> volumes holding each agent's login and state — there's no undo.

## Authentication

`ANTHROPIC_API_KEY` isn't required to start. If you leave it empty in `.env`, the first time
you connect to each agent's session you run `/login` interactively and pick whichever
provider you want; it's persisted in that agent's volume (`/root/.pi/agent`), so it's only
needed once per container.

## Connecting to an agent

Each agent runs in a persistent tmux session (stays alive even with nobody connected).
`setup.py` resolves the right container for a role via `docker compose ps -q <role>`, so
these work regardless of `CONTAINER_PREFIX`:

```bash
python setup.py --tmux <role>   # attach to the agent's persistent tmux session
python setup.py --bash <role>   # plain interactive bash shell in the container
python setup.py --logs <role>   # tail -f the last 100 lines of the container's logs
```

(equivalent to `docker exec -it pi-<role> tmux attach -t pi` / `docker exec -it pi-<role>
bash` / `docker logs --tail 100 -f pi-<role>`, if you'd rather run Docker directly.)

To detach from tmux **without killing the session**: `Ctrl-b` followed by `d` (tmux's
default prefix — untouched here). `Ctrl+D` inside `pi`, on the other hand, makes `pi` end
its own session (same as `bash` or a Python REPL); since it's the only process in that tmux
session, the session closes with it, and `entrypoint.sh`'s watchdog brings it back up within
~5s — the Docker container itself never restarts, only the `pi` process inside it.

## Remote VS Code

No special setup is needed in the images. If `docker compose` runs on a remote machine (e.g.
an EC2 instance): connect with **Remote-SSH** to that machine using your normal SSH access
to the instance, and once inside that remote window use the **Dev Containers → Attach to
Running Container** extension — it will see that machine's local Docker daemon normally.
Every container has a fixed `container_name` (`pi-manager`, `pi-backend`, ... — or
`${CONTAINER_PREFIX}-manager`, etc. if you changed `CONTAINER_PREFIX` in `.env`) to make it
easy to spot in the list.

## Plugins/packages per agent

Each service in `docker-compose.yml` has its own `PI_PACKAGES` variable (extra pi packages
installed via `pi install npm:...` / `git:...`, space-separated) and its own
`agents/<role>/pi/` folder, mounted at `/workspace/.pi` in the container (local project
extensions live under `agents/<role>/pi/extensions/`; other `.pi` configuration can go
alongside it as needed). `pi-link` is installed on all 5 since it's the shared communication
mechanism; the rest of each role's plugins/skills are managed independently.

## Team context (`AGENTS.md`)

`pi` automatically loads `AGENTS.md` from the working directory on startup. Each role has
its own at `agents/<role>/AGENTS.md`, mounted at `/workspace/AGENTS.md` in its container: it
explains that agent's role, who the rest of the team is, and how to talk to them via
pi-link (`link_list`, `link_send`, `link_prompt`, `link_compact`). Since it's a regular bind
mount, editing it from inside the session writes the change straight back into the repo —
nothing extra needed to persist it.

## Troubleshooting

**Broken special characters (`_` instead of accents/¡¿/ñ)** — the image sets
`LANG=LC_ALL=C.UTF-8` in the Dockerfile; if you see this after an image change, rebuild with
`python setup.py --start`.

**Colors/grays showing up as black inside tmux** — `docker/generate-tmux-conf.sh` generates
`/etc/tmux.conf` at build time with `default-terminal tmux-256color` + `terminal-overrides
",*:RGB"` to negotiate truecolor correctly. If it persists, the *client* terminal you're
running `python setup.py --tmux <role>` from is likely not advertising truecolor support.

**An agent doesn't show up on pi-link / `link_list` doesn't see it** — check in order:

```bash
python setup.py --logs <role>                          # did the broker start? hub or spoke?
docker exec pi-<role> cat /var/run/pi-link/hub.addr     # who is the mesh pointing at right now?
docker exec pi-<role> tmux capture-pane -t pi -p        # pi-link's on-screen status
```

(the last two are quick one-off commands, not worth a dedicated `setup.py` flag — or run
`python setup.py --bash <role>` and type them directly inside the container.)

## TODO

- **Tech stack per role** (backend Java/Python, frontend Angular, devops
  terraform/kubectl...) — once decided, `Dockerfile.pi` will be split into one per role with
  the matching toolchain (flagged with `TODO` in the file itself).
- **Headless Eclipse pi extension** for Java code management, pending integration once the
  backend stack is confirmed.
- **`cypress/included` version** — `Dockerfile.cypress` uses `latest` as a placeholder; pin
  it to the project's actual Cypress version.

## License

[MIT](LICENSE) © 2026 Xan
