"""Exact current channel snapshots without managed ORM or child-tenant guesses."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.resource_reference.application.contracts import canonical_target_id


@dataclass(frozen=True, slots=True)
class ChannelDisclosureFact:
    id: str
    tenant_id: int
    name: str
    creator_user_id: int
    is_shared: bool
    update_time: datetime | None


class ChannelReferenceSourceRepository:
    async def aload_disclosure(self, session, source_keys) -> tuple[ChannelDisclosureFact, ...]:
        if not source_keys:
            return ()
        tenant = ChannelReferenceBindingRepository._tenant_id()
        if len(source_keys) > 200 or not session.in_transaction():
            raise ReferenceCoverageNotReadyError(reason="channel_disclosure_batch_or_transaction_invalid")
        ids = tuple(dict.fromkeys(key.source_id for key in source_keys))
        query = select(
            Channel.id, Channel.tenant_id, Channel.name, Channel.user_id, Channel.is_shared, Channel.update_time
        ).where(Channel.id.in_(ids))
        with session.no_autoflush, strict_tenant_filter():
            rows = {row.id: row for row in (await session.execute(query)).all()}
        result = []
        for key in source_keys:
            row = rows.get(key.source_id)
            if (
                row is None
                or row.tenant_id != tenant
                or row.tenant_id != key.tenant_id
                or type(row.name) is not str
                or type(row.user_id) is not int
                or row.user_id <= 0
                or type(row.is_shared) is not bool
            ):
                raise ReferenceCoverageNotReadyError(reason="channel_disclosure_metadata_incomplete")
            result.append(
                ChannelDisclosureFact(row.id, row.tenant_id, row.name, row.user_id, row.is_shared, row.update_time)
            )
        return tuple(result)

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

    async def aload_delivery_target(self, session, space_id: str, folder_id: str | None, user_id: int):
        """Current-read only targets the read runtime has already locked.

        Preserve the original SPACE creator/admin gate. Folder kind/parent
        is checked before article uploads, not after their MinIO side effects.
        """
        tenant_id = ChannelReferenceBindingRepository._tenant_id()
        space_id = int(canonical_target_id(space_id))
        folder_id = int(canonical_target_id(folder_id)) if folder_id is not None else None
        with session.no_autoflush, strict_tenant_filter():
            space = (
                await session.execute(
                    select(Knowledge.id, Knowledge.type, Knowledge.tenant_id)
                    .where(Knowledge.id == space_id)
                    .with_for_update()
                )
            ).one_or_none()
        if space is None or space.type != KnowledgeTypeEnum.SPACE.value or space.tenant_id != tenant_id:
            raise SpacePermissionDeniedError()
        # Membership has no tenant column: the exact globally unique SPACE
        # parent above is the isolation boundary, never a caller tenant hint.
        with session.no_autoflush:
            membership = (
                await session.exec(
                    select(SpaceChannelMember.id).where(
                        SpaceChannelMember.business_id == str(space_id),
                        SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                        SpaceChannelMember.user_id == user_id,
                        SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                        SpaceChannelMember.user_role.in_((UserRoleEnum.CREATOR, UserRoleEnum.ADMIN)),
                    )
                )
            ).first()
        if membership is None:
            raise SpacePermissionDeniedError()
        if folder_id is not None:
            with session.no_autoflush, strict_tenant_filter():
                folder = (
                    await session.execute(
                        select(
                            KnowledgeFile.id,
                            KnowledgeFile.knowledge_id,
                            KnowledgeFile.file_type,
                            KnowledgeFile.tenant_id,
                        )
                        .where(KnowledgeFile.id == folder_id)
                        .with_for_update()
                    )
                ).one_or_none()
            if (
                folder is None
                or folder.file_type != FileType.DIR.value
                or folder.knowledge_id != space_id
                or folder.tenant_id != tenant_id
            ):
                raise SpacePermissionDeniedError()
