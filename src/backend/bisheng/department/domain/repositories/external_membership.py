"""外部成员补齐前核验本地挂载和主部门, 不迁移人工归属。"""

from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


class ExternalDepartmentMembershipRepository:
    @classmethod
    async def should_add(cls, session, *, department, user_id, local_tenant_id):
        if get_current_tenant_id() != 1 or type(local_tenant_id) is not int or local_tenant_id < 1:
            raise KunlianBindingConflictError()
        # 与租户成员入口保持锁顺序; 同一用户的并发补齐在 SQL 提交前串行。
        tenant = (await session.exec(select(Tenant).where(Tenant.id == local_tenant_id).with_for_update())).first()
        if tenant is None or tenant.status != "active":
            raise KunlianIdentityUnavailableError()
        if (
            tenant.parent_tenant_id != (None if local_tenant_id == 1 else 1)
            or tenant.root_dept_id != department.id
            or department.tenant_id != 1
            or department.status != "active"
            or not department.path
            or (local_tenant_id == 1 and (department.parent_id is not None or department.is_tenant_root))
            or (
                local_tenant_id != 1
                and (department.is_tenant_root != 1 or department.mounted_tenant_id != local_tenant_id)
            )
        ):
            raise KunlianBindingConflictError()
        user = (await session.exec(select(User).where(User.user_id == user_id).with_for_update())).first()
        if user is None or user.source != "kunlian" or not (user.external_id or "").startswith("kunlian:"):
            raise KunlianBindingConflictError()
        memberships = (await session.exec(select(UserTenant).where(UserTenant.user_id == user_id))).all()
        if (
            len(memberships) != 1
            or memberships[0].tenant_id != local_tenant_id
            or memberships[0].status != "active"
            or memberships[0].is_active != 1
        ):
            raise KunlianIdentityUnavailableError()
        if user.delete:
            # 停用资料投影保留原归属, 但不能新增组织成员。
            return False
        primaries = (
            await session.exec(
                select(UserDepartment)
                .where(UserDepartment.user_id == user_id, UserDepartment.is_primary == 1)
                .with_for_update()
            )
        ).all()
        if len(primaries) > 1:
            raise KunlianBindingConflictError()
        if not primaries:
            return True
        with bypass_tenant_filter():
            primary = await session.get(Department, primaries[0].department_id)
            if primary is None or primary.status != "active" or not primary.path:
                raise KunlianBindingConflictError()
            ancestor_ids = [int(part) for part in primary.path.split("/") if part.isdigit()]
            ancestors = (await session.exec(select(Department).where(Department.id.in_(ancestor_ids)))).all()
        mounts = {row.id: row.mounted_tenant_id for row in ancestors if row.is_tenant_root == 1}
        derived_tenant = next((mounts[did] for did in reversed(ancestor_ids) if did in mounts), 1)
        if derived_tenant != local_tenant_id or not primary.path.startswith(department.path.rstrip("/") + "/"):
            raise KunlianBindingConflictError()
        # 主部门已合法属于目标租户时保持原位置, 不在根部门另加主关联。
        return primary.id == department.id
