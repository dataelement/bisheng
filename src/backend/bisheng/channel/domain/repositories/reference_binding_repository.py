"""Channel and tenant-less children in the reference writer's transaction."""

from collections.abc import Iterable

from sqlalchemy import delete, inspect
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id


class ChannelReferenceBindingRepository:
    """No session factory, transaction ownership or implicit commit."""

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = _resolve_tenant_id()
        if is_tenant_filter_bypassed() or type(tenant_id) is not int or tenant_id <= 0:
            raise ChannelNotFoundError()
        return tenant_id

    async def aget(self, session: AsyncSession, channel_id: str, *, for_update: bool = False) -> Channel | None:
        tenant_id = self._tenant_id()
        query = select(Channel).where(Channel.id == channel_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.exec(query)).one_or_none()
        return row if row is not None and row.tenant_id == tenant_id else None

    async def aget_by_creation_request(self, session: AsyncSession, user_id: int, request_id: str) -> Channel | None:
        self._tenant_id()
        with session.no_autoflush, strict_tenant_filter():
            return (
                await session.exec(
                    select(Channel).where(Channel.user_id == user_id, Channel.creation_request_id == request_id)
                )
            ).one_or_none()

    async def _parent(self, session: AsyncSession, channel_id: str) -> Channel:
        row = await self.aget(session, channel_id)
        if row is None:
            raise ChannelNotFoundError()
        return row

    async def alist_sync_rows(
        self, session: AsyncSession, channel_id: str, *, for_update: bool = False
    ) -> tuple[ChannelKnowledgeSync, ...]:
        await self._parent(session, channel_id)
        query = (
            select(ChannelKnowledgeSync, Channel.tenant_id)
            .join(Channel, Channel.id == ChannelKnowledgeSync.channel_id)
            .where(Channel.id == channel_id)
            .order_by(ChannelKnowledgeSync.id)
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.exec(query)).all()
        if any(tenant != self._tenant_id() for _, tenant in rows):
            raise ChannelNotFoundError()
        return tuple(row for row, _ in rows)

    async def alist_members(
        self, session: AsyncSession, channel_id: str, *, for_update: bool = False
    ) -> tuple[SpaceChannelMember, ...]:
        await self._parent(session, channel_id)
        query = (
            select(SpaceChannelMember, Channel.tenant_id)
            .join(Channel, Channel.id == SpaceChannelMember.business_id)
            .where(Channel.id == channel_id, SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL)
            .order_by(SpaceChannelMember.id)
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.exec(query)).all()
        return tuple(row for row, tenant in rows if tenant == self._tenant_id())

    async def ainsert(self, session: AsyncSession, channel: Channel) -> Channel:
        tenant_id = self._tenant_id()
        if channel.tenant_id not in (None, tenant_id) or inspect(channel).persistent:
            raise ChannelNotFoundError()
        channel.tenant_id = tenant_id
        session.add(channel)
        await session.flush()
        return channel

    def _assert_bound(self, session: AsyncSession, channel: Channel) -> None:
        state = inspect(channel)
        if (
            channel.tenant_id != self._tenant_id()
            or not state.persistent
            or state.session is not session.sync_session
            or state.attrs.tenant_id.history.has_changes()
            or state.attrs.id.history.has_changes()
        ):
            raise ChannelNotFoundError()

    async def asave(self, session: AsyncSession, channel: Channel) -> Channel:
        self._assert_bound(session, channel)
        await session.flush()
        return channel

    def _parent_exists(self, channel: Channel):
        return select(Channel.id).where(Channel.id == channel.id, Channel.tenant_id == self._tenant_id()).exists()

    async def areplace_sync_rows(
        self, session: AsyncSession, channel: Channel, rows: Iterable[ChannelKnowledgeSync]
    ) -> None:
        self._assert_bound(session, channel)
        rows = tuple(rows)
        if any(row.channel_id != channel.id or inspect(row).persistent for row in rows):
            raise ChannelNotFoundError()
        await session.execute(
            delete(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.channel_id == channel.id, self._parent_exists(channel))
            .execution_options(synchronize_session=False)
        )
        session.add_all(rows)
        await session.flush()

    async def aensure_creator(self, session: AsyncSession, channel: Channel, *, binding_key: str) -> None:
        self._assert_bound(session, channel)
        if any(member.user_id == channel.user_id for member in await self.alist_members(session, channel.id)):
            return
        session.add(
            SpaceChannelMember(
                business_id=channel.id,
                business_type=BusinessTypeEnum.CHANNEL,
                user_id=channel.user_id,
                user_role=UserRoleEnum.CREATOR,
                relation=ChannelRelationEnum.OWNER,
                grant_subject_type="self",
                grant_subject_id=channel.user_id,
                grant_relation=ChannelRelationEnum.OWNER,
                grant_model_id=ChannelRelationEnum.OWNER.value,
                grant_binding_key=binding_key,
            )
        )
        await session.flush()

    async def adelete_channel_configuration(self, session: AsyncSession, channel: Channel) -> None:
        self._assert_bound(session, channel)
        await self.areplace_sync_rows(session, channel, ())
        await session.execute(
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel.id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                self._parent_exists(channel),
            )
            .execution_options(synchronize_session=False)
        )
        await session.delete(channel)
        await session.flush()
