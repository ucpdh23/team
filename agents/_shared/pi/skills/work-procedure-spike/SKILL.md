---
name: work-procedure-spike
description: "Work procedure for time-boxed investigations whose deliverable is knowledge, a report with options and a recommendation, not shipped code. Use when an ADO Task header says `Procedure: work-procedure-spike`."
---

# Work procedure: spike

For researching feasibility, comparing options or reducing uncertainty before committing to work.
**No product changes are merged.** Throwaway prototypes stay in the spike's workitem folder or a scratch
branch. Authorization boundaries in your `AGENTS.md` always apply.

1. **Frame (manager)**: a Task with `Procedure: work-procedure-spike`, the question to answer, a **time
   box**, and what a useful answer looks like. Open questions for the human go as a comment on the parent.
2. **Investigate (assigned roles)**: read code, try prototypes, measure. Keep notes in
   `workitems/<id>-short_name/`.
3. **Report** in the workitem `README.md`, bullets first, details below:
   - the question and the short answer;
   - options with pros, cons, cost and risk;
   - a recommendation;
   - UML class/sequence diagrams of the real code or of the proposed design (Mermaid; ASCII when posted in
     ADO);
   - links to prototypes or evidence.
4. **Hand-off**: the role tells manager; manager posts a summary comment (bullets + link/location of the
   report) on the ticket and asks the human for a decision.
5. **Close**: when the human decides, manager closes the spike. A "go" opens new workitems with
   `work-procedure-standard` (or another); the spike's report is their analysis input.

If the time box runs out, report what is known and what is missing instead of extending silently.
