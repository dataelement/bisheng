#!/usr/bin/env python3
"""Close the permission gate of hosted apps deleted before the delete fix.

Why: until 2026-09-16 ``AppStateService.delete`` flipped the app to ``deleted`` and only
then re-read its permission record. The app adapter refuses to build a target for a
deleted app (19003), so the delete projection never ran and the app kept its
``permission_enabled`` markers. The service is fixed; this script repairs apps deleted
earlier by projecting the removal with the record as it was before the transition (the
same record the fixed service uses).

What "repaired" means: F048's RESOURCE_DELETE plan removes only the ``permission_enabled``
markers (``user:*`` / ``service_account:*``) — closing that gate denies every check on the
resource. Grant links, ``custom_mode`` markers and visible-projection tuples on the object
stay, exactly as after deleting any other F048 resource type, so they are reported but
not treated as leftovers.

Run from ``src/backend``. Dry-run is the default and writes nothing::

    PYTHONPATH=./ .venv/bin/python scripts/repair_deleted_app_grants.py
    PYTHONPATH=./ .venv/bin/python scripts/repair_deleted_app_grants.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/repair_deleted_app_grants.py --apply --app-id <app_id>

Exit codes: 0 = nothing left to repair (or dry-run finished), 1 = at least one app still
has a ``permission_enabled`` marker after ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import gc
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.app import App  # noqa: E402

# A live state the app adapter accepts; only used to rebuild the pre-deletion target.
_PRE_DELETION_STATE = "stopped"
_GATE_RELATION = "permission_enabled"


async def _deleted_apps(app_id: str | None) -> list[App]:
    statement = select(App).where(App.state == "deleted")
    if app_id:
        statement = statement.where(App.id == app_id)
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            return list((await session.exec(statement.order_by(App.update_time.asc()))).all())


async def run(args: argparse.Namespace) -> int:
    from bisheng.core.openfga.manager import aget_fga_client
    from bisheng.permission.application.access import get_f048_resource_adapter
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    fga = await aget_fga_client()
    if fga is None:
        print("OpenFGA client unavailable — is openfga.enabled set for this config?")
        return 1
    adapter = await get_f048_resource_adapter("app")

    apps = await _deleted_apps(args.app_id)
    print(f"deleted apps found: {len(apps)} (mode: {'apply' if args.apply else 'dry-run'})")
    still_dirty = 0
    for app in apps:
        tuples = await fga.read_tuples(object=f"app:{app.id}")
        gate = [t for t in tuples if t.get("relation") == _GATE_RELATION]
        if not gate:
            print(f"  closed   app:{app.id} slug={app.slug} (other tuples kept by design: {len(tuples)})")
            continue
        print(f"  open     app:{app.id} slug={app.slug} tenant={app.tenant_id} gate_markers={len(gate)}")
        if not args.apply:
            continue

        set_current_tenant_id(int(app.tenant_id or 0))
        record = await adapter.load_permission_record(app.id)
        if record is None:
            print("    skipped: no permission record (the mirror row is gone; needs a manual look)")
            still_dirty += 1
            continue
        await adapter.project_delete(
            record=dataclasses.replace(record, state=_PRE_DELETION_STATE),
            actor=PermissionActor(
                user_id=args.operator_id,
                current_tenant_id=int(app.tenant_id or 0),
                super_admin=False,
            ),
        )
        remaining = await fga.read_tuples(object=f"app:{app.id}")
        gate_left = [t for t in remaining if t.get("relation") == _GATE_RELATION]
        print(
            f"    projected removal; gate_markers left={len(gate_left)} (other tuples kept by design: {len(remaining) - len(gate_left)})"
        )
        if gate_left:
            still_dirty += 1
    return 1 if still_dirty else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Project the removal (default: dry-run)")
    parser.add_argument("--app-id", help="Repair a single deleted app")
    parser.add_argument("--operator-id", type=int, default=1, help="Operator recorded on the projection (default 1)")
    args = parser.parse_args()

    async def _main() -> int:
        try:
            await initialize_app_context(settings, instance_role="script")
            from bisheng.api.services.f048_permission_runtime import initialize_f048_worker_runtime
            from bisheng.permission.application.process_runtime import register_f048_permission_runtime_context

            register_f048_permission_runtime_context(initialize_f048_worker_runtime)
            return await run(args)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
