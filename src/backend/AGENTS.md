# Backend Reference

Auto-loaded when editing files in `src/backend/`. Complements root `AGENTS.md`.
- Architectural **laws** (inviolable) → `docs/constitution.md` (C1–C7).
- Deep **subsystem architecture** (workflow / RAG / linsight / permission / gateway / multi-tenant / data models) → `docs/architecture/`.
- **This file = coding conventions + a quick map. Do not duplicate architecture prose here** — link to `architecture/` instead.

---

## Coding Conventions

**Module layout**: `<module>/{api/router.py, api/endpoints/, domain/services/, domain/models/, domain/schemas/, domain/repositories/}`. Register the router in `bisheng/api/router.py`. Layered call chain & prohibitions → constitution **C1**.

**API**:
```python
from bisheng.common.dependencies.user_deps import UserPayload
user: UserPayload = Depends(UserPayload.get_login_user)   # WebSocket: get_login_user_from_ws

from bisheng.common.schemas.api import resp_200, resp_500
return resp_200(data)        # success
return resp_500(code, msg)   # business error
```
Error codes (MMMEE) & module numbers → constitution **C5**. Pagination: `PageData[T]` (new code, fields `data` + `total`); `PageList[T]` legacy-compat only.

---

## Error Handling

**Never silently swallow exceptions.** `except: pass`, `except Exception: pass`, or discarding error returns without logging is forbidden. At minimum, use `logger.exception(...)` (auto-attaches traceback) and either re-raise, raise a domain error (`BaseErrorCode` subclass in `common/errcode/`), or let the middleware turn it into a 500.

The only exception: the failure is **explicitly** non-critical to the main flow — best-effort cleanup, optional cache write, opportunistic telemetry. Then the swallow must be intentional, narrow (catch the specific exception, not bare `Exception`), and carry a one-line comment stating *why* it's safe to ignore.

**Don't launder exceptions through `resp_500(message=str(e))`.** That erases the original exception type and traceback — a different flavor of silent swallow. `resp_500` is a generic response formatter, not a business-error sink: any failure the frontend may branch on belongs in a `BaseErrorCode` subclass (`raise XxxError()` / `XxxError.return_resp()`); truly internal failures should propagate.

```python
# ❌ Hides real failures
try:
    do_something()
except Exception:
    pass

# ✅ Critical path: log + propagate
try:
    do_something()
except Exception:
    logger.exception("do_something failed")
    raise

# ✅ Best-effort: narrow exception + reason comment
try:
    cache.delete(key)
except RedisError:
    logger.warning("cache eviction failed for %s; will expire via TTL", key)  # main flow unaffected
```

Applies to async (`asyncio.gather(..., return_exceptions=True)` results must be inspected) and Celery tasks (raise to let retry/dead-letter handle it; only swallow with an explicit reason).

---

## Commands (cwd: `src/backend/`)

```bash
# Dependencies (uv, lockfile = uv.lock, Python must be 3.11.x — pyproject requires-python >=3.11)
uv sync --frozen --python uv run python

# Tests
uv run pytest test/                               # all
uv run pytest test/<module>/test_xxx.py::test_fn  # single test
uv run pytest test/ -k "keyword"                  # filter by keyword
uv run pytest test/ -m "not e2e"                  # exclude e2e
# New tests go under test/<module>/ (e.g. test/approval/), not test/ root
# asyncio_mode=auto — no @pytest.mark.asyncio needed on async functions

# Format / Lint (matches PostToolUse hook)
uv run ruff format <file_or_dir>
uv run ruff check --fix <file_or_dir>

# Start API (port 7860; config = filename relative to the bisheng package dir)
export config=config.yaml
uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# Celery (one terminal per queue)
uv run celery -A bisheng.worker.main worker -l info -c 20  -P threads -Q knowledge_celery -n knowledge@%h
uv run celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery  -n workflow@%h
uv run celery -A bisheng.worker.main beat -l info

# Linsight Worker (optional)
uv run python bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5

# DB migration (alembic.ini in src/backend/)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "msg"   # autogen reflects MySQL only; review DM8 compat manually
```

