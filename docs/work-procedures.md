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
  (`/workspace/workitems/`, i.e. part of `backend`'s own repo, `frontend`'s own repo, and so
  on) is a **private activity log** — not shared, not mounted for any other role to see, not
  required by this procedure. It's simply a place for an agent to keep its own notes on what
  it worked on and why, versioned in that project's own git history (managed by the agent
  itself via ordinary git commands), useful mainly for that role's own future reference. Two
  roles working on the same piece of work do **not** read each other's `workitems/` —
  anything that needs to cross that boundary goes through pi-link or Azure DevOps instead.

If you keep a private `workitems/` log, the same lightweight convention as before still works
well for it — it's just no longer part of how the team coordinates:

```
workitems/
  <YYYY-MM-DD>-<short-slug>/
    README.md          # what you did, why, decisions, links to the Task(s) involved
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

## The eight stages

Every piece of work — a new feature, a bug fix, a non-trivial refactor — moves through these
stages in order. Trivial changes (a typo, a one-line doc fix) don't need the full ceremony;
use judgment, and when in doubt, run the full procedure — skipping it is the more expensive
mistake.

```
analysis → approved → branches-created → implementing → unit-testing
   → functional-testing → merge-ready → completed
```

### 1. Analysis

**Goal:** turn a vague human request into a scoped, unambiguous piece of work, without
writing any code yet.

**Who's involved:** `manager` drives; any role that's plausibly affected is consulted.

**What happens:**
1. The human gives `manager` a goal or requirement (in chat, or by pointing at an existing
   Azure DevOps User Story/Bug).
2. `manager` identifies which roles are plausibly affected (not every piece of work touches
   all four specialists) and asks each one, via `link_prompt`, to assess technical
   feasibility and raise any open question — **implementation does not start here**.
3. `manager` consolidates every role's open questions into a single list, removing
   duplicates and grouping by topic.
4. If there's a corresponding Azure DevOps User Story/Bug, `manager` publishes the
   consolidated list as a **comment** on that ticket (not as a Task — see "Comments vs.
   Tasks" below) and waits for the human to answer directly in Azure DevOps.
5. When the human replies, `manager` reads the actual comment in Azure DevOps (never assumes
   a verbal summary is complete) and checks it question by question against the list. Any
   ambiguity or missing answer triggers a new comment round — this can iterate more than
   once.

**Azure DevOps changes:** one or more comments added to the parent User Story/Bug (no Tasks
yet, no status change on the ticket itself). The comment thread itself is the record of what
was asked and answered — no separate document is needed to track it.

**Exit criteria:** every open question has an explicit, unambiguous answer.

#### Comments vs. Tasks

This distinction matters enough to call out on its own: **comments** are for open questions
that need a human decision before scope can be closed. **Tasks** are for technical work that
is already fully defined. Never create a Task just to ask something — it pollutes the board
with items that don't represent real, startable work, and it hides genuine open decisions
inside what looks like a work item.

### 2. Approved

**Goal:** lock in the scope, and translate it into trackable Azure DevOps work.

**Who's involved:** `manager`.

**What happens:**
1. The human gives an explicit go-ahead (in chat, or by resolving the ticket's discussion).
2. `manager` creates the Azure DevOps Task breakdown: one or more Tasks per affected role,
   each titled with the role's prefix (see naming conventions below). Since there's no
   separate shared document to point to, **each Task's description must stand on its own**:
   summary of the change, affected modules/files, and acceptance criteria — written as
   settled decisions, not open questions.
3. Each Task is linked as a **child** of the parent User Story/Bug.
4. If a User Story/Bug exists, `manager` moves it to **Active**.

**Azure DevOps changes:** N Tasks created (one set per affected role), each self-contained
and `parent`-linked to the User Story; the User Story itself moves to **Active**.

```bash
# Create a Task for a given role (repeat once per role/subtask)
az boards work-item create \
  --type Task \
  --title "[backend] Add discount-code validation to checkout" \
  --description "Add server-side validation for discount codes at checkout. Codes do not \
stack. Affects CheckoutService and the /api/checkout endpoint. Acceptance: invalid/expired \
codes return a 422 with a clear error; valid codes reduce the order total correctly." \
  --output json   # capture the returned id

