"""Bounded role-owned before images and same-UOW cleanup for department retirement."""

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess
from bisheng.user.domain.models.user_role import UserRole

LIMIT = 1000


class DepartmentRoleRetirementRepository:
    async def snapshot(self, department_id, session, *, lock=False):
        async def rows(model, predicate):
            statement = select(model).where(predicate).order_by(model.id).limit(LIMIT + 1)
            if lock:
                statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
            values = list((await session.exec(statement)).all())
            if len(values) > LIMIT:
                raise ValueError("ARCHIVE_ROLE_SCOPE_TOO_LARGE")
            return [row.model_dump(mode="json") for row in values]

        with bypass_tenant_filter():
            roles = await rows(Role, Role.department_id == department_id)
            ids = [row["id"] for row in roles]
            if not ids:
                return {"roles": [], "user_roles": [], "role_access": []}
            # A department-owned role cannot silently carry foreign/global authority.
            if any(row["id"] <= 2 or row["role_type"] != "tenant" for row in roles):
                raise ValueError("ARCHIVE_PROTECTED_ROLE")
            tenant_ids = {row["tenant_id"] for row in roles}
            user_roles = await rows(UserRole, UserRole.role_id.in_(ids))
            access = await rows(RoleAccess, RoleAccess.role_id.in_(ids))
            if len(tenant_ids) != 1 or any(row["tenant_id"] not in tenant_ids for row in [*user_roles, *access]):
                raise ValueError("ARCHIVE_ROLE_TENANT_CONFLICT")
            return {"roles": roles, "user_roles": user_roles, "role_access": access}

    async def cleanup(self, before, tenant_id, session):
        ids = [row["id"] for row in before["roles"]]
        if not ids:
            return
        for model, key in ((UserRole, UserRole.role_id), (RoleAccess, RoleAccess.role_id), (Role, Role.id)):
            await session.exec(delete(model).where(model.tenant_id == tenant_id, key.in_(ids)))
        with bypass_tenant_filter():
            for key in (UserRole.role_id, RoleAccess.role_id, Role.id):
                if (await session.exec(select(key).where(key.in_(ids)).limit(1))).first() is not None:
                    raise ValueError("ARCHIVE_ROLE_REFERENCES_REMAIN")
