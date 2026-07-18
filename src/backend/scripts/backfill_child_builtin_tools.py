#!/usr/bin/env python3
import argparse
import asyncio
import gc
import json

from sqlmodel import col, select  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant  # noqa: E402
from bisheng.tool.domain.const import ToolPresetType  # noqa: E402
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType  # noqa: E402


async def _copy_root_builtin_tools_to_tenant(tenant_id: int) -> dict:
    result = {
        "tenant_id": tenant_id,
        "created_types": 0,
        "created_tools": 0,
        "skipped_tools": 0,
    }
    if tenant_id == ROOT_TENANT_ID:
        return result

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            root_types = (await session.exec(
                select(GptsToolsType).where(
                    GptsToolsType.tenant_id == ROOT_TENANT_ID,
                    GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                    GptsToolsType.is_delete == 0,
                ).order_by(GptsToolsType.id.asc())
            )).all()
            if not root_types:
                return result

            root_tools = (await session.exec(
                select(GptsTools).where(
                    col(GptsTools.type).in_([row.id for row in root_types]),
                    GptsTools.is_delete == 0,
                ).order_by(GptsTools.id.asc())
            )).all()
            child_types = (await session.exec(
                select(GptsToolsType).where(
                    GptsToolsType.tenant_id == tenant_id,
                    GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                    GptsToolsType.is_delete == 0,
                )
            )).all()
            child_tools = (await session.exec(
                select(GptsTools).where(
                    GptsTools.tenant_id == tenant_id,
                    GptsTools.is_delete == 0,
                )
            )).all()

        child_type_by_name = {row.name: row for row in child_types}
        child_tool_by_key = {row.tool_key: row for row in child_tools}
        type_map: dict[int, GptsToolsType] = {}

        for root_type in root_types:
            child_type = child_type_by_name.get(root_type.name)
            if child_type is None:
                child_type = GptsToolsType(
                    name=root_type.name,
                    logo=root_type.logo,
                    extra=root_type.extra,
                    description=root_type.description,
                    server_host=root_type.server_host,
                    auth_method=root_type.auth_method,
                    api_key=root_type.api_key,
                    auth_type=root_type.auth_type,
                    is_preset=root_type.is_preset,
                    user_id=root_type.user_id,
                    tenant_id=tenant_id,
                    openapi_schema=root_type.openapi_schema,
                    is_shared=root_type.is_shared,
                )
                session.add(child_type)
                await session.flush()
                result["created_types"] += 1
                child_type_by_name[child_type.name] = child_type
            type_map[root_type.id] = child_type

        for root_tool in root_tools:
            if root_tool.tool_key in child_tool_by_key:
                result["skipped_tools"] += 1
                continue
            child_type = type_map.get(root_tool.type)
            if child_type is None:
                result["skipped_tools"] += 1
                continue
            new_tool = GptsTools(
                name=root_tool.name,
                logo=root_tool.logo,
                desc=root_tool.desc,
                tool_key=root_tool.tool_key,
                type=child_type.id,
                is_preset=root_tool.is_preset,
                is_delete=root_tool.is_delete,
                api_params=root_tool.api_params,
                user_id=root_tool.user_id,
                tenant_id=tenant_id,
                extra=root_tool.extra,
            )
            session.add(new_tool)
            result["created_tools"] += 1

        await session.commit()
    return result


async def backfill(dry_run: bool) -> int:
    summaries = []
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            rows = (await session.exec(
                select(Tenant).where(
                    Tenant.parent_tenant_id == ROOT_TENANT_ID,
                    Tenant.status != 'archived',
                ).order_by(Tenant.id.asc())
            )).all()
    for tenant in rows:
        if dry_run:
            summary = {
                "tenant_id": tenant.id,
                "tenant_name": tenant.tenant_name,
                "created_types": 0,
                "created_tools": 0,
                "skipped_tools": 0,
                "dry_run": True,
            }
            print(f"[dry-run] would backfill builtin tools for tenant_id={tenant.id} tenant_name={tenant.tenant_name}")
        else:
            summary = await _copy_root_builtin_tools_to_tenant(tenant.id)
            summary["tenant_name"] = tenant.tenant_name
            print(
                f"[done] tenant_id={tenant.id} tenant_name={tenant.tenant_name} "
                f"created_types={summary['created_types']} created_tools={summary['created_tools']} "
                f"skipped_tools={summary['skipped_tools']}"
            )
        summaries.append(summary)
    print(json.dumps({"dry_run": dry_run, "tenants": summaries}, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill builtin tools for child tenants")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing data")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()


    async def _main() -> int:
        try:
            return await backfill(args.dry_run)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)


    raise SystemExit(asyncio.run(_main()))
