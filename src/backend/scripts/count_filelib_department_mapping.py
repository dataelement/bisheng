#!/usr/bin/env python3
"""Print total row count in ``filelib_department_mapping``.

Run from ``src/backend`` (requires ``config`` env pointing at config.yaml)::

    export config=/path/to/config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/count_filelib_department_mapping.py

    bash scripts/count_filelib_department_mapping.sh
"""

from __future__ import annotations

import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import func  # noqa: E402
from sqlmodel import select  # noqa: E402

from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.open_endpoints.domain.models.filelib_department_mapping import (  # noqa: E402
    FilelibDepartmentMapping,
)


async def count_filelib_department_mapping_rows() -> int:
    async with get_async_db_session() as session:
        total = await session.scalar(select(func.count()).select_from(FilelibDepartmentMapping))
        return int(total or 0)


async def _run() -> int:
    total = await count_filelib_department_mapping_rows()
    print(f"[count_filelib_department_mapping] total={total}")
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:
        print(f"[count_filelib_department_mapping] failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
