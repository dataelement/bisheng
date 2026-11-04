#!/usr/bin/env python3
"""Preserve enterprise capability access as revocable all-member grants.

Run after publish_authorization_model_change.py while API/workers are stopped.
Dry-run is the default; apply requires the live Store ID and an audit operator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import app_context, close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.runtime_heartbeat import list_runtime_heartbeats  # noqa: E402
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill  # noqa: E402
from bisheng.permission.application.runtime import build_f048_permission_runtime  # noqa: E402
from bisheng.permission.domain.models import (  # noqa: E402
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository  # noqa: E402
from bisheng.permission.domain.schemas import VerifiedPermissionTarget  # noqa: E402
from bisheng.permission.domain.services.permission_action_service import PermissionActor  # noqa: E402
from bisheng.tool.domain.const import ToolPresetType  # noqa: E402
from bisheng.tool.domain.models.gpts_tools import GptsToolsType  # noqa: E402


def migration_state(mode, operation, has_tenant_source):
    """An explicit revocation survives every migration rerun."""
    if operation is not None and str(operation.status) != "FINALIZED":
        raise RuntimeError("Reconcile the existing capability projection before retrying migration")
    if mode is not None and mode.projection_state != "CURRENT":
        raise RuntimeError("Reconcile the resource permission projection before migration")
    if operation is not None or has_tenant_source:
        return "preserved"
    return "create" if mode is None else "migrate"


async def inventory():
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tools = (
                await session.exec(
                    select(GptsToolsType).where(
                        GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                        GptsToolsType.is_delete == 0,
                    )
                )
            ).all()
            skills = (await session.exec(select(LinsightSkill).where(LinsightSkill.source != "personal"))).all()
    result = []
    for row in tools:
        # Preset classification is authoritative; historical creator metadata stays intact.
        result.append((row.tenant_id, "tool", str(row.id), None))
    result.extend((row.tenant_id, "linsight_skill", str(row.id), row.created_by) for row in skills)
    return sorted(result)


async def run(args):
    await initialize_app_context(settings, instance_role="script")
    client = await app_context.get_context("openfga").async_get_instance()
    if args.apply:
        if args.confirm_store_id != client.store_id:
            raise RuntimeError("Store confirmation mismatch")
        if await list_runtime_heartbeats():
            raise RuntimeError("Stop API and worker permission runtimes before applying migration")
    components = await build_f048_permission_runtime(client)
    runtime = components.facade
    catalog = await runtime.current_catalog()
    await components.marker.wait_until_ready(
        timeout_seconds=float(settings.openfga.recent_consistency_window_seconds) + 5
    )
    results = []
    for tenant_id, resource_type, resource_id, owner in await inventory():
        if not tenant_id or not resource_id.isdigit():
            raise RuntimeError("Capability is missing its tenant or resource identity")
        token = set_current_tenant_id(tenant_id)
        try:
            key = f"capability-default-v1:{tenant_id}:{resource_type}:{resource_id}"
            operation = await ProjectionRepository().aget_operation_by_idempotency(key)
            async with get_async_db_session() as session:
                mode = (
                    await session.exec(
                        select(ResourcePermissionMode).where(
                            ResourcePermissionMode.tenant_id == tenant_id,
                            ResourcePermissionMode.resource_type == resource_type,
                            ResourcePermissionMode.resource_id == resource_id,
                        )
                    )
                ).first()
                source = (
                    await session.exec(
                        select(PermissionGrantAssignee)
                        .join(
                            PermissionGrant,
                            PermissionGrant.id == PermissionGrantAssignee.grant_id,
                        )
                        .where(
                            PermissionGrant.tenant_id == tenant_id,
                            PermissionGrant.resource_type == resource_type,
                            PermissionGrant.resource_id == resource_id,
                            PermissionGrantAssignee.subject_type == "tenant",
                        )
                    )
                ).first()
            state = migration_state(mode, operation, source is not None)
            actor = PermissionActor(user_id=args.operator_id, current_tenant_id=tenant_id, super_admin=True)
            target = VerifiedPermissionTarget.from_business_service(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_version=int(mode.version) if mode else 0,
                context_version=key,
            )
            runtime.tenant_use_grant(target, catalog)
            if args.apply and state == "create":
                if owner:
                    await runtime.authorize_created(
                        actor=actor, target=target, owner_user_id=owner, mode="CUSTOM", shared_with_tenant=True
                    )
                else:
                    await runtime.authorize_system_owned(actor=actor, target=target, action_codes=("use", "visible"))
            elif args.apply and state == "migrate":
                await runtime.migrate_capability_default(
                    actor=actor, target=target, remove_public_markers=resource_type == "tool"
                )
            results.append({"tenant_id": tenant_id, "type": resource_type, "id": resource_id, "action": state})
        finally:
            current_tenant_id.reset(token)
    print(json.dumps({"applied": args.apply, "resources": results}, ensure_ascii=False))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-store-id")
    parser.add_argument("--operator-id", type=int, default=1)
    args = parser.parse_args(argv)
    if args.operator_id <= 0 or (args.apply and not args.confirm_store_id):
        parser.error("A positive operator ID and --confirm-store-id for apply are required")
    return args


async def main():
    try:
        await run(parse_args())
    finally:
        await close_app_context()


if __name__ == "__main__":
    asyncio.run(main())
