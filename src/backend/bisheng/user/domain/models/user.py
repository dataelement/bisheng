from datetime import datetime
from typing import ClassVar, List, Optional

from pydantic import field_validator
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, and_, func, or_, text, update
from sqlalchemy.orm import selectinload
from sqlmodel import Field, select, Relationship, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group import DefaultGroup, Group
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.user.domain.models.user_role import UserRole


class UserBase(SQLModelSerializable):
    user_name: str = Field(index=True)
    email: Optional[str] = Field(default=None, index=True)
    phone_number: Optional[str] = Field(default=None, index=True)
    dept_id: Optional[str] = Field(default=None, index=True)
    remark: Optional[str] = Field(default=None, index=False)
    avatar: Optional[str] = Field(default=None, index=False)
    source: str = Field(
        default='local',
        sa_column=Column(
            String(32), nullable=False,
            server_default=text("'local'"),
            comment='Source: local/feishu/wecom/dingtalk/generic_api',
        ),
    )
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(255), nullable=True,
            comment='External employee ID for sync',
        ),
    )
    delete: int = Field(default=0, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('user_name')
    @classmethod
    def validate_str(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            raise ValueError('user_name Tidak boleh kosong.')
        return v


class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)
    password: str = Field(index=False)
    password_update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')), description='Password Last Modified')
    # v2.5.1 F012: JWT invalidation counter — incremented whenever the user's
    # leaf tenant changes (via UserTenantSyncService). The value is embedded in
    # issued JWTs; middleware compares against the current DB value and rejects
    # stale tokens with 401.
    token_version: int = Field(
        default=0,
        sa_column=Column(
            'token_version',
            Integer,
            nullable=False,
            server_default=text('0'),
            comment='v2.5.1 F012: JWT invalidation counter; +1 on leaf tenant change',
        ),
    )

    # DefinitiongroupsAndrolesQuery Relationships for
    groups: List["Group"] = Relationship(link_model=UserGroup)
    roles: List["Role"] = Relationship(link_model=UserRole)

    departments: List["Department"] = Relationship(link_model=UserDepartment)

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uk_user_source_external_id'),
    )


class UserRead(UserBase):
    user_id: Optional[int] = None
    role: Optional[str] = None  # admin；非超管时由服务端序列化（见 /user/info）
    access_token: Optional[str] = None
    web_menu: Optional[List[str]] = None
    # True if any assigned role sets quota_config.menu_approval_mode (需审批模式)
    menu_approval_mode: Optional[bool] = None
    admin_groups: Optional[List[int]] = None  # Managed User GroupsIDVertical
    # PRD 3.2.2 用户组管理入口：超管 / 部门管理员
    can_manage_user_groups: Optional[bool] = None
    is_department_admin: Optional[bool] = None
    # Multi-tenant fields (F010)
    requires_tenant_selection: Optional[bool] = None
    tenants: Optional[List[dict]] = None
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    # Tenant-tree admin UI flags. Optional so older clients ignore them.
    is_global_super: Optional[bool] = None
    is_child_admin: Optional[bool] = None
    leaf_tenant_id: Optional[int] = None
    leaf_tenant_name: Optional[str] = None


class UserQuery(UserBase):
    pass


class UserLogin(UserBase):
    password: str

    captcha_key: Optional[str] = None
    captcha: Optional[str] = None


class UserCreate(UserBase):
    external_id: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = Field(default='')
    captcha_key: Optional[str] = None
    captcha: Optional[str] = None
    default_groupid: Optional[int] = Field(default=None)
    default_roleid: Optional[int] = Field(default=None)


class UserUpdate(SQLModelSerializable):
    user_id: int
    avatar: Optional[str] = None
    delete: Optional[int] = 0


