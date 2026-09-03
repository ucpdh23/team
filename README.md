# team-pi

Docker Compose infrastructure that implements a **software development team built on AI
agents**: 5 [pi](https://pi.dev) agents (`@earendil-works/pi-coding-agent`), each in its own
container with its own role, coordinating with each other in real time through
**[pi-link](https://pi.dev/packages/pi-link)**. This isn't a simulation of a team — it's a
working one, meant to own real deliverables end to end.

## Goal

Create a 5-role system to handle development activities. 5 members as a small size group, where
**each role knows exactly what it owns, what it works on, and how it's expected to coordinate with the rest**.

- **Specialization, not imitation** — the split isn't about mirroring how human teams happen
  to be organized. One agent covering backend, frontend, infra and tests at once drowns in
  context that isn't its own and can only push on one front at a time. A focused role keeps
  each agent's context to what that role actually needs, and lets all five make progress in
  parallel.
- **Boundaries are structural** — each role gets its own container, its own technological
  independence and its own capabilities (repo, credentials, extensions — see
  [`ARCHITECTURE.md`](ARCHITECTURE.md)), enforced by the infrastructure itself rather than
  just described in an `AGENTS.md`. It's also why the model fits projects where backend and
  frontend already live in separate, technologically independent repositories: each role
  works only inside its own.
- **Independent verification** — `cypress` runs end-to-end tests as a role of its own, so
  integration correctness isn't self-certified by whoever built the feature. That doesn't
  replace `backend`'s/`frontend`'s own unit and integration testing — it adds a check neither
  of them can skip on their own.
- **Scales without a redesign** — a second backend, a new specialty: one more
  container/repo/`AGENTS.md` on the same pattern. `manager` stays responsible for
  distributing work across however many roles actually exist.

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

Every container is independent at the network level — there's no "special" container at the
infrastructure level, and every one runs the same 3 components (`pi` in a persistent tmux
session, `pi-link`, and a broker script that gives the 5 of them a shared mesh without
sharing a network). All 5 also share one explicit Docker network (`team-net`), and `devops`
can start further sibling containers on it (Docker-outside-of-Docker) — e.g. a database
`backend` needs during development, reachable by its container name on that same network.
Full technical detail — the topology diagram, how the hub-election/broker mechanism works,
the DooD setup, and how `backend`'s headless Eclipse (`jdtbridge`) is wired up — lives in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — technical detail: the pi-link mesh/broker
  mechanism, and how `backend`'s headless Eclipse (`jdtbridge`) is wired up.
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
├── README.md                    # this file: what/why, and the commands to run it
├── ARCHITECTURE.md              # technical detail: pi-link mesh, backend's headless Eclipse
├── docs/                        # mounted read-write at /docs in every container (not /workspace)
│   ├── introduction.md         # human-oriented intro to the team
│   └── work-procedures.md      # detailed workflow: stages, roles, ADO/local workitem changes
├── cost-tracking/
│   └── <role>/                  # mounted at ~/.pi/cost-tracker in that role's container — see
│                                 # "LLM cost tracking" below
├── docker/
│   ├── Dockerfile.pi           # base image: manager, frontend (backend/devops have their own)
│   ├── Dockerfile.backend      # backend image: Java/Maven toolchain + headless Eclipse/jdtbridge
│   ├── Dockerfile.devops       # devops image: adds Docker CLI (Docker-outside-of-Docker, see ARCHITECTURE.md)
│   ├── Dockerfile.cypress      # variant on top of cypress/included (TODO: pin version)
│   ├── entrypoint.sh           # installs pi packages, starts broker + tmux session, watchdogs
│   ├── pi-link-broker.sh       # hub election (flock) + socat relays (see ARCHITECTURE.md)
│   └── generate-tmux-conf.sh   # generates /etc/tmux.conf at build time (colors + extended-keys)
├── agents/
│   └── <role>/
│       ├── AGENTS.md           # team context, mounted at ~/.pi/agent/AGENTS.md (global for pi)
│       └── pi/
│           └── extensions/     # mounted at ~/.pi/agent/extensions in the container — global
│                                # pi extensions specific to this role (see "Plugins/packages
│                                # per agent" below)
```

There's no `workspace/` folder in this repo: `/workspace` inside each container is a named Docker
volume (`<role>-workspace`), not a bind mount to anything here — so it's guaranteed empty on first
run, with nothing of this project's ever leaking into it. `git clone $REPO_URL .` there (or let the
agent do it); the agent's own `workitems/` folder (see `docs/work-procedures.md`) ends up inside
that same volume, private to this role.

`<role>` is one of: `manager`, `backend`, `frontend`, `devops`, `cypress`.

## Requirements

- Docker and Docker Compose v2 (`docker compose ...`, not `docker-compose`).
- Python 3 (stdlib only) to run `setup.py` — works the same on Windows and Linux.
- A machine with internet access for the build (pulls the base Node/Cypress image and
  installs `pi` and `pi-link` via npm).

## Getting started

```bash
python setup.py --init      # interactively builds .env from .env.example (Enter keeps the default)
python setup.py --start     # docker compose up -d --build
python setup.py --git-clone # git clone each role's REPO_URL into its /workspace, if set
```

## Configuration (`.env`)

`setup.py --init` walks through every variable in `.env.example`, proposing its value as
the default (Enter accepts it); it writes the result to `.env` (backing up any existing one
to `.env.bak` first). You can also skip it and copy/edit `.env.example` by hand. Variables:

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Optional — see [Authentication](#authentication) below. |
| `CONTAINER_PREFIX` | Prefix for the 5 container names (default `pi`, i.e. `pi-manager`, ...). Change it to run several instances of this project on the same machine without name clashes. |
| `<ROLE>_REPO_URL` | Git remote (origin) URL for that role's real repository — SSH or HTTPS. Exposed inside each container as `REPO_URL`. Empty until each role's repo/stack is decided. `/workspace` is a named Docker volume (`<role>-workspace`), not a bind mount to this repo, so it's always empty on first run: `python setup.py --git-clone` clones it there for every role that has one set (or let the agent do it itself) without worrying about clashing with anything this project mounts — pi's own per-role state (`AGENTS.md`, extensions, login) lives entirely under `~/.pi/agent` instead, never under `/workspace`. |
| `<ROLE>_GIT_TOKEN` | Access token (PAT) for that role's `REPO_URL` when it's `https://` — scope it to just that one repo (GitHub fine-grained PAT, or an Azure DevOps PAT limited to `Code: Read & Write`). Exposed inside each container as `GIT_TOKEN`; `entrypoint.sh` wires it into a git credential helper that reads it from the environment at auth time, so it's never written to the remote URL or `.git/config`. Leave it empty and use an SSH `REPO_URL` instead if you'd rather set up SSH manually for a given role — the two don't conflict. |
| `ADO_ORGANIZATION_URL`, `ADO_PROJECT` | Shared Azure DevOps organization/project (see `docs/work-procedures.md`). Exposed as-is inside every container; `entrypoint.sh` runs `az devops configure --defaults organization=$ADO_ORGANIZATION_URL project=$ADO_PROJECT` automatically on every start, so `az boards`/`az repos` commands don't need `--organization`/`--project` in that role's session. |
| `<ROLE>_ADO_PAT` | Azure DevOps PAT for that role, used by `az boards`/`az repos` inside its container — see [Azure DevOps CLI authentication](#azure-devops-cli-authentication) below for exactly which scopes each role needs. Exposed inside each container as `ADO_PAT`; `entrypoint.sh` maps it to `AZURE_DEVOPS_EXT_PAT`, the environment variable az CLI's `azure-devops` extension reads automatically — no `az devops login` needed, and it's never written to disk. |
| `BACKEND_VNC_PASSWORD`, `BACKEND_VNC_PORT`, `BACKEND_VNC_BIND` | VNC/noVNC access to the `backend` container's headless Eclipse (see [Eclipse GUI access](#eclipse-gui-access-backend-via-novnc) below). Empty password = VNC disabled (default). Port defaults to `6080`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). |
| `FRONTEND_PORT`, `FRONTEND_BIND` | Access to the `frontend` container's dev server (see [Frontend dev server access](#frontend-dev-server-access) below). Same accessibility criteria as the backend VNC variables above: port defaults to `4200`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). |

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

## Azure DevOps CLI authentication

Each role authenticates its own `az boards`/`az repos` calls with its own PAT
(`<ROLE>_ADO_PAT` in `.env`, see [Configuration](#configuration-env) above) — same pattern as
git: `entrypoint.sh` exposes it to az CLI via `AZURE_DEVOPS_EXT_PAT`, so there's no
interactive `az devops login` and nothing is written to disk. All five get their own
variable even though, in practice, you may hand out the same PAT to more than one role
to start with — keeping them separate from day one costs nothing and means you can later
scope, rotate or revoke one role's access without touching the others.

Scopes are entirely up to you (Azure DevOps PATs are created and managed outside this
repo, in your own organization), but here's the minimum each role actually needs, based on
what it does per `docs/work-procedures.md` and its own `agents/<role>/AGENTS.md`:

| Role | Minimum PAT scope | Why |
|---|---|---|
| `manager` | **Work Items** — Read, Write, & Manage | Creates/links Tasks (`az boards work-item create`, `relation add`), moves the parent User Story/Bug through states, posts comments. Never opens PRs itself, so no Code scope needed. |
| `backend`, `frontend`, `devops` | **Work Items** — Read & Write | Moves its own Task(s) to Active/Closed as it works. Add **Code** — Read & Write only if that role's `REPO_URL` points at **Azure Repos** and it uses `az repos pr create` to open its PR (see the worked example in `docs/work-procedures.md`); not needed if that role's repo lives on GitHub (opens PRs with `gh` instead, already installed). |
| `cypress` | **Work Items** — Read & Write | Same as above, only if it keeps its own e2e Task in ADO (optional, see `agents/cypress/AGENTS.md`) — otherwise this PAT can be left empty. |

If a role's repo is on GitHub rather than Azure Repos, that role doesn't need Azure DevOps
Code access at all — its `<ROLE>_GIT_TOKEN` (a GitHub fine-grained PAT, see above) already
covers pushing code and opening PRs there via `gh`.

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

## Eclipse GUI access (backend, via noVNC)

The `backend` container runs a full headless Eclipse with the
[jdtbridge](https://github.com/kaluchi/jdtbridge) plugin, driven day-to-day by the agent
through the `jdt` CLI (how it's wired up — Xvfb, the `jdtls`/`jdtbridge` split — is in
[`ARCHITECTURE.md`](ARCHITECTURE.md#java-code-intelligence-in-backend-jdtbridge--headless-eclipse)).
Its GUI is still occasionally needed: to *import* a new project into Eclipse's workspace
(`jdtbridge` has no command for that — `File → Import → Existing Maven Projects`, for
example), or to get a real graphical Java debugger (breakpoints, variable inspection) rather
than just console output. For that, the same Xvfb display Eclipse already runs on is exposed
over VNC:

1. Set `BACKEND_VNC_PASSWORD` in `.env` (`python setup.py --init`, or edit it by hand — see
   `.env.example`). Leave it empty and nothing starts: `entrypoint.sh` refuses to run
   `x11vnc`/`websockify` without a password, so there's no unauthenticated VNC server by
   default.
2. `python setup.py --start` (or restart just `backend` after editing `.env`).
3. Open `http://127.0.0.1:${BACKEND_VNC_PORT:-6080}/vnc.html` in a browser (no VNC client
   needed) and enter the password. The port is only published on the host's loopback
   interface (`BACKEND_VNC_BIND`, default `127.0.0.1`) — if `docker compose` runs on a remote
   machine, reach it through an SSH tunnel (same pattern as [Remote VS
   Code](#remote-vs-code) above), not by changing this to a wider bind address.

**Running Docker inside WSL2** (not Docker Desktop's own VM, `dockerd` running directly
inside a WSL2 distro): `127.0.0.1` published there is often unreachable from Windows'
browser, because WSL2's automatic "localhost forwarding" into Windows arrives through the
distro's virtual network interface, not through loopback — and Docker's loopback-only
publish only accepts connections arriving on loopback itself. Fix: set `BACKEND_VNC_BIND=
0.0.0.0` in `.env` and restart `backend`; WSL2's forwarding does reach `0.0.0.0`-bound ports,
so `http://localhost:6080/vnc.html` from Windows then works with no other setup. This is
safe in the WSL2 case specifically because the distro's network is already NAT'd behind
Windows (nothing on your LAN can reach it) unless you've turned on WSL's "mirrored"
networking mode — and the VNC connection itself still requires `BACKEND_VNC_PASSWORD`
either way.

Once a project is imported this way, `jdt`/`jdtbridge` picks it up immediately — same running
Eclipse instance and workspace as the CLI. See
[`ARCHITECTURE.md`](ARCHITECTURE.md#java-code-intelligence-in-backend-jdtbridge--headless-eclipse)
for what noVNC does and doesn't show live; to watch the agent's own terminal in real time
instead, use `python setup.py --tmux backend`.

## Frontend dev server access

The `frontend` container publishes port `4200` (the conventional Angular CLI dev-server
port, `ng serve`'s default) to the host, so you can connect to whatever the agent has
running there from outside the container — same accessibility criteria as the backend VNC
setup above:

1. Port and bind are configurable via `FRONTEND_PORT`/`FRONTEND_BIND` in `.env` (defaults:
   `4200` and `127.0.0.1`) — no separate enable/disable switch here (unlike
   `BACKEND_VNC_PASSWORD`): a dev server isn't authenticated by itself either way, so
   there's no unauthenticated-by-default risk this port mapping newly introduces.
2. `python setup.py --start` (or restart just `frontend` after editing `.env`).
3. Open `http://127.0.0.1:${FRONTEND_PORT:-4200}` in a browser. The port is only published
   on the host's loopback interface by default (`FRONTEND_BIND`) — if `docker compose` runs
   on a remote machine, reach it through an SSH tunnel (same pattern as [Remote VS
   Code](#remote-vs-code) above), not by changing this to a wider bind address.

**The dev server itself must listen on `0.0.0.0` inside the container, not just
`localhost`/`127.0.0.1`** — Docker's port publishing forwards to the container's network
interface, not into its loopback namespace, so a server bound only to `127.0.0.1` *inside*
the container is unreachable from outside it no matter how the port is published on the
host. For Angular's CLI this means starting it with `ng serve --host 0.0.0.0` (the default,
`ng serve` alone, binds to `localhost` only and won't work here).

**Running Docker inside WSL2**: same fix and same reasoning as the backend VNC section above
— set `FRONTEND_BIND=0.0.0.0` in `.env` and restart `frontend` if `http://localhost:4200`
from Windows doesn't reach it.

## Plugins/packages per agent

Each service in `docker-compose.yml` has its own `PI_PACKAGES` variable (extra pi packages
installed via `pi install npm:...` / `git:...`, space-separated) and its own
`agents/<role>/pi/extensions/` folder, mounted at `~/.pi/agent/extensions` in the
container — global pi extensions for that role (not project-local: the same `~/.pi/agent`
named volume already holds that role's `AGENTS.md`, login and settings, so this is one more
file bind-mounted inside it, same pattern). `PI_PACKAGES` and this folder cover different
needs: `PI_PACKAGES` installs published packages by name/URL, this folder is for extensions
that live only in this repo and aren't published anywhere. `pi-link` and `pi-cost-counter`
(see below) are installed on all 5 by `entrypoint.sh` since they're shared infrastructure,
not per-role choices; the rest of
each role's plugins/skills are managed independently via `PI_PACKAGES`.

## LLM cost tracking

All 5 agents install [`@ctogg/pi-cost-counter`](https://pi.dev/packages/@ctogg/pi-cost-counter),
which tracks the cost of each LLM call and persists it under `~/.pi/cost-tracker/`. That
directory is bind-mounted per role to `cost-tracking/<role>/` in this repo (instead of a
Docker volume) specifically so it's browsable from the host without `docker exec`: open
`cost-tracking/` to see every role's cost data side by side, or `cost-tracking/<role>/` for
just one. Its contents change on every run and aren't meant to be versioned — see
`.gitignore`.

## Team context (`AGENTS.md`)

`pi` loads `AGENTS.md` from `~/.pi/agent/AGENTS.md` (global instructions) plus any found
walking up from the working directory, concatenating all of them. Each role's team context
lives at `agents/<role>/AGENTS.md`, mounted at `~/.pi/agent/AGENTS.md` inside its container
(not under `/workspace` — see [Folder structure](#folder-structure)): it explains that
agent's role, who the rest of the team is, and how to talk to them via pi-link (`link_list`,
`link_send`, `link_prompt`, `link_compact`). Since it's a regular bind mount, editing it from
inside the session writes the change straight back into the repo — nothing extra needed to
persist it. `docs/` (introduction, work procedures) is mounted the same way, at `/docs`
rather than `/workspace/docs`, so `/workspace` stays free for the role's actual repository.

## Troubleshooting

**Broken special characters (`_` instead of accents/¡¿/ñ)** — the image sets
`LANG=LC_ALL=C.UTF-8` in the Dockerfile; if you see this after an image change, rebuild with
`python setup.py --start`.

**Colors/grays showing up as black inside tmux** — `docker/generate-tmux-conf.sh` generates
`/etc/tmux.conf` at build time with `default-terminal tmux-256color` + `terminal-overrides
",*:RGB"` to negotiate truecolor correctly. If it persists, the *client* terminal you're
running `python setup.py --tmux <role>` from is likely not advertising truecolor support.

**Mouse wheel scrolling in tmux** — `/etc/tmux.conf` also sets `mouse on`, so scrolling up
with the wheel enters tmux's copy-mode automatically and scrolls the pane's history;
scrolling back down to the bottom exits copy-mode on its own, no `Ctrl-b [`/`q` needed.
Trade-off: selecting text with the mouse to copy it now needs **Shift+drag** in most
terminal emulators instead of a plain drag, since tmux itself intercepts plain mouse clicks
for its own use (pane focus, drag-to-resize, etc.) once mouse mode is on.

**An agent doesn't show up on pi-link / `link_list` doesn't see it** — check in order:

```bash
python setup.py --logs <role>                          # did the broker start? hub or spoke?
docker exec pi-<role> cat /var/run/pi-link/hub.addr     # who is the mesh pointing at right now?
docker exec pi-<role> tmux capture-pane -t pi -p        # pi-link's on-screen status
```

(the last two are quick one-off commands, not worth a dedicated `setup.py` flag — or run
`python setup.py --bash <role>` and type them directly inside the container.)

## TODO

- **Tech stack per role** (frontend Angular, ...) — once decided, `Dockerfile.pi` will be
  split for it too, adding its matching toolchain (flagged with `TODO` in the file itself;
  backend and devops already have their own `Dockerfile.backend`/`Dockerfile.devops`).
- **Headless Eclipse pi extension** for Java code management, pending integration once the
  backend stack is confirmed.
- **`cypress/included` version** — `Dockerfile.cypress` uses `latest` as a placeholder; pin
  it to the project's actual Cypress version.

## License

[MIT](LICENSE) © 2026 Xan
