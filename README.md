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
| **backend** | `pi-backend` | Backend service/API development — language picked per project, `java`, `kotlin` or `python` today (see [Backend stack](#backend-stack)). |
| **frontend** | `pi-frontend` | User interface development — framework picked per project, `angular` or `nextjs` today (see [Frontend stack](#frontend-stack)). |
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

A sixth container, [`console`](#the-console), sits on that same network but is not an agent:
it runs no `pi`, takes no part in the mesh, and observes — cost, who is talking to whom,
container state, the agents' tmux panes — plus it schedules the team's own scripts. The one
thing it does beyond looking is [typing into an agent's terminal](#typing-into-an-agent-tmux-tab),
which you open on purpose and which needs a `CONSOLE_TOKEN`.
Full technical detail — the topology diagram, how the hub-election/broker mechanism works,
the DooD setup, how a role ships several language variants of its image, and how the `java`
backend's headless Eclipse (`jdtbridge`) is wired up — lives in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — technical detail: the pi-link mesh/broker
  mechanism, how `backend` and `frontend` each ship several stack variants of their image, and
  how the `java` backend's headless Eclipse (`jdtbridge`) is wired up.
- [`docs/introduction.md`](docs/introduction.md) — a human-oriented introduction to the
  team, written for someone joining the project (what this is, who's on the team, how to
  work with it).
- [`console/sdk/README.md`](console/sdk/README.md) — the API the console offers to the
  scripts you schedule in it (`notify`, `state`, `ado.query`, `log`), with a worked example.
- [`docs/work-procedures.md`](docs/work-procedures.md) — the detailed workflow: the eight
  stages a piece of work moves through, each role's objectives, and exactly what changes in
  Azure DevOps and in each role's own `workitems/` folder along the way.

## Folder structure

```
.
├── docker-compose.yml
├── .env.example              # copy to .env — ANTHROPIC_API_KEY is optional (see Authentication)
├── .gitattributes            # forces LF on checkout — CRLF breaks the scripts inside the containers
├── README.md                    # this file: what/why, and the commands to run it
├── ARCHITECTURE.md              # technical detail: pi-link mesh, backend's headless Eclipse
├── docs/                        # mounted read-write at /docs in every container (not /workspace)
│   ├── introduction.md         # human-oriented intro to the team
│   └── work-procedures.md      # detailed workflow: stages, roles, ADO/local workitem changes
├── cost-tracking/
│   └── <role>/                  # mounted at ~/.pi/cost-tracker in that role's container — see
│                                 # "LLM cost tracking" below
├── docker/
│   ├── Dockerfile.pi           # base image: manager (every other role has its own)
│   ├── Dockerfile.backend.java   # backend, java variant: Java/Maven + headless Eclipse/jdtbridge
│   ├── Dockerfile.backend.kotlin # backend, kotlin variant: Kotlin/Gradle/Maven + Kotlin LS
│   ├── Dockerfile.backend.python # backend, python variant: Python 3.14/uv + ruff/mypy/pyright
│   ├── Dockerfile.frontend.angular # frontend, angular variant: Angular CLI + chromium (ng test)
│   ├── Dockerfile.frontend.nextjs  # frontend, nextjs variant: create-next-app, no browser
│   ├── Dockerfile.devops       # devops image: adds Docker CLI (Docker-outside-of-Docker, see ARCHITECTURE.md)
│   ├── Dockerfile.cypress      # variant on top of cypress/included (TODO: pin version)
│   ├── Dockerfile.console      # console image: python + az CLI (see "The console" below)
│   ├── entrypoint.sh           # installs pi packages, starts broker + tmux session, watchdogs
│   ├── pi-link-broker.sh       # hub election (flock) + socat relays (see ARCHITECTURE.md)
│   └── generate-tmux-conf.sh   # generates /etc/tmux.conf at build time (colors + extended-keys)
├── console/                     # the console's own code (standard library only)
│   ├── server.py  costs.py  events.py  inbox.py  cron.py  system.py  tmux.py  terminal.py  websocket.py  ...
│   ├── sdk/                     # console_sdk: the API the cron's scripts use (see its README)
│   ├── static/                  # the web itself: one page, five views
│   └── tests/                   # browser test of the console (reuses the cypress image)
├── agents/
│   ├── _shared/
│   │   └── pi/extensions/
│   │       └── team-console/   # one extension for the 5 roles: reports who talks to whom and
│   │                            # picks up the console's scheduled notices
│   └── <role>/
│       ├── AGENTS.md           # team context, mounted at ~/.pi/agent/AGENTS.md (global for pi)
│       │                        # backend/frontend have one per stack instead:
│       │                        # AGENTS.java.md, AGENTS.kotlin.md, AGENTS.python.md /
│       │                        # AGENTS.angular.md, AGENTS.nextjs.md — see below
│       └── pi/
│           └── extensions/     # mounted at ~/.pi/agent/extensions in the container — global
│                                # pi extensions specific to this role (see "Plugins/packages
│                                # per agent" below)
└── tmp/                         # not versioned (see .gitignore)
    └── scripts/                 # the cron's scripts: yours, not this project's — the folder
                                 # is kept in the checkout, its contents are not
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

### Updating without losing what's inside a container

A container is recreated when the hash of its service definition changes, or when its image
does — not merely because you ran `--start`. That matters because **only volumes survive a
recreation**: `/workspace`, `~/.pi/agent`, `backend`'s Eclipse workspace and `cost-tracking/`
are volumes and persist, but anything installed by hand inside a container is not. An Eclipse
plugin added from the Marketplace, for instance, lands in `/opt/eclipse`, which lives in the
image layer and is gone the next time that container is recreated.

Two options keep an update from touching more than it has to:

```bash
python setup.py --update console            # only this service; the rest of the team is left alone
python setup.py --update backend console    # several at once
python setup.py --start --no-build          # bring everything up without rebuilding images
```

`--no-build` also works with `--update`. Use it when you only want things running: a rebuild
can produce a new image — and therefore a recreation — even when the code you care about did
not change, because any file inside what the `Dockerfile` copies invalidates that layer.

If a customization matters, the durable answer is to put it in the image (`docker/Dockerfile.<role>`)
or in a volume, rather than installing it inside a running container. `docker compose up -d
--no-recreate` is the escape hatch when you need to start something *right now* without
touching an existing container.

## Configuration (`.env`)

`setup.py --init` walks through every variable in `.env.example`, proposing its value as
the default (Enter accepts it); it writes the result to `.env` (backing up any existing one
to `.env.bak` first). Variables with a closed set of options — `BACKEND_STACK` today — are
asked as a numbered menu instead of free text, and the answer is validated there rather than
failing later during `docker compose up`. You can also skip it and copy/edit `.env.example`
by hand. Variables:

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Optional — see [Authentication](#authentication) below. |
| `CONTAINER_PREFIX` | Prefix for the 5 container names (default `pi`, i.e. `pi-manager`, ...). Change it to run several instances of this project on the same machine without name clashes. |
| `BACKEND_STACK` | Language/toolchain of the `backend` role: `java` (default), `kotlin` or `python`. Picks which image that container is built from and which team context its agent boots with — see [Backend stack](#backend-stack). Optional: an `.env` without it behaves exactly as before, building the Java image. |
| `FRONTEND_STACK` | Framework of the `frontend` role: `angular` (default) or `nextjs`. Same mechanism as `BACKEND_STACK` — see [Frontend stack](#frontend-stack). Also optional. |
| `<ROLE>_REPO_URL` | Git remote (origin) URL for that role's real repository — SSH or HTTPS. Exposed inside each container as `REPO_URL`. Empty until each role's repo/stack is decided. `/workspace` is a named Docker volume (`<role>-workspace`), not a bind mount to this repo, so it's always empty on first run: `python setup.py --git-clone` clones it there for every role that has one set (or let the agent do it itself) without worrying about clashing with anything this project mounts — pi's own per-role state (`AGENTS.md`, extensions, login) lives entirely under `~/.pi/agent` instead, never under `/workspace`. |
| `<ROLE>_GIT_TOKEN` | Access token (PAT) for that role's `REPO_URL` when it's `https://` — scope it to just that one repo (GitHub fine-grained PAT, or an Azure DevOps PAT limited to `Code: Read & Write`). Exposed inside each container as `GIT_TOKEN`; `entrypoint.sh` wires it into a git credential helper that reads it from the environment at auth time, so it's never written to the remote URL or `.git/config`. Leave it empty and use an SSH `REPO_URL` instead if you'd rather set up SSH manually for a given role — the two don't conflict. |
| `ADO_ORGANIZATION_URL`, `ADO_PROJECT` | Shared Azure DevOps organization/project (see `docs/work-procedures.md`). Exposed as-is inside every container; `entrypoint.sh` runs `az devops configure --defaults organization=$ADO_ORGANIZATION_URL project=$ADO_PROJECT` automatically on every start, so `az boards`/`az repos` commands don't need `--organization`/`--project` in that role's session. |
| `<ROLE>_ADO_PAT` | Azure DevOps PAT for that role, used by `az boards`/`az repos` inside its container — see [Azure DevOps CLI authentication](#azure-devops-cli-authentication) below for exactly which scopes each role needs. Exposed inside each container as `ADO_PAT`; `entrypoint.sh` maps it to `AZURE_DEVOPS_EXT_PAT`, the environment variable az CLI's `azure-devops` extension reads automatically — no `az devops login` needed, and it's never written to disk. |
| `BACKEND_VNC_PASSWORD`, `BACKEND_VNC_PORT`, `BACKEND_VNC_BIND` | **`BACKEND_STACK=java` only** — VNC/noVNC access to the `backend` container's headless Eclipse (see [Eclipse GUI access](#eclipse-gui-access-backend-java-variant-via-novnc) below). Empty password = VNC disabled (default). Port defaults to `6080`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). Other stacks ship no GUI, so these do nothing there. |
| `FRONTEND_PORT`, `FRONTEND_BIND` | Access to the `frontend` container's dev server (see [Frontend dev server access](#frontend-dev-server-access) below). Same accessibility criteria as the backend VNC variables above: port defaults to `4200`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). |
| `FRONTEND_DEV_PORT` | The port the dev server listens on **inside** the container (`FRONTEND_PORT` above is the host's — they're different things). Defaults to `4200`, Angular's own default; Next.js defaults to `3000`. Also exposed to the agent so it serves on the port actually published rather than on its framework's default. |

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

## Backend stack

`backend`'s **role** in the team is fixed — the service/API, the data model, the contract
`frontend` consumes. The **language** it works in isn't, and is picked per project with
`BACKEND_STACK` in `.env`:

| `BACKEND_STACK` | Toolchain in the container |
|---|---|
| `java` (default) | Java 21 (Temurin), Maven, Eclipse JDT Language Server, and a full headless Eclipse with [jdtbridge](https://github.com/kaluchi/jdtbridge) driven through the `jdt` CLI — plus [GUI access over noVNC](#eclipse-gui-access-backend-java-variant-via-novnc). |
| `kotlin` | Kotlin 2 (`kotlinc` + REPL) on JDK 21 (Temurin), Gradle *and* Maven (both are used in the Kotlin/JVM world; the real project decides), [Kotlin Language Server](https://github.com/fwcd/kotlin-language-server), and `ktlint` for the official style guide. |
| `python` | Python 3.14 with [uv](https://docs.astral.sh/uv/) as project/dependency manager, [ruff](https://docs.astral.sh/ruff/) to lint and format, and both [pyright](https://github.com/microsoft/pyright) (the language server, and a type checker on its own) and `mypy` — they aren't interchangeable, so the real project picks. A C toolchain is included for dependencies that still build from source. |

All of them carry `git`/`gh`/`az` like every other role and the same pi/pi-link setup; `java`
and `kotlin` also carry Python 3.14 for support scripts (in the `python` variant it's the
application's own language, with the tooling to match).

`python setup.py --init` asks for this as a menu; you can also set it by hand in `.env`. It's
optional — an `.env` that doesn't mention `BACKEND_STACK` at all builds the Java image, same
as before this existed. After changing it, rebuild that container:

```bash
python setup.py --start   # docker compose up -d --build
```

Each variant builds its own image (`team-pi-backend-java`, `team-pi-backend-kotlin`,
`team-pi-backend-python`), so
switching back doesn't mean rebuilding from scratch. What does **not** reset is that role's
state: `/workspace` and its pi login live in named volumes that survive the switch, so if the
new stack means a different repository, change `BACKEND_REPO_URL` too and clear
`/workspace` before cloning into it.

Two things are `java`-only, because they exist to serve Eclipse's GUI: the `BACKEND_VNC_*`
variables and the noVNC endpoint. On any other stack nothing listens there — the port mapping
stays in `docker-compose.yml` but is inert. Kotlin has no equivalent: Eclipse's Kotlin support
is discontinued, and code intelligence there goes through the Kotlin Language Server instead
(headless, no framebuffer needed).

### Adding a new backend stack

A stack is **two files**, and nothing else — no changes to `docker-compose.yml`, `setup.py` or
`.env.example`. To add `go`, say:

1. `docker/Dockerfile.backend.go` — the image, building whatever that toolchain needs. Use
   `Dockerfile.backend.kotlin` or `.python` as the starting point rather than the Java one:
   they're the variants without the Eclipse/Xvfb/VNC machinery. Keep the shared tail as is
   (`gh`, `az`, the pi install, `WORKDIR /workspace`, the entrypoint) — `entrypoint.sh` is
   shared by every variant and already skips its Eclipse/VNC block when the image has no
   `/opt/eclipse`.
2. `agents/backend/AGENTS.go.md` — the team context its agent boots with. Copy
   `AGENTS.python.md` and rewrite the "Your role" opening and the "Stack and architecture"
   section; everything from *The rest of the team* to the end of *Team work procedure* is
   about the role in the team, not the language, and should stay identical across variants.

`setup.py --init` picks the new option up on its own: it globs `docker/Dockerfile.backend.*`
and offers the stacks that also have a matching `AGENTS.<stack>.md`, so a half-added variant
never shows up in the menu. See [`ARCHITECTURE.md`](ARCHITECTURE.md#stack-variants)
for why it resolves this way.

## Frontend stack

Same mechanism as [Backend stack](#backend-stack) above, with its own variable —
`FRONTEND_STACK` in `.env`:

| `FRONTEND_STACK` | Toolchain in the container |
|---|---|
| `angular` (default) | Angular CLI (`ng new`, `ng serve`). No browser: on Angular 20+ `ng test` runs on vitest + jsdom and needs none. Dev server on `4200`. |
| `nextjs` | `create-next-app` for scaffolding. Next itself is deliberately *not* global — it's a project dependency, so the version that applies is always the one the project declares. No browser: Next's scaffolded tests run on jsdom. Dev server on `3000`. |

Unlike the backend variants, which diverge by entire toolchains, these two are both Node and
both test on jsdom, so the images differ by little beyond which CLI is global. The substantial
divergence is each variant's `AGENTS.md` — how to serve and on which port, and (for Next) the
fact that server-side and browser-side code don't reach the API by the same hostname.

Neither image carries a browser. If your Angular project is an older, Karma-based one that
needs Chromium for `ng test`, `docker/Dockerfile.frontend.angular` has the two lines to add it
written out as a comment — it's left out by default because a current `ng new` doesn't use it
and it costs ~790 MB. Real browser testing is the `cypress` role's job anyway.

**Ports.** Two different numbers, and it's worth keeping them straight:

- `FRONTEND_PORT` — the port on the **host**, what you open in your browser. Change it to
  avoid a collision on your machine.
- `FRONTEND_DEV_PORT` — the port the dev server listens on **inside** the container. It
  defaults to `4200`; with `nextjs` set it to `3000` (Next's default) or leave it at `4200`
  and the agent will start Next there — both work, because the agent reads this variable and
  serves on it rather than assuming its framework's default.

Everything else works exactly as in the backend: each variant builds its own image
(`team-pi-frontend-angular`, `team-pi-frontend-nextjs`), the variable is optional (an `.env`
without it builds Angular, as before), `python setup.py --start` rebuilds after a change, and
`/workspace` plus the pi login survive the switch — so change `FRONTEND_REPO_URL` too if the
new framework means a different repository.

Adding a third framework follows [the same two-file recipe](#adding-a-new-backend-stack) as the
backend, with `frontend` in place of `backend` in both filenames.

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

## Eclipse GUI access (backend, java variant, via noVNC)

This section applies to `BACKEND_STACK=java` only — the `kotlin` variant ships no Eclipse and
no GUI (see [Backend stack](#backend-stack)).

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

The `frontend` container publishes its dev-server port to the host, so you can connect to
whatever the agent has running there from outside the container — same accessibility criteria
as the backend VNC setup above:

1. Ports and bind are configurable via `FRONTEND_PORT`/`FRONTEND_DEV_PORT`/`FRONTEND_BIND` in
   `.env` (defaults: `4200`, `4200` and `127.0.0.1`) — see [Frontend
   stack](#frontend-stack) for the difference between the two port variables. There's no
   separate enable/disable switch here (unlike `BACKEND_VNC_PASSWORD`): a dev server isn't
   authenticated by itself either way, so there's no unauthenticated-by-default risk this port
   mapping newly introduces.
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
`ng serve` alone, binds to `localhost` only and won't work here); `next dev` already binds
`0.0.0.0` by default, so with the `nextjs` variant there's nothing to add. Each variant's
`AGENTS.md` tells its own agent this, so it should already be handled.

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

## The console

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

### The five tabs

| Tab | What it's for |
|---|---|
| **Sistema** | What exists and what's alive: containers with uptime, CPU/memory, image and ports; what's attached to `team-net` (including the siblings `devops` starts); disk usage per volume; and each agent's live state — idle, thinking, running a tool, context consumed — read from the pi-link hub's own `GET /status`, which needs no registration. |
| **Actividad** | Who talks to whom. Each message lights the edge between two agents and fades over ~10 s, a dot travels from sender to recipient, and the list below shows one line per message with how long delivery took. |
| **Costes** | The LLM cost dashboard: total and per agent, over time, by model. Same data as [LLM cost tracking](#llm-cost-tracking) below, read from `cost-tracking/`. |
| **Cron** | Schedules the team's scripts (below), with history, full output of each run, "run now", and the notices still waiting to be delivered to an agent. |
| **Tmux** | The five agents' panes side by side, **read-only**, refreshed every 5 s. Click one to enlarge it; **Escribir** turns it into a real terminal you can type in (needs `CONSOLE_TOKEN`, see [below](#typing-into-an-agent-tmux-tab)). The `attach` button still copies the `docker exec` command for a terminal of your own. |

### Typing into an agent (Tmux tab)

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
images. Details in [`ARCHITECTURE.md`](ARCHITECTURE.md#the-tmux-terminal).

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

### What it records, and what it deliberately doesn't

Each agent carries one extra pi extension (`agents/_shared/pi/extensions/team-console`,
mounted into all five) that reports every message the agent sends or receives over pi-link.
What's stored is **only metadata** — sender, recipient, timestamp, size. Never the text:
fragments of the projects the agents work on travel over that mesh, and none of it belongs in
an observability database. The console enforces that at the boundary, dropping any field that
looks like it carries text, so a future emitter cannot smuggle a conversation in by accident.

If the console is down the agents do not notice: the extension queues events with a bounded
buffer, a short timeout and backoff, and delivers them when it comes back.

### Scheduled scripts (Cron tab)

The scripts are **yours, not this project's** — they live in `tmp/scripts/`, which is not
versioned, and are mounted read-only into the console. The web schedules what's in that
catalog; there is no free-form command field, which is what keeps a console without
authentication from meaning arbitrary execution for anyone who reaches the port.

They're Python, and they get an API to talk to the team — `notify()`, `state`, `ado.query()`,
`log()` — documented with a full example in [`console/sdk/README.md`](console/sdk/README.md).
The case that motivated it: at 20:00 on weekdays, query ADO for the manager's open tickets and
tell it about them. The manager receives it as a message and starts a turn even if it was
idle, because delivery goes through the same mechanism pi-link uses — the console leaves the
notice in a queue and that agent's extension injects it.

Schedules are evaluated in the **container's** timezone (`TZ`, `Europe/Madrid` by default);
the times you see in the page are drawn in your browser's. The Cron tab states which one it's
scheduling in.

### Configuration

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

### Publishing it, and several clusters on one machine

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
> (see [`ARCHITECTURE.md`](ARCHITECTURE.md)). The difference is that here there's a web in
> front. That's why the port is on loopback by default, why the cron can only run scripts you
> placed in the catalog, why typing into an agent requires `CONSOLE_TOKEN`, and why publishing
> it elsewhere without setting one prints a warning at startup.

### Without Docker

`python setup.py --console-local [PORT]` runs only the cost view on the host, reading a
`cost-tracking/` folder from disk (`--cost-dir` to point it at an export from another run).
Everything else — containers, events, cron, tmux — lives in the container.

### Checking it still works

`console/tests/` holds a browser test that drives the real console and fails on any uncaught
page error. It reuses the `cypress` image, adds no dependency, and seeds and cleans up its own
data, so it can run against a working team — see [`console/tests/README.md`](console/tests/README.md).

## LLM cost tracking

All 5 agents install [`@ctogg/pi-cost-counter`](https://pi.dev/packages/@ctogg/pi-cost-counter),
which tracks the cost of each LLM call and persists it under `~/.pi/cost-tracker/`. That
directory is bind-mounted per role to `cost-tracking/<role>/` in this repo (instead of a
Docker volume) specifically so it's browsable from the host without `docker exec`: open
`cost-tracking/` to see every role's cost data side by side, or `cost-tracking/<role>/` for
just one. Its contents change on every run and aren't meant to be versioned — see
`.gitignore`. The **Costes** tab of [the console](#the-console) is the same data, aggregated
and drawn.

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

**Build fails on Windows with `/usr/bin/env: 'bash\r': No such file or directory`** — Git for
Windows with its default `core.autocrlf=true` converted this repo's shell scripts to CRLF on
checkout, so the shebang line became `#!/usr/bin/env bash\r` and the container looked for an
interpreter literally called `bash\r`. The repo's `.gitattributes` (`* text=auto eol=lf`)
prevents it for any fresh clone, and every Dockerfile strips CRs from the scripts it copies
before running them, so a build works either way. If you cloned **before** `.gitattributes`
existed, your working tree still holds the converted files — renormalize it once:

```bash
git add --renormalize .
git checkout -- .
```

(`git status` should then show nothing; if it lists the `.sh` files, commit that renormalization
or reset it, whichever fits.) A fresh `git clone` also does the job.

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

**The console's Sistema tab shows only the console itself** — it lists the containers of its
own Compose project (label `com.docker.compose.project`) plus any whose name starts with
`CONTAINER_PREFIX`. If your agents were created from a *different checkout* — another
directory is another Compose project — or before you changed `CONTAINER_PREFIX`, they fall
outside both. The tab says so, naming its own project and the other ones it can see on the
same daemon. Compare:

```bash
docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}'
curl -s localhost:4070/api/health          # fields: project, prefix, containers
```

The fix is usually to work from a single checkout: bring the branch there and run
`python setup.py --start`, which creates all six containers in the same project.

**`ports are not available: ... bind: address already in use` on 4070** — something else is
already publishing that port, most often a console from *another* checkout of this project
(with Docker Desktop + WSL2 the daemon and `localhost` are shared). Find it and either stop it
or give this cluster its own port:

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 4070
echo "CONSOLE_PORT=4071" >> .env && python setup.py --start
```

**The console is up but the graph in Actividad stays empty** — the agents report what they
send through the extension mounted at `agents/_shared/pi/extensions/team-console`, which only
exists in containers created *after* that mount was added. Recreate them
(`python setup.py --start`) and check that one of them sees it:

```bash
docker exec pi-manager ls /root/.pi/agent/extensions/team-console
docker exec pi-manager printenv CONSOLE_URL
```

## TODO

- **More stacks** — `go` for the backend, another framework for the frontend, following [the
  two-file recipe](#adding-a-new-backend-stack) below.
- **Headless Eclipse pi extension** for Java code management, pending integration once the
  backend stack is confirmed.
- **`cypress/included` version** — `Dockerfile.cypress` uses `latest` as a placeholder; pin
  it to the project's actual Cypress version.
- **Console authentication** — `CONSOLE_TOKEN` exists but is opt-in, and the port is on
  loopback by default. If the console starts being published on shared networks routinely, it
  should be required rather than offered (it already is, for the tmux terminal).

## License

[MIT](LICENSE) © 2026 Xan
