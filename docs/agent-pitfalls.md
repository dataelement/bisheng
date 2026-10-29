# Agent Pitfalls — Factual and Method

Moved out of root `AGENTS.md §7` to keep the root file short. Root keeps a one-line index and the two destructive-git rules.

## Where subsystem pitfalls live

Backend runtime pitfalls (tenant-filter SELECT-only gap, ruff hook import trap, Celery Beat × multi-tenant, DB config Redis TTL and db index, single-host compose hiding multi-node bugs, `create_time` tie-breaking, duplicate table definitions, non-admin permission verification, baseline-diff regression judgement) → `src/backend/AGENTS.md` §Known Pitfalls; config/packaging contracts (new YAML top-level keys, `uv export`, committed CLI wheel, dependency licensing) → the same file's §Config & Packaging Contracts. Linsight agent-framework contracts → `src/backend/bisheng/linsight/AGENTS.md`; skill-pack authoring → `.../linsight/builtin_skills/AGENTS.md`. Client pitfalls (MinIO presigned-URL host, sandboxed `srcDoc` storage, markdown pipeline, local dev login, `pnpm install` breaking jest) → `src/frontend/client/AGENTS.md` §Known Pitfalls. MinIO `sharepoint` image-proxy pitfall → `src/frontend/platform/AGENTS.md` §Known Pitfalls. Commercial edition (`BISHENG_PRO` env, gateway proxy, SSO) → `docs/architecture/11-gateway.md`.

## Factual pitfalls

| Pitfall | Reality |
|---------|---------|
| `/api/v1/env` version field | Hardcoded `2.4.0` in source — unreliable. Use route probing instead. |
| Passwords in config.yaml | Fernet-encrypted. Never write plaintext passwords into the YAML. |
| First registered user | Becomes `super_admin` automatically. In multi-tenant mode, create the tenant first. |
| `docker compose restart bisheng-backend` | `bisheng-backend` is a `container_name`; the compose *service* names are `backend` / `backend_worker`. The wrong one fails with `no such service` and restarts nothing — and if the container happened to restart on its own, `Up N seconds` makes it look like the command worked. |
| "I clicked it and nothing happened" | Read `process_time` for that request in the backend access log first. "Slow" (a synchronous blocking action) and "broken" (a callback that never refreshed) have completely different fixes, and a second click usually returns a state-conflict error — if the frontend only toasts it without rolling back or re-syncing, the UI stays stuck on the old state forever. |

## Method pitfalls

These cost more than the factual ones above.

- **To decide whether code is still live, trace its callers and its frontend entry point** — its presence in the tree proves nothing. This repo carries a lot of paths whose UI was removed while the backend implementation stayed. Grep the backend, then the frontend API layer and component usages, and then check whether guard conditions and field defaults leave the branch permanently untaken. Reading statically and treating leftovers as current produces badly wrong conclusions.
- **Before naming a root cause, check the magnitude and measure where the bug reproduces.** Write down the number your explanation predicts and do the byte arithmetic; if it doesn't add up, it isn't the cause. A memory problem has three shapes and each leaves a different trace: live objects (tracemalloc grows), allocator retention (RSS plateaus near a peak, `malloc_trim` gives some back), a native leak (linear growth per operation that neither gc nor trim recovers) — a linear climb rules out the second outright. Take the decisive measurements in the environment that actually shows the bug; when two environments differ in several variables (branch, database, a fix), split them before attributing, and until then call it a correlation. A suspected mechanism that a 50-line script can test gets the script first. The COFCO task-mode OOM was blamed on missing summarization for two rounds; the real cause — dmPython ≤ 2.5.38 leaking one reference per `fetchall` value — only surfaced through a minimal repro and per-layer A/B.
- **Let the root cause determine the scope; don't fold every gap you pass into one change.** For each candidate ask "once the root cause is fixed, does this still hold?" — the ones that don't go on an explicit "not doing" list with the reason. Before editing a prompt or adding a fallback, read what the existing template / DB config / YAML **actually contains**; absence from the code is not absence from the system. And the right treatment for dead code is deletion, not reconnection.
- **Surface model misbehaviour; do not paper over it with a fallback.** A model that claims a deliverable it never produced is a diagnosable defect — manufacturing the file on its behalf destroys the evidence and makes the defect unmeasurable. Preference order: fix the prompt, then detect and log or flag, then let the UI show the anomaly honestly (greyed out and marked "not generated", not a normal-looking link that does nothing). Keep a fallback only where it is already an established product contract.
- **When several agents share one working tree, repository-wide git writes are forbidden**: `git stash` (including pop/apply), `git checkout .`, `git reset --hard`, `git clean`, and `git restore` without a path. They act on the whole tree rather than "your" files and silently swallow another session's in-progress work. Read committed content with `git show HEAD:<path>`, inspect your own edits with `git diff HEAD -- <path>`, and use `git worktree add` when you need a clean checkout; a path-scoped `git checkout <ref> -- <path>` is safe. Put this in the task brief when dispatching concurrent sub-agents.
- **`git checkout --theirs <file>` takes the other side's *whole file*, not just the conflicted hunks.** On files where both sides added entries independently (locale JSON, error-code copy) it silently drops everything unique to your side, and the result still parses and still looks like a one-line diff. Use `git checkout --merge -- <file>` to restore the conflict markers and resolve hunk by hunk, then validate by parsing the file.

## Why AGENTS.md entries must be verified

A hypothesis written as a rule is loaded into every later session as fact: the 2026-08 guess that history summarization "does nothing for process memory" graduated from memory into `linsight/AGENTS.md` unmeasured and steered a 2026-10 OOM investigation for three rounds.
