# Planner

Before any code change, write `cache/last-plan.md` with:

- Goal
- Affected modules (graph nodes)
- Execution order
- Estimated complexity (low / medium / high)
- Risk analysis
- Testing strategy
- Rollback strategy
- Files that will change

Present that plan and wait for user approval. Do not implement until approved.

Exceptions: Project Brain initialization; user said “just do it” / “implement now” for an already-stated plan.
