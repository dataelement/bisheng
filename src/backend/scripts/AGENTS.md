# Backend Scripts — Conventions

Auto-loaded when editing files under `src/backend/scripts/`. Complements `src/backend/AGENTS.md`.

This directory holds **manual maintenance, migration, and one-off operational scripts** for the backend. The rules below are mandatory for any new script added here.

---

## 1. Working Directory

**All scripts MUST be executed from `src/backend/` (the backend root).**

Relative paths in shell wrappers (`scripts/foo.py`, `bisheng/script/foo.py`) and the `PYTHONPATH="./"` convention below both depend on this. Running from anywhere else will break imports.

```bash
cd src/backend/
bash scripts/<your_script>.sh [args...]
```

---

## 2. Python Import Path

**Shell wrappers MUST set `PYTHONPATH="./"`** before invoking Python. This adds the backend root to `sys.path` so `from bisheng.xxx import ...` resolves against the local source tree — no `pip install -e .` required.

Minimal template:

```bash
#!/bin/bash
set -e
export PYTHONPATH="./"
python scripts/<your_script>.py "$@"
```

For scripts intended to run directly with `python scripts/foo.py` (no shell wrapper), the Python file itself should bootstrap `sys.path` so it still works when called from any cwd:

```python
import os, sys
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.database import get_async_db_session  # noqa: E402
```

This makes the script robust to direct `python` invocation while the `.sh` wrapper continues to rely on `PYTHONPATH`.

---

## 3. Python Interpreter Resolution

Two acceptable patterns:

**(a) Short form** — fine for scripts that are only run by operators who know to activate the venv first:

```bash
export PYTHONPATH="./"
python scripts/foo.py
```

**(b) Auto-detect form (recommended for new scripts)** — works whether or not a venv is active:

```bash
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found." >&2
    exit 1
fi

"${PYTHON_BIN}" scripts/foo.py "$@"
```

Examples in this directory: `migrate_workstation_models_to_workbench.sh`, `set_admin.sh`.

---

## 4. File Layout

| File                | Purpose                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| `scripts/<name>.py` | The implementation — must be runnable directly via `python scripts/<name>.py`.                   |
| `scripts/<name>.sh` | Optional shell wrapper — handles `PYTHONPATH`, interpreter detection, and argument forwarding.   |
| `scripts/sql/`      | One-off SQL fixtures referenced by scripts.                                                      |
| `scripts/README.md` | User-facing index — add a short entry whenever you add a new script.                             |

Naming: `snake_case` for both `.py` and `.sh` (e.g. `set_admin.sh`, not `set-admin.sh`).

---

## 5. Argument Handling

- Use `argparse` in the Python script for both validation and `--help` output.
- The shell wrapper should forward all arguments verbatim with `"$@"`.

  ```bash
  "${PYTHON_BIN}" scripts/foo.py "$@"
  ```

- Dry-run is the safe default for any destructive operation. Require `--apply` (or equivalent) to write.
- Exit codes: `0` = success, non-zero = failure. Pick distinct codes for different failure categories (user not found vs. external system unreachable) so wrappers can branch on them.

---

## 6. Runtime Environment Initialization

A script must run against the **same environment the live service runs against** — same config file, same `settings`, same initialized infra clients. Mismatches here are silent and dangerous: the script reads a different DB/Milvus/Redis than the service, or an infra client is simply absent and a call fails deep in the stack.

### 6.1 Config file (`config` env var)

The service and every script resolve config through `os.getenv('config', 'config.yaml')` (see `bisheng/common/services/config_service.py`). **Export the same `config` the running service uses** before invoking the script, or you will load the wrong YAML (wrong DB / Milvus / Redis endpoints):

```bash
export config=config.yaml      # must match the value the API/Celery process runs with
export PYTHONPATH="./"
python scripts/<your_script>.py
```

Always import the shared settings singleton — never re-parse the YAML yourself:

```python
from bisheng.common.services.config_service import settings  # YAML → env → DB → Redis, identical to the service
```

### 6.2 Context initialization and resource ownership

FastAPI initializes the complete shared application context in its lifespan
with `initialize_app_context(config=settings)`. Standalone scripts do not run
that lifespan. Choose the clients the script actually needs and use the same
settings and context interfaces as the service.

**DB-only scripts must explicitly own their database manager.**
`get_async_db_session()` closes a session, not its connection pool. A lazily
registered database does not set `app_context.is_initialized()` to true;
`close_app_context()` then returns without closing it. Exit code 0 and closed
sessions therefore do not prove cleanup succeeded. Do not initialize the entire
FastAPI environment merely to make this global flag true.

```python
from bisheng.common.services.config_service import settings
from bisheng.core.context.manager import app_context
from bisheng.core.database.manager import DatabaseManager

async def _main():
    database = DatabaseManager(
        database_url=settings.database_url,
        engine_config=settings.database_pool.as_engine_kwargs(),
    )
    try:
        app_context.register_context(database)
        await app_context.async_get_instance(DatabaseManager.name)
        return await run()  # uses get_async_db_session(), same service config
    finally:
        await database.async_close()

asyncio.run(_main())
```

- Construct, initialize, use and close owned async resources in **one event
  loop**. Never put cleanup in a second `asyncio.run()` or leave it to `__del__`
  after the loop has closed. Register cleanup before registration/initialization
  can fail; `try/finally` or `AsyncExitStack` must cover partial initialization,
  business errors and cancellation as well as normal/no-op results.
