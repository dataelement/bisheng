#!/usr/bin/env python3
"""Upgrade the knowledge search catalog and its F048 permission projection.

Run from src/backend with the live service config. Default: read-only preview
including the live Store ID. Apply requires --confirm-store-id and --operator-id.
One maintenance operation registers missing rows and reconciles the knowledge
category through the permission facade. Success means the projection is CURRENT.
Run one upgrade process during maintenance; a retry resumes from committed rows
and preserves existing catalog configuration and permission modes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlmodel import select  # noqa: E402

from bisheng.api.services.f048_system_resource_bootstrap import (  # noqa: E402
    load_system_owned_resource_inventory,
)
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    app_context,
    close_app_context,
    initialize_app_context,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.permission.application.runtime import build_f048_permission_runtime  # noqa: E402
from bisheng.permission.application.system_resource_reconcile import (  # noqa: E402
    reconcile_system_owned_resources,
)
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
        return {
            "status": "planned",
            "create_category": category is None,
            "create_tool": True,
            **({"category_id": category.id} if category is not None else {}),
        }

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


async def reconcile_category(category_id: int, facade, *, apply: bool, operator_id: int) -> dict:
    """Reconcile exactly the verified system-owned knowledge tool category."""
    inventory = await load_system_owned_resource_inventory()
    invalid = [item for item in inventory.invalid if item.resource_id == str(category_id)]
    if invalid:
        raise ValueError(f"Knowledge tool category conflicts with system ownership: {invalid[0].reason}")
    resources = tuple(
        item
        for item in inventory.resources
        if item.resource_type == "tool" and item.resource_id == str(category_id) and item.tenant_id == 1
    )
    if len(resources) != 1:
        raise ValueError("Expected one verified system-owned knowledge tool category.")
    report = await reconcile_system_owned_resources(facade, resources, apply=apply, operator_id=operator_id)
    return {
        "ready": report.current_count == 1,
        "before": [asdict(item) for item in report.before],
        "after": [asdict(item) for item in report.after],
    }


async def run(*, apply: bool, confirm_store_id: str | None = None, operator_id: int = 1) -> dict:
    if operator_id <= 0 or (apply and not confirm_store_id):
        raise ValueError("Apply requires the previewed Store ID and a positive audit operator ID.")
    try:
        await initialize_app_context(settings, instance_role="script")
        manager = app_context.get_context("openfga")
        client = await manager.async_get_instance()
        if apply and confirm_store_id != client.store_id:
            raise ValueError("Store confirmation must match the live permission Store.")
        components = await build_f048_permission_runtime(client)
        await components.marker.wait_until_ready(
            timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5.0,
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                catalog = await register(session, apply=False)
        permission = {"ready": False, "status": "planned_with_category"}
        if "category_id" in catalog:
            # Validate existing projection state before committing any new tool row.
            permission = await reconcile_category(
                catalog["category_id"],
                components.facade,
                apply=False,
                operator_id=operator_id,
            )
        if apply:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    catalog = await register(session, apply=True)
            permission = await reconcile_category(
                catalog["category_id"],
                components.facade,
                apply=True,
                operator_id=operator_id,
            )
            if not permission["ready"]:
                raise RuntimeError("Knowledge tool permission projection must reach CURRENT.")
        return {
            "mode": "apply" if apply else "dry-run",
            "store_id": client.store_id,
            "model_id": client.model_id,
            "catalog": catalog,
            "permission": permission,
            "ready": catalog["status"] in {"current", "registered"} and permission["ready"],
        }
    finally:
        await close_app_context()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Register and reconcile the knowledge tool")
    parser.add_argument("--confirm-store-id", help="Live Store ID returned by preview")
    parser.add_argument("--operator-id", type=int, help="Positive audit operator ID")
    args = parser.parse_args(argv)
    if args.apply and (not args.confirm_store_id or args.operator_id is None):
        parser.error("--apply requires --confirm-store-id and --operator-id")
    if args.operator_id is not None and args.operator_id <= 0:
        parser.error("--operator-id must be positive")
    return args


def main() -> int:
    args = parse_args()
    result = asyncio.run(
        run(
            apply=args.apply,
            confirm_store_id=args.confirm_store_id,
            operator_id=args.operator_id or 1,
        )
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
