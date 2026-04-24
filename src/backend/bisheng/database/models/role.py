from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, Computed, DateTime, Integer, JSON, String, false, text, func, delete, and_, or_, UniqueConstraint
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.role_access import RoleAccess
from bisheng.user.domain.models.user_role import UserRole


class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='Frontend Display Name')
    role_type: str = Field(
        default='tenant',
        sa_column=Column(String(16), nullable=False, server_default=text("'tenant'"),
                         comment='global: cross-tenant visible; tenant: tenant-scoped'),
    )
    department_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True,
                         comment='Department scope ID; NULL = no scope restriction'),
    )
    quota_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True,
                         comment='Resource quota config JSON'),
    )
    remark: Optional[str] = Field(default=None, index=False)
    # ── deprecated fields (AD-07, AD-08) ──
    group_id: Optional[int] = Field(default=None, index=True)  # deprecated: use department_id
    knowledge_space_file_limit: Optional[int] = Field(default=0, index=False)  # deprecated: use quota_config
    # timestamps
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Role(RoleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Role creator user ID'),
    )
    department_scope_key: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            Computed('COALESCE(department_id, -1)', persisted=True),
            nullable=False,
            comment='Normalized department scope key; -1 = no scope restriction',
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            'tenant_id',
            'role_type',
            'role_name',
            'department_scope_key',
            name='uk_tenant_roletype_rolename_scope_key',
        ),
    )


class RoleRead(RoleBase):
    id: Optional[int] = None


class RoleUpdate(RoleBase):
    role_name: Optional[str] = None
    remark: Optional[str] = None
    knowledge_space_file_limit: Optional[int] = None


class RoleCreate(RoleBase):
    pass


