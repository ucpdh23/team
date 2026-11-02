---
name: work-procedure-infra-only
description: Work procedure for infrastructure-only changes (docker-compose, Dockerfiles, CI/CD pipelines, environments, observability) that devops carries out without backend, frontend or cypress work. Use when an ADO Task header says `Procedure: work-procedure-infra-only`.
---

# Work procedure: infra-only

For changes that live entirely in infrastructure and do not alter application code. If application code or
contracts have to change, split that part into Tasks for the owning roles under `work-procedure-standard`.
Authorization boundaries in your `AGENTS.md` always apply.

1. **Analysis (manager + devops)**: manager sends the goal; devops answers with feasibility, impact on other
   roles (what breaks, who must rebuild or reconnect) and open questions, as bullets plus a sequence or
   deployment diagram of the real infrastructure. Questions for the human go as a comment on the ticket.
2. **Approved**: manager creates a single `[devops]` Task with the header `Procedure:
   work-procedure-infra-only`, acceptance criteria and a diagram. Affected roles are informed, not tasked.
3. **Branch + implement** (devops): `feature/<task-id>-<slug>`. Test on a sibling container or the local
   compose first, never first on a shared environment.
4. **Safety**: take a backup before touching any shared or real environment; request credentials
   interactively or via environment variables, never in files, logs or arguments; destructive operations,
   restores and real deployments need the human's explicit authorization in devops' own session.
5. **Verify**: show the change works (service up, healthcheck, connectivity from the roles that use it) and
   that nothing else regressed. Ask affected roles to confirm only what concerns them.
6. **PR**: devops opens it referencing the Task; a human merges.
7. **Close**: manager closes the Task after devops reports the result and the merge, with a short summary of
   what changed and what other roles must do (if anything).

devops keeps `workitems/<id>-short_name/README.md` (what changed, how to roll back, evidence).
