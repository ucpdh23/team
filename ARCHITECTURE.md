# Architecture

Technical/internal detail for **team-pi**: how the 5 containers discover and talk to each
other over pi-link, how a role can ship more than one language variant of its image, how the
`java` backend's headless Eclipse (`jdtbridge`) is wired up, and how the `console` container
watches all of it without taking part. For what this project is, why it's organized into 5
roles, and the commands to actually run it, see [`README.md`](README.md).

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

A sixth container, **`console`**, shares that network without being part of the mesh: it runs
no `pi`, no broker, and never competes for the hub lock. It observes and schedules — see
[`console`: watching the team](#console-watching-the-team) below.

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

## Stack variants

A role's **place in the team** is fixed; the **technology it works in** isn't. `backend` and
`frontend` each carry a variant selector — `BACKEND_STACK` (`java` by default, plus `kotlin`
and `python`) and `FRONTEND_STACK` (`angular` by default, plus `nextjs`) — and both resolve
entirely through Compose's own variable interpolation: no override files, no profiles, no
second service definition.

```yaml
build:
  dockerfile: docker/Dockerfile.backend.${BACKEND_STACK:-java}
image: team-pi-backend-${BACKEND_STACK:-java}
volumes:
  - ./agents/backend/AGENTS.${BACKEND_STACK:-java}.md:/root/.pi/agent/AGENTS.md
```

So a variant is exactly **two files** — the image that builds its toolchain
(`docker/Dockerfile.<role>.<stack>`) and the team context its agent boots with
(`agents/<role>/AGENTS.<stack>.md`) — and nothing else in the service changes: same
container name, same network, same volumes, same pi-link wiring, same Azure DevOps
credentials. That's the point: the stack decides what's *inside* the container, never the
role's place in the team, so the other four agents don't need to know or care which one is
running.

Three consequences worth stating explicitly:

- **The `:-java`/`:-angular` defaults are load-bearing.** An existing `.env` written before
  this mechanism existed has neither variable and keeps building the same images as before —
  they're optional, not required.
- **A variant is only offered once both files exist.** `setup.py --init` carries no hardcoded
  list: `discover_stacks(role)` globs `docker/Dockerfile.<role>.*` and keeps the stacks that
  also have a matching `agents/<role>/AGENTS.<stack>.md`, then asks as a numbered menu and
  validates the answer. `python` was added exactly that way — two files, nothing else.
- **Extending the mechanism to a second role cost one line.** `ENV_CHOICES` maps a variable
  name to a function returning its options, so `frontend` joined by adding
  `"FRONTEND_STACK": lambda: discover_stacks("frontend")`. A third role would be the same.

The two roles lean on the mechanism to very different degrees, and it's worth being honest
about that. The backend variants diverge by entire toolchains — different compilers, build
tools and language servers, gigabytes apart. The frontend ones are both Node and both test on
jsdom, so their images differ by little more than which CLI is installed globally; the
substantial divergence there is each variant's `AGENTS.md` — how to start the dev server and on
which port, and, for Next, that server-side and browser-side code don't reach the API by the
same hostname. They're still kept as two images rather than one parameterized image: it keeps a
single mechanism across both roles, avoids leaving one framework's CLI inside the other's
container, and lets either diverge further later without a redesign.

One assumption worth not inheriting: a browser is **not** part of the `angular` image. `ng test`
on Angular 20+ goes through the `@angular/build:unit-test` builder (vitest on jsdom) and needs
none — verified by scaffolding with `ng new` and running `ng test` with no Chromium present.
Only an older, Karma-based Angular would need one, and `docker/Dockerfile.frontend.angular`
carries the exact two lines to add it, commented out, rather than shipping ~790 MB of browser
against a maybe. Real browser testing belongs to `cypress`, which has its own image.

What the variants don't share is the GUI machinery. The `java` image carries a full headless
Eclipse (next section) and therefore Xvfb, x11vnc and noVNC; `kotlin` and `python` carry none
of it — Eclipse's Kotlin support is discontinued, Python was never in that ecosystem, and the
equivalent in both is a plain LSP server (Kotlin Language Server, pyright) that needs no
framebuffer. `entrypoint.sh` is shared by all
variants all the same: its whole Eclipse/VNC block is already gated on `/opt/eclipse/eclipse`
existing in the image, so on a Kotlin or Python container it simply doesn't run — no
per-variant entrypoint is needed. For the same reason the `backend` service keeps its `6080` port mapping
and its `backend-eclipse-workspace` volume unconditionally: on a variant with no Eclipse
nothing listens on that port and the volume is one more empty directory, which is a smaller
price than splitting the service definition in two.

## Java code intelligence in `backend`: jdtbridge + headless Eclipse

Everything in this section applies to the **`java` backend variant only**
(`BACKEND_STACK=java`, the default) — see the previous section. The `java` backend's toolchain (see
`docker/Dockerfile.backend.java` and
[`agents/backend/AGENTS.java.md`](agents/backend/AGENTS.java.md)) includes two independent
layers of Java tooling:

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
access](README.md#eclipse-gui-access-backend-java-variant-via-novnc) in the README for the commands to
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


## `console`: watching the team

The sixth container in `docker-compose.yml` is not an agent. It runs no `pi`, has no tmux
session, no workspace and no repository, and takes no part in the pi-link mesh. What it does
is answer the questions the team cannot answer about itself: what is running, what is it
costing, who is talking to whom, and what should happen at eight in the evening.

For what each tab shows and how to configure it, see [The console](README.md#the-console) in
the README. What follows is why it is built the way it is.

### Three channels, kept separate on purpose

| Channel | Direction | Carries |
|---|---|---|
| `POST /api/events` | agent → console | Who talked to whom, through a pi extension |
| `POST /api/inbox/take` + `/ack` | agent → console | The agent collecting scheduled notices for itself |
| `GET http://<hub>:9901/status` | console → mesh | Each agent's live state, read-only |
| Docker socket | console → host daemon | Container inventory, network, disk, tmux panes |

The direction matters: **the agents call the console, never the other way round**. That is
what makes the console optional infrastructure — if it is down or being rebuilt, the five
agents keep working and nothing about their behaviour changes.

### Why the console does not join the mesh

Sending a message over pi-link requires registering: the hub drops anything arriving from an
unregistered socket, and it overwrites the `from` field with the name the sender registered
under, so there is no "just send one message". And registering is not free — it broadcasts
`terminal_joined` and puts the console in all five agents' `link_list`, where `manager`, whose
job is handing work to whoever it sees connected, would eventually try to delegate to it.
Hiding in another pi-link group (`console@ops`) does not help either: group isolation blocks
routing between groups, so the console would be invisible *and* mute.

So the console never registers. Instead, the extension every agent already carries polls
`/api/inbox/take` for notices addressed to it and injects them with
`pi.sendMessage(..., { triggerTurn: true })` — the exact mechanism pi-link itself uses, so the
agent starts a turn even when idle. Beyond having no presence, this buys two things the
WebSocket route could not: an `ack`, so the console knows a notice was actually delivered, and
a notice for a stopped agent waiting in the queue instead of failing with "terminal not found".

`triggerTurn` is load-bearing rather than cosmetic. A custom message only reaches the agent —
and therefore other extensions — when it goes through the agent: `_appendCustomMessage()` in
pi's `agent-session.js` calls `_emit()`, which walks the UI listeners only, while extension
events come from `_handleAgentEvent`, subscribed to the agent. Anything injecting custom
messages later must go through the agent or it will be invisible to everything but the screen.

For live state the console uses the hub's own `GET /status` (an HTTP endpoint the hub serves
on the port the broker already exposes). It is read-only, requires no registration, and
returns the full roster with each terminal's status and context usage — so the console can
show what every agent is doing without existing, as far as the mesh is concerned.

### What is recorded about the conversation

Only metadata: sender, recipient, timestamp, size. **Never the message text.** Fragments of
the projects the agents work on travel over that mesh — code, paths, occasionally a credential
being debugged — and none of it belongs in an observability database. The promise is enforced
where the data is stored, not left to the emitters: the ingest drops any field that looks like
it carries text, so a future emitter cannot smuggle a conversation in by accident.

The primary source is the **sending** side (`link_send`), which carries the exact recipient and
the real instant. The receiving side is complementary: it measures how long delivery took —
pi-link batches incoming messages in 200 ms windows and holds them during compaction — and it
still sees agents whose own extension is missing.

One extension file serves all five roles. `docker-compose.yml` mounts
`agents/_shared/pi/extensions/team-console` *inside* each role's existing extensions mount;
Docker applies bind mounts by path depth, so the role's own directory survives underneath, and
pi finds it because it also looks in `~/.pi/agent/extensions/<dir>/index.ts`.

### Docker-outside-of-Docker, again — and what it costs

The console mounts the host's Docker socket, exactly like `devops` (see the section above and
its security note, which applies here word for word: anything that can talk to that socket has
root-level control of the host). It is what makes four things possible that pi-link cannot
answer: the container inventory including **stopped** agents, CPU/memory, the network and disk
usage, and `exec` for the tmux mosaic. No `docker` client is installed — the API is HTTP over
a unix socket, spoken with `http.client`, including the 8-byte framed stream that `exec`
answers with.

