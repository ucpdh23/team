---
name: work-procedure-minor-fix
description: Lightweight work procedure for minor bug fixes with no design impact, such as a wrong literal or label, an icon, a style tweak, a typo in code. Use when an ADO Task header says `Procedure: work-procedure-minor-fix`.
---

# Work procedure: minor fix

For small, low-risk changes: text literals, an icon, spacing/colors, a typo, a trivial config value.
**Not** for anything touching API contracts, data model, security, or behavior beyond the stated change:
if it grows, tell manager and switch to `work-procedure-standard`.

Authorization boundaries in your `AGENTS.md` always apply.

1. **Request**: manager records the change in a single Task (`[<role>] ...`) with the header
   `Procedure: work-procedure-minor-fix`, a bullet with what changes and where, and the acceptance
   check. No question round and no diagram required.
2. **Branch + implement**: `feature/<task-id>-<slug>`, make the change, nothing else (no drive-by refactors).
3. **Verify**: run only the tests/checks that cover the touched code; add a test only if the change adds
   logic. Look at the result (screenshot or output) when it is visual.
4. **Report**: tell manager what changed, files touched and the check done. Keep it to a few bullets.
5. **PR**: open it referencing the Task; a human merges.
6. **Close**: manager closes the Task (and parent, if any) with a one-line comment.

Cypress is involved only if the change alters a user flow. The role keeps a short
`workitems/<id>-short_name/README.md` (what, why, check).
