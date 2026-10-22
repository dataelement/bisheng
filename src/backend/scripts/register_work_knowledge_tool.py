#!/usr/bin/env python3
"""Register the built-in knowledge search catalog entry in an existing database.

Run from src/backend with the live service config. Default: read-only preview.
Use --apply to insert the missing category/tool in one transaction, then run
reconcile_f048_system_owned_resources.py to provision the permission projection.
Run a single registration process during the release maintenance window.
Existing catalog entries and administrator configuration are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session, get_database_connection  # noqa: E402
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType  # noqa: E402

TOOL_KEY = "bisheng_knowledge_search"


def seed_records() -> tuple[dict, dict]:
    data_dir = _BACKEND_ROOT / "bisheng/database/data"
    tools = json.loads((data_dir / "t_gpts_tools.json").read_text())
    categories = json.loads((data_dir / "t_gpts_tools_type.json").read_text())
    tool = next(item for item in tools if item["tool_key"] == TOOL_KEY)
    category = next(item for item in categories if item["id"] == tool["type"])
    return category, tool


def require_system_entry(row) -> None:
    if row.tenant_id != 1 or row.user_id is not None or row.is_preset != 1 or row.is_delete != 0:
        raise ValueError("Catalog conflict: expected an active system-owned preset entry.")


async def register(session, *, apply: bool) -> dict:
    category_seed, tool_seed = seed_records()
    tools = (await session.exec(select(GptsTools).where(GptsTools.tool_key == TOOL_KEY))).all()
    if len(tools) > 1:
        raise ValueError("Catalog conflict: multiple tools share the built-in key.")
    if tools:
        tool = tools[0]
        require_system_entry(tool)
        category = await session.get(GptsToolsType, tool.type)
        if category is None:
            raise ValueError("Catalog conflict: the tool category is missing.")
        require_system_entry(category)
        return {"status": "current", "tool_id": tool.id, "category_id": category.id}

    categories = (await session.exec(select(GptsToolsType).where(GptsToolsType.name == category_seed["name"]))).all()
    if len(categories) > 1:
        raise ValueError("Catalog conflict: multiple categories share the built-in name.")
    category = categories[0] if categories else None
    if category is not None:
        require_system_entry(category)
    if not apply:
        return {"status": "planned", "create_category": category is None, "create_tool": True}

    if category is None:
        category = GptsToolsType(**{k: v for k, v in category_seed.items() if k != "id"}, tenant_id=1)
        session.add(category)
        await session.flush()
    tool = GptsTools(**{k: v for k, v in tool_seed.items() if k not in {"id", "type"}}, type=category.id, tenant_id=1)
    session.add(tool)
    await session.flush()
    result = {"status": "registered", "tool_id": tool.id, "category_id": category.id}
    await session.commit()
    return result


async def run(*, apply: bool) -> dict:
    connection = await get_database_connection()
    try:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await register(session, apply=apply)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Insert missing catalog entries")
    args = parser.parse_args()
    result = asyncio.run(run(apply=args.apply))
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
