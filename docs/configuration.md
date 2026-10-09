# Configuration reference

Every `.env` variable, Azure DevOps authentication and per-agent packages. Summary: [README](../README.md#configuration-env).

## Configuration (`.env`)

`setup.py --init` walks through every variable in `.env.example`, proposing its value as
the default (Enter accepts it); it writes the result to `.env` (backing up any existing one
to `.env.bak` first). Variables with a closed set of options — `BACKEND_STACK` today — are
asked as a numbered menu instead of free text, and the answer is validated there rather than
failing later during `docker compose up`. You can also skip it and copy/edit `.env.example`
by hand. Variables:

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Optional — see [Authentication](../README.md#authentication) below. |
| `CONTAINER_PREFIX` | Prefix for the 5 container names (default `pi`, i.e. `pi-manager`, ...). Change it to run several instances of this project on the same machine without name clashes. |
| `BACKEND_STACK` | Language/toolchain of the `backend` role: `java` (default), `kotlin` or `python`. Picks which image that container is built from and which team context its agent boots with — see [Backend stack](stacks.md#backend-stack). Optional: an `.env` without it behaves exactly as before, building the Java image. |
| `FRONTEND_STACK` | Framework of the `frontend` role: `angular` (default) or `nextjs`. Same mechanism as `BACKEND_STACK` — see [Frontend stack](stacks.md#frontend-stack). Also optional. |
| `<ROLE>_REPO_URL` | Git remote (origin) URL for that role's real repository — SSH or HTTPS. Exposed inside each container as `REPO_URL`. Empty until each role's repo/stack is decided. `/workspace` is a named Docker volume (`<role>-workspace`), not a bind mount to this repo, so it's always empty on first run: `python setup.py --git-clone` clones it there for every role that has one set (or let the agent do it itself) without worrying about clashing with anything this project mounts — pi's own per-role state (`AGENTS.md`, extensions, login) lives entirely under `~/.pi/agent` instead, never under `/workspace`. |
| `<ROLE>_GIT_TOKEN` | Access token (PAT) for that role's `REPO_URL` when it's `https://` — scope it to just that one repo (GitHub fine-grained PAT, or an Azure DevOps PAT limited to `Code: Read & Write`). Exposed inside each container as `GIT_TOKEN`; `entrypoint.sh` wires it into a git credential helper that reads it from the environment at auth time, so it's never written to the remote URL or `.git/config`. Leave it empty and use an SSH `REPO_URL` instead if you'd rather set up SSH manually for a given role — the two don't conflict. |
| `ADO_ORGANIZATION_URL`, `ADO_PROJECT` | Shared Azure DevOps organization/project (see `docs/work-procedures.md`). Exposed as-is inside every container; `entrypoint.sh` runs `az devops configure --defaults organization=$ADO_ORGANIZATION_URL project=$ADO_PROJECT` automatically on every start, so `az boards`/`az repos` commands don't need `--organization`/`--project` in that role's session. |
| `<ROLE>_ADO_PAT` | Azure DevOps PAT for that role, used by `az boards`/`az repos` inside its container — see [Azure DevOps CLI authentication](#azure-devops-cli-authentication) below for exactly which scopes each role needs. Exposed inside each container as `ADO_PAT`; `entrypoint.sh` maps it to `AZURE_DEVOPS_EXT_PAT`, the environment variable az CLI's `azure-devops` extension reads automatically — no `az devops login` needed, and it's never written to disk. |
| `BACKEND_VNC_PASSWORD`, `BACKEND_VNC_PORT`, `BACKEND_VNC_BIND` | **`BACKEND_STACK=java` only** — VNC/noVNC access to the `backend` container's headless Eclipse (see [Eclipse GUI access](access.md#eclipse-gui-access-backend-java-variant-via-novnc) below). Empty password = VNC disabled (default). Port defaults to `6080`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). Other stacks ship no GUI, so these do nothing there. |
| `FRONTEND_PORT`, `FRONTEND_BIND` | Access to the `frontend` container's dev server (see [Frontend dev server access](access.md#frontend-dev-server-access) below). Same accessibility criteria as the backend VNC variables above: port defaults to `4200`; bind defaults to `127.0.0.1` (set to `0.0.0.0` if running Docker inside WSL2). |
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
