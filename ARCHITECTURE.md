# Architecture

Technical/internal detail for **team-pi**: how the 5 containers discover and talk to each
other over pi-link, and how `backend`'s headless Eclipse (`jdtbridge`) is wired up. For what
this project is, why it's organized into 5 roles, and the commands to actually run it, see
[`README.md`](README.md).

## Container topology & the pi-link mesh

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

## Java code intelligence in `backend`: jdtbridge + headless Eclipse

`backend`'s toolchain (see `docker/Dockerfile.backend` and
[`agents/backend/AGENTS.md`](agents/backend/AGENTS.md)) includes two independent layers of
Java tooling:

- **Eclipse JDT Language Server** (`jdtls`, headless, no GUI) — a standalone LSP server
  talking over stdio. The runtime is installed; connecting an LSP client to it is a separate
  layer, not verified yet in this project.
- **A full Eclipse IDE instance** (SWT/GTK, running headless under Xvfb — Eclipse needs a
  framebuffer even with nobody watching) with the
  [jdtbridge](https://github.com/kaluchi/jdtbridge) plugin, which exposes Eclipse's own JDT
  functionality (semantic search, incremental compilation, tests, refactor) as an HTTP server
  on loopback, plus a Node CLI (`jdt`) the agent drives day to day. Unlike `jdtls` above, this
  needs a real running Eclipse instance behind it — that's what Xvfb is for.

`jdtbridge` has no command to *import* a new project into Eclipse's workspace, though — that
still needs Eclipse's own GUI (`File → Import → Existing Maven Projects`, for example), and
it's also the only way to get a real graphical Java debugger (breakpoints, variable
inspection) rather than just console output. For that, the same Xvfb display Eclipse already
runs on is exposed over VNC (`x11vnc` + `websockify`/noVNC) — see [Eclipse GUI
access](README.md#eclipse-gui-access-backend-via-novnc) in the README for the commands to
enable and reach it.

Once a project is imported this way, `jdt`/`jdtbridge` picks it up immediately — the import
step and the CLI share the same running Eclipse instance and workspace
(`backend-eclipse-workspace` volume).

**What you will and won't see live over noVNC**: the agent doesn't type inside Eclipse's
editor — it writes files directly under `/workspace` with its own tools. Eclipse only
reflects those changes once refreshed (`jdt refresh`, or its own file-watcher if enabled), so
noVNC shows you the current indexed/compiled/debug state, not a live keystroke-by-keystroke
view. For watching the agent's own terminal in real time, use `python setup.py --tmux
backend` instead.
