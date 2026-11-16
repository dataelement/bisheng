"""Business-owned reads and writes for explicit department projection recovery."""

from contextlib import asynccontextmanager

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant


def department_snapshot(row):
    if row is None:
        return None
    return {
        "id": int(row.id),
        "tenant_id": int(row.tenant_id),
        "parent_id": row.parent_id,
        "path": row.path,
        "status": row.status,
        "deleted": int(row.is_deleted or 0),
        "is_tenant_root": int(row.is_tenant_root or 0),
        "mounted_tenant_id": row.mounted_tenant_id,
        "state": row.permission_projection_state,
        "version": int(row.permission_projection_version),
        "operation_id": row.permission_projection_operation_id,
    }


class DepartmentRecoveryRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _session(self, session=None):
        if session is not None:
            yield session
        else:
            async with self.session_factory() as own:
                yield own

    async def high_water(self):
        async with self._session() as session:
            return int((await session.exec(select(func.max(Department.id)))).one() or 0)

    async def page(self, after, upper, limit):
        async with self._session() as session:
            rows = (
                await session.exec(
                    select(
                        Department.id,
                        Department.tenant_id,
                        Department.parent_id,
                        Department.path,
                        Department.status,
                        Department.is_deleted,
                        Department.is_tenant_root,
                        Department.mounted_tenant_id,
                        Department.permission_projection_state,
                        Department.permission_projection_version,
                        Department.permission_projection_operation_id,
                    )
                    .where(
                        Department.id > after,
                        Department.id <= upper,
                    )
                    .order_by(Department.id)
                    .limit(limit)
                )
            ).all()
            return [department_snapshot(row) for row in rows]

    async def get(self, department_id, *, session=None, lock=False):
        async with self._session(session) as db:
            statement = select(Department).where(Department.id == department_id)
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            return department_snapshot((await db.exec(statement)).first())

    async def ancestors(self, department, *, session=None, lock=False):
        rows = []
        seen = {department["id"]}
        current = department["parent_id"]
        with bypass_tenant_filter():
            async with self._session(session) as db:
                # The path is a read hint, never proof: follow actual parent IDs
                # below, falling back to primary-key reads for stale paths.
                hints = {int(value) for value in department["path"].split("/") if value.isdecimal()}
                hints.discard(department["id"])
                if len(hints) > 100:
                    raise ValueError("ANCESTRY_CYCLE_OR_LIMIT")
                prefetched = {}
                if hints:
                    prefetched = {
                        int(row.id): department_snapshot(row)
                        for row in (await db.exec(select(Department).where(Department.id.in_(hints)))).all()
                    }
                while current is not None:
                    if current in seen or len(rows) >= 100:
                        raise ValueError("ANCESTRY_CYCLE_OR_LIMIT")
                    seen.add(current)
                    row = prefetched.get(current) or await self.get(current, session=db)
                    if row is None:
                        raise ValueError("ANCESTOR_MISSING")
                    rows.append(row)
                    current = row["parent_id"]
                if lock:
                    identities = [row["id"] for row in rows]
                    locked = {}
                    if identities:
                        statement = (
                            select(Department)
                            .where(Department.id.in_(identities))
                            .order_by(Department.id)
                            .with_for_update(nowait=True)
                            .execution_options(populate_existing=True)
                        )
                        locked = {int(row.id): department_snapshot(row) for row in (await db.exec(statement)).all()}
                    # Use current locking reads, not a repeatable-read snapshot from
                    # before the locks. A changed chain requires a new preview.
                    fresh, current, visited = [], department["parent_id"], {department["id"]}
                    while current is not None:
                        item = locked.get(current)
                        if item is None or current in visited:
                            raise ValueError("ANCESTRY_CHANGED_DURING_RECOVERY")
                        visited.add(current)
                        fresh.append(item)
                        current = item["parent_id"]
                    return fresh
        return rows

    async def mount_facts(self, department, ancestors, *, session=None, lock=False):
        with bypass_tenant_filter():
            async with self._session(session) as db:
                mounts = [row for row in [department, *ancestors] if row["is_tenant_root"]]
                if not mounts:
                    return []
                facts = []
                for row in mounts:
                    statement = select(Tenant).where(Tenant.id == row["mounted_tenant_id"])
                    if lock:
                        statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
                    target = (await db.exec(statement)).first()
                    if target is None or target.status != "active" or target.root_dept_id != row["id"]:
                        raise ValueError("MOUNT_BINDING_INVALID")
                    facts.append({"id": int(target.id), "root_dept_id": target.root_dept_id, "status": target.status})
                nested = (
                    await db.exec(
                        select(Department.id)
                        .where(
                            Department.path.startswith(department["path"]),
                            Department.id != department["id"],
                            Department.is_tenant_root == 1,
                        )
                        .limit(1)
                    )
                ).first()
                if len(mounts) > 1 or (mounts and nested is not None):
                    raise ValueError("NESTED_MOUNT")
                return facts

    async def finalize(self, before, target_version, session):
        result = await session.execute(
            update(Department)
            .where(
                Department.id == before["id"],
                Department.tenant_id == before["tenant_id"],
                Department.parent_id == before["parent_id"],
                Department.path == before["path"],
                Department.status == before["status"],
                Department.is_deleted == before["deleted"],
                Department.permission_projection_operation_id == before["operation_id"],
                Department.permission_projection_version == before["version"],
                Department.permission_projection_state == before["state"],
            )
            .values(permission_projection_state="CURRENT", permission_projection_version=target_version)
        )
        return result.rowcount == 1
