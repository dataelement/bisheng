#!/usr/bin/env python3
"""Backfill child-tenant builtin tools and their F048 system projections.

Run from ``src/backend``. The default applies the idempotent copy; pass
``--dry-run`` to list candidate tenants without changing business or permission
state.
"""

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    close_app_context,
    initialize_app_context,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant  # noqa: E402
from bisheng.workstation.domain.services.workstation_service import (  # noqa: E402
    WorkStationService,
)


async def _copy_root_builtin_tools_to_tenant(tenant_id: int) -> dict:
    return await WorkStationService.acopy_root_builtin_tools_to_tenant(tenant_id)


async def backfill(dry_run: bool) -> int:
    summaries = []
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            rows = (
                await session.exec(
                    select(Tenant)
                    .where(
                        Tenant.parent_tenant_id == ROOT_TENANT_ID,
                        Tenant.status != "archived",
                    )
                    .order_by(Tenant.id.asc())
                )
            ).all()
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
                f"skipped_tools={summary['skipped_tools']} projected_types={summary['projected_types']}"
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
            await initialize_app_context(settings, instance_role="script")
            from bisheng.api.services.f048_permission_runtime import (
                initialize_f048_worker_runtime,
            )
            from bisheng.permission.application.process_runtime import (
                register_f048_permission_runtime_context,
            )

            register_f048_permission_runtime_context(initialize_f048_worker_runtime)
            return await backfill(args.dry_run)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    raise SystemExit(asyncio.run(_main()))
