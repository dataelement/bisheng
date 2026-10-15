from datetime import datetime

from sqlalchemy import INT, Column, DateTime, Integer, delete, func, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class UserGroupBase(SQLModelSerializable):
    user_id: int | None = Field(default=None, foreign_key="user.user_id", primary_key=True, ondelete="CASCADE")

    group_id: int | None = Field(default=None, foreign_key="group.id", primary_key=True, ondelete="CASCADE")
    is_group_admin: bool = Field(
        default=False, index=False, description="Is Group Admin"
    )  # Admin does not belong to this user group
    remark: str | None = Field(default=None, index=False)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class UserGroup(UserGroupBase, table=True):
    id: int | None = Field(default=None, sa_column=Column(INT, primary_key=True, autoincrement=True))


class UserGroupRead(UserGroupBase):
    id: int | None = None


class UserGroupUpdate(UserGroupBase):
    user_id: int | None = None
    group_id: int | None = None
    is_group_admin: bool | None = None
    remark: str | None = None


class UserGroupCreate(UserGroupBase):
    pass


class UserGroupDao(UserGroupBase):
    @classmethod
    def get_user_group(cls, user_id: int) -> list[UserGroup]:
        """
        Get the user group the user is in
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 0)
            return session.exec(statement).all()

    @classmethod
    async def aget_user_group(cls, user_id: int) -> list[UserGroup]:
        """
        Get the user group the user is in asynchronously
        """
        statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 0)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_user_admin_group(cls, user_id: int) -> list[UserGroup]:
        """
        Get user groups where the user is an administrator
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    async def aget_user_admin_group(cls, user_id: int, group_id: int = None) -> list[UserGroup]:
        """
        Get user groups where the user is an administrator, If it passes,group_idOnly the group's admin information will be retrieved
        """
        statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 1)
        if group_id:
            statement = statement.where(UserGroup.group_id == group_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def insert_user_group(cls, user_group: UserGroupCreate) -> UserGroup:
        with get_sync_db_session() as session:
            user_group = UserGroup.validate(user_group)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def insert_user_group_admin(cls, user_id: int, group_id: int) -> UserGroup:
        """
        Set user as group administrator
        """
        with get_sync_db_session() as session:
            user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=True)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def delete_user_group(cls, user_id: int, group_id: int) -> None:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
            user_group = session.exec(statement).first()
            session.delete(user_group)
            session.commit()

    @classmethod
    def delete_user_groups(cls, user_id: int, group_ids: list[int]):
        """
        Remove users from certain groups
        """
        with get_sync_db_session() as session:
            # Empty all old user groups first
            statement = (
                delete(UserGroup)
                .where(UserGroup.user_id == user_id)
                .where(UserGroup.is_group_admin == 0)
                .where(UserGroup.group_id.in_(group_ids))
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def add_user_groups(cls, user_id: int, group_ids: list[int]):
        """
        Add users to some groups
        """
        with get_sync_db_session() as session:
            for group_id in group_ids:
                user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=0)
                session.add(user_group)
            session.commit()

    @classmethod
    def batch_add_group_members(cls, group_id: int, user_ids: list[int]) -> None:
        """Batch add multiple users as non-admin members of a single group in one transaction."""
        if not user_ids:
            return
        with get_sync_db_session() as session:
            session.add_all([UserGroup(user_id=uid, group_id=group_id, is_group_admin=0) for uid in user_ids])
            session.commit()

    @classmethod
    def batch_delete_group_members(cls, group_id: int, user_ids: list[int]) -> None:
        """Batch remove non-admin memberships for multiple users from a single group."""
        if not user_ids:
            return
        with get_sync_db_session() as session:
            statement = delete(UserGroup).where(
                UserGroup.group_id == group_id,
                UserGroup.is_group_admin == 0,
                UserGroup.user_id.in_(user_ids),
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def get_group_user(cls, group_id: int, page_size: str = None, page_num: str = None) -> list[UserGroup]:
        """
        Get all users in a group, excluding admins
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id).where(UserGroup.is_group_admin == 0)
            if page_num and page_size:
                statement = statement.offset((int(page_num) - 1) * int(page_size)).limit(int(page_size))
            return session.exec(statement).all()

    @classmethod
    def get_groups_user(cls, group_ids: list[int], page: int = 0, limit: int = 0) -> list[UserGroup]:
        """
        Batch Get Users Under Grouping
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids)).where(UserGroup.is_group_admin == 0)
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            return session.exec(statement).all()

    @classmethod
    async def aget_group_users(cls, group_ids: list[int], page: int = 0, limit: int = 0) -> list[UserGroup]:
        """
        Batch Get Users Under Grouping
        Args:
            group_ids:
            page:
            limit:

        Returns:

        """
        statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def is_users_in_group(cls, group_id: int, user_ids: list[int]) -> list[UserGroup]:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id, UserGroup.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    def get_groups_admins(cls, group_ids: list[int]) -> list[UserGroup]:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids), UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    def update_user_groups(cls, user_groups: list[UserGroup]) -> list[UserGroup]:
        with get_sync_db_session() as session:
            session.add_all(user_groups)
            session.commit()
            return user_groups

    @classmethod
    def delete_group_admins(cls, group_id: int, admin_ids: list[int]) -> None:
        """
        Bulk delete user groupsadmin
        """
        with get_sync_db_session() as session:
            statement = (
                delete(UserGroup)
                .where(UserGroup.group_id == group_id)
                .where(UserGroup.user_id.in_(admin_ids))
                .where(UserGroup.is_group_admin == 1)
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def delete_group_all_admin(cls, group_id: int) -> None:
        """
        Remove all administrators under the user group
        """
        with get_sync_db_session() as session:
            statement = delete(UserGroup).where(UserGroup.group_id == group_id).where(UserGroup.is_group_admin == 1)
            session.exec(statement)
            session.commit()

    # --- Async methods (F003) ---

    @classmethod
    async def aget_group_members(
        cls,
        group_id: int,
        page: int = 1,
        limit: int = 20,
        keyword: str = "",
    ) -> tuple[list[dict], int]:
        """Paginated member list (non-admin) with user details."""
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            base = (
                select(
                    UserGroup.user_id, User.user_name, UserGroup.is_group_admin, UserGroup.create_time, User.external_id
                )
                .join(User, UserGroup.user_id == User.user_id)
                .where(UserGroup.group_id == group_id, UserGroup.is_group_admin == 0, User.delete == 0)
            )
            if keyword:
                base = base.where(User.user_name.like(f"%{keyword}%"))

            count_stmt = select(func.count()).select_from(base.subquery())
            total = (await session.exec(count_stmt)).one()

            stmt = base.offset((page - 1) * limit).limit(limit)
            rows = (await session.exec(stmt)).all()
            members = [
                {
                    "user_id": r[0],
                    "user_name": r[1],
                    "is_group_admin": bool(r[2]),
                    "create_time": r[3],
                    "external_id": r[4],
                }
                for r in rows
            ]
            return members, total

    @classmethod
    async def aget_plain_member_user_ids(cls, group_id: int) -> list[int]:
        """当前组内普通成员 user_id 列表（不含 is_group_admin=1，不含已删除用户）。"""
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            stmt = (
                select(UserGroup.user_id)
                .join(User, UserGroup.user_id == User.user_id)
                .where(
                    UserGroup.group_id == group_id,
                    UserGroup.is_group_admin == False,  # noqa: E712
                    User.delete == 0,
                )
            )
            rows = (await session.exec(stmt)).all()
            out: list[int] = []
            for r in rows:
                if isinstance(r, (tuple, list)):
                    out.append(int(r[0]))
                else:
                    out.append(int(r))
            return out

    @classmethod
    async def adelete_plain_members_batch(
        cls,
        group_id: int,
        user_ids: list[int],
    ) -> None:
        """批量删除普通成员行（仅 is_group_admin=0）。"""
        if not user_ids:
            return
        async with get_async_db_session() as session:
            await session.exec(
                delete(UserGroup).where(
                    UserGroup.group_id == group_id,
                    UserGroup.user_id.in_(user_ids),
                    UserGroup.is_group_admin == False,  # noqa: E712
                )
            )
            await session.commit()

    @classmethod
    async def aget_group_member_count(cls, group_id: int) -> int:
        """Count non-admin members of a group (excluding deleted users)."""
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            stmt = (
                select(func.count(UserGroup.id))
                .join(User, UserGroup.user_id == User.user_id)
                .where(
                    UserGroup.group_id == group_id,
                    UserGroup.is_group_admin == 0,
                    User.delete == 0,
                )
            )
            result = await session.exec(stmt)
            return result.one()

    @classmethod
    async def aget_group_member_counts(cls, group_ids: list[int]) -> dict[int, int]:
        """批量统计多个用户组的普通成员数，避免列表页逐条 count。"""
        from bisheng.user.domain.models.user import User

        if not group_ids:
            return {}

        async with get_async_db_session() as session:
            stmt = (
                select(UserGroup.group_id, func.count(UserGroup.id))
                .join(User, UserGroup.user_id == User.user_id)
                .where(
                    UserGroup.group_id.in_(group_ids),
                    UserGroup.is_group_admin == 0,
                    User.delete == 0,
                )
                .group_by(UserGroup.group_id)
            )
            rows = (await session.exec(stmt)).all()

        counts: dict[int, int] = {int(group_id): int(count) for group_id, count in rows}
        for group_id in group_ids:
            counts.setdefault(int(group_id), 0)
        return counts

    @classmethod
    async def aadd_members_batch(cls, group_id: int, user_ids: list[int]) -> None:
        """Batch add members (is_group_admin=0)."""
        async with get_async_db_session() as session:
            for uid in user_ids:
                session.add(UserGroup(user_id=uid, group_id=group_id, is_group_admin=False))
            await session.commit()

    @classmethod
    async def aremove_member(cls, group_id: int, user_id: int) -> None:
        """Remove a single non-admin member."""
        async with get_async_db_session() as session:
            await session.exec(
                delete(UserGroup).where(
                    UserGroup.group_id == group_id,
                    UserGroup.user_id == user_id,
                    UserGroup.is_group_admin == 0,
                )
            )
            await session.commit()

    @classmethod
    async def acheck_members_exist(
        cls,
        group_id: int,
        user_ids: list[int],
    ) -> list[int]:
        """Return user_ids that already exist in the group (member or admin)."""
        async with get_async_db_session() as session:
            stmt = select(UserGroup.user_id).where(
                UserGroup.group_id == group_id,
                UserGroup.user_id.in_(user_ids),
            )
            result = await session.exec(stmt)
            return result.all()

    @classmethod
    async def aget_plain_member_row(
        cls,
        group_id: int,
        user_id: int,
    ) -> UserGroup | None:
        """Return membership row if user is a non-admin member of the group."""
        async with get_async_db_session() as session:
            stmt = select(UserGroup).where(
                UserGroup.group_id == group_id,
                UserGroup.user_id == user_id,
                UserGroup.is_group_admin == False,  # noqa: E712
            )
            result = await session.exec(stmt)
            return result.first()

    @classmethod
    async def aget_group_admins_detail(cls, group_id: int) -> list[dict]:
        """Get group admins with user details."""
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            stmt = (
                select(UserGroup.user_id, User.user_name)
                .join(User, UserGroup.user_id == User.user_id)
                .where(UserGroup.group_id == group_id, UserGroup.is_group_admin == 1, User.delete == 0)
            )
            rows = (await session.exec(stmt)).all()
            return [{"user_id": r[0], "user_name": r[1]} for r in rows]

    @classmethod
    async def aset_admins_batch(
        cls,
        group_id: int,
        add_ids: list[int],
        remove_ids: list[int],
    ) -> None:
        """Batch set/remove admins. Upgrades plain member rows to admin when needed."""
        async with get_async_db_session() as session:
            if remove_ids:
                await session.exec(
                    delete(UserGroup).where(
                        UserGroup.group_id == group_id,
                        UserGroup.user_id.in_(remove_ids),
                        UserGroup.is_group_admin == 1,
                    )
                )
            for uid in add_ids:
                result = await session.exec(
                    select(UserGroup).where(
                        UserGroup.group_id == group_id,
                        UserGroup.user_id == uid,
                    )
                )
                row = result.first()
                if row:
                    if not row.is_group_admin:
                        row.is_group_admin = True
                        session.add(row)
                else:
                    session.add(
                        UserGroup(
                            user_id=uid,
                            group_id=group_id,
                            is_group_admin=True,
                        )
                    )
            await session.commit()

    @classmethod
    async def aget_user_visible_group_ids(cls, user_id: int) -> list[int]:
        """Get all group IDs where user is member or admin."""
        async with get_async_db_session() as session:
            stmt = select(UserGroup.group_id).where(UserGroup.user_id == user_id)
            result = await session.exec(stmt)
            return result.all()

    @classmethod
    async def aget_user_groups_batch(cls, user_ids: list[int]) -> dict:
        """
        Async: For a list of user_ids, return a map of user_id -> List[Group].
        Only includes non-admin group memberships (is_group_admin == 0).
        """
        from bisheng.database.models.group import Group

        if not user_ids:
            return {}
        statement = (
            select(UserGroup.user_id, Group)
            .join(Group, UserGroup.group_id == Group.id)
            .where(
                UserGroup.user_id.in_(user_ids),
                UserGroup.is_group_admin == 0,
            )
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        result: dict = {}
        for uid, group in rows:
            result.setdefault(uid, []).append(group)
        return result