The difference from `devops` is that here there is a web in front of the socket, which is why:
the port is published on loopback by default, the cron can only run scripts already present in
the mounted catalog (there is no free-form command field), and starting with the port bound
beyond loopback without a `CONSOLE_TOKEN` prints a warning.

### Identifying the team

A container belongs to the team if Compose created it (label
`com.docker.compose.container-number`, which Compose writes on containers and never on images)
**and** it either shares the console's Compose project or starts with `CONTAINER_PREFIX`. Both
criteria are used because each fails alone: a team started from another checkout is only found
by the prefix, and containers created before someone changed `CONTAINER_PREFIX` are only found
by the project. The `container-number` requirement is what keeps a plain
`docker run team-pi-manager` out of the table — Compose stamps `project` and `service` onto the
images it builds, and containers inherit their image's labels.

### Storage

One SQLite file in the `console-data` volume holds everything the console has to remember:
message metadata, the notice queue, cron jobs, their runs and the scripts' persistent state.
SQLite rather than the JSONL files `cost-tracking/` uses, because here a single process writes
— the JSONL format exists there precisely because five containers write at once — and because
every refresh aggregates by agent, by pair and by time window, which in JSONL means re-reading
the whole history each time. Costs stay where they are: they are read from the same `.jsonl`
files the agents write, with no second source of truth.

