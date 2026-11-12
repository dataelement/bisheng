"""Exact, read-only assistant facts in the admission caller's transaction."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession
from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareLink, ShareLinkStatusEnum


@dataclass(frozen=True, slots=True)
class AssistantSourceDisclosureRow:
    id: str
    tenant_id: int
    name: str
    status: int
    user_id: int
    is_delete: int
    update_time: datetime | None


class AssistantReferenceSourceRepository:
    async def ahas_legacy_name_retention(self, session, source_key, extractor_version):
        from bisheng.resource_reference.application.contracts import SourceKey, SourceType
        from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet

        tenant = _resolve_tenant_id()
        if (
            type(source_key) is not SourceKey
            or source_key.tenant_id != tenant
            or source_key.source_type != SourceType.ASSISTANT
            or source_key.source_version != "current"
            or is_tenant_filter_bypassed()
        ):
            raise ReferenceCoverageNotReadyError(reason="assistant_legacy_name_scope")
        model = BusinessReferenceSet
        query = select(model.extractor_version, model.ready, model.effective, model.source_revision).where(
            model.tenant_id == tenant,
            model.source_type == "assistant",
            model.source_id == source_key.source_id,
            model.source_version == "current",
            model.record_kind == "source",
        )
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(query)).one_or_none()
        return bool(
            row
            and row.extractor_version == extractor_version
            and row.ready
            and row.effective
            and row.source_revision > 0
        )

    """Column projections never attach an outside resource to the identity map."""

    @staticmethod
    def _context() -> None:
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0 or is_tenant_filter_bypassed():
            raise UnAuthorizedError()

    async def alist_disclosure_rows(
        self, session, *, assistant_ids: tuple[str, ...]
    ) -> tuple[AssistantSourceDisclosureRow, ...]:
        tenant = _resolve_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or is_tenant_filter_bypassed()
            or type(tenant) is not int
            or tenant <= 0
            or type(assistant_ids) is not tuple
            or len(assistant_ids) > 200
            or any(type(ident) is not str or not ident for ident in assistant_ids)
        ):
            raise ReferenceCoverageNotReadyError(reason="assistant_disclosure_scope")
        if not assistant_ids:
            return ()
        columns = ("id", "tenant_id", "name", "status", "user_id", "is_delete", "update_time")
        query = select(*(getattr(Assistant, name) for name in columns)).where(
            Assistant.tenant_id == tenant, Assistant.id.in_(tuple(dict.fromkeys(assistant_ids)))
        )
        with session.no_autoflush, strict_tenant_filter():
            rows = (await session.execute(query)).mappings().all()
        return tuple(AssistantSourceDisclosureRow(**row) for row in rows)

    async def _require_inspection(
        self, session: AsyncSession, token: str, assistant_id: str, *, for_update: bool
    ) -> None:
        query = select(
            ShareLink.tenant_id,
            ShareLink.status,
            ShareLink.resource_type,
            ShareLink.resource_id,
            ShareLink.create_user_id,
        ).where(ShareLink.share_token == token)
        if for_update:
            query = query.with_for_update()
        # The actual unguessable token is the existing view grant. Only its
        # exact row is discovered here; expiry semantics remain unchanged.
        with session.no_autoflush, bypass_tenant_filter():
            row = (await session.execute(query)).one_or_none()
        if row is None or row.status != ShareLinkStatusEnum.ACTIVE:
            raise UnAuthorizedError()
        if row.resource_type == ResourceTypeEnum.ASSISTANT:
            matched = str(row.resource_id) == assistant_id
        elif row.resource_type == ResourceTypeEnum.WORKBENCH_CHAT:
            conversation_query = select(
                MessageSession.tenant_id,
                MessageSession.flow_id,
                MessageSession.flow_type,
                MessageSession.is_delete,
                MessageSession.user_id,
            ).where(MessageSession.chat_id == row.resource_id)
            if for_update:
                conversation_query = conversation_query.with_for_update()
            # A token identifies this exact conversation. Its persisted parent
            # is the source binding; client-supplied meta_data is never proof.
            with session.no_autoflush, bypass_tenant_filter():
                conversation = (await session.execute(conversation_query)).one_or_none()
            matched = (
                conversation is not None
                and conversation.flow_id == assistant_id
                and conversation.flow_type == FlowType.ASSISTANT.value
                and not conversation.is_delete
                and conversation.tenant_id == row.tenant_id
                and str(conversation.user_id) == str(row.create_user_id)
            )
        else:
            matched = False
        if not matched or type(row.tenant_id) is not int or row.tenant_id <= 0:
            raise UnAuthorizedError()

    async def aload(
        self,
        session: AsyncSession,
        assistant_id: str,
        *,
        for_update: bool = False,
        inspect_token: str | None = None,
    ) -> tuple[dict, tuple[dict, ...]] | None:
        self._context()
        if inspect_token is not None:
            await self._require_inspection(session, inspect_token, assistant_id, for_update=for_update)
        root_query = select(*Assistant.__table__.columns).where(Assistant.id == assistant_id)
        if for_update:
            root_query = root_query.with_for_update()
        # Even a real token retains the original source candidate range.
        # It cannot discover an arbitrary outside business tenant/root.
        with session.no_autoflush:
            root = (await session.execute(root_query)).mappings().one_or_none()
        if root is None:
            return None
        link_query = (
            select(*AssistantLink.__table__.columns)
            .where(AssistantLink.assistant_id == assistant_id)
            .order_by(AssistantLink.id)
        )
        if for_update:
            link_query = link_query.with_for_update()
        with session.no_autoflush:
            links = (await session.execute(link_query)).mappings().all()
        if any(link["tenant_id"] != root["tenant_id"] for link in links):
            raise UnAuthorizedError()
        return deepcopy(dict(root)), tuple(deepcopy(dict(link)) for link in links)
