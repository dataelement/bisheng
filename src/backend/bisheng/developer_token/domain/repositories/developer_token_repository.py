from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, update
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.developer_token.domain.models import DeveloperToken


class DeveloperTokenRepository:
    @classmethod
    async def list_tokens(
        cls,
        *,
        page: int = 1,
        limit: int = 20,
        keyword: str | None = None,
        tenant_id: int | None = None,
        user_id: int | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[DeveloperToken], int]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(DeveloperToken).where(DeveloperToken.logic_delete == 0)
                count_stmt = (
                    select(func.count())
                    .select_from(DeveloperToken)
                    .where(
                        DeveloperToken.logic_delete == 0,
                    )
                )

                if keyword:
                    like = f"%{keyword}%"
                    condition = or_(DeveloperToken.name.like(like), DeveloperToken.token_prefix.like(like))
                    stmt = stmt.where(condition)
                    count_stmt = count_stmt.where(condition)
                if tenant_id is not None:
                    stmt = stmt.where(DeveloperToken.tenant_id == tenant_id)
                    count_stmt = count_stmt.where(DeveloperToken.tenant_id == tenant_id)
                if user_id is not None:
                    stmt = stmt.where(DeveloperToken.user_id == user_id)
                    count_stmt = count_stmt.where(DeveloperToken.user_id == user_id)
                if enabled is not None:
                    stmt = stmt.where(DeveloperToken.enabled == enabled)
                    count_stmt = count_stmt.where(DeveloperToken.enabled == enabled)

                total_result = await session.exec(count_stmt)
                total = int(total_result.one() or 0)

                stmt = stmt.order_by(DeveloperToken.id.desc())
                stmt = stmt.offset((page - 1) * limit).limit(limit)
                result = await session.exec(stmt)
                return list(result.all()), total

    @classmethod
    async def get_token_by_id(cls, token_id: int, include_deleted: bool = False) -> DeveloperToken | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(DeveloperToken).where(DeveloperToken.id == token_id)
                if not include_deleted:
                    stmt = stmt.where(DeveloperToken.logic_delete == 0)
                result = await session.exec(stmt)
                return result.first()

    @classmethod
    async def get_token_by_hash(cls, token_hash: str) -> DeveloperToken | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(DeveloperToken).where(
                        DeveloperToken.token_hash == token_hash,
                        DeveloperToken.logic_delete == 0,
                    )
                )
                return result.first()

    @classmethod
    async def create_token(cls, token: DeveloperToken) -> DeveloperToken:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                session.add(token)
                await session.commit()
                await session.refresh(token)
                return token

    @classmethod
    async def update_token(cls, token_id: int, **fields) -> DeveloperToken | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(DeveloperToken).where(
                        DeveloperToken.id == token_id,
                        DeveloperToken.logic_delete == 0,
                    )
                )
                token = result.first()
                if token is None:
                    return None
                for key, value in fields.items():
                    if hasattr(token, key):
                        setattr(token, key, value)
                session.add(token)
                await session.commit()
                await session.refresh(token)
                return token

    @classmethod
    async def logic_delete_token(cls, token_id: int, operator_id: int | None = None) -> bool:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    update(DeveloperToken)
                    .where(
                        DeveloperToken.id == token_id,
                        DeveloperToken.logic_delete == 0,
                    )
                    .values(
                        logic_delete=1,
                        updated_by=operator_id,
                        update_time=datetime.now(),
                    )
                )
                await session.commit()
                return (getattr(result, "rowcount", 0) or 0) > 0

    @classmethod
    async def update_last_used(cls, token_id: int, ip_address: str | None) -> bool:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    update(DeveloperToken)
                    .where(
                        DeveloperToken.id == token_id,
                        DeveloperToken.logic_delete == 0,
                    )
                    .values(
                        last_used_time=datetime.now(),
                        last_used_ip=ip_address,
                    )
                )
                await session.commit()
                return (getattr(result, "rowcount", 0) or 0) > 0
