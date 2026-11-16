"""Same-UOW, leaf-only department retirement; never changes unrelated users or grants."""

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.department.domain.repositories.iam_oneoff_repository import IamOneoffDepartmentRepository


class IamArchiveDepartmentRepository(IamOneoffDepartmentRepository):
    async def archive_snapshot(self, department, role_repository, *, session, lock=False):
        async def rows(model):
            statement = select(model).where(model.department_id == department["id"]).order_by(model.id).limit(1001)
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            with bypass_tenant_filter():
                values = list((await session.exec(statement)).all())
            if hasattr(model, "tenant_id") and any(row.tenant_id != department["tenant_id"] for row in values):
                raise ValueError("ARCHIVE_ASSOCIATION_TENANT_CONFLICT")
            if len(values) > 1000:
                raise ValueError("ARCHIVE_ASSOCIATION_SCOPE_TOO_LARGE")
            return [row.model_dump(mode="json") for row in values]

        statement = select(Department).where(Department.id == department["id"])
        if lock:
            statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
        row = (await session.exec(statement)).first()
        if row is None or row.tenant_id != department["tenant_id"]:
            raise ValueError("ARCHIVE_DEPARTMENT_IDENTITY_CHANGED")
        associations = {
            "memberships": await rows(UserDepartment),
            "admins": await rows(DepartmentAdminGrant),
            **await role_repository.snapshot(department["id"], session, lock=lock),
        }
        if any(role["tenant_id"] != department["tenant_id"] for role in associations["roles"]):
            raise ValueError("ARCHIVE_ROLE_TENANT_CONFLICT")
        return associations, row.last_sync_ts

    async def archive_gate(self, before, archive, operation_id, session):
        await self.require_leaf(before, session=session)
        source = archive["source"]
        statement = (
            self._guard(before)
            .where(
                Department.source == source["source"],
                Department.external_id == source["external_id"],
                Department.last_sync_ts == archive["last_sync_ts"],
            )
            .values(
                status="archived",
                is_deleted=1,
                permission_projection_state="FAILED_CLOSED",
                permission_projection_operation_id=operation_id,
            )
        )
        if (await session.exec(statement)).rowcount != 1:
            raise ValueError("ARCHIVE_GATE_CONFLICT")

    async def cleanup_archive(self, department, expected, role_repository, session):
        actual, _ = await self.archive_snapshot(department, role_repository, session=session, lock=True)
        if actual != expected:
            raise ValueError("ARCHIVE_ASSOCIATIONS_CHANGED")
        for model in (UserDepartment, DepartmentAdminGrant):
            await session.exec(
                delete(model).where(
                    model.department_id.in_(
                        select(Department.id).where(
                            Department.id == department["id"], Department.tenant_id == department["tenant_id"]
                        )
                    )
                )
            )
        await role_repository.cleanup(expected, department["tenant_id"], session)
        after, _ = await self.archive_snapshot(department, role_repository, session=session, lock=True)
        if any(after.values()):
            raise ValueError("ARCHIVE_ASSOCIATIONS_NOT_EMPTY")