class RoleDao(RoleBase):

    # ── Legacy methods (kept for backward compat) ──

    @classmethod
    def get_role_by_groups(cls, group: List[int], keyword: str = None, page: int = 0, limit: int = 0) -> List[Role]:
        statement = select(Role).where(Role.id > AdminRole)
        if group:
            statement = statement.where(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Role.create_time.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def count_role_by_groups(cls, group: List[int], keyword: str = None) -> int:
        statement = select(func.count(Role.id)).where(Role.id > AdminRole)
        if group:
            statement = statement.where(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        with get_sync_db_session() as session:
            return session.scalar(statement)

    @classmethod
    def insert_role(cls, role: RoleCreate):
        with get_sync_db_session() as session:
            session.add(role)
            session.commit()
            session.refresh(role)
            return role

    @classmethod
    async def ainsert_role(cls, role: Role) -> Role:
        async with get_async_db_session() as session:
            session.add(role)
            await session.commit()
            await session.refresh(role)
            return role

    @classmethod
    async def update_role(cls, role: Role):
        if not role.id:
            raise ValueError("Role ID is required for update")
        async with get_async_db_session() as session:
            session.add(role)
            await session.commit()
            await session.refresh(role)
            return role

    @classmethod
    def delete_role(cls, role_id: int):
        with get_sync_db_session() as session:
            session.exec(delete(Role).where(Role.id == role_id))
            session.exec(delete(UserRole).where(UserRole.role_id == role_id))
            session.exec(delete(RoleAccess).where(RoleAccess.role_id == role_id))
            session.commit()

    @classmethod
    async def adelete_role(cls, role_id: int):
        async with get_async_db_session() as session:
            await session.exec(delete(Role).where(Role.id == role_id))
            await session.exec(delete(UserRole).where(UserRole.role_id == role_id))
            await session.exec(delete(RoleAccess).where(RoleAccess.role_id == role_id))
            await session.commit()

    @classmethod
    def get_role_by_ids(cls, role_ids: List[int]) -> List[Role]:
        with get_sync_db_session() as session:
            return session.query(Role).filter(Role.id.in_(role_ids)).all()

    @classmethod
    async def aget_role_by_ids(cls, role_ids: List[int]) -> List[Role]:
        statement = select(Role).where(Role.id.in_(role_ids))
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    def get_role_by_id(cls, role_id: int) -> Role:
        with get_sync_db_session() as session:
            return session.query(Role).filter(Role.id == role_id).first()

    @classmethod
    async def aget_role_by_id(cls, role_id: int) -> Role:
        async with get_async_db_session() as session:
            result = await session.execute(select(Role).where(Role.id == role_id))
            return result.scalars().first()

    @classmethod
    def delete_role_by_group_id(cls, group_id: int):
        from bisheng.user.domain.models.user_role import UserRole
        with get_sync_db_session() as session:
            all_user = select(UserRole, Role).join(
                Role, and_(UserRole.role_id == Role.id,
                           Role.group_id == group_id)).group_by(UserRole.id)
            all_user = session.exec(all_user).all()
            session.exec(delete(UserRole).where(UserRole.id.in_([one.UserRole.id for one in all_user])))
            session.exec(delete(Role).where(Role.group_id == group_id))
            session.commit()

    # ── New methods for F005 (AD-09) ──

    @classmethod
    def _build_visible_roles_stmt(
        cls,
        tenant_id: int,
        keyword: str = None,
        department_ids: List[int] = None,
        tenant_custom_roles_only: bool = False,
    ):
        """Build statement for visible roles: global + current tenant, excluding AdminRole.

        Args:
            tenant_id: Current tenant ID.
            keyword: Optional keyword filter on role_name.
            department_ids: When set (department admin): **global** preset roles plus
                **tenant** roles whose ``department_id`` is NULL (global scope) or in this subtree.
            tenant_custom_roles_only: When True and ``department_ids`` is None (tenant admin),
                exclude ``global`` roles so the list only contains editable tenant roles.
        """
        # bypass_tenant_filter is used by callers, so explicitly scope tenant roles
        stmt = select(Role).where(
            Role.id > AdminRole,
            or_(
                Role.role_type == 'global',
                and_(Role.role_type == 'tenant', Role.tenant_id == tenant_id),
            ),
        )
        if keyword:
            stmt = stmt.where(Role.role_name.like(f'%{keyword}%'))
        if department_ids is not None:
            if not department_ids:
                stmt = stmt.where(
                    or_(
                        Role.role_type == 'global',
                        and_(
                            Role.role_type == 'tenant',
                            Role.department_id.is_(None),
                        ),
                    ),
                )
            else:
                stmt = stmt.where(
                    or_(
                        Role.role_type == 'global',
                        and_(
                            Role.role_type == 'tenant',
                            or_(
                                Role.department_id.is_(None),
                                Role.department_id.in_(department_ids),
                            ),
                        ),
                    ),
                )
        elif tenant_custom_roles_only:
            stmt = stmt.where(Role.role_type == 'tenant')
        return stmt

    @classmethod
    async def aget_visible_roles(
        cls,
        tenant_id: int,
        keyword: str = None,
        page: int = 1,
        limit: int = 10,
        department_ids: List[int] = None,
        tenant_custom_roles_only: bool = False,
    ) -> List[Role]:
        """Get visible roles for role list API (AD-09).

        Returns global roles + current tenant's roles, excluding AdminRole(id=1).
        Uses bypass_tenant_filter so global roles from other tenants are visible.
        """
        from bisheng.core.context.tenant import bypass_tenant_filter
        stmt = cls._build_visible_roles_stmt(
            tenant_id, keyword, department_ids, tenant_custom_roles_only,
        )
        stmt = stmt.order_by(Role.create_time.desc())
        if page and limit:
            stmt = stmt.offset((page - 1) * limit).limit(limit)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(stmt)).all()

    @classmethod
    async def acount_visible_roles(
        cls,
        tenant_id: int,
        keyword: str = None,
        department_ids: List[int] = None,
        tenant_custom_roles_only: bool = False,
    ) -> int:
        """Count visible roles (companion for aget_visible_roles)."""
        from bisheng.core.context.tenant import bypass_tenant_filter
        base_stmt = cls._build_visible_roles_stmt(
            tenant_id, keyword, department_ids, tenant_custom_roles_only,
        )
        stmt = select(func.count()).select_from(base_stmt.subquery())
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await session.scalar(stmt)

    @classmethod
    async def aget_role_by_name(
        cls,
        tenant_id: int,
        role_type: str,
        role_name: str,
        department_id: Optional[int],
    ) -> Optional[Role]:
        """Check for duplicate role name within the same role scope."""
        stmt = select(Role).where(
            Role.role_type == role_type,
            Role.role_name == role_name,
        )
        if department_id is None:
            stmt = stmt.where(Role.department_id.is_(None))
        else:
            stmt = stmt.where(Role.department_id == department_id)
        # tenant_id filtering is auto-injected by INV-1 for role_type='tenant'
        # For global roles, we also need to check
        async with get_async_db_session() as session:
            return (await session.exec(stmt)).first()

    @classmethod
    async def aget_user_count_by_role_ids(cls, role_ids: List[int]) -> dict:
        """Get user count for each role ID. Returns {role_id: count}."""
        if not role_ids:
            return {}
        stmt = select(UserRole.role_id, func.count(UserRole.user_id)).where(
            UserRole.role_id.in_(role_ids)
        ).group_by(UserRole.role_id)
        async with get_async_db_session() as session:
            rows = (await session.exec(stmt)).all()
            return {row[0]: row[1] for row in rows}
