from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import col, select

from bisheng.approval.domain.models.user_menu_access import (
    UserMenuAccess,
    UserMenuAccessStatus,
)
from bisheng.core.database import get_async_db_session


class UserMenuAccessRepository:
    @classmethod
    async def list_active_menu_keys(cls, tenant_id: int, user_id: int) -> list[str]:
        statement = select(UserMenuAccess.menu_key).where(
            UserMenuAccess.tenant_id == tenant_id,
            UserMenuAccess.user_id == user_id,
            UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return list(dict.fromkeys(rows))

    @classmethod
    async def get_active_grant(cls, tenant_id: int, user_id: int, menu_key: str) -> Optional[UserMenuAccess]:
        statement = select(UserMenuAccess).where(
            UserMenuAccess.tenant_id == tenant_id,
            UserMenuAccess.user_id == user_id,
            UserMenuAccess.menu_key == menu_key,
            UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def upsert_active_grant(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        menu_key: str,
        menu_name: str | None,
        grant_source: str,
        grant_instance_id: int | None = None,
    ) -> UserMenuAccess:
        async with get_async_db_session() as session:
            statement = select(UserMenuAccess).where(
                UserMenuAccess.tenant_id == tenant_id,
                UserMenuAccess.user_id == user_id,
                UserMenuAccess.menu_key == menu_key,
                UserMenuAccess.grant_source == grant_source,
            )
            row = (await session.exec(statement)).first()
            if row:
                row.menu_name = menu_name
                row.grant_instance_id = grant_instance_id
                row.status = UserMenuAccessStatus.ACTIVE
                row.revoked_reason = None
                row.revoked_by_user_id = None
                row.revoked_at = None
            else:
                row = UserMenuAccess(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    menu_key=menu_key,
                    menu_name=menu_name,
                    grant_source=grant_source,
                    grant_instance_id=grant_instance_id,
                    status=UserMenuAccessStatus.ACTIVE,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get_revoked_instance_ids(cls, instance_ids: list[int]) -> set[int]:
        """Return the subset of instance_ids whose approval grant has been revoked."""
        if not instance_ids:
            return set()
        statement = select(UserMenuAccess.grant_instance_id).where(
            col(UserMenuAccess.grant_instance_id).in_(instance_ids),
            UserMenuAccess.status == UserMenuAccessStatus.REVOKED,
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return {r for r in rows if r is not None}

    @classmethod
    async def revoke_grant(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        menu_key: str,
        grant_source: str,
        revoked_by_user_id: int,
        revoked_reason: str | None = None,
    ) -> Optional[UserMenuAccess]:
        async with get_async_db_session() as session:
            statement = select(UserMenuAccess).where(
                UserMenuAccess.tenant_id == tenant_id,
                UserMenuAccess.user_id == user_id,
                UserMenuAccess.menu_key == menu_key,
                UserMenuAccess.grant_source == grant_source,
                UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
            )
            row = (await session.exec(statement)).first()
            if not row:
                return None
            row.status = UserMenuAccessStatus.REVOKED
            row.revoked_by_user_id = revoked_by_user_id
            row.revoked_reason = revoked_reason
            row.revoked_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return row

