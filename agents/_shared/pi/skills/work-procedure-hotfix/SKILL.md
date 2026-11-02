---
name: work-procedure-hotfix
description: Work procedure for urgent fixes to a defect in production or one that blocks the team, with a short analysis, targeted tests and a post-fix report. Use when an ADO Task header says `Procedure: work-procedure-hotfix`.
---

# Work procedure: hotfix

For urgent defects in a live or shared environment. Speed is allowed; skipping safety is not.
Authorization boundaries in your `AGENTS.md` always apply (a deployment still needs the human's explicit
authorization in the executing role's session).

1. **Triage (manager + affected roles)**: write in the Task, as short bullets: symptom, impact, suspected
   root cause, risk of regression, rollback option. One quick round over pi-link, no formal question round
   unless the fix is ambiguous.
2. **Branch** from the branch that is in production (`hotfix/<task-id>-<slug>`), not from an
   in-progress feature branch.
3. **Fix** the root cause, minimal diff, no unrelated changes.
4. **Verify**: write a regression test that fails before the fix and passes after; run the tests around the
   touched code. Reproduce the original symptom once more on the fixed build.
5. **Functional check**: only the affected flow, with cypress if it is UI-observable.
6. **PR + deploy**: open a PR referencing the Task; the human merges and authorizes any deployment.
   devops deploys; backup first for any real environment, per `AGENTS.md`.
7. **Post-fix report** (manager, ADO comment): cause, fix, verification, and any follow-up (proper
   refactor, missing test, monitoring) as a separate ticket if needed.

Tasks carry `Procedure: work-procedure-hotfix` and any `Adaptations:`. Roles keep a short
`workitems/<id>-short_name/README.md` (timeline, cause, fix, evidence).
