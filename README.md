# team-pi

Docker Compose infrastructure that implements a **software development team built on AI
agents**: 5 [pi](https://pi.dev) agents (`@earendil-works/pi-coding-agent`), each in its own
container with its own role, coordinating with each other in real time through
**[pi-link](https://pi.dev/packages/pi-link)**. It isn't a simulation of a team — it's a
working one, meant to own real deliverables end to end.

## Goal

Five roles, each knowing exactly what it owns and how it coordinates with the rest:

- **Specialization, not imitation** — a focused role keeps each agent's context to what it
  needs, and lets all five make progress in parallel.
- **Boundaries are structural** — each role has its own container, repo, credentials and
  extensions (see [`ARCHITECTURE.md`](ARCHITECTURE.md)), enforced by the infrastructure
  rather than just described in an `AGENTS.md`.
- **Independent verification** — `cypress` runs end-to-end tests as a role of its own, so
  integration correctness isn't self-certified by whoever built the feature.
- **Scales without a redesign** — a new specialty is one more container/repo/`AGENTS.md`
  on the same pattern.

| Role | Container | Responsibility |
|---|---|---|
| **manager** | `pi-manager` | Coordinates the team, breaks down and prioritizes tasks, main point of contact for the human in charge. |
| **backend** | `pi-backend` | Backend service/API — `java`, `kotlin` or `python` (see [Backend stack](#backend-stack)). |
| **frontend** | `pi-frontend` | User interface — `angular` or `nextjs` (see [Frontend stack](#frontend-stack)). |
| **devops** | `pi-devops` | Infrastructure, CI/CD, deployment and observability — including this very infrastructure. |
| **cypress** | `pi-cypress` | End-to-end testing of backend + frontend together. |

## Architecture

Every container runs the same three components: `pi` in a persistent tmux session, `pi-link`,
and a broker script that gives the five a shared mesh. All five share one Docker network
(`team-net`), and `devops` can start sibling containers on it. A sixth container,
[`console`](#the-console), is not an agent: it observes the team and schedules scripts.
Full technical detail is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — pi-link mesh, stack variants, headless Eclipse.
- [`docs/introduction.md`](docs/introduction.md) — introduction for someone joining the project.
- [`docs/work-procedures.md`](docs/work-procedures.md) — the workflow, stage by stage.
- [`docs/configuration.md`](docs/configuration.md) — every `.env` variable, Azure DevOps auth, per-agent packages.
- [`docs/stacks.md`](docs/stacks.md) — backend/frontend stacks and how to add one.
- [`docs/access.md`](docs/access.md) — tmux, remote VS Code, Eclipse over noVNC, frontend dev server.
- [`docs/console.md`](docs/console.md) — the console in detail.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common problems.
- [`console/sdk/README.md`](console/sdk/README.md) and [`docs/cron-scripts/`](docs/cron-scripts/) — API and examples for the console's cron.

## Folder structure

```
.
├── docker-compose.yml
├── .env.example              # copy to .env (or run setup.py --init)
├── setup.py                  # all the commands below
├── ARCHITECTURE.md
├── docs/                     # documentation; mounted at /docs in every container
├── docker/                   # Dockerfiles (one per role/variant), entrypoint, broker
├── console/                  # the console's own code (standard library only)
├── agents/
│   ├── _shared/pi/           # extension and skills shared by the five roles
│   └── <role>/
│       ├── AGENTS.md         # team context (backend/frontend: one per stack)
│       ├── startup/          # your own *.sh, run on every container start
│       └── pi/               # that role's extensions and skills
├── cost-tracking/<role>/     # LLM cost data, browsable from the host
└── tmp/scripts/              # the cron's scripts: yours, not versioned
```

There's no `workspace/` folder: `/workspace` in each container is a named Docker volume
(`<role>-workspace`), always empty on first run. `git clone $REPO_URL .` there, or let the
agent do it. `<role>` is one of `manager`, `backend`, `frontend`, `devops`, `cypress`.

## Requirements

- Docker and Docker Compose v2 (`docker compose ...`).
- Python 3 (stdlib only) to run `setup.py`, on Windows or Linux.
- Internet access for the build.

## Getting started

```bash
python setup.py --init      # builds .env from .env.example (Enter keeps the default)
python setup.py --start     # docker compose up -d --build
python setup.py --git-clone # git clone each role's REPO_URL into its /workspace, if set
```

Then log in once: `python setup.py --tmux manager`, run `/login`, and copy it to the others
with `python setup.py --share-auth` (see [Authentication](#authentication)).

Other commands:

```bash
python setup.py --stop                 # docker compose down (volumes are kept)
python setup.py --update backend       # recreate only that service
python setup.py --start --no-build     # bring everything up without rebuilding
python setup.py --tmux|--bash|--logs <role>
python setup.py --console              # open the console in the browser
```

> **Do not run `docker compose down -v`** unless you want to wipe each agent's login and state.

### What survives recreating a container

**Only volumes survive**: `/workspace`, `~/.pi/agent`, backend's Eclipse workspace
(`/root/eclipse-workspace`) and `cost-tracking/`. Anything installed by hand elsewhere — an
Eclipse plugin in `/opt/eclipse`, another Java — is gone. Two ways to keep it:

- Put it in the image (`docker/Dockerfile.<role>`).
- Put a script in `agents/<role>/startup/*.sh`. It runs as root on every container start,
  before Eclipse and pi, so it must be idempotent. A failing script is logged and the
  container starts anyway. See `agents/<role>/startup/README.md`.

## Configuration (`.env`)

`python setup.py --init` walks through every variable in `.env.example`. The ones you'll
usually touch:

| Variable | Meaning |
|---|---|
| `CONTAINER_PREFIX` | Prefix for container names (default `pi`). Change it to run several clusters on one machine. |
| `BACKEND_STACK`, `FRONTEND_STACK` | Language/framework of those roles — see [Backend stack](#backend-stack) and [Frontend stack](#frontend-stack). |
| `<ROLE>_REPO_URL`, `<ROLE>_GIT_TOKEN` | Git remote and access token for that role's repository. |
| `ADO_ORGANIZATION_URL`, `ADO_PROJECT`, `<ROLE>_ADO_PAT` | Azure DevOps organization/project and each role's PAT. |
| `CONSOLE_TOKEN` | Protects the console and enables typing into an agent. |

The full table, the Azure DevOps scopes per role and per-agent packages are in
[`docs/configuration.md`](docs/configuration.md).

## Backend stack

`backend`'s role is fixed; its language is picked with `BACKEND_STACK`: `java` (default; Java 21,
Maven, headless Eclipse), `kotlin` (Gradle/Maven, Kotlin LS) or `python` (3.14, uv, ruff,
pyright/mypy). Each builds its own image, so switching back doesn't rebuild from scratch.
A new stack is two files (a Dockerfile and an `AGENTS.<stack>.md`). Details and the recipe:
[`docs/stacks.md`](docs/stacks.md).

## Frontend stack

Same mechanism with `FRONTEND_STACK`: `angular` (default, dev server on 4200) or `nextjs`
(3000). Neither image carries a browser; real browser testing is `cypress`'s job. Host port is
`FRONTEND_PORT`, in-container port is `FRONTEND_DEV_PORT`. Details: [`docs/stacks.md`](docs/stacks.md).

## Authentication

`ANTHROPIC_API_KEY` is optional. Otherwise run `/login` once in an agent's session; it's
saved in that agent's volume (`/root/.pi/agent`). To log in only once for the whole team,
log in on the manager and run:

```bash
python setup.py --share-auth   # copies the manager's auth.json to the other four containers
```

An agent whose pi was already open may need `/login` or a restart to see it. Azure DevOps and
git authentication are per role, through environment variables — see
[`docs/configuration.md`](docs/configuration.md#azure-devops-cli-authentication).

## Connecting to an agent

```bash
python setup.py --tmux <role>   # attach to the persistent tmux session (Ctrl-b d to detach)
python setup.py --bash <role>   # plain shell in the container
python setup.py --logs <role>   # tail the container's logs
```

`Ctrl+D` inside `pi` ends `pi`, but the watchdog restarts it within ~5 s. Remote VS Code is
covered in [`docs/access.md`](docs/access.md#remote-vs-code).

## Eclipse GUI access (backend, java variant, via noVNC)

Set `BACKEND_VNC_PASSWORD` in `.env`, restart `backend`, and open
`http://127.0.0.1:6080/vnc.html`. Needed to import projects into Eclipse's workspace or to use
the graphical debugger. Without a password nothing is exposed. WSL2 and remote-machine notes
are in [`docs/access.md`](docs/access.md#eclipse-gui-access-backend-java-variant-via-novnc).

## Frontend dev server access

The dev server is published on `127.0.0.1:${FRONTEND_PORT:-4200}`. It must listen on
`0.0.0.0` inside the container (`ng serve --host 0.0.0.0`). Details:
[`docs/access.md`](docs/access.md#frontend-dev-server-access).

## The console

A web console on **http://localhost:4070**, started with everything else by
`python setup.py --start`. It is not an agent: it observes (system, who talks to whom, costs,
the agents' tmux panes), schedules your scripts, and — only with a `CONSOLE_TOKEN` — opens a
real terminal into one agent (Alt+B/M/F/C/D jump between agents, also from write mode).
Tabs, typing into an agent, cron, publishing it and several clusters on one machine:
[`docs/console.md`](docs/console.md).

## LLM cost tracking

All five agents install [`@ctogg/pi-cost-counter`](https://pi.dev/packages/@ctogg/pi-cost-counter),
which writes to `~/.pi/cost-tracker/`, bind-mounted to `cost-tracking/<role>/` so you can
browse it from the host. It isn't versioned. The console's **Costes** tab draws the same data.

## Team context (`AGENTS.md`)

Each role's team context is `agents/<role>/AGENTS.md`, mounted at `~/.pi/agent/AGENTS.md`: it
explains the role, the rest of the team and how to talk to them via pi-link. It's a bind
mount, so editing it from inside the session writes straight back to the repo. `docs/` is
mounted at `/docs`, keeping `/workspace` free for the role's real repository.

## Troubleshooting

Windows CRLF build errors, garbled characters, tmux colors and mouse, agents missing from
pi-link, an empty console, port 4070 already in use: see
[`docs/troubleshooting.md`](docs/troubleshooting.md).

## TODO

- **More stacks** — `go` for the backend, another framework for the frontend ([recipe](docs/stacks.md#adding-a-new-backend-stack)).
- **Headless Eclipse pi extension** for Java code management, pending the backend stack.
- **`cypress/included` version** — `Dockerfile.cypress` uses `latest`; pin it to the project's version.
- **Console authentication** — `CONSOLE_TOKEN` is opt-in; it should be required if the console
  is routinely published on shared networks (it already is for the tmux terminal).

## License

[MIT](LICENSE) © 2026 Xan
