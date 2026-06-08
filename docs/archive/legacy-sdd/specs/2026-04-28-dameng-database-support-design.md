# DaMeng Database Support Design

**Date:** 2026-04-28  
**Status:** Approved  
**Branch:** feat/2.5.0-dm

---

## Goal

Add DaMeng (达梦) database support to Bisheng so customers can choose DaMeng instead of MySQL. Both databases must continue working from the same codebase — no parallel forks.

---

## Constraints & Decisions

| Topic | Decision |
|---|---|
| Deployment model | DaMeng is an alternative to MySQL; both supported simultaneously via `database_url` |
| Async driver | `dmAsync` (analogous to `aiomysql` for MySQL) |
| Sync driver | `dmPython` |
| Connection URL format | `dm+dmPython://user:pass@host:5236/schema` (sync) / `dm+dmAsync://...` (async) |
| Driver installation | `dmPython` and `dmAsync` are added to main `pyproject.toml` dependencies |
| `LONGTEXT` equivalent | `CLOB` on DaMeng |
| `ON UPDATE CURRENT_TIMESTAMP` | Database triggers on DaMeng (not application-level) |
| Migration strategy | Single track; dialect-aware branching at runtime (not parallel version files) |
| `information_schema` queries | Replaced with helper functions that branch on `conn.dialect.name` |

---

## Architecture

```
bisheng/core/database/
├── connection.py              # +dmPython→dmAsync URL conversion
├── dialect_helpers.py         # NEW — central dialect utilities
└── alembic/
    ├── env.py                 # Extend ensure_alembic_version_table for DaMeng
    └── versions/
        └── vX_dm_triggers.py  # NEW — CREATE TRIGGER for ON UPDATE CURRENT_TIMESTAMP

Model files (5 total):
  bisheng/database/models/message.py
  bisheng/common/models/config.py
  bisheng/tool/domain/models/gpts_tools.py
  bisheng/linsight/domain/models/linsight_sop.py
  bisheng/finetune/domain/models/finetune.py

pyproject.toml                 # Add dmPython, dmAsync to main dependencies
```

**Data flow:**  
`database_url` in `config.yaml` → `DatabaseConnectionManager` detects `dm+dmPython` → converts to `dm+dmAsync` for async engine → `LargeText` TypeDecorator renders `CLOB` when DaMeng dialect active → migrations call `dialect_helpers` instead of raw `information_schema` SQL.

---

## Component 1: `dialect_helpers.py` (new)

Location: `bisheng/core/database/dialect_helpers.py`

### Dialect detection

```python
def get_dialect_name(conn_or_engine) -> str:
    """Returns 'mysql' | 'dm' | 'sqlite' | 'postgresql'"""
```

### `LargeText` custom type

Replaces `sqlalchemy.dialects.mysql.LONGTEXT` in all 5 model files.

```python
class LargeText(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":   return dialect.type_descriptor(LONGTEXT())
        if dialect.name == "dm":      return dialect.type_descriptor(CLOB())
        return dialect.type_descriptor(Text())
```

### Migration guard helpers

Replace all 49 `information_schema` call sites in the 34 migration files:

```python
def table_exists(conn, table_name: str) -> bool: ...
def column_exists(conn, table_name: str, column_name: str) -> bool: ...
def index_exists(conn, table_name: str, index_name: str) -> bool: ...
def get_column_type(conn, table_name: str, column_name: str) -> str | None: ...
def get_version_num_length(conn) -> int | None: ...
```

Each function branches on `conn.dialect.name`.

---

## Component 2: Dialect-Agnostic Introspection via SQLAlchemy Inspector

Instead of raw `information_schema` SQL (which is MySQL-specific), all migration guard helpers use SQLAlchemy's `inspect()` API. This is dialect-agnostic and works on any properly-implemented SQLAlchemy dialect including DaMeng — no MySQL→DaMeng SQL mapping needed.

```python
from sqlalchemy import inspect

def table_exists(conn, table_name: str) -> bool:
    return inspect(conn).has_table(table_name)

def column_exists(conn, table_name: str, column_name: str) -> bool:
    cols = [c["name"] for c in inspect(conn).get_columns(table_name)]
    return column_name in cols

def index_exists(conn, table_name: str, index_name: str) -> bool:
    indexes = [i["name"] for i in inspect(conn).get_indexes(table_name)]
    return index_name in indexes

def get_version_num_length(conn) -> int | None:
    cols = inspect(conn).get_columns("alembic_version")
    for c in cols:
        if c["name"] == "version_num":
            return getattr(c["type"], "length", None)
    return None
```

