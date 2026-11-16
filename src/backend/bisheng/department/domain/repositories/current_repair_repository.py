"""Current organization facts and guarded maintenance gates; no schema changes."""

from sqlalchemy import update
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.repositories.projection_recovery_repository import DepartmentRecoveryRepository


class CurrentDepartmentRepairRepository(DepartmentRecoveryRepository):
    max_members = 10000

    async def members(self, identity, *, session=None, lock=False):
        async with self._session(session) as db:
            statement = (
                select(UserDepartment)
                .where(UserDepartment.department_id == identity)
                .order_by(UserDepartment.id)
                .limit(self.max_members + 1)
            )
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            rows = list((await db.exec(statement)).all())
            if len(rows) > self.max_members or any(int(row.user_id) <= 0 for row in rows):
                raise ValueError("MEMBERSHIP_SCOPE_TOO_LARGE_OR_INVALID")
            return sorted({int(row.user_id) for row in rows})

    async def failure_context(self, department, *, session=None):
        """Bounded diagnostics following only the selected node's parent IDs."""
        result, seen, current = {"chain": []}, set(), department
        fields = (
            "id",
            "tenant_id",
            "parent_id",
            "path",
            "status",
            "deleted",
            "state",
            "operation_id",
            "is_tenant_root",
            "mounted_tenant_id",
        )
        with bypass_tenant_filter():
            while current is not None:
                if current["id"] in seen:
                    result["cycle_at_department_id"] = current["id"]
                    break
                if len(seen) >= 100:
                    result["ancestor_limit"] = 100
                    break
                seen.add(current["id"])
                result["chain"].append({key: current[key] for key in fields})
                parent = current["parent_id"]
                if parent is None:
                    break
                current = await self.get(parent, session=session)
                if current is None:
                    result["missing_parent_id"] = parent
        return result

    async def set_gate(self, before, operation_id, session):
        statement = self._guard(before).values(
            permission_projection_state="FAILED_CLOSED", permission_projection_operation_id=operation_id
        )
        if (await session.exec(statement)).rowcount != 1:
            raise ValueError("DEPARTMENT_GATE_CONFLICT")

    async def finish(self, before, operation_id, target_version, session):
        guarded = before | {"state": "FAILED_CLOSED", "operation_id": operation_id}
        statement = self._guard(guarded).values(
            permission_projection_state="CURRENT", permission_projection_version=target_version
        )
        if (await session.exec(statement)).rowcount != 1:
            raise ValueError("DEPARTMENT_FINALIZE_CONFLICT")

    @staticmethod
    def _guard(before):
        return (
            update(Department)
            .where(
                Department.id == before["id"],
                Department.tenant_id == before["tenant_id"],
                Department.parent_id == before["parent_id"],
                Department.path == before["path"],
                Department.status == before["status"],
                Department.is_deleted == before["deleted"],
                Department.is_tenant_root == before["is_tenant_root"],
                Department.mounted_tenant_id == before["mounted_tenant_id"],
                Department.permission_projection_state == before["state"],
                Department.permission_projection_version == before["version"],
                Department.permission_projection_operation_id == before["operation_id"],
            )
            .execution_options(synchronize_session=False)
        )
