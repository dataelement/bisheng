#!/usr/bin/env python3
"""Repair exact permission ownership left behind by an audited Child -> Root unmount.

From src/backend, with the live config::
    python scripts/repair_unmounted_tenant_permissions.py --source-tenant 18 --operator-id 1 --plan-file /private/plan.json
    python scripts/repair_unmounted_tenant_permissions.py --source-tenant 18 --operator-id 1 --plan-file /private/plan.json --apply --confirm-checksum <preview checksum>

Preview is read-only apart from the private backup file. Apply requires that
same immutable preview, archived Child, actual Root-owned resources, CURRENT
source mirrors, no conflicting destination and exact physical Grant graph.
Existing native journals own all writes and retries. --resume completes only
those original journals after interruption. No broad tuple reconcile or model
publication. Neither presets nor unrelated resources are migrated.
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope  # noqa: E402
from bisheng.permission.application.control_state import SqlPermissionControlState  # noqa: E402
from bisheng.permission.application.tenant_resource_transfer import (  # noqa: E402
    transfer_projection,
    verify_transfer_input,
)
from bisheng.permission.domain.repositories.tenant_transfer_repository import MODELS  # noqa: E402
from bisheng.permission.domain.services.tenant_transfer_policy import blocked, checksum, compile_transfer  # noqa: E402
from bisheng.tenant.application.resource_tenant_transfer import ResourceTenantTransferApplication  # noqa: E402
from scripts.f048_maintenance_runtime import (  # noqa: E402
    build_maintenance_projection,
    close_maintenance_context,
    initialize_maintenance_context,
    maintenance_client,
)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-tenant", type=int, required=True)
    parser.add_argument("--operator-id", type=int, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--resume", action="store_true")
    parser.add_argument("--confirm-checksum")
    args = parser.parse_args(argv)
    if args.source_tenant <= 1 or args.operator_id <= 0:
        parser.error("source must be a Child and operator must be positive")
    if (args.apply or args.resume) and not args.confirm_checksum:
        parser.error("apply/resume requires the immutable preview checksum")
    return args


async def verify(app, plan, before_graph, *, operator_id):
    """Verify full selected SQL provenance and full affected physical objects, not samples."""
    before = plan["permissions"]
    rename = {}
    for snapshot in before:
        compiled = compile_transfer(
            snapshot, source=plan["source"], destination=plan["destination"], pin=plan["pin"], operator_id=operator_id
        )
        old = {row.user for row in compiled.deltas if row.relation == "grant" and row.action == "DELETE"}
        new = {row.user for row in compiled.deltas if row.relation == "grant" and row.action == "WRITE"}
        # Pair by the model tuple, not ordering of opaque hashes.
        for old_key in old:
            model = next(row.user for row in compiled.deltas if row.object == old_key and row.relation == "model")
            new_key = next(
                row.object
                for row in compiled.deltas
                if row.action == "WRITE" and row.relation == "model" and row.user == model
            )
            rename[old_key] = new_key
        assert len(old) == len(new)
    expected = {key: set() for key in before_graph}
    for key, rows in before_graph.items():
        target = rename.get(key, key)
        expected.setdefault(target, set()).update(
            (rename.get(user, user), relation, rename.get(obj, obj)) for user, relation, obj in rows
        )
    for key in sorted(expected):
        if await app.projection._fga.read_object(key) != expected[key]:
            blocked("physical AFTER graph differs: " + key)
    with bypass_tenant_filter():
        async with app.sessions() as session:
            if await app.permissions.pin(session) != plan["pin"]:
                blocked("Catalog changed during verification")
            for snapshot in before:
                for model, key in zip(MODELS, ("mode", "grants", "assignees", "visible"), strict=True):
                    rows = [snapshot[key]] if key == "mode" else snapshot[key]
                    table = model.__table__
                    for old in rows:
                        # Core mappings preserve every frozen provenance field for comparison.
                        actual = (
                            (await session.execute(select(*table.c).where(table.c.id == old["id"]))).mappings().one()
                        )
                        wanted = {**old, "tenant_id": plan["destination"]}
                        if key == "mode":
                            wanted.update(
                                version=old["version"] + 1,
                                projection_state="CURRENT",
                                operation_id=actual["operation_id"],
                            )
                        for ignored in ("create_time", "update_time"):
                            wanted.pop(ignored, None)
                        observed = {name: actual[name] for name in wanted}
                        if checksum(observed) != checksum(wanted):
                            blocked("SQL AFTER differs: " + model.__tablename__)
    state = SqlPermissionControlState(session_factory=app.sessions)
    with tenant_execution_scope(plan["destination"]):
        for snapshot in before:
            mode = snapshot["mode"]
            version, _ = await state.permission_version(
                tenant_id=plan["destination"], resource_type=mode["resource_type"], resource_id=mode["resource_id"]
            )
            if version != mode["version"] + 1:
                blocked("permission readback differs")


async def execute(args):
    try:
        await initialize_maintenance_context(config=settings)
        client = await maintenance_client()
        if not await client.check(
            user=f"user:{args.operator_id}",
            relation="super_admin",
            object="system:global",
            consistency="HIGHER_CONSISTENCY",
        ):
            blocked("operator is not a current global administrator")
        # Register only live business models needed by this exact ownership inventory.
        from bisheng.channel.domain.models import channel  # noqa: F401
        from bisheng.database.models import assistant, flow  # noqa: F401
        from bisheng.knowledge.domain.models import knowledge, knowledge_file  # noqa: F401
        from bisheng.tool.domain.models import gpts_tools  # noqa: F401

        composed = await build_maintenance_projection(client)
        app = ResourceTenantTransferApplication(projection=transfer_projection(composed.projection, client))
        if args.apply or args.resume:
            document = json.loads(args.plan_file.read_text())
            plan = document["plan"]
            if (
                document["schema"] != 1
                or plan["source"] != args.source_tenant
                or plan["destination"] != 1
                or document["checksum"] != args.confirm_checksum
                or checksum(plan) != args.confirm_checksum
                or document["graph_checksum"] != checksum(document["fga_before"])
            ):
                blocked("saved preview confirmation differs")
            if args.resume:
                await app.resume(source=args.source_tenant, resources=plan["resources"])
            else:
                await app.apply(
                    plan,
                    operator_id=args.operator_id,
                    expected_checksum=args.confirm_checksum,
                    expected_graph=document["fga_before"],
                )
            await verify(app, plan, document["fga_before"], operator_id=args.operator_id)
            print(
                json.dumps(
                    {"state": "verified", "resource_count": len(plan["resources"]), "checksum": args.confirm_checksum}
                )
            )
            return 0
        plan = await app.preview(source=args.source_tenant, historical=True)
        graph = await verify_transfer_input(
            app.projection,
            plan["permissions"],
            source=args.source_tenant,
            destination=1,
            pin=plan["pin"],
            operator_id=args.operator_id,
        )
        graph = {key: sorted(rows) for key, rows in graph.items()}
        document = {
            "schema": 1,
            "plan": plan,
            "checksum": checksum(plan),
            "fga_before": graph,
            "graph_checksum": checksum(graph),
        }
        args.plan_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(args.plan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(document, output, sort_keys=True, default=str)
            output.flush()
            os.fsync(output.fileno())
        print(
            json.dumps(
                {
                    "state": "preview",
                    "resource_count": len(plan["resources"]),
                    "by_type": dict(Counter(kind for kind, ident in plan["resources"])),
                    "checksum": document["checksum"],
                    "backup_file": str(args.plan_file),
                }
            )
        )
        return 0
    finally:
        await close_maintenance_context()


def main():
    return asyncio.run(execute(arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