This eliminates all `information_schema`, `DATABASE()`, `SYSOBJECTS`, `SYSCOLUMNS`, and `SYSINDEXES` references from the codebase entirely.

---

## Component 3: `connection.py` changes

### URL conversion

```python
def _convert_to_async_url(self, url: str) -> str:
    if "pymysql" in url:   return url.replace("pymysql", "aiomysql")
    if "psycopg2" in url:  return url.replace("psycopg2", "asyncpg")
    if "dmPython" in url:  return url.replace("dmPython", "dmAsync")  # NEW
    return url
```

### Engine config

`_get_default_engine_config` needs a DaMeng branch — no `charset` connect arg, no pool size override beyond defaults. The `pool_size`, `max_overflow`, `pool_timeout`, `pool_pre_ping`, `pool_recycle` defaults apply as-is.

---

## Component 4: `alembic/env.py` change

`ensure_alembic_version_table()` currently only handles MySQL. Add a DaMeng branch:

```python
def ensure_alembic_version_table(connection) -> None:
    dialect_name = connection.dialect.name
    if dialect_name not in ("mysql", "dm"):
        return
    # check/create/widen alembic_version using dialect_helpers
```

---

## Component 5: `ON UPDATE CURRENT_TIMESTAMP` triggers

New migration file: `vX_dm_triggers.py`

Tables requiring triggers (all have an `update_time` column):

- `flow`, `flowversion`, `assistant`, `assistantlink`
- `role`, `roleaccess`, `usergroup`, `group_resource`  
- `flow_version`, `mark_record`, `mark_task`, `evaluation`
- `user_link`, `recall_chunk`, `failed_tuple`, `tenant`
- DDD module tables: `knowledge`, `knowledgefile`, `llm_server`, `llm_model`
- Other tables identified during implementation scan

Trigger template per table:

```sql
CREATE OR REPLACE TRIGGER trg_{table}_update_time
BEFORE UPDATE ON {table}
FOR EACH ROW
BEGIN
  :new.update_time := CURRENT_TIMESTAMP;
END
```

> **Note:** DaMeng uses Oracle-style PL/SQL trigger syntax (`:new.col := value`). Verify exact syntax against DaMeng documentation before implementation.

`upgrade()` — skips entirely if `dialect != "dm"`.  
`downgrade()` — drops triggers if `dialect == "dm"`.

---

## Component 6: Model file changes

Replace in 5 model files:

```python
# Before
from sqlalchemy.dialects.mysql import LONGTEXT
Column(LONGTEXT)

# After
from bisheng.core.database.dialect_helpers import LargeText
Column(LargeText)
```

`mysql_charset` / `mysql_collate` in `__table_args__` — **no change needed**. SQLAlchemy silently ignores unrecognised dialect-prefixed table kwargs on other dialects.

---

## Component 7: `pyproject.toml`

Add to main `dependencies`:

```toml
"dmPython>=X.Y",
"dmAsync>=X.Y",
```

Exact version numbers to be confirmed from the DaMeng installation package.

---

## Testing

| Layer | What |
|---|---|
| Unit | `LargeText.load_dialect_impl` with mock dialects (`mysql`, `dm`, `sqlite`) |
| Unit | Each `dialect_helpers` function with mock `conn.dialect.name = "dm"` |
| Integration (manual) | `alembic upgrade head` against `192.168.107.9` — all migrations green |
| Regression | Existing test suite (SQLite) must remain green |

---

## What Does NOT Change

- All business logic, DAOs, services, API endpoints
- Alembic migration history chain (single linear track)
- MySQL and SQLite paths
- Frontend code

---

## Deployment Steps (DaMeng customer)

1. Ensure `dmPython` and `dmAsync` are available (installed with DaMeng server package)
2. Set in `config.yaml`:
   ```yaml
   database_url: dm+dmPython://SYSDBA:password@192.168.107.9:5236/BISHENG
   ```
3. Run `alembic upgrade head` — migrations auto-detect dialect, create DaMeng triggers, use DaMeng-compatible DDL
4. Start Bisheng normally
