# Execution pipeline — every prompt

## Cache (start of every prompt after init)

1. Read `cache/recent-context.md`.
2. Related to last task → skip Stage 2; load from `cache/recent-files.md` + those memory files.
3. Unrelated → Stage 2.

## Stage 1 — Task classification

Classify complexity: low / medium / high. Type: feature / bugfix / refactor / docs / config. Write `tasks/active.md`.

## Stage 2 — Graph retrieval

Open `graph/graph.json`. List affected modules, files, and memory files. Do not load file contents yet.

Routing (node → memory):

| Nodes | Memory |
|---|---|
| discord_bot, discord_tickets, discord_messages | `memory/frontend.md` |
| rag_pipeline, rag_retrieve, embeddings_gemini, generation* | `memory/backend.md` |
| pinecone_client, pinecone_metadata | `memory/api.md` + `memory/backend.md` |
| tickets_store | `memory/database.md` |
| routing_*, tickets_helpers, process_lock, logger, errors, main | `memory/backend.md` |
| config | `memory/dependencies.md` |
| scripts, tests | `memory/patterns.md` |

## Stage 3 — Context loading

Load only memory files from Stage 2. Load `overview.md` only for project-wide docs/architecture work.

## Stage 4 — Planning

Write `cache/last-plan.md` (see `planner.md`). Wait for approval before code.

## Stage 5 — Execution

Implement only the plan. Follow `standards/general.md`. No drive-by refactors. Preserve architecture.

## Stage 6 — Static validation

Syntax, imports, missing deps. Python: compile/lints on touched files. Fail → Stage 5.

## Stage 7 — AI review

Score vs `reviews/code-quality.md` (each /100): Architecture, Maintainability, Readability, Intent Matching, Side Effects, Scalability, Security, Overall. Overall < 90 → fix and re-review.

## Stage 8 — Knowledge sync

Incremental updates only to affected `memory/*.md`. Patch `graph.json` / `nodes.json` / `edges.json` if modules changed. Append `tasks/completed.md` and `tasks/changelog.md`. Overwrite `cache/recent-context.md` and `cache/recent-files.md`. Clear or rewrite `tasks/active.md`.

## Stage 9 — Response

Report: what changed, files, review scores, memory updated, graph updated yes/no.

## Failure

Log `tasks/failed.md` with reason and rollback. Do not sync memory/graph. Do not mark completed.
