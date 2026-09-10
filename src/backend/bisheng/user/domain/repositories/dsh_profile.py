"""User-owned SQL changes and bounded current identity snapshots for DSH."""

from contextlib import contextmanager

from sqlalchemy import inspect
from sqlmodel import Session, col, select

from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


class UserDshProfileRepository:
    PROFILE_FIELDS = {"user_name"}

    @staticmethod
    def access_users(
        session: Session,
        *,
        after_user_id: int = 0,
        limit: int = 20,
        keyword: str = "",
        user_ids: list[int] | None = None,
    ) -> list[tuple[int, str]]:
        """Read one page plus a lookahead of active users for DSH administration."""
        tenant = get_current_tenant_id()
        if tenant is None or not 1 <= limit <= 100:
            raise ValueError("A current tenant and a bounded page are required")
        statement = (
            select(User.user_id, User.user_name)
            .join(UserTenant, UserTenant.user_id == User.user_id)
            .join(Tenant, Tenant.id == UserTenant.tenant_id)
            .where(
                UserTenant.tenant_id == tenant,
                UserTenant.is_active == 1,
                UserTenant.status == "active",
                Tenant.status == "active",
                User.delete == 0,
                User.user_id > after_user_id,
            )
            .order_by(User.user_id)
            .limit(limit + 1)
        )
        if user_ids is not None:
            statement = statement.where(col(User.user_id).in_(user_ids))
        if keyword:
            statement = statement.where(col(User.user_name).contains(keyword, autoescape=True))
        with strict_tenant_filter():
            return [(user_id, name) for user_id, name in session.exec(statement).all()]

    @staticmethod
    @contextmanager
    def transaction():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            yield session
            session.commit()

    @staticmethod
    def detach(session: Session, user: User) -> User:
        session.flush()
        session.refresh(user)
        session.expunge(user)
        return user

    @classmethod
    def activate_tenant(cls, session: Session, user_id: int, tenant_id: int) -> User:
        user = cls.get_for_update(session, user_id)
        memberships = session.exec(select(UserTenant).where(UserTenant.user_id == user_id).with_for_update()).all()
        target = next((row for row in memberships if row.tenant_id == tenant_id), None)
        for row in memberships:
            row.is_active = None
        session.flush()
        if target is None:
            target = UserTenant(user_id=user_id, tenant_id=tenant_id, is_default=1)
            session.add(target)
        target.is_active, target.status = 1, "active"
        user.token_version += 1
        session.flush()
        return user

    @staticmethod
    def get_for_update(session: Session, user_id: int) -> User:
        user = session.exec(select(User).where(User.user_id == user_id).with_for_update()).one_or_none()
        if user is None:
            raise ValueError("User not found")
        return user

    @classmethod
    def apply_detached_changes(cls, session: Session, changed: User) -> tuple[User, bool]:
        state = inspect(changed)
        updates = {
            attribute.key: getattr(changed, attribute.key)
            for attribute in state.mapper.column_attrs
            if attribute.key not in {"user_id", "dsh_profile_version", "token_version", "create_time"}
            and state.attrs[attribute.key].history.has_changes()
        }
        user = cls.get_for_update(session, changed.user_id)
        profile_changed = any(
            key in cls.PROFILE_FIELDS and getattr(user, key) != value for key, value in updates.items()
        )
        for key, value in updates.items():
            setattr(user, key, value)
        session.flush()
        return user, profile_changed

    @classmethod
    def bump_snapshot(cls, session: Session, user: User) -> dict | None:
        if inspect(user).session is not session:
            raise ValueError("The owning user must belong to the transaction")
        user.dsh_profile_version += 1
        session.flush()
        return cls.batch_snapshot(session, [user.user_id]).get(user.user_id)

    @staticmethod
    def batch_snapshot(session: Session, user_ids: list[int]) -> dict[int, dict]:
        ids = sorted(set(user_ids))
        if len(ids) > 100:
            raise ValueError("A profile batch cannot exceed 100 users")
        if not ids:
            return {}
        users = session.exec(select(User).where(User.user_id.in_(ids))).all()
        memberships = session.exec(
            select(UserTenant).where(UserTenant.user_id.in_(ids), UserTenant.is_active == 1)
        ).all()
        tenants = {row.user_id: row.tenant_id for row in memberships}
        return {
            user.user_id: {
                "tenant_id": str(tenants[user.user_id]),
                "user_id": str(user.user_id),
                "username": user.user_name,
                "display_name": user.user_name,
                "profile_version": user.dsh_profile_version,
            }
            for user in users
            if user.user_id in tenants
        }

    @staticmethod
    def cursor_ids(session: Session, *, after_user_id: int = 0, limit: int = 100) -> list[int]:
        if not 1 <= limit <= 100:
            raise ValueError("A profile cursor batch must be between 1 and 100")
        return list(
            session.exec(select(User.user_id).where(User.user_id > after_user_id).order_by(User.user_id).limit(limit))
        )
