"""Department and UserDepartment ORM models + DAO classes.

Part of F002-department-tree.
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    JSON,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
    update,
)
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session

logger = logging.getLogger(__name__)


class Department(SQLModelSerializable, table=True):
    __tablename__ = 'department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    dept_id: str = Field(
        sa_column=Column(
            String(64), nullable=False, unique=True,
            comment='Business key, e.g. BS@a3f7e',
        ),
    )
    name: str = Field(
        sa_column=Column(String(128), nullable=False, comment='Department name'),
    )
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='Parent department ID, NULL=root',
        ),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
            comment='Tenant ID',
        ),
    )
    path: str = Field(
        default='',
        sa_column=Column(
            String(512), nullable=False,
            server_default=text("''"), index=True,
            comment='Materialized path /1/2/3/',
        ),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('0'),
            comment='Sort order among siblings',
        ),
    )
    source: str = Field(
        default='local',
        sa_column=Column(
            String(32), nullable=False,
            server_default=text("'local'"),
            comment='Source: local/feishu/wecom/dingtalk',
        ),
    )
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(128), nullable=True,
            comment='External department ID for sync',
        ),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"), index=True,
            comment='Status: active/archived',
        ),
    )
    default_role_ids: Optional[list] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Default role IDs for department members',
        ),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Creator user ID'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uk_source_external_id'),
    )


class UserDepartment(SQLModelSerializable, table=True):
    __tablename__ = 'user_department'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment='User ID'),
    )
    department_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, index=True,
            comment='Department ID',
        ),
    )
    is_primary: int = Field(
        default=1,
        sa_column=Column(
            SmallInteger, nullable=False,
            server_default=text('1'),
            comment='1=primary department, 0=secondary',
        ),
    )
    source: str = Field(
        default='local',
        sa_column=Column(
            String(32), nullable=False,
            server_default=text("'local'"),
            comment='Source: local/feishu/wecom/dingtalk',
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'department_id', name='uk_user_dept'),
    )


# ---------------------------------------------------------------------------
# DAO: DepartmentDao
# ---------------------------------------------------------------------------

class DepartmentDao:

    @classmethod
    def get_by_id(cls, dept_id: int) -> Optional[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.id == dept_id)
            ).first()

    @classmethod
    async def aget_by_id(cls, dept_id: int) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.id == dept_id)
            )
            return result.first()

    @classmethod
    def get_by_dept_id(cls, dept_id: str) -> Optional[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.dept_id == dept_id)
            ).first()

    @classmethod
    async def aget_by_ids(cls, dept_ids: List[int]) -> List[Department]:
        if not dept_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.id.in_(dept_ids))
            )
            return result.all()

    @classmethod
    async def aget_by_dept_id(cls, dept_id: str) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.dept_id == dept_id)
            )
            return result.first()

    @classmethod
    def create(cls, dept: Department) -> Department:
        with get_sync_db_session() as session:
            session.add(dept)
            session.flush()
            session.refresh(dept)
            return dept

    @classmethod
    async def acreate(cls, dept: Department) -> Department:
        async with get_async_db_session() as session:
            session.add(dept)
            await session.flush()
            await session.refresh(dept)
            return dept

    @classmethod
    def update(cls, dept: Department) -> Department:
        with get_sync_db_session() as session:
            session.add(dept)
            session.commit()
            session.refresh(dept)
            return dept

    @classmethod
    async def aupdate(cls, dept: Department) -> Department:
        async with get_async_db_session() as session:
            session.add(dept)
            await session.commit()
            await session.refresh(dept)
            return dept

    @classmethod
    def get_children(cls, parent_id: int) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.parent_id == parent_id,
                    Department.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_children(cls, parent_id: int) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.parent_id == parent_id,
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_subtree(cls, path_prefix: str) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_subtree(cls, path_prefix: str) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_subtree_ids(cls, path_prefix: str) -> List[int]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department.id).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_subtree_ids(cls, path_prefix: str) -> List[int]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department.id).where(
                    Department.path.like(f'{path_prefix}%'),
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_all_active(cls) -> List[Department]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(Department.status == 'active')
            ).all()

    @classmethod
    async def aget_all_active(cls) -> List[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(Department.status == 'active')
            )
            return result.all()

    @classmethod
    async def aget_active_by_tenant(cls, tenant_id: int) -> List[Department]:
        """Get all active departments for a specific tenant."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            )
            return result.all()

    @classmethod
    async def aget_by_external_id(
        cls, external_id: str, tenant_id: int,
    ) -> Optional[Department]:
        """Get department by external_id within a tenant (for org sync)."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.external_id == external_id,
                    Department.tenant_id == tenant_id,
                )
            )
            return result.first()

    @classmethod
    def update_paths_batch(cls, old_prefix: str, new_prefix: str) -> None:
        with get_sync_db_session() as session:
            session.execute(
                update(Department)
                .where(Department.path.like(f'{old_prefix}%'))
                .values(path=func.replace(Department.path, old_prefix, new_prefix))
            )
            session.commit()

    @classmethod
    async def aupdate_paths_batch(cls, old_prefix: str, new_prefix: str) -> None:
        async with get_async_db_session() as session:
            await session.execute(
                update(Department)
                .where(Department.path.like(f'{old_prefix}%'))
                .values(path=func.replace(Department.path, old_prefix, new_prefix))
            )
            await session.commit()

    @classmethod
    def get_root_by_tenant(cls, tenant_id: int) -> Optional[Department]:
        """Get the root department for a specific tenant.

        Uses bypass_tenant_filter() at call site since this queries
        a specific tenant_id explicitly.
        """
        with get_sync_db_session() as session:
            return session.exec(
                select(Department).where(
                    Department.parent_id.is_(None),
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            ).first()

    @classmethod
    async def aget_root_by_tenant(cls, tenant_id: int) -> Optional[Department]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Department).where(
                    Department.parent_id.is_(None),
                    Department.tenant_id == tenant_id,
                    Department.status == 'active',
                )
            )
            return result.first()

    @classmethod
    def check_name_duplicate(
        cls, parent_id: int, name: str, exclude_id: Optional[int] = None,
    ) -> bool:
        with get_sync_db_session() as session:
            stmt = select(Department).where(
                Department.parent_id == parent_id,
                Department.name == name,
                Department.status == 'active',
            )
            if exclude_id is not None:
                stmt = stmt.where(Department.id != exclude_id)
            return session.exec(stmt).first() is not None

    @classmethod
    async def acheck_name_duplicate(
        cls, parent_id: int, name: str, exclude_id: Optional[int] = None,
    ) -> bool:
        async with get_async_db_session() as session:
            stmt = select(Department).where(
                Department.parent_id == parent_id,
                Department.name == name,
                Department.status == 'active',
            )
            if exclude_id is not None:
                stmt = stmt.where(Department.id != exclude_id)
            result = await session.exec(stmt)
            return result.first() is not None

    @classmethod
    async def aget_user_admin_departments(cls, user_id: int) -> List[Department]:
        """Get departments where user is admin via OpenFGA.

        Uses FGAClient.list_objects() which respects admin inheritance from parent.
        Returns empty list if FGA is unavailable.
        """
        from bisheng.core.openfga.manager import aget_fga_client

        fga = await aget_fga_client()
        if fga is None:
            return []
        try:
            raw = await fga.list_objects(
                user=f'user:{user_id}', relation='admin', type='department',
            )
        except Exception:
            logger.warning(
                'FGA list_objects failed for user %d department admin', user_id,
            )
            return []
        dept_ids = [int(obj.split(':', 1)[1]) for obj in raw if ':' in obj]
        if not dept_ids:
            return []
        return await cls.aget_by_ids(dept_ids)


# ---------------------------------------------------------------------------
# DAO: UserDepartmentDao
# ---------------------------------------------------------------------------

class UserDepartmentDao:

    @classmethod
    def add_member(
        cls, user_id: int, department_id: int,
        is_primary: int = 1, source: str = 'local',
    ) -> UserDepartment:
        with get_sync_db_session() as session:
            ud = UserDepartment(
                user_id=user_id,
                department_id=department_id,
                is_primary=is_primary,
                source=source,
            )
            session.add(ud)
            session.commit()
            session.refresh(ud)
            return ud

    @classmethod
    async def aadd_member(
        cls, user_id: int, department_id: int,
        is_primary: int = 1, source: str = 'local',
    ) -> UserDepartment:
        async with get_async_db_session() as session:
            ud = UserDepartment(
                user_id=user_id,
                department_id=department_id,
                is_primary=is_primary,
                source=source,
            )
            session.add(ud)
            await session.commit()
            await session.refresh(ud)
            return ud

    @classmethod
    def batch_add_members(cls, entries: List[dict]) -> None:
        with get_sync_db_session() as session:
            for entry in entries:
                session.add(UserDepartment(**entry))
            session.commit()

    @classmethod
    async def abatch_add_members(cls, entries: List[dict]) -> None:
        async with get_async_db_session() as session:
            for entry in entries:
                session.add(UserDepartment(**entry))
            await session.commit()

    @classmethod
    def remove_member(cls, user_id: int, department_id: int) -> None:
        with get_sync_db_session() as session:
            ud = session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            ).first()
            if ud:
                session.delete(ud)
                session.commit()

    @classmethod
    async def aremove_member(cls, user_id: int, department_id: int) -> None:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            )
            ud = result.first()
            if ud:
                await session.delete(ud)
                await session.commit()

    @classmethod
    def get_members(
        cls, department_id: int, page: int = 1, limit: int = 20,
        keyword: str = '',
    ) -> Tuple[List, int]:
        """Return (rows, total) for department members with pagination.

        Each row is a UserDepartment joined with user info.
        """
        from bisheng.database.models.user import User

        with get_sync_db_session() as session:
            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time,
                )
                .join(User, User.user_id == UserDepartment.user_id)
                .where(
                    UserDepartment.department_id == department_id,
                    User.delete == 0,
                )
            )
            if keyword:
                base = base.where(User.user_name.like(f'%{keyword}%'))

            total = session.exec(
                select(func.count()).select_from(base.subquery())
            ).one()

            rows = session.exec(
                base.offset((page - 1) * limit).limit(limit)
            ).all()
            return rows, total

    @classmethod
    async def aget_members(
        cls, department_id: int, page: int = 1, limit: int = 20,
        keyword: str = '',
    ) -> Tuple[List, int]:
        from bisheng.database.models.user import User

        async with get_async_db_session() as session:
            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time,
                )
                .join(User, User.user_id == UserDepartment.user_id)
                .where(
                    UserDepartment.department_id == department_id,
                    User.delete == 0,
                )
            )
            if keyword:
                base = base.where(User.user_name.like(f'%{keyword}%'))

            total_result = await session.exec(
                select(func.count()).select_from(base.subquery())
            )
            total = total_result.one()

            result = await session.exec(
                base.offset((page - 1) * limit).limit(limit)
            )
            rows = result.all()
            return rows, total

    @classmethod
    def get_member_count(cls, department_id: int) -> int:
        with get_sync_db_session() as session:
            return session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == department_id,
                )
            ).one()

    @classmethod
    async def aget_member_count(cls, department_id: int) -> int:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == department_id,
                )
            )
            return result.one()

    @classmethod
    def get_user_departments(cls, user_id: int) -> List[UserDepartment]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                )
            ).all()

    @classmethod
    async def aget_user_departments(cls, user_id: int) -> List[UserDepartment]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                )
            )
            return result.all()

    @classmethod
    def get_user_primary_department(cls, user_id: int) -> Optional[UserDepartment]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.is_primary == 1,
                )
            ).first()

    @classmethod
    async def aget_user_primary_department(
        cls, user_id: int,
    ) -> Optional[UserDepartment]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.is_primary == 1,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_user_ids(cls, user_ids: List[int]) -> List[UserDepartment]:
        """Batch load UserDepartment records for multiple users."""
        if not user_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id.in_(user_ids),
                )
            )
            return result.all()

    @classmethod
    def check_member_exists(cls, user_id: int, department_id: int) -> bool:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            ).first() is not None

    @classmethod
    async def acheck_member_exists(
        cls, user_id: int, department_id: int,
    ) -> bool:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == department_id,
                )
            )
            return result.first() is not None
