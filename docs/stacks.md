# Backend and frontend stacks

How each role picks its language/framework. Summary: [README](../README.md#backend-stack).

## Backend stack

`backend`'s **role** in the team is fixed — the service/API, the data model, the contract
`frontend` consumes. The **language** it works in isn't, and is picked per project with
`BACKEND_STACK` in `.env`:

| `BACKEND_STACK` | Toolchain in the container |
|---|---|
| `java` (default) | Java 21 (Temurin), Maven, Eclipse JDT Language Server, and a full headless Eclipse with [jdtbridge](https://github.com/kaluchi/jdtbridge) driven through the `jdt` CLI — plus [GUI access over noVNC](access.md#eclipse-gui-access-backend-java-variant-via-novnc). |
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
never shows up in the menu. See [`ARCHITECTURE.md`](../ARCHITECTURE.md#stack-variants)
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
