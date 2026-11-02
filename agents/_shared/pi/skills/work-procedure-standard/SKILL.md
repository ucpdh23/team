---
name: work-procedure-standard
description: "Default team work procedure, 8 stages from analysis to completed, for any non-trivial feature, bug fix or refactor. Use when an ADO Task header says `Procedure: work-procedure-standard`, or says nothing about a procedure."
---

# Work procedure: standard

```
analysis → approved → branches-created → implementing → unit-testing
   → functional-testing → merge-ready → completed
```

Applies to features, non-trivial bug fixes and refactors. Cheaper variants exist
(`work-procedure-minor-fix`, `-hotfix`, `-spike`, `-infra-only`); if this one is too heavy or too light,
propose an adaptation to manager. Authorization boundaries in your `AGENTS.md` always apply.

Ground rules:
- **manager** owns ticket state and updates ADO in batches (not per message). Other roles report to manager
  over pi-link and keep their own `workitems/<id>-short_name/README.md` current.
- Each Task header starts with `Procedure: <skill>` and `Adaptations: <none | what / why / approver>`.
- Long texts: bullets with short descriptions first, detailed analysis below, UML class/sequence diagrams
  referencing the real classes (Mermaid in READMEs, ASCII in ADO fields).

## 1. Analysis (manager drives; affected roles consulted)
- Goal: a scoped, unambiguous piece of work. **No code yet.**
- manager asks each plausibly affected role (`link_prompt`) for feasibility and open questions, merges them
  into one deduplicated list and posts it as a **comment** on the parent User Story/Bug (never as a Task).
- The human answers in ADO. manager reads the actual comment, checks it question by question, and repeats
  the round if anything is ambiguous.
- Comments are for open decisions; Tasks are for fully defined work.
- Exit: every open question has an explicit answer.

## 2. Approved (manager)
- Human gives an explicit go-ahead.
- manager creates one or more Tasks per affected role, titled `[<role>] short description`, each a
  **child** of the parent. Each Task stands on its own: header, summary, affected modules, acceptance
  criteria, and at least one ASCII diagram (flow, class, sequence or data). A Task without a diagram is sent
  back.
- Parent moves to **Active**.

```bash
# Write the description to a file first so diagram alignment survives shell escaping.
cat > /tmp/task.txt <<'T'
Procedure: work-procedure-standard
Adaptations: none

- Summary ...
- Acceptance: ...

Flow:
[frontend] POST /api/x --> [backend] XService.apply() --> 200 | 422
T
az boards work-item create --type Task --title "[backend] Short description" \
  --description "$(cat /tmp/task.txt)" --output json
az boards work-item relation add --id <TASK_ID> --relation-type parent --target-id <PARENT_ID>
```
- Exit: Tasks exist, are linked, and each role agrees its acceptance criteria are clear.

## 3. Branches created
- Each role creates `feature/<task-id>-<slug>` off the appropriate base and reports the name to manager.

## 4. Implementing
- Roles work against their Task's acceptance criteria and talk directly over pi-link at shared boundaries
  (e.g. backend/frontend on a request shape), no need to route via manager.
- Roles report milestones and blockers to manager; manager escalates blockers to the human at once and
  records significant ones as a comment on the Task. manager sets the Task **Active** when the role starts.
- Exit: each role reports implementation complete.

## 5. Unit testing
- Each role runs the unit tests relevant to its change and reports pass/fail. Failures are fixed first; the
  stage does not pass partially.

## 6. Functional testing
- manager asks backend and frontend to bring up the integrated environment, and, if the change is
  UI-observable, cypress (check `link_list` first, it is not always connected).
- A cypress failure is UI/selector/timing evidence until shown otherwise; business logic is confirmed by
  backend/frontend functional tests.
- Defects go back to stage 4. Significant ones may become their own Bug linked to the parent.
- `*IT`/integration tests that mutate a real database: see Authorization boundaries in your `AGENTS.md`.

## 7. Merge-ready
- Each role pushes and opens its own PR against the base branch referencing its Task. Agents never merge.

```bash
az repos pr create --repository <repo> --source-branch feature/<task-id>-<slug> \
  --target-branch main --title "..." --description "Implements <TASK_ID>." --work-items <TASK_ID>
```
- Exit: PRs open and passing CI; only human review pending.

## 8. Completed
- After the human merges, roles tell manager. manager moves Tasks to **Closed**, the parent to
  **Resolved/Closed**, and adds a short closing comment with anything non-obvious (workaround, decision that
  may be revisited).

## Naming
- Task: `[<role>] <short description>` · Branch: `feature/<task-id>-<slug>` ·
  Workitem folder: `<id>-short_name` or `<yyyymmdd>-short_name`.

## ADO configuration (once per container)
```bash
az login
az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>
```