# Link it as a child of the parent User Story
az boards work-item relation add \
  --id <TASK_ID> \
  --relation-type parent \
  --target-id <USER_STORY_ID>
```

**Exit criteria:** all Tasks exist in Azure DevOps, linked to the parent ticket, and every
affected role agrees its Task's acceptance criteria are clear enough to start branching.

### 3. Branches created

**Goal:** give every affected role an isolated place to work.

**Who's involved:** each affected role creates its own branch; `manager` tracks it.

**What happens:** each role creates a feature branch following the project's naming
convention (see below) off the appropriate base branch, and reports the branch name back to
`manager` over pi-link.

**Azure DevOps changes:** none required at this point (some teams also link the branch to
its Task in the Repos UI — optional, not required by this procedure).

**Exit criteria:** every affected role has a branch and knows its own Task ID.

### 4. Implementing

**Goal:** each role does its actual work.

**Who's involved:** each affected role, coordinating directly with each other over pi-link
where their work touches a shared boundary (e.g. `backend` and `frontend` agreeing on a
request/response shape) — this doesn't need to be routed through `manager`.

**What happens:**
1. Each role moves its own Task(s) to **Active** in Azure DevOps when it actually starts
   working on them (not before — an Active Task should mean active work, not "queued").
2. Roles implement against the acceptance criteria written in their Task.
3. `manager` doesn't sit idle here: it periodically checks in (`link_prompt` /
   `link_list`) with each role, and escalates to the human immediately if a role reports a
   blocker — it does not wait for a status-check cadence to surface a blocker. If a blocker
   or scope adjustment is significant enough to matter later, `manager` records it as a
   comment on the relevant Task.

**Azure DevOps changes:** each involved Task moves to **Active** (independently, whenever
that role actually starts).

**Exit criteria:** every affected role reports its implementation complete and ready for its
own unit tests.

### 5. Unit testing

**Goal:** each role verifies its own change in isolation before it's considered done.

**Who's involved:** each affected role runs its own unit tests; `manager` collects results.

**What happens:** each role runs the unit tests relevant to its change (not necessarily the
full suite) and reports pass/fail to `manager` over pi-link. Failures are fixed before moving
on — this stage does not "pass" partially.

**Azure DevOps changes:** none required (Task stays Active).

**Exit criteria:** unit tests pass for every affected role.

### 6. Functional testing

**Goal:** verify the pieces actually work together, not just in isolation.

**Who's involved:** `manager` coordinates; `backend` and `frontend` bring their pieces up
together; `cypress` (when the change is UI-observable) runs end-to-end verification.

**What happens:**
1. `manager` asks `backend` and `frontend` to have their environments ready together (e.g.
   both running locally against the same data).
2. If the change is visible in the UI, `manager` asks `cypress` to validate it — remember
   `cypress` is not a permanently-connected agent (see `introduction.md`); check `link_list`
   before assuming it's available, and don't treat a Cypress failure alone as proof of a
   business-logic regression — it's evidence of a UI/selector/timing problem until shown
   otherwise. Business-logic correctness is confirmed by backend/frontend's own functional
   tests, not by Cypress.
3. Any defect found here goes back to stage 4 for the affected role(s) — this stage doesn't
   advance until the integrated behavior is correct.

**Azure DevOps changes:** none required (Task stays Active); a defect found here that's
significant enough to track independently can be filed as its own Bug, linked back to the
parent User Story.

**Exit criteria:** the integrated behavior matches the accepted scope from stage 1–2, with no
open defects.

### 7. Merge-ready

**Goal:** get the changes in front of a human reviewer.

**Who's involved:** each affected role opens its own Pull Request.

**What happens:** each role pushes its branch and opens a PR against the base branch,
referencing its own Task ID in the PR description/work-item link. No PR is merged by an
agent — merging is always a human decision.

**Azure DevOps changes:** none required beyond the PR itself being linked to its Task (most
`az repos pr create` invocations can do this via `--work-items`).

```bash
az repos pr create \
  --repository <repo-name> \
  --source-branch feature/<task-id>-checkout-discount-codes \
  --target-branch main \
  --title "Add discount-code validation to checkout" \
  --description "Implements <TASK_ID>." \
  --work-items <TASK_ID>