class UserDao(UserBase):

    @classmethod
    def get_user(cls, user_id: int) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_id == user_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_user(cls, user_id: int) -> User | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_id == user_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_user_by_ids(cls, user_ids: List[int]) -> List[User] | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    async def aget_user_by_ids(cls, user_ids: List[int]) -> List[User] | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_id.in_(user_ids))
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_user_by_username(cls, username: str) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name == username)
            return session.exec(statement).first()

    @classmethod
    async def aget_user_by_username(cls, username: str) -> User | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_name == username)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def aget_users_by_username(cls, username: str) -> List[User]:
        """同名用户可能多条；用于重名校验等。"""
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_name == username)
            result = await session.exec(statement)
            return list(result.all())

    @classmethod
    async def aget_login_candidates_by_account(cls, account: str) -> List[User]:
        """登录账号仅支持 external_id（人员ID），并过滤禁用账号。"""
        acc = (account or '').strip()
        if not acc:
            return []
        async with get_async_db_session() as session:
            statement = select(User).where(
                User.delete == 0,
                User.external_id == acc,
            )
            result = await session.exec(statement)
            return list(result.all())

    @classmethod
    async def aexists_disabled_login_account(cls, account: str) -> bool:
        """与登录账号字段一致（external_id），且 delete=1 的禁用用户是否存在。"""
        acc = (account or "").strip()
        if not acc:
            return False
        async with get_async_db_session() as session:
            statement = (
                select(User.user_id)
                .where(User.delete == 1, User.external_id == acc)
                .limit(1)
            )
            result = await session.exec(statement)
            return result.first() is not None

    @classmethod
    async def aget_user_for_login(cls, account: str) -> User | None:
        """兼容旧调用：仅返回首条；登录请用 ``aget_login_candidates_by_account``。"""
        rows = await cls.aget_login_candidates_by_account(account)
        return rows[0] if rows else None

    @classmethod
    def update_user(cls, user: User) -> User:
        with get_sync_db_session() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    async def aupdate_user(cls, user: User) -> User:
        async with get_async_db_session() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    @classmethod
    def _filter_users_statement(cls,
                                statement,
                                user_ids: List[int],
                                keyword: str = None):
        if user_ids:
            statement = statement.where(User.user_id.in_(user_ids))
        if keyword:
            statement = statement.where(User.user_name.like(f'%{keyword}%'))
        return statement.order_by(User.user_id.desc())

    @classmethod
    def filter_users(cls,
                     user_ids: List[int],
                     keyword: str = None,
                     page: int = 0,
                     limit: int = 0) -> (List[User], int):
        statement = select(User)
        statement = cls._filter_users_statement(statement, user_ids, keyword)
        count_statement = select(func.count(User.user_id))
        count_statement = cls._filter_users_statement(count_statement, user_ids, keyword)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(User.user_id.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    async def afilter_users(cls,
                            user_ids: List[int],
                            keyword: str = None,
                            page: int = 0,
                            limit: int = 0) -> List[User]:
        statement = select(User)
        statement = cls._filter_users_statement(statement, user_ids, keyword)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(User.user_id.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_unique_user_by_name(cls, user_name: str) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name == user_name)
            return session.exec(statement).first()

    @classmethod
    def search_user_by_name(cls, user_name: str) -> List[User] | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name.like('%{}%'.format(user_name)))
            return session.exec(statement).all()

    @classmethod
    def create_user(cls, db_user: User) -> User:
        with get_sync_db_session() as session:
            session.add(db_user)
            session.commit()
            session.refresh(db_user)
            return db_user

    @classmethod
    async def add_user_and_default_role(cls, user: User) -> User:
        """
        Add users and add default roles
        """
        async with get_async_db_session() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            db_user_role = UserRole(user_id=user.user_id, role_id=DefaultRole)
            session.add(db_user_role)
            await session.commit()
            await session.refresh(user)
            return user

    @classmethod
    async def add_user_and_configured_default_auth(
        cls,
        user: User,
        default_groupid: Optional[int] = None,
        default_roleid: Optional[int] = None) -> User:
        """
        Add SSO users with configured default group and role.
        """
        group_id = default_groupid or DefaultGroup
        role_id = default_roleid or DefaultRole

        async with get_async_db_session() as session:
            if default_groupid is not None:
                group_result = await session.exec(select(Group).where(Group.id == group_id))
                if not group_result.first():
                    raise ValueError('Configured default_groupid does not exist')

            role_result = await session.exec(select(Role).where(Role.id == role_id))
            role = role_result.first()
            if not role:
                raise ValueError('Configured default_roleid does not exist')
            if role.group_id != group_id:
                raise ValueError('Configured default_roleid does not belong to default_groupid')

            session.add(user)
            await session.commit()
            await session.refresh(user)

            db_user_role = UserRole(user_id=user.user_id, role_id=role_id)
            session.add(db_user_role)

            db_user_group = UserGroup(user_id=user.user_id, group_id=group_id, is_group_admin=False)
            session.add(db_user_group)

            await session.commit()
            await session.refresh(user)
            return user

    @classmethod
    async def add_user_and_admin_role(cls, user: User) -> User:
        """
        Add users and add super admin roles
        """
        async with get_async_db_session() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            db_user_role = UserRole(user_id=user.user_id, role_id=AdminRole)
            session.add(db_user_role)
            await session.commit()
            await session.refresh(user)
            return user

    @classmethod
    def add_user_with_groups_and_roles(cls, user: User, group_ids: List[int],
                                       role_ids: List[int]) -> User:
        with get_sync_db_session() as session:
            session.add(user)
            session.flush()
            for group_id in group_ids:
                db_user_group = UserGroup(user_id=user.user_id, group_id=group_id)
                session.add(db_user_group)
            for role_id in role_ids:
                db_user_role = UserRole(user_id=user.user_id, role_id=role_id)
                session.add(db_user_role)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def get_all_users(cls, page: int = 0, limit: int = 0) -> List[User]:
        """
        Pagination Get All Users
        """
        statement = select(User)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_user_with_group_role(cls, *, start_time: datetime = None, end_time: datetime = None,
                                 user_ids: List[int] = None, page: int = 0, page_size: int = 0) -> List[User]:
        statement = select(User)
        if start_time and end_time:
            statement = statement.where(User.create_time >= start_time, User.create_time < end_time)
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        if user_ids:
            statement = statement.where(col(User.user_id).in_(user_ids))
        statement = statement.order_by(User.user_id)
        statement = statement.options(
            selectinload(User.groups),  # type: ignore
            selectinload(User.roles)  # type: ignore
        )
        with get_sync_db_session() as session:
            users = session.exec(statement).all()

        # Load department info (UserDepartment lacks FK annotations, so query explicitly)
        # if users:
        #     from collections import defaultdict
        #     from bisheng.database.models.department import (
        #         Department, DepartmentDao, UserDepartmentDao,
        #     )
        #     all_user_ids = [u.user_id for u in users]
        #     ud_rows = UserDepartmentDao.get_by_user_ids(all_user_ids)
        #     dept_ids = list({ud.department_id for ud in ud_rows})
        #     dept_map = {d.id: d for d in DepartmentDao.get_by_ids(dept_ids)}
        #     user_dept_map = defaultdict(list)
        #     for ud in ud_rows:
        #         if ud.department_id in dept_map:
        #             user_dept_map[ud.user_id].append(dept_map[ud.department_id])
        #     for user in users:
        #         user.departments = user_dept_map.get(user.user_id, [])

        return users

    @classmethod
    def get_first_user(cls) -> User | None:
        statement = select(User).order_by(col(User.user_id).asc()).limit(1)
        with get_sync_db_session() as session:
            return session.exec(statement).first()

    @classmethod
    async def aget_by_source_external_id(cls, source: str, external_id: str) -> Optional['User']:
        """Get user by source + external_id combination (for org sync matching)."""
        async with get_async_db_session() as session:
            statement = select(User).where(
                User.source == source,
                User.external_id == external_id,
            )
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def aget_by_external_id(cls, external_id: str) -> Optional['User']:
        """Get user by external_id globally (cross-source)."""
        async with get_async_db_session() as session:
            statement = select(User).where(User.external_id == external_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def aget_users_by_external_id(cls, external_id: str) -> List['User']:
        """Get all users by external_id globally, including soft-deleted rows."""
        async with get_async_db_session() as session:
            statement = select(User).where(User.external_id == external_id)
            result = await session.exec(statement)
            return list(result.all())

    # ---------------------------------------------------------------
    # v2.5.1 F012: token_version helpers
    # ---------------------------------------------------------------
    TOKEN_VERSION_CACHE_KEY: ClassVar[str] = 'user:{user_id}:token_version'
    TOKEN_VERSION_CACHE_TTL: ClassVar[int] = 300  # seconds

    @classmethod
    async def aget_token_version(cls, user_id: int) -> int:
        """Return the user's current token_version, preferring the Redis cache.

        Cache miss falls back to a single DB read and repopulates the cache.
        Redis infra failure is fail-open — we fall back to DB so login and
        request flows are never blocked by cache infrastructure outages.
        """
        from bisheng.core.cache.redis_manager import get_redis_client

        cache_key = cls.TOKEN_VERSION_CACHE_KEY.format(user_id=user_id)
        try:
            redis = await get_redis_client()
            cached = await redis.aget(cache_key)
            if cached is not None:
                return int(cached)
        except Exception:
            # Redis unavailable — continue to DB read.
            pass

        async with get_async_db_session() as session:
            result = await session.exec(
                select(User.token_version).where(User.user_id == user_id)
            )
            row = result.first()
            if row is None:
                return 0
            version = int(row)

        try:
            redis = await get_redis_client()
            await redis.aset(cache_key, version, expiration=cls.TOKEN_VERSION_CACHE_TTL)
        except Exception:
            pass
        return version

    @classmethod
    async def aincrement_token_version(cls, user_id: int) -> int:
        """Atomically bump token_version via SQL and invalidate the Redis cache.

        Returns the new token_version. We use an atomic UPDATE (token_version +
        1) to avoid a read-modify-write race; we then re-read to return the
        new value so callers can embed it in a freshly issued JWT.
        """
        from bisheng.core.cache.redis_manager import get_redis_client

        async with get_async_db_session() as session:
            await session.exec(
                update(User)
                .where(User.user_id == user_id)
                .values(token_version=User.token_version + 1)
            )
            await session.commit()

            result = await session.exec(
                select(User.token_version).where(User.user_id == user_id)
            )
            row = result.first()
            new_version = int(row) if row is not None else 0

        cache_key = cls.TOKEN_VERSION_CACHE_KEY.format(user_id=user_id)
        try:
            redis = await get_redis_client()
            # Refresh (not just DEL) so the immediate-next aget_token_version
            # hits cache — saves a DB round-trip on the login critical path.
            await redis.aset(cache_key, new_version,
                             expiration=cls.TOKEN_VERSION_CACHE_TTL)
        except Exception:
            pass
        return new_version

    @classmethod
    async def alist_users_paginated(
        cls, offset: int = 0, limit: int = 500
    ) -> List['User']:
        """Page through active users ordered by user_id — used by the F012
        Celery 6h reconcile task so it can walk the whole user table in
        bounded batches without loading everything into memory.
        """
        async with get_async_db_session() as session:
            statement = (
                select(User)
                .where(User.delete == 0)
                .order_by(User.user_id.asc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(statement)
            return list(result.all())

    @classmethod
    async def aget_by_source(cls, source: str, tenant_id: int) -> List['User']:
        """Get all users from a given source within a tenant (for reconcile)."""
        async with get_async_db_session() as session:
            statement = select(User).join(
                UserTenant, User.user_id == UserTenant.user_id,
            ).where(
                User.source == source,
                UserTenant.tenant_id == tenant_id,
            )
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def aget_by_source_or_local_external_ids(
        cls, source: str, tenant_id: int, external_ids: List[str],
    ) -> List['User']:
        """Get provider users plus local rows claimable by external_id.

        Org sync can adopt local accounts when the upstream employee ID matches
        ``user.external_id``. Loading only ``source == provider`` prevents the
        reconciler's local-conflict branch from ever seeing those rows.
        """
        clean_external_ids = []
        for ext in external_ids or []:
            if ext is None:
                continue
            ext = str(ext).strip()
            if ext:
                clean_external_ids.append(ext)
        clean_external_ids = list(dict.fromkeys(clean_external_ids))
        source_clause = User.source == source
        if clean_external_ids:
            source_clause = or_(
                source_clause,
                and_(
                    User.source == 'local',
                    User.external_id.in_(clean_external_ids),
                ),
            )
        async with get_async_db_session() as session:
            statement = select(User).join(
                UserTenant, User.user_id == UserTenant.user_id,
            ).where(
                source_clause,
                UserTenant.tenant_id == tenant_id,
            )
            result = await session.exec(statement)
            return result.all()
