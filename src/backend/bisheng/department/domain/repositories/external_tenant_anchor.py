"""部门 Owner 的受控结构事务, 不认领旧组织或创建管理员。"""

from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.department import Department


class ExternalTenantAnchorRepository:
    @classmethod
    async def ensure(cls, session, *, root_department_id, local_tenant_id, source_key, display_name):
        if get_current_tenant_id() != 1 or local_tenant_id <= 1:
            raise KunlianBindingConflictError()
        root = (
            await session.exec(select(Department).where(Department.id == root_department_id).with_for_update())
        ).first()
        if (
            root is None
            or root.tenant_id != 1
            or root.parent_id is not None
            or root.status != "active"
            or root.is_tenant_root
            or not root.path
        ):
            raise KunlianBindingConflictError()
        dept_id = "KL@" + source_key[:56]
        if (await session.exec(select(Department).where(Department.dept_id == dept_id))).first():
            # 只有租户 Owner 的原子回执可以证明已创建, 不能按业务码认领。
            raise KunlianBindingConflictError()
        row = Department(
            dept_id=dept_id,
            name=display_name,
            parent_id=root.id,
            tenant_id=1,
            source="local",
            is_tenant_root=1,
            mounted_tenant_id=local_tenant_id,
        )
        session.add(row)
        await session.flush()
        row.path = root.path.rstrip("/") + "/" + str(row.id) + "/"
        session.add(row)
        return row.id
