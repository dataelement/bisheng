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

**Logging**: project logger is loguru (`from loguru import logger`), which formats with **str.format `{}`**, *not* printf. So:

- Use `{}` / `{!r}` placeholders with each value passed as a separate arg — `logger.info("parsed {} files for kb={}", n, kb_id)`, `logger.debug("payload={!r}", obj)`. This is lazy (skipped when the level is off) and the loguru-native form.
- **Never use printf `%s` / `%r` / `%d` with loguru.** It does not interpolate them — the placeholder is printed literally and the args are silently dropped (this is a real bug, not a style nit: it has burned dry-run scripts).
- f-strings (`logger.info(f"...")`) are also safe and still common in the tree; acceptable, but prefer `{}` for new logs.
- Never downgrade `logger.exception(...)` (auto-attaches the traceback) to `logger.error`.

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
    logger.warning("cache eviction failed for {}; will expire via TTL", key)  # main flow unaffected
```

Applies to async (`asyncio.gather(..., return_exceptions=True)` results must be inspected) and Celery tasks (raise to let retry/dead-letter handle it; only swallow with an explicit reason).

---

## Commands (cwd: `src/backend/`)

```bash
# Dependencies (uv, lockfile = uv.lock, Python must be 3.11.x — pyproject requires-python >=3.11)
uv sync --frozen

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

# DB migration (alembic.ini in src/backend/; revisions live in bisheng/core/database/alembic/versions/)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "msg"   # autogen reflects MySQL only; review DM8 compat manually
```

**Ruff is the sole authority on formatting.** The PostToolUse hook runs `ruff format` + `ruff check --fix` on every file you write — let it. You don't need to format by hand; the hook does it. Do **not** work around the hook to keep the diff small — e.g. reaching for a different edit approach, partial writes, or reverting the hook's reflow because it "touched too many lines." If ruff reflows lines you didn't change, that reflow is correct and stays in. A smaller diff is never a reason to bypass formatting.

**Migration vs. script — keep them separate:**

- **Schema changes** (DDL: create/alter/drop table, columns, indexes, constraints) → Alembic revision under `bisheng/core/database/alembic/versions/`. These are versioned and replayed on every environment via `alembic upgrade head`.
- **One-off data migration or cleanup** (backfill/transform rows, purge stale data, fix-up jobs run once) → a standalone script under `scripts/`, **not** Alembic. Don't bury data-only operations in schema revisions.

---

## Quick Map (indexes — architecture detail in `docs/architecture/`)

**Domain modules** — convention: own top dir under `bisheng/` with `api/` + `domain/` (knowledge, linsight, permission, approval, tenant, evaluation, llm, chat_session, …). `ls bisheng/` is the authoritative list — do not maintain a full enumeration here, it rots. Structural exceptions: `workflow/` (engine layout: graph/nodes/edges, no api/domain) and `mcp_manage/` (clients/langchain only).
**Non-standalone** (single-file routes under `api/v1/`, no top dir): assistant, audit, group, tag, mark, flows, skillcenter, variable, report, invite_code, plus legacy chat/dataset/endpoints.
→ responsibilities: `architecture/02-backend-modules.md`.

**API routes**: v1 `/api/v1` (frontend-facing) + v2 RPC `/api/v2` (in `open_endpoints/api/`) — authoritative registry: `bisheng/api/router.py`.

**Subsystems** (quick entry points; architecture in the linked doc):
- **Workflow engine** — LangGraph DAG. Key files `workflow/graph/{graph_engine,graph_state,workflow}.py`, `nodes/node_manage.py`. Node types = `NodeType` enum in `workflow/common/node.py`. Add node = enum member + node class under `workflow/nodes/<name>/` (inherit `BaseNode`) + register in `NODE_CLASS_MAP` (`node_manage.py`). → `architecture/03`
- **Knowledge/RAG** — Load → Transform → Ingest; Milvus (dense) + ES (sparse) dual write; async via `knowledge_celery`. Core: `knowledge/rag/pipeline/base.py`. → `architecture/04`
- **Linsight agent** — independent Worker via Redis queue. `linsight/worker.py`, `linsight/domain/task_exec.py`. → `architecture/05`
- **Permission** (ReBAC / OpenFGA) → `architecture/10` (+ constitution C4)
- **Multi-tenant** → `architecture/12` (+ constitution C3)
- **Gateway** (commercial) → `architecture/11`
- **Approval center (F025)** — `approval/` (domain module) + `worker/approval/` (outbox exec) + `notification/` (in-app messages). Read the `approval-module` skill before touching it.

**Cross-cutting dirs** (not domain modules; touched constantly):
- `core/` — config loading, Alembic migrations (`core/database/alembic/versions/`), tenant ContextVar (`core/context/tenant.py`), OpenFGA client (`core/openfga/manager.py`)
- `common/` — `resp_*`/pagination schemas (`common/schemas/api.py`), error codes (`common/errcode/`), auth deps (`common/dependencies/`)
- `database/models/` — legacy ORM layer; many live models (e.g. `FlowType`) are here, not in domain modules
- `worker/` — Celery task tree (knowledge, workflow, approval, telemetry, …); app entry `worker/main.py`

**Key enums**: `FlowType` (`database/models/flow.py`) ASSISTANT=5, WORKFLOW=10, WORKSTATION=15, LINSIGHT=20, CHANNEL_ARTICLE=25, KNOLEDGE_SPACE=30 (member name is misspelled in code — no W; grep accordingly). File states: WAITING(5)→PROCESSING(1)→SUCCESS(2)/FAILED(3)/TIMEOUT(6). → models detail: `architecture/07-data-models.md` + `architecture/数据库表结构与关联说明.md`.

**Celery queues**: `knowledge_celery` (20 threads, doc parse/embed/vector), `workflow_celery` (100, DAG exec), `celery` default (100, telemetry). Beat iterates all active tenants per task.

**Storage (6 engines)**: MySQL, Redis, Milvus, Elasticsearch (dual: business + stats), MinIO, OpenFGA.

**Config**: load priority `YAML → env (BS_*) → DB (initdb_config) → Redis (100s TTL)`. Detail → `architecture/08-deployment.md`.

---

## Known Pitfalls

- **Tenant auto-filter only intercepts SELECT.** The `do_orm_execute` listener (`core/database/tenant_filter.py`) returns early for non-SELECT; `before_flush` auto-fills `tenant_id` on INSERT. Bulk `update()` / `delete()` statements and raw `text()` SQL get **no** tenant injection — hand-write the `tenant_id` condition (has leaked cross-tenant twice: LLM module, F035).
- **The ruff PostToolUse hook deletes not-yet-used imports.** Every written `.py` gets `ruff check --fix`; an import added in one edit whose usage lands only in a later edit is removed as unused (F401) in between. Land import + usage in the same edit, or write the usage first.
- **Celery Beat × multi-tenant.** A Beat schedule fires once; the task body iterates all active tenants — call `set_current_tenant_id()` per iteration, and wrap the cross-tenant enumeration query itself in `bypass_tenant_filter()` (`core/context/tenant.py`), otherwise queries fail on missing tenant context.
- **DB config changes take up to 100s.** DB-layer config is cached in Redis with a 100s TTL — don't chase "config not applied" inside that window.

---

## Entry Points

- `main.py` — FastAPI app creation + lifespan
- `api/router.py` — global route registration
- `config.yaml` — main config (local dev)

Infra init order & middleware stack → `architecture/01-architecture-overview.md`.
