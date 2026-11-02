# Work Procedures

This document describes, stage by stage, how a piece of work moves through the team-pi
team from "the human asks for something" to "it's merged and closed" — who does what, what
gets communicated over pi-link, and exactly what changes in Azure DevOps at each step. It's
written for a human joining the project, but it's also the procedure the agents themselves
are expected to follow.

If you haven't read [`introduction.md`](introduction.md) yet, start there for the high-level
picture of the team. This document assumes you already know who the five roles are.

## What's shared, what's private

Coordination between roles and record-keeping for a piece of work don't live in the same
place:

- **Azure DevOps (Boards)** is the *only* cross-role shared source of truth. The User
  Story/Bug being worked on, the Tasks that break it into per-role work, comments for open
  questions, and the Pull Requests that implement it — that's what any role (or a human
  stakeholder) looks at to know what's being worked on, by whom, and whether it's done.
- **pi-link** is how roles actually talk to each other while work is in progress —
  synchronous questions (`link_prompt`), async handoffs (`link_send`), presence
  (`link_list`). It's the conversation; Azure DevOps is the record of what the conversation
  produced.
- **Each role's own `workitems/` folder**, inside its own project workspace
  (`/workspace/workitems/`), is that role's **record of the work**: every piece of work it does is
  reflected there, one folder per workitem. It is not shared: other roles do not read it, anything that
  must cross roles goes through pi-link or Azure DevOps. It is versioned in that project's own git.

```
workitems/
  <id>-short_name/            # ADO id, or <yyyymmdd>-short_name when there is no ADO item
    README.md                 # central file: summary bullets, procedure + adaptations, status,
                              # decisions, analysis with diagrams, test results, links (ADO, branches, PRs)
    ...                       # related files and resources (diagrams, logs, screenshots), linked from README
```

### Azure DevOps configuration

This template doesn't hardcode an organization or project — that's specific to whoever
deploys it. Before the team can use Azure Boards for real, set the defaults once (per
container, or bake them into your own fork of this repo):

```bash
az login
az devops configure --defaults organization=https://dev.azure.com/<your-org> project=<your-project>
```

All `az boards` / `az repos` examples below omit `--organization`/`--project` for
readability, assuming this default is set; add them explicitly if you prefer not to rely on
the default.

## Roles and objectives, stage-independent

These are each role's standing objectives — what it's *for*, regardless of which stage a
given piece of work is in:

| Role | Objective |
|---|---|
| **manager** | Turn ambiguous human goals into a scoped, tracked piece of work; keep Azure DevOps accurate and current as the single shared record; detect and escalate blockers; never let a role start implementing before scope is agreed. |
| **backend** | Deliver a correct, tested API/service change; keep the contract with `frontend` explicit and versioned; never merge without its own unit tests passing. |
| **frontend** | Deliver a correct, tested UI change that matches the agreed contract with `backend`; flag any contract mismatch immediately instead of working around it silently. |
| **devops** | Keep infrastructure, environments and pipelines consistent with what backend/frontend need; execute anything destructive (DB resets, deployments) only with explicit human authorization, never unilaterally. |
| **cypress** | Independently verify that backend and frontend actually work together from a user's perspective; report failures precisely enough (which step, which screenshot) that they're actionable. |

## Work procedures

There is not one single procedure: each is a **skill** in `agents/_shared/pi/skills/`, visible to every
role, and each piece of work picks the one that fits.

| Skill | Use it for |
|---|---|
| `work-procedure-standard` | Default. Features, non-trivial fixes, refactors: the 8 stages `analysis → approved → branches-created → implementing → unit-testing → functional-testing → merge-ready → completed`, with all `az` commands and the Task/diagram conventions. |
| `work-procedure-minor-fix` | Literals, an icon, a style tweak, a typo: one Task, no question round, minimal verification. |
| `work-procedure-hotfix` | Urgent defect in a live or shared environment: short triage, branch from production, regression test, post-fix report. |
| `work-procedure-spike` | Time-boxed investigation: the deliverable is a report with options and a recommendation, nothing merged. |
| `work-procedure-infra-only` | Infrastructure/CI/CD changes carried out by devops alone. |

**How a piece of work picks one.** `manager` chooses the procedure when it creates the ADO Task and writes
it at the top of the Task description:

```
Procedure: work-procedure-hotfix
Adaptations: Omitted cypress run. Reason: no UI impact. Approved by: manager (2026-11-02)
```

- No `Procedure:` line means `work-procedure-standard`.
- A procedure can be adapted when the case requires it. The adaptation (what changes, why, who approved)
  is recorded in the Task header and in the role's workitem README. Any role may propose one; `manager`
  decides. An adaptation touching an action that needs the human's authorization must be approved by the
  human.
