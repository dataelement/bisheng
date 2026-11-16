"""Authoritative reads and optimistic lifecycle writes; no positive cache."""

from sqlalchemy import update
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.open_api.domain.models.kunlian_credential import KunlianCredential


class KunlianCredentialRepository:
    @staticmethod
    async def insert(row):
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @staticmethod
    async def by_hash(digest):
        async with get_async_db_session() as session:
            return (await session.exec(select(KunlianCredential).where(KunlianCredential.token_hash == digest))).first()

    @staticmethod
    async def get(key_id):
        async with get_async_db_session() as session:
            return (await session.exec(select(KunlianCredential).where(KunlianCredential.id == key_id))).first()

    @staticmethod
    async def list(*, offset, limit):
        async with get_async_db_session() as session:
            return list(
                (
                    await session.exec(
                        select(KunlianCredential).order_by(col(KunlianCredential.id).desc()).offset(offset).limit(limit)
                    )
                ).all()
            )

    @staticmethod
    async def _save(session, row, expected_revision):
        # Patch only mutable policy, preventing a stale management request from
        # restoring a revoked key or changing the immutable integration binding.
        result = await session.exec(
            update(KunlianCredential)
            .where(
                KunlianCredential.id == row.id,
                KunlianCredential.policy_revision == expected_revision,
            )
            .values(
                tenant_ids=row.tenant_ids,
                capabilities=row.capabilities,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
                policy_revision=row.policy_revision,
            )
        )
        return result.rowcount == 1

    @classmethod
    async def save(cls, row, *, expected_revision):
        async with get_async_db_session() as session:
            async with session.begin():
                return await cls._save(session, row, expected_revision)

    @classmethod
    async def rotate(cls, old, new, *, expected_revision):
        async with get_async_db_session() as session:
            async with session.begin():
                if not await cls._save(session, old, expected_revision):
                    return None
                session.add(new)
                await session.flush()
            await session.refresh(new)
        return new