- Scripts needing multiple engines must initialize their actual DB/Redis/FGA/
  object-store clients explicitly, or use the full shared application context
  when that complete lifecycle is intended. Do not assume a raw script has API
  clients available. Close only resources the script owns, in reverse order.
  For subsets and failed initialization, never rely solely on the global
  `close_app_context()` guard; the flag can still be false.
- Test with a native context and real connection pool: verify engine disposal
  happens before the loop closes on success, no-op, reported business error,
  exception, initialization failure and cancellation. A mocked close function,
  a CLOSED flag alone, or process exit 0 cannot prove the pool was released.

Verified references: `migrate_model_token_configs.py` and
`test/llm/test_model_token_config_cli_runtime.py` (native pool disposal and CLI
loop-boundary checks); `unify_knowledge_spaces.py::_runtime` and
`test/knowledge_unification/test_migration_cli_runtime.py` (owned DB/Redis,
partial initialization and cancellation); `f048_maintenance_runtime.py` uses an
`AsyncExitStack` for its explicit maintenance composition.

2026-11-19 onsite repro: the old model-token CLI returned 0 with no data changes
on 165, but called no database-manager close and emitted `Event loop is closed`.
The same read-only operation with explicit database close did not emit it.
Full FastAPI initialization was not needed for this DB-only operation.

---

## 7. Database & Tenant Context

Scripts run **outside** the FastAPI request lifecycle, so the automatic tenant filter has no active tenant context. If your script touches tenant-scoped tables:

```python
from bisheng.core.context.tenant import bypass_tenant_filter

with bypass_tenant_filter():
    # cross-tenant reads/writes here
    ...
```

Without `bypass_tenant_filter()`, every query gets `WHERE tenant_id = NULL` injected and returns zero rows.

For async DB work use `get_async_db_session()` + `asyncio.run(main())`; for sync use `get_sync_db_session()`. Don't mix the two in one transaction.

### 7.1 SQLModel async query API

`get_async_db_session()` returns SQLModel's `AsyncSession`. For ORM/select
queries, use `session.exec()` and consume the typed result directly:

```python
statement = select(ResourcePermissionMode).where(...)
row = (await session.exec(statement)).first()
```

Do **not** use the SQLAlchemy-style
`(await session.execute(statement)).scalars().first()` for SQLModel selects.
It emits a production `DeprecationWarning` telling operators to use
`session.exec()`, adds noise to maintenance-script output, and makes real
recovery warnings easier to miss. Use `session.execute()` only when a script
specifically needs SQLAlchemy `Row` semantics or an API unsupported by
`session.exec()`; document that exception next to the call.

---

## 8. Documentation Requirement

Every new script MUST:

1. Have a module-level docstring explaining **what it does, why it exists, and how to run it** (including the dry-run / apply distinction if applicable).
2. Add a short entry to `scripts/README.md` under the appropriate section, with at least one example invocation.

Operators should be able to discover the script from `README.md` alone.

---

## 9. Reference Script Layout (minimal)

`scripts/set_admin.sh`:

```bash
#!/bin/bash
set -e
[ -z "$1" ] && { echo "Usage: $0 <user_id>" >&2; exit 1; }
export PYTHONPATH="./"
# ... interpreter detection ...
"${PYTHON_BIN}" scripts/set_admin.py "$@"
```

`scripts/set_admin.py`:

```python
"""Module docstring with usage example."""
from __future__ import annotations
import argparse, asyncio, os, sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# from bisheng.* imports here

async def run(args) -> int: ...

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # add arguments
    args = parser.parse_args()
    return asyncio.run(run(args))

if __name__ == '__main__':
    sys.exit(main())
```

---

## 10. 迁移脚本必须验证完整流程的规模成本

新增或修改迁移脚本，必须同时审查 preview、apply、verify 和 resume
的总体成本；不能因采用分页、BatchCheck 或 checkpoint 就认定性能合格。

- 按实际待迁移关系处理数据，不额外穷举“用户 × 全部资源”等组合。
  可批量读取或校验的事实不得写成逐项 SQL/远程调用；关联集合、
  查找索引和不变配置应在合适作用域内构建一次，避免循环内全量扫描。
- 大表使用主键游标、必要字段和有界批次；限制跨页累积、缓存、
  deepcopy 和整体 JSON 编码的内存。确需全量比较时，说明原因并采用
  有容量上限的方案。无变更路径不得无故全量加锁或重写数据。
- 区分事实完整性校验与 API 一致性探针：完整性校验不得用抽样替代；
  API 一致性探针采用有界样本。每次全量扫描、重复读取和阶段复核
  都应说明必要性；复用原 Run 的冻结材料，同时保留必要的实时状态、
  租户、权限及提交结果检查，不以提速为由削弱恢复合同。
- 验证必须覆盖正常、无变更、大量异常和中断恢复路径，并比较 N、2N
  数据量下的 SQL/远程调用数、扫描行数、事务次数、峰值内存及耗时。
  分别放大资源、成员、引用和 tuple 等维度，防止乘积开销被小样本掩盖。
  本机或模拟服务耗时不能直接作为生产维护窗口。

验证依据：F048 的 735eb5f3ca、7d9a1be214 改动历史及定向测试；
F118 的性能评估见 ../../../docs/reviews/v310b1-migration-performance-20261119.md，
包含实际函数的查询计数、规模对比和权限发布测试。
