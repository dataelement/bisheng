"""Database operations for Open API credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func
from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope


class CredentialRepository:
    @classmethod
    async def create(cls, row: ApiCredential) -> ApiCredential:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def create_with_delegate_entries(
        cls,
        row: ApiCredential,
        entries: tuple[tuple[str, int], ...],
    ) -> ApiCredential:
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(row)
                await session.flush()
                for subject_type, subject_id in entries:
                    session.add(
                        ApiCredentialDelegateScope(
                            tenant_id=row.tenant_id,
                            credential_id=row.id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )
            await session.refresh(row)
        return row

    @classmethod
    async def get(cls, credential_id: int) -> ApiCredential | None:
        async with get_async_db_session() as session:
            return (await session.exec(select(ApiCredential).where(ApiCredential.id == credential_id))).first()

    @classmethod
    async def get_by_hash(cls, token_hash: str) -> ApiCredential | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(ApiCredential).where(ApiCredential.token_hash == token_hash))).first()

    @classmethod
    def get_for_execution_sync(cls, credential_id: int) -> ApiCredential | None:
        with bypass_tenant_filter():
            with get_sync_db_session() as session:
                return session.exec(select(ApiCredential).where(ApiCredential.id == credential_id)).first()

    @classmethod
    async def list_by_subject(
        cls,
        subject_kind: str,
        subject_id: int,
        *,
        include_revoked: bool = True,
    ) -> list[ApiCredential]:
        statement = select(ApiCredential).where(
            ApiCredential.subject_kind == subject_kind,
            ApiCredential.subject_id == subject_id,
        )
        if not include_revoked:
            statement = statement.where(col(ApiCredential.revoked_at).is_(None))
        statement = statement.order_by(col(ApiCredential.id).desc())
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    async def list_natural_person_page(
        cls,
        *,
        tenant_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[ApiCredential], int]:
        filters = (
            ApiCredential.tenant_id == tenant_id,
            ApiCredential.subject_kind == "natural_person",
        )
        statement = (
            select(ApiCredential)
            .where(*filters)
            .order_by(col(ApiCredential.id).desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count()).select_from(ApiCredential).where(*filters)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = list((await session.exec(statement)).all())
                total = int((await session.exec(count_statement)).one())
        return rows, total

    @classmethod
    async def revoke_natural_person(
        cls,
        *,
        tenant_id: int,
        user_id: int,
        reason: str,
    ) -> list[ApiCredential]:
        now = datetime.now()
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(ApiCredential).where(
                    ApiCredential.tenant_id == tenant_id,
                    ApiCredential.subject_kind == "natural_person",
                    ApiCredential.subject_id == user_id,
                    col(ApiCredential.revoked_at).is_(None),
                )
                rows = list((await session.exec(statement)).all())
                for row in rows:
                    row.revoked_at = now
                    row.revoke_reason = reason
                    row.update_time = now
                    session.add(row)
                await session.commit()
        return rows

    @classmethod
    async def save(cls, row: ApiCredential) -> ApiCredential:
        row.update_time = datetime.now()
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def save_with_delegate_entries(
        cls,
        row: ApiCredential,
        entries: tuple[tuple[str, int], ...],
    ) -> ApiCredential:
        row.update_time = datetime.now()
        async with get_async_db_session() as session:
            async with session.begin():
                session.add(row)
                await session.exec(
                    delete(ApiCredentialDelegateScope).where(
                        ApiCredentialDelegateScope.credential_id == row.id
                    )
                )
                for subject_type, subject_id in entries:
                    session.add(
                        ApiCredentialDelegateScope(
                            tenant_id=row.tenant_id,
                            credential_id=row.id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )
            await session.refresh(row)
        return row

    @classmethod
    async def revoke_subject(cls, subject_kind: str, subject_id: int, *, reason: str) -> list[ApiCredential]:
        now = datetime.now()
        async with get_async_db_session() as session:
            statement = select(ApiCredential).where(
                ApiCredential.subject_kind == subject_kind,
                ApiCredential.subject_id == subject_id,
                col(ApiCredential.revoked_at).is_(None),
            )
            rows = list((await session.exec(statement)).all())
            for row in rows:
                row.revoked_at = now
                row.revoke_reason = reason
                row.update_time = now
                session.add(row)
            await session.commit()
        return rows

    @classmethod
    async def touch_last_used(cls, credential_id: int, *, used_at: datetime) -> bool:
        async with get_async_db_session() as session:
            row = (await session.exec(select(ApiCredential).where(ApiCredential.id == credential_id))).first()
            if row is None:
                return False
            row.last_used_at = used_at
            row.update_time = used_at
            session.add(row)
            await session.commit()
        return True
