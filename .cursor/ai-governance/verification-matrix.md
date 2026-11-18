# Verification matrix

Map change types to real repo commands. Prefer the smallest useful set.

## Commands

```bash
# Backend (cwd: src/backend/)
uv sync --frozen
uv run pytest test/<module>/test_xxx.py::test_fn
uv run pytest test/<module>/test_xxx.py
uv run pytest test/ -k "keyword" -m "not e2e"
uv run ruff format <file> && uv run ruff check --fix <file>

# Platform (cwd: src/frontend/platform/)
npx vitest run <files>

# Client (cwd: src/frontend/client/)
npx jest <files> --coverage=false --watchAll=false

# Architecture guard (repo root)
bash scripts/arch-guard.sh <file>
```

Neither frontend has a lint or typecheck script; do not invent one.

## By change type

| Change | Minimum verify | Expand when |
|--------|----------------|-------------|
| Docs only | — | — |
| Local UI / pure helper (no contract/semantics change) | Named vitest / jest files | Touched shared types → callers' tests |
| Backend private logic | Named pytest file + ruff + arch-guard | Callers of the changed function |
| Shared semantics (dedup/quota/visibility/cache/events/points) | Mocked tests on that invariant | Every caller of the shared rule |
| Public API / schema | Mocked API test through real Router + Service: 5-digit code + response fields | Portal BFF / other frontend consumers |
| Auth / permissions | Mocked allow and deny cases; deny must not leak body | Tenant isolation case |
| Writes (insert/update/delete/status/count/lock) | Mocked repository: written on success, untouched on rejection | Real-DB flow in `e2e/` |
| Migrations | Review against `AGENTS.md` §3.2 DM8 bans | `uv run alembic upgrade head` only when the user asks |
| Deploy / CI / Docker | Manual review of manifests | Local image build if user asks |

"Minimum verify" above means local, mocked checks. Real-environment checks follow the split below.

## Local vs e2e

| Where | What | When it runs |
|-------|------|--------------|
| Local (implementation) | Mocked unit tests; API tests through real routes/services with repositories, DB sessions, external clients, and Celery mocked; ruff; arch-guard | Every task |
| Root `e2e/<feature>/` | Real-env API flow against the 171 MySQL (call → assert status/business code → SELECT the named tables → act again on what the DB says); UI steps or Playwright script; `README.md` with services, accounts, data preconditions, run command | Only when the user asks ("跑 e2e" / `/e2e-test`) |

- Do not start services, drive a browser, or connect to the shared DB during implementation.
- The only e2e location is the repository root `e2e/`. Do not create `e2e/` under frontend or backend directories.

## Rules

1. Do not invent commands.
2. Do not skip failing tests; fix or ask.
3. Report skipped checks with reasons, and list e2e checks written but not run.
4. A swallowed exception (`except` then `ok: True`) is not a passing test.