**Ruff is the sole authority on formatting.** The PostToolUse hook runs `ruff format` + `ruff check --fix` on every file you write — let it. You don't need to format by hand; the hook does it. Do **not** work around the hook to keep the diff small — e.g. reaching for a different edit approach, partial writes, or reverting the hook's reflow because it "touched too many lines." If ruff reflows lines you didn't change, that reflow is correct and stays in. A smaller diff is never a reason to bypass formatting.

**Migration vs. script — keep them separate:**

- **Schema changes** (DDL: create/alter/drop table, columns, indexes, constraints) → Alembic revision under `migrations/versions/`. These are versioned and replayed on every environment via `alembic upgrade head`.
- **One-off data migration or cleanup** (backfill/transform rows, purge stale data, fix-up jobs run once) → a standalone script under `scripts/`, **not** Alembic. Don't bury data-only operations in schema revisions.

---

## Quick Map (indexes — architecture detail in `docs/architecture/`)

**Domain modules** (own top dir + `api/` + `domain/`): knowledge, workflow, permission, linsight, llm, chat_session, tool, channel, message, user, finetune, share_link, telemetry_search, workstation, open_endpoints, mcp_manage.
**Non-standalone** (routes under `api/v1/`, no top dir): assistant, evaluation, audit, group, tag, mark, flows, skillcenter, variable, report, invite_code.
→ responsibilities: `architecture/02-backend-modules.md`.

**API routes**: v1 `/api/v1` (29 routes, frontend-facing); v2 RPC `/api/v2` (6 routes, in `open_endpoints/api/`).

**Subsystems** (quick entry points; architecture in the linked doc):
- **Workflow engine** — LangGraph DAG. Key files `workflow/graph/{graph_engine,graph_state,workflow}.py`, `nodes/node_manage.py`. 14 node types. Add node = enum in `workflow/common/node.py` + node class under `workflow/nodes/<name>/` (inherit `BaseNode`) + register in `NODE_CLASS_MAP`. → `architecture/03`
- **Knowledge/RAG** — Load → Transform → Ingest; Milvus (dense) + ES (sparse) dual write; async via `knowledge_celery`. Core: `knowledge/rag/pipeline/base.py`. → `architecture/04`
- **Linsight agent** — independent Worker via Redis queue. `linsight/worker.py`, `linsight/domain/task_exec.py`. → `architecture/05`
- **Permission** (ReBAC / OpenFGA) → `architecture/10` (+ constitution C4)
- **Multi-tenant** → `architecture/12` (+ constitution C3)
- **Gateway** (commercial) → `architecture/11`

**Key enums**: `FlowType` ASSISTANT=5, WORKFLOW=10, WORKSTATION=15, LINSIGHT=20, CHANNEL_ARTICLE=25, KNOWLEDGE_SPACE=30. File states: WAITING(5)→PROCESSING(1)→SUCCESS(2)/FAILED(3)/TIMEOUT(6). → models detail: `architecture/07-data-models.md` + `数据库表结构与关联说明.md`.

**Celery queues**: `knowledge_celery` (20 threads, doc parse/embed/vector), `workflow_celery` (100, DAG exec), `celery` default (100, telemetry). Beat iterates all active tenants per task.

**Storage (6 engines)**: MySQL, Redis, Milvus, Elasticsearch (dual: business + stats), MinIO, OpenFGA.

**Config**: load priority `YAML → env (BS_*) → DB (initdb_config) → Redis (100s TTL)`. Detail → `architecture/08-deployment.md`.

---

## Entry Points

- `main.py` — FastAPI app creation + lifespan
- `api/router.py` — global route registration
- `config.yaml` — main config (local dev)

Infra init order & middleware stack → `architecture/01-architecture-overview.md`.
