# Connecting to the agents and their tools

tmux, VS Code, Eclipse over noVNC and the frontend dev server. Summary: [README](../README.md#connecting-to-an-agent).

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
no GUI (see [Backend stack](stacks.md#backend-stack)).

The `backend` container runs a full headless Eclipse with the
[jdtbridge](https://github.com/kaluchi/jdtbridge) plugin, driven day-to-day by the agent
through the `jdt` CLI (how it's wired up — Xvfb, the `jdtls`/`jdtbridge` split — is in
[`ARCHITECTURE.md`](../ARCHITECTURE.md#java-code-intelligence-in-backend-jdtbridge--headless-eclipse)).
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
[`ARCHITECTURE.md`](../ARCHITECTURE.md#java-code-intelligence-in-backend-jdtbridge--headless-eclipse)
for what noVNC does and doesn't show live; to watch the agent's own terminal in real time
instead, use `python setup.py --tmux backend`.

## Frontend dev server access

The `frontend` container publishes its dev-server port to the host, so you can connect to
whatever the agent has running there from outside the container — same accessibility criteria
as the backend VNC setup above:

1. Ports and bind are configurable via `FRONTEND_PORT`/`FRONTEND_DEV_PORT`/`FRONTEND_BIND` in
   `.env` (defaults: `4200`, `4200` and `127.0.0.1`) — see [Frontend
   stack](stacks.md#frontend-stack) for the difference between the two port variables. There's no
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
