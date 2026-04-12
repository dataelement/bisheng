from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, JSON, String, text, func, delete, and_, or_, UniqueConstraint
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
    __table_args__ = (
        UniqueConstraint('tenant_id', 'role_type', 'role_name', name='uk_tenant_roletype_rolename'),
    )
    id: Optional[int] = Field(default=None, primary_key=True)


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
    def _build_visible_roles_stmt(cls, tenant_id: int, keyword: str = None,
                                  department_ids: List[int] = None):
        """Build statement for visible roles: global + current tenant, excluding AdminRole.

        Args:
            tenant_id: Current tenant ID.
            keyword: Optional keyword filter on role_name.
            department_ids: Optional list of department IDs to filter by
                (for department admin scope). None = no dept filtering.
        """
        stmt = select(Role).where(
            Role.id > AdminRole,
            or_(
                Role.role_type == 'global',
                Role.role_type == 'tenant',
            ),
        )
        if keyword:
            stmt = stmt.where(Role.role_name.like(f'%{keyword}%'))
        if department_ids is not None:
            # Department admin: only see global roles + roles in their dept subtree
            stmt = stmt.where(
                or_(
                    Role.role_type == 'global',
                    Role.department_id.in_(department_ids),
                    Role.department_id.is_(None),
                )
            )
        return stmt

    @classmethod
    async def aget_visible_roles(cls, tenant_id: int, keyword: str = None,
                                 page: int = 1, limit: int = 10,
                                 department_ids: List[int] = None) -> List[Role]:
        """Get visible roles for role list API (AD-09).

        Returns global roles + current tenant's roles, excluding AdminRole(id=1).
        For department admins, also filters by department subtree.
        """
        stmt = cls._build_visible_roles_stmt(tenant_id, keyword, department_ids)
        stmt = stmt.order_by(Role.create_time.desc())
        if page and limit:
            stmt = stmt.offset((page - 1) * limit).limit(limit)
        async with get_async_db_session() as session:
            return (await session.exec(stmt)).all()

    @classmethod
    async def acount_visible_roles(cls, tenant_id: int, keyword: str = None,
                                   department_ids: List[int] = None) -> int:
        """Count visible roles (companion for aget_visible_roles)."""
        base_stmt = cls._build_visible_roles_stmt(tenant_id, keyword, department_ids)
        stmt = select(func.count()).select_from(base_stmt.subquery())
        async with get_async_db_session() as session:
            return await session.scalar(stmt)

    @classmethod
    async def aget_role_by_name(cls, tenant_id: int, role_type: str,
                                role_name: str) -> Optional[Role]:
        """Check for duplicate role name within (tenant_id, role_type) scope."""
        stmt = select(Role).where(
            Role.role_type == role_type,
            Role.role_name == role_name,
        )
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
