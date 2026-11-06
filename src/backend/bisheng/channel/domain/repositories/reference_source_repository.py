"""Exact current channel snapshots without managed ORM or child-tenant guesses."""

from copy import deepcopy

from sqlmodel import select

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.core.context.tenant import strict_tenant_filter


class ChannelReferenceSourceRepository:
    async def aload(self, session, channel_id: str, *, for_update: bool = False):
        tenant_id = ChannelReferenceBindingRepository._tenant_id()
        query = select(*Channel.__table__.columns).where(Channel.id == channel_id)
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            channel = (await session.execute(query)).mappings().one_or_none()
        if channel is None or channel["tenant_id"] != tenant_id:
            return None
        query = (
            select(*ChannelKnowledgeSync.__table__.columns, Channel.tenant_id.label("source_tenant_id"))
            .join(Channel, Channel.id == ChannelKnowledgeSync.channel_id)
            .where(Channel.id == channel_id)
            .order_by(ChannelKnowledgeSync.id)
        )
        if for_update:
            query = query.with_for_update()
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.execute(query)).mappings().all()
        if any(row["source_tenant_id"] != tenant_id for row in rows):
            raise ChannelNotFoundError()
        return deepcopy(dict(channel)), tuple(
            deepcopy({key: value for key, value in row.items() if key != "source_tenant_id"}) for row in rows
        )
