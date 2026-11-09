"""Frozen permission rows only; no grants are allocated and no FGA is called."""

from collections import defaultdict

from sqlalchemy import bindparam, select, update

from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.f118_catalog_write_repository import _blocked, _Current
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration.f118_plan import (
    PermissionResourceBaseline,
    ResourceRetirementPlan,
    ResourceRetirementPlanner,
)


class F118ResourceWriteRepository:
    def __init__(self, *, snapshot_repository=None, permission_planner=None):
        self.planner = permission_planner
        self.snapshots = snapshot_repository or PermissionMigrationSnapshotRepository()
        if not isinstance(self.snapshots, PermissionMigrationSnapshotRepository):
            _blocked("actual_snapshot_repository_required")

    async def aread_resource(self, session, *, mode_id, resource_keys, lock=False):
        current = _Current(session)
        result = await self.snapshots.aload_resource(session, mode_id=mode_id, resource_keys=resource_keys, lock=lock)
        current.check()
        return result

    async def alist_resources(self, session, *, lock=False):
        """One complete tenant pass; reject orphan buckets instead of hiding them."""
        current = _Current(session)
        if lock:
            # Run precedes these bounded row locks. This is used only for the
            # final SQL transaction, after all external IO has finished.
            for model in (
                ResourcePermissionMode,
                PermissionGrant,
                PermissionGrantAssignee,
                PermissionVisibleSourceProjection,
            ):
                table, after = model.__table__, 0
                while True:
                    page = (
                        await current.execute(
                            select(table.c.id)
                            .where(table.c.tenant_id == current.tenant, table.c.id > after)
                            .order_by(table.c.id)
                            .limit(200)
                            .with_for_update()
                        )
                    ).all()
                    if len(page) < 200:
                        break
                    after = page[-1][0]
        values = []
        for method in (
            self.snapshots.alist_resource_modes,
            self.snapshots.alist_grants,
            self.snapshots.alist_assignees,
            self.snapshots.alist_visible_sources,
        ):
            rows, after = [], None
            while True:
                current.check()
                page = await method(session, after_id=after, limit=200)
                current.check()
                rows.extend(page)
                if len(page) < 200:
                    break
                after = page[-1].id
            values.append(rows)
        modes, grants, sources, visible = values
        by_key, by_grant, by_visible = defaultdict(list), defaultdict(list), defaultdict(list)
        for row in grants:
            by_key[(row.resource_type, row.resource_id)].append(row)
        for row in sources:
            by_grant[row.grant_id].append(row)
        for row in visible:
            by_visible[(row.source.resource_type, row.source.resource_id)].append(row)
        keys = {(row.resource_type, row.resource_id) for row in modes}
        if set(by_key) - keys or set(by_visible) - keys or set(by_grant) - {row.id for row in grants}:
            _blocked("orphan_permission_rows")
        return tuple(
            PermissionResourceBaseline(
                current.tenant,
                row.resource_type,
                row.resource_id,
                row,
                tuple(by_key[(row.resource_type, row.resource_id)]),
                tuple(
                    source for grant in by_key[(row.resource_type, row.resource_id)] for source in by_grant[grant.id]
                ),
                tuple(by_visible[(row.resource_type, row.resource_id)]),
            )
            for row in modes
        )

    async def _updates(self, current, model, rows, names):
        table = model.__table__
        query = (
            update(table)
            .where(table.c.id == bindparam("f118_pk"), table.c.tenant_id == bindparam("f118_tenant"))
            .values(**{name: bindparam("f118_" + name) for name in names}, update_time=table.c.update_time)
        )
        for start in range(0, len(rows), 200):
            result = await current.execute(query, rows[start : start + 200])
            if result.rowcount != len(rows[start : start + 200]):
                _blocked("resource_write_conflict")

    async def aapply_resource(self, session, *, plan):
        if type(plan) is not ResourceRetirementPlan or plan.after is None or plan.namespace_target is None:
            _blocked("complete_resource_plan_required")
        if (
            type(self.planner) is not ResourceRetirementPlanner
            or plan.catalog_plan is not self.planner.catalog_plan
            or self.planner.build(before=plan.before, namespace_target=plan.namespace_target) != plan
        ):
            _blocked("resource_plan_changed")
        current = _Current(session)
        if plan.before.tenant_id != current.tenant:
            _blocked("resource_tenant_changed")
        keys = tuple(
            dict.fromkeys(
                (
                    (plan.before.resource_type, plan.before.resource_id),
                    (plan.after.resource_type, plan.after.resource_id),
                )
            )
        )
        before = await self.aread_resource(session, mode_id=plan.before.mode.id, resource_keys=keys, lock=True)
        if before == plan.after:
            return before
        if before != plan.before:
            _blocked("resource_before_changed")
        async with session.begin_nested():
            owned = _Current(session)
            if owned.tenant != current.tenant:
                _blocked("resource_tenant_changed")
            mode = ResourcePermissionMode.__table__
            changes = {
                name: getattr(plan.after.mode, name)
                for name in ("resource_type", "parent_type")
                if getattr(plan.before.mode, name) != getattr(plan.after.mode, name)
            }
            if changes:
                await owned.execute(
                    update(mode)
                    .where(mode.c.id == before.mode.id, mode.c.tenant_id == current.tenant)
                    .values(**changes, update_time=mode.c.update_time)
                )
            grant_updates = [
                {"f118_pk": old.id, "f118_tenant": current.tenant, "f118_resource_type": new.resource_type}
                for old, new in zip(plan.before.grants, plan.after.grants, strict=True)
                if old.resource_type != new.resource_type
            ]
            await self._updates(owned, PermissionGrant, grant_updates, ("resource_type",))
            visible_updates = [
                {
                    "f118_pk": old.id,
                    "f118_tenant": current.tenant,
                    "f118_resource_type": new.source.resource_type,
                    "f118_tuple_fingerprint": new.source.tuple_fingerprint,
                }
                for old, new in zip(plan.before.visible_sources, plan.after.visible_sources, strict=True)
                if (old.source.resource_type, old.source.tuple_fingerprint)
                != (new.source.resource_type, new.source.tuple_fingerprint)
            ]
            await self._updates(
                owned, PermissionVisibleSourceProjection, visible_updates, ("resource_type", "tuple_fingerprint")
            )
            result = await self.aread_resource(session, mode_id=before.mode.id, resource_keys=keys, lock=True)
            if result != plan.after:
                _blocked("resource_after_changed")
            owned.check()
        current.check()
        return result
