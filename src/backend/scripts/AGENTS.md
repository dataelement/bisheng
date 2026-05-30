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

## 6. Database & Tenant Context

Scripts run **outside** the FastAPI request lifecycle, so the automatic tenant filter has no active tenant context. If your script touches tenant-scoped tables:

```python
from bisheng.core.context.tenant import bypass_tenant_filter

with bypass_tenant_filter():
    # cross-tenant reads/writes here
    ...
```

Without `bypass_tenant_filter()`, every query gets `WHERE tenant_id = NULL` injected and returns zero rows.

For async DB work use `get_async_db_session()` + `asyncio.run(main())`; for sync use `get_sync_db_session()`. Don't mix the two in one transaction.

---

## 7. Documentation Requirement

Every new script MUST:

1. Have a module-level docstring explaining **what it does, why it exists, and how to run it** (including the dry-run / apply distinction if applicable).
2. Add a short entry to `scripts/README.md` under the appropriate section, with at least one example invocation.

Operators should be able to discover the script from `README.md` alone.

---

## 8. Reference Script Layout (minimal)

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