## `devops`: Docker-outside-of-Docker

`devops` needs to be able to stand up real infrastructure for the project it's working on —
typically a database (e.g. MySQL) that `backend` connects to during development — without
that being pre-baked into this repo (each project's actual infra needs are unknown ahead of
time). The `devops` container is given the ability to run **sibling containers** on the
host's own Docker daemon for that.

### Docker-outside-of-Docker (DooD), not Docker-in-Docker (DinD)

Rather than running a **nested** `dockerd` inside the `devops` container (true DinD — which
needs `privileged: true`, effectively giving that container full control over its own kernel
namespace and a meaningfully larger blast radius if compromised), `docker-compose.yml` mounts
the **host's own Docker socket** into it:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

The `docker`/`docker compose`/`docker buildx` **client** binaries are installed in
`docker/Dockerfile.devops` (no engine); every command `devops` runs is actually executed by
the **host's** Docker daemon. A container `devops` starts this way (e.g. `docker run mysql:8
...`) is a **sibling** of the 5 team containers — living directly in the host's Docker,
not nested inside `devops` — which is exactly why it can be reachable by `backend` at all.

**Security implication, explicitly**: mounting the host's Docker socket is equivalent to
giving that container root-level control over the host (anything that can talk to the
Docker socket can, among other things, mount the host's filesystem into a new container and
read/write it as root). This is an intentional, accepted trade-off for the `devops` role
specifically — it's the one role whose job is infrastructure — not something extended to any
other container in this project.

### Reaching sibling containers from the rest of the team

All 5 team containers are attached to one explicit, named bridge network
(`docker-compose.yml`'s top-level `networks: team-net`, real Docker name
`${CONTAINER_PREFIX:-pi}-net`) instead of relying on Compose's implicit per-project default
network, precisely so `devops` has a **stable, predictable name** to attach new containers
to — it doesn't need to inspect `docker network ls` or guess a Compose-generated name.
That name is exposed inside the `devops` container as the `TEAM_NETWORK_NAME` environment
variable. To make a new container reachable by `backend` (or anyone else on the team):

```bash
docker run -d --name devops-mysql --network "$TEAM_NETWORK_NAME" \
  -e MYSQL_ROOT_PASSWORD=... mysql:8
```

Because `team-net` is a **user-defined bridge network** (as opposed to Docker's legacy
`bridge` default network), Docker's embedded DNS resolves container names automatically for
anything else attached to that same network — so `backend` reaches it simply at host
`devops-mysql`, port `3306`, no manual IP wiring, `--link`, or extra `ports:` publishing
needed. This holds for any container `devops` starts this way, not just a database.

`docker-compose.yml`'s own default network (created implicitly when no `networks:` section
exists) would have worked too, but its name depends on the Compose project name (usually the
repo's directory name), which isn't guaranteed stable across machines/checkouts — the
explicit `team-net` name removes that guesswork.