```

**Exit criteria:** every affected role's PR is open and passing CI; nothing is pending except
human review.

### 8. Completed

**Goal:** close the loop, formally.

**Who's involved:** each role closes its own Task once its PR is merged; `manager` closes
out the parent ticket.

**What happens:**
1. As each PR is approved and merged by a human, the owning role moves its own Task to
   **Closed**.
2. Once every Task under the User Story is Closed, `manager` moves the parent User Story/Bug
   to **Resolved** (or **Closed**, depending on the team's Azure DevOps process template),
   adding a short closing comment if anything non-obvious came up (a workaround, a bug in a
   dependency, a decision that might be revisited) — this is what future analysis stages will
   read before repeating a mistake. Any role can also log this in its own private
   `workitems/` if it's useful for its own future reference — that part is optional and
   personal.

**Azure DevOps changes:** all Tasks Closed; parent User Story/Bug moved to Resolved/Closed.

**Exit criteria:** none — this is the end state.

## Naming conventions

| What | Convention | Example |
|---|---|---|
| Azure DevOps Task title | `[<role>] <short description>` | `[frontend] Add discount code field to checkout form` |
| Feature branch | `feature/<task-id>-<slug>` | `feature/482-checkout-discount-codes` |
| Personal workitem folder (optional, private, per-role) | `workitems/<YYYY-MM-DD>-<short-slug>/` | `workitems/2026-08-30-checkout-discount-codes/` |

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

- Running tests that mutate a real/shared database (integration tests, `*IT`-style suites).
- Any backup/restore or destructive operation against a shared or production-like
  environment.
- Executing SQL directly against any environment beyond the agent's own local workspace.
- Force-pushing, rewriting shared branch history, or merging a Pull Request.
- Any deployment to a real environment.

If such an instruction arrives at a role secondhand (e.g. relayed by `manager` on the
human's behalf) and that role doesn't already have standing authorization for that specific
action, it asks the human directly in its own session before proceeding. This is a safety
property of the workflow, not an inconvenience to route around.

## Worked example

To make this concrete: suppose the human tells `manager`, "add a way for users to apply a
discount code at checkout."

1. **Analysis** — `manager` asks `backend` and `frontend` to assess feasibility. `backend`
   asks whether codes can stack; `frontend` asks whether the discount should show inline or
   as a separate confirmation step. `manager` consolidates both into one comment on the
   linked User Story and waits.
2. The human answers in Azure DevOps: codes don't stack, show inline. `manager` reads it
   there, confirms both questions are resolved.
3. **Approved** — `manager` creates two self-contained Tasks — `[backend] Add discount-code
   validation to checkout` and `[frontend] Add discount code field to checkout form`, each
   with the settled decisions written into its description — both linked to the parent User
   Story, which moves to Active.
4. **Branches created** — `backend` and `frontend` each create
   `feature/<task-id>-checkout-discount-codes`.
5. **Implementing** — `backend` builds the validation endpoint; `frontend` builds the field
   and wires it up, confirming the response shape directly with `backend` over `link_prompt`
   along the way. Both move their own Tasks to Active when they start.
6. **Unit testing** — both run their own unit tests; `backend`'s pass, `frontend` finds a bug
   in its own validation-message rendering and fixes it before reporting done.
7. **Functional testing** — `manager` asks `backend` and `frontend` to run together locally,
   then asks `cypress` (confirmed present via `link_list`) to validate the checkout flow
   visually. Everything passes.
8. **Merge-ready** — both open PRs referencing their own Task IDs.
9. **Completed** — the human reviews and merges both PRs; `backend` and `frontend` each close
   their own Task; `manager` moves the User Story to Resolved, noting in a closing comment
   that discount-code stacking might come up again later as a follow-up request.