- No adaptation, and no procedure, relaxes the [authorization boundaries](#authorization-boundaries).

**Who keeps ticket state.** `manager` owns the state of the User Story/Bug and Tasks and closes them. Other
roles report progress to `manager` over pi-link; `manager` gathers it in its own workitem README and
publishes to ADO at meaningful points (questions after analysis, Tasks on approval, milestone or blocker
summaries, closing summary) instead of on every message.

**How long texts are written.** Short: bullet points with a short description first, then the detailed
analysis from general to low level. Technical analyses (backend, frontend, devops) include UML class and
sequence diagrams naming the project's real classes and architecture: Mermaid in workitem READMEs, ASCII
in ADO fields.

## Naming conventions

| What | Convention | Example |
|---|---|---|
| Azure DevOps Task title | `[<role>] <short description>` | `[frontend] Add discount code field to checkout form` |
| Feature branch | `feature/<task-id>-<slug>` | `feature/482-checkout-discount-codes` |
| Workitem folder (per role, private) | `workitems/<id>-short_name/` or `workitems/<yyyymmdd>-short_name/` | `workitems/482-checkout_discount_codes/` |

## Communication protocol (pi-link)

- Use `link_prompt` when you need a **synchronous** answer before you can proceed (e.g.
  asking `frontend` to confirm a field name before finalizing an API contract).
- Use `link_send` (with `triggerTurn: true`) to **hand off work asynchronously** and expect a
  callback when it's done, rather than blocking on it.
- **Never mix the two on the same terminal at once** — don't send a `link_send` and then a
  `link_prompt` to the same agent before the first one reports completion. It creates
  ambiguity about which request a reply is answering.
- Use `link_list` at the start of any coordination to confirm who's actually connected right
  now — terminal availability (especially `cypress`, which isn't permanently connected) can
  change between sessions.
- Don't assume another role has verified something it hasn't **explicitly** confirmed in its
  own message (e.g. don't assume a database backup happened because it was requested — wait
  for `devops` to confirm it did).

## Authorization boundaries

Some actions always require the human's **explicit, direct** authorization in the relevant
role's own session — not an instruction relayed by another agent, and not an assumption based
on the work having been approved in general:

- Any backup/restore or destructive operation against a shared or production-like
  environment.
- Executing SQL directly against any environment beyond the agent's own local workspace.
- Force-pushing, rewriting shared branch history, or merging a Pull Request.
- Any deployment to a real environment.

**Exception — `*IT` / integration tests that mutate a real database.** `manager`'s request is enough for
`backend` to run them; no separate human authorization is needed for the run itself. What changes is
supervision:

- **Automatic, unsupervised execution**: a backup before and a restore after, coordinated with `devops`, are
  **mandatory**.
- **Step-by-step execution supervised by the human**: the human decides whether backup/restore is needed,
  since they know the application's state and their intention better.

If such an instruction arrives at a role secondhand (e.g. relayed by `manager` on the
human's behalf) and that role doesn't already have standing authorization for that specific
action, it asks the human directly in its own session before proceeding. This is a safety
property of the workflow, not an inconvenience to route around.

## Worked example

To make this concrete: suppose the human tells `manager`, "add a way for users to apply a
discount code at checkout."

1. **Analysis** (`work-procedure-standard`) — `manager` asks `backend` and `frontend` to assess feasibility. `backend`
   asks whether codes can stack; `frontend` asks whether the discount should show inline or
   as a separate confirmation step. `manager` consolidates both into one comment on the
   linked User Story and waits.
2. The human answers in Azure DevOps: codes don't stack, show inline. `manager` reads it
   there, confirms both questions are resolved.
3. **Approved** — `manager` creates two self-contained Tasks — `[backend] Add discount-code
   validation to checkout` and `[frontend] Add discount code field to checkout form`, each
   with the settled decisions and an ASCII flow diagram written into its description — both
   linked to the parent User Story, which moves to Active.
4. **Branches created** — `backend` and `frontend` each create
   `feature/<task-id>-checkout-discount-codes`.
5. **Implementing** — `backend` builds the validation endpoint; `frontend` builds the field
   and wires it up, confirming the response shape directly with `backend` over `link_prompt`
   along the way. They tell `manager` when they start, and `manager` moves their Tasks to Active.
6. **Unit testing** — both run their own unit tests; `backend`'s pass, `frontend` finds a bug
   in its own validation-message rendering and fixes it before reporting done.
7. **Functional testing** — `manager` asks `backend` and `frontend` to run together locally,
   then asks `cypress` (confirmed present via `link_list`) to validate the checkout flow
   visually. Everything passes.
8. **Merge-ready** — both open PRs referencing their own Task IDs.
9. **Completed** — the human reviews and merges both PRs; `backend` and `frontend` tell `manager`,
   who closes both Tasks and moves the User Story to Resolved, noting in a closing comment
   that discount-code stacking might come up again later as a follow-up request.
