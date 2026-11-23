"""Minimal source/target reservation and a single irreversible worker claim."""

from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeCPError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState


class CopyRepository:
    @staticmethod
    async def pending_targets(resource_ids):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list(
                    (
                        await session.exec(
                            select(Knowledge.id).where(
                                Knowledge.id.in_([int(value) for value in resource_ids]),
                                Knowledge.copy_source_id.is_not(None),
                                Knowledge.copy_target_id.is_(None),
                                Knowledge.state != KnowledgeState.PUBLISHED.value,
                            )
                        )
                    ).all()
                )

    @staticmethod
    async def reserve(source, target):
        tenant_id = int(source.tenant_id)
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            try:
                async with get_async_db_session() as session:
                    current = (
                        await session.exec(
                            select(Knowledge)
                            .where(Knowledge.id == source.id, Knowledge.tenant_id == tenant_id)
                            .with_for_update()
                        )
                    ).first()
                    if (
                        current is None
                        or current.state != KnowledgeState.PUBLISHED.value
                        or current.copy_target_id is not None
                        or target.tenant_id != tenant_id
                    ):
                        raise KnowledgeCPError()
                    target.copy_source_id = current.id
                    target.copy_target_id = None
                    target.state = KnowledgeState.UNPUBLISHED.value
                    session.add(target)
                    await session.flush()
                    current.state = KnowledgeState.COPYING.value
                    current.copy_target_id = target.id
                    session.add(current)
                    await session.commit()
                    await session.refresh(target)
                    return target
            except Exception:
                # A commit exception is not proof of rollback. Inspect the fixed flush ID only.
                if target.id is not None:
                    async with get_async_db_session() as session:
                        stored = await session.get(Knowledge, target.id)
                        original = await session.get(Knowledge, source.id)
                        if (
                            stored is not None
                            and original is not None
                            and stored.tenant_id == tenant_id
                            and stored.copy_source_id == source.id
                            and original.copy_target_id == stored.id
                        ):
                            return stored
                raise

    @staticmethod
    def inspect(tenant_id, source_id, target_id):
        with tenant_execution_scope(tenant_id), strict_tenant_filter(), get_sync_db_session() as session:
            source = session.get(Knowledge, source_id)
            target = session.get(Knowledge, target_id)
            if (
                source is None
                or target is None
                or source.tenant_id != tenant_id
                or target.tenant_id != tenant_id
                or target.copy_source_id != source_id
                or source.copy_target_id != target_id
            ):
                raise KnowledgeCPError()
            return source, target

    @staticmethod
    def claim(tenant_id, source_id, target_id, actor_id):
        with tenant_execution_scope(tenant_id), strict_tenant_filter(), get_sync_db_session() as session:
            source = session.exec(
                select(Knowledge).where(Knowledge.id == source_id, Knowledge.tenant_id == tenant_id).with_for_update()
            ).first()
            target = session.exec(
                select(Knowledge).where(Knowledge.id == target_id, Knowledge.tenant_id == tenant_id).with_for_update()
            ).first()
            if (
                source is None
                or target is None
                or source.copy_target_id != target_id
                or target.copy_source_id != source_id
                or target.user_id != actor_id
                or source.state != KnowledgeState.COPYING.value
            ):
                raise KnowledgeCPError()
            if target.state != KnowledgeState.UNPUBLISHED.value:
                return None  # Duplicate delivery never adopts a running or failed worker.
            result = session.exec(
                update(Knowledge)
                .where(
                    Knowledge.tenant_id == tenant_id,
                    Knowledge.id == target_id,
                    Knowledge.state == KnowledgeState.UNPUBLISHED.value,
                    Knowledge.copy_source_id == source_id,
                )
                .values(state=KnowledgeState.COPYING.value)
            )
            if result.rowcount != 1:
                return None
            session.commit()
            session.refresh(target)
            return source, target

    @staticmethod
    def finish(tenant_id, source_id, target_id, *, succeeded):
        with tenant_execution_scope(tenant_id), strict_tenant_filter(), get_sync_db_session() as session:
            source = session.exec(
                select(Knowledge).where(Knowledge.id == source_id, Knowledge.tenant_id == tenant_id).with_for_update()
            ).first()
            target = session.exec(
                select(Knowledge).where(Knowledge.id == target_id, Knowledge.tenant_id == tenant_id).with_for_update()
            ).first()
            if (
                source is None
                or target is None
                or source.copy_target_id != target_id
                or target.copy_source_id != source_id
                or target.state != KnowledgeState.COPYING.value
            ):
                raise KnowledgeCPError()
            target.state = KnowledgeState.PUBLISHED.value if succeeded else KnowledgeState.FAILED.value
            session.add(target)
            if succeeded:
                source.copy_target_id = None
                source.state = KnowledgeState.PUBLISHED.value
                session.add(source)
            session.commit()
