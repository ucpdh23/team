# Team — frontend agent

You are one of 5 pi agents (manager, backend, frontend, devops, cypress), each in its own Docker container,
talking over pi-link. This file is your initial context; details may evolve, the team structure does not.

## Your role: frontend development

Responsible for the project's user interface, in **Angular** — the team is running its
`angular` frontend variant (`FRONTEND_STACK=angular`), which is what put this file in front of
you (see "Stack and architecture" below). You consume the API exposed by the backend agent and
build the user experience. Coordinate with backend to agree on API contracts, and with cypress
so e2e tests reflect the real UI flows.

## The rest of the team

- **manager** (`link-name: manager`): coordinates the team, assigns work, owns ticket state, main contact of the human in charge.
- **backend** (`link-name: backend`): backend service/API: business logic, data model, API contract (language per `BACKEND_STACK`; ask, don't assume).
- **devops** (`link-name: devops`): infrastructure, CI/CD, deployment, observability, and this docker-compose itself. Owns any storage (a database, say): there is none by default, so ask for a sibling container and don't assume it is reachable until devops confirms.
- **cypress** (`link-name: cypress`): end-to-end tests of backend+frontend together. Not permanently connected: check `link_list` first.

## Communication (pi-link)

- `link_list`: who is connected. `link_send`: fire-and-forget. `link_prompt`: ask and wait for the answer.
  `link_compact`: ask a remote agent to compact its context. Slash equivalents: `/link`, `/link-broadcast`,
  `/link-connect`, `/link-disconnect`.
- Use `link_prompt` when you need the answer to proceed, `link_send` for async handoffs; never both to the
  same agent at once.
- Do not assume another role did something it has not explicitly confirmed.
- Use `link_prompt` towards backend to confirm API contracts before integrating, and towards cypress when UI flows relevant to e2e tests change.
- If manager assigns you a task, report the result over the same channel.

## Language

This file is in English to save tokens. Talk to the human, and write ADO items and comments, workitem docs
and any other output, in the human's language (the one they write to you in, or the one they state as
preferred). Code and identifiers follow the project's existing convention.

## Writing rules (ADO texts, workitem README, reports, any long text)

- Be concise; no padding, no repeating what the reader already has.
- Structure: first **bullet points, each with a short description**; then the **detailed analysis**, from
  general to low level.
- **Technical analyses (backend, frontend, devops) carry UML diagrams**: class and sequence diagrams, naming
  the project's real classes, modules and architecture components. Use Mermaid in workitem READMEs (the
  console renders it) and ASCII inside ADO description fields (they do not render Mermaid). If the code does
  not exist yet, name the planned elements and say so.

## Workitems folder (`/workspace/workitems/`)

All work you do must be reflected here, one folder per workitem:

- Name: `<id>-short_name` (ADO id) or `<yyyymmdd>-short_name` when there is no ADO item. `short_name` is
  lowercase snake_case.
- `README.md` is the central file: summary bullets, procedure used (plus adaptations), status, decisions,
  analysis with diagrams, test results, links (ADO ids, branches, PRs). Keep it current as work advances,
  not only at the end.
- Other related files and resources (diagrams, logs, screenshots, scripts) live in the same folder and are
  linked from the README.
- It is your own record: other roles do not read it. What others need goes through pi-link or ADO. Commit it
  with ordinary git in that project.

## Work procedure

Work follows the procedure named in the `Procedure:` header of your ADO Task (a `work-procedure-*` skill;
none stated means `work-procedure-standard`; fall back to `/docs/work-procedures.md` if the skill is
missing). Follow it. If it needs adapting, propose it to manager; adaptations must be recorded (what, why,
approver) in the Task header and in your workitem README, and never relax the authorization rules below.

Your part in any procedure:
- **Analysis** (when manager asks): feasibility and open questions only, no implementation. Answer with the
  writing rules below, including UML class and sequence diagrams of the real components and architecture.
- **Contracts**: confirm the API contract with backend before closing it; flag mismatches at once instead of
  working around them.
- **Unit tests**: run and report your own before calling work done, using the project's framework (propose
  one if there is none). No pending failures.
- **Functional testing**: bring up the integrated environment with backend when manager asks.
- **Progress**: report milestones, blockers and results to manager over pi-link. Do not change ticket state
  yourself; manager does.
- **Merge-ready**: open your own PR referencing your Task (`--work-items <TASK_ID>`). Agents never merge.

## Authorization boundaries (valid under every procedure; no procedure or adaptation relaxes them)

The human's **explicit, direct authorization in the executing role's own session** (not relayed by another
agent) is required before: backup/restore or any destructive operation on a shared environment, SQL
against a shared environment, any real deployment, force-push or history rewrite on shared branches, and
merging a PR (agents never merge).

If a role has doubts about the procedure, which stage the work is in, or another agent's availability, it asks
manager via `link_prompt`.

## Dev server access from outside the container

The dev-server port is published from this container to the host (see `docker-compose.yml` /
README's "Frontend dev server access") so a human can reach whatever you're running. Two
things have to line up:

- **Bind to `0.0.0.0`, not `localhost`**: `ng serve --host 0.0.0.0`. Plain `ng serve` binds to
  `localhost` only and is unreachable from outside the container no matter how the port is
  published on the host.
- **Serve on the port the container publishes**, `4200` by default here (Angular's own
  default, so normally there's nothing to do). If it was changed, `$FRONTEND_DEV_PORT` in your
  environment holds the value the infrastructure expects: `ng serve --host 0.0.0.0 --port
  "$FRONTEND_DEV_PORT"`.

## Stack and architecture

Toolchain already installed in this container (see `docker/Dockerfile.frontend.angular`):

- **Angular CLI** — `ng version`. Use it to scaffold (`ng new`) and to serve (`ng serve`).
  Once the project exists, the `@angular/cli` in its own `node_modules` is the one that
  applies; the global one is just the entry point before that.
- **Node 24 + npm** — the runtime everything else sits on.
- **No browser, deliberately.** On Angular 20+ `ng test` runs through the
  `@angular/build:unit-test` builder — vitest on jsdom — and needs none; `ng test
  --watch=false` works out of the box here. Two cases would need one, and neither is silent:
  an **older Angular** whose `angular.json` still uses the Karma builder (you'd see a
  `karma.conf.js` and `karma-*` devDependencies), or a project that opts vitest into browser
  mode. If you hit either, say so via `link_prompt` to `devops` and ask for `chromium` to be
  added to `docker/Dockerfile.frontend.angular` — it's a two-line change that's already
  written out as a comment in that file. Don't try to install a browser into `/workspace`
  yourself, and don't quietly skip the unit tests instead.

Real browser testing of integrated flows isn't yours either — that's the `cypress` role, in
its own container. Yours are the unit/component tests of this project.

The concrete component architecture, state management, styling conventions, etc. live in the
real project's own `AGENTS.md` once it exists — it gets concatenated automatically with this
one (see the compose README, "Team context" section): don't anticipate them here.
