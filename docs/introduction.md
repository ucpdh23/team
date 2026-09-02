# Introduction

Welcome to **team-pi** — a small, always-on software team made of five [pi](https://pi.dev)
coding agents, each running in its own Docker container, coordinating with each other in
real time. This document is written for a **human** joining the project: it explains what
this is, who's on the team, and how to think about working alongside it. For the technical
setup (how the containers are wired, how pi-link works under the hood, how to connect to a
session) see the root [`README.md`](../README.md). For the detailed day-to-day workflow
(stages, ADO Tasks, local workitems), see [`work-procedures.md`](work-procedures.md).

## What this is

Instead of one coding agent working alone in one terminal, `team-pi` runs **five agents at
once**, each with a distinct role, each with its own container, workspace, and memory. They
talk to each other by prompt — asking questions, handing off work, reporting results — the
same way a small human team would use a group chat, except the whole conversation is between
agents, and a human oversees the outcome rather than every individual exchange.

The idea is to mirror how a real software team is organized: someone coordinates and keeps
the big picture, someone owns the backend, someone owns the frontend, someone owns the
infrastructure, and someone verifies that everything actually works together end-to-end.

## The team

| Role | Container | Mission |
|---|---|---|
| **manager** | `pi-manager` | The team's coordinator. Turns a goal from the human into concrete work, decides who does what, tracks progress, and is the main point of contact for the human in charge. |
| **backend** | `pi-backend` | Owns the backend service/API: business logic, data model, persistence, and the contract the frontend consumes. |
| **frontend** | `pi-frontend` | Owns the user interface: builds screens and flows against the backend's API. |
| **devops** | `pi-devops` | Owns infrastructure, CI/CD, deployment and observability — including the very docker-compose setup that runs this team. |
| **cypress** | `pi-cypress` | Owns end-to-end testing: verifies backend and frontend actually work together from a user's point of view. |

None of the five is a network-level "master" — they're peers on equal footing, each with its
own container and its own persistent tmux session. `manager` is a *coordination* role, not an
infrastructure hub: if you kill any container, the rest keep working and reconnect on their
own (see the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for how that failover actually
works).

## How they talk to each other

All five agents share a communication mesh called **pi-link**. In practice this means any
agent can:

- list who else is currently connected and what they're doing (`link_list`);
- send another agent a message and move on without waiting (`link_send`);
- send another agent a prompt and wait synchronously for its answer (`link_prompt`);
- ask a busy agent to free up context before handing it more work (`link_compact`).

You, as a human, don't need to relay messages between agents yourself — that's the whole
point. You give `manager` a goal, and the team figures out internally who needs to talk to
whom.

## How to think about working with this team

- **Talk to `manager` first**, the same way you'd talk to a tech lead rather than picking a
  random engineer for every request. `manager` will loop in the right specialist(s).
- **Expect questions before commitment.** For anything non-trivial, the team analyzes and
  raises open questions *before* writing code — see the "Intake & Analysis" stage in
  [`work-procedures.md`](work-procedures.md). This is deliberate: it keeps you in the loop on
  scope decisions instead of discovering them after the fact.
- **Some things always require your explicit sign-off** — running tests that mutate a real
  database, executing SQL against a shared environment, merging a Pull Request, or anything
  destructive/irreversible. Agents will ask rather than assume. See the "Authorization
  boundaries" section of `work-procedures.md` for the full list.
- **Work is tracked in two places on purpose**: a private `workitems/` folder inside each
  role's own project (the working notes and technical detail that role uses day to day, not
  shared with the rest of the team) and Azure DevOps Boards (the record of what happened,
  visible to anyone outside this repo). Neither replaces the other.
- **You can drop into any agent's session at any time** (`docker exec -it pi-<role> tmux
  attach -t pi`) to see exactly what it's doing, ask it something directly, or redirect it —
  the team structure doesn't require you to go through `manager` for everything, it's just
  the recommended default for new work.

## Where to go next

- [`work-procedures.md`](work-procedures.md) — the full workflow: stages, what each role
  does at each stage, and exactly what changes in Azure DevOps and in the local `workitems/`
  folder along the way.
- [`../README.md`](../README.md) — the role model, how to run and connect to the containers,
  authenticate, and troubleshoot.
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — technical detail: how pi-link achieves
  cross-container discovery, and how `backend`'s headless Eclipse is wired up.
- `agents/<role>/AGENTS.md` — the context each agent itself loads on startup (its own role,
  who the rest of the team is, and how to use pi-link). This is written for the agents, not
  for humans, but it's worth skimming to understand what each one already "knows" by default.
