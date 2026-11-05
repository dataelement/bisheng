"""Exact, read-only assistant facts in the admission caller's transaction."""

from copy import deepcopy

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareLink, ShareLinkStatusEnum


class AssistantReferenceSourceRepository:
    """Column projections never attach an outside resource to the identity map."""

    @staticmethod
    def _context() -> None:
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0 or is_tenant_filter_bypassed():
            raise UnAuthorizedError()

    async def _inspection_tenant(
        self, session: AsyncSession, token: str, assistant_id: str, *, for_update: bool
    ) -> int:
        query = select(
            ShareLink.tenant_id, ShareLink.status, ShareLink.resource_type, ShareLink.resource_id, ShareLink.meta_data
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
            matched = isinstance(row.meta_data, dict) and str(row.meta_data.get("flowId") or "") == assistant_id
        else:
            matched = False
        if not matched or type(row.tenant_id) is not int or row.tenant_id <= 0:
            raise UnAuthorizedError()
        return row.tenant_id

    async def aload(
        self,
        session: AsyncSession,
        assistant_id: str,
        *,
        for_update: bool = False,
        inspect_token: str | None = None,
    ) -> tuple[dict, tuple[dict, ...]] | None:
        self._context()
        inspection_tenant = (
            await self._inspection_tenant(session, inspect_token, assistant_id, for_update=for_update)
            if inspect_token is not None
            else None
        )
        root_query = select(*Assistant.__table__.columns).where(Assistant.id == assistant_id)
        if for_update:
            root_query = root_query.with_for_update()
        if inspection_tenant is not None:
            # A verified exact token grants inspection of this one owning
            # tenant/root, never a tenant-wide scan or a write capability.
            root_query = root_query.where(Assistant.tenant_id == inspection_tenant)
            with session.no_autoflush, bypass_tenant_filter():
                root = (await session.execute(root_query)).mappings().one_or_none()
        else:
            # Normal reads retain the production SELECT tenant listener. A
            # visible Root row still needs the Owner's real F048 decision.
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
        if inspection_tenant is not None:
            link_query = link_query.where(AssistantLink.tenant_id == inspection_tenant)
            with session.no_autoflush, bypass_tenant_filter():
                links = (await session.execute(link_query)).mappings().all()
        else:
            with session.no_autoflush:
                links = (await session.execute(link_query)).mappings().all()
        if any(link["tenant_id"] != root["tenant_id"] for link in links):
            raise UnAuthorizedError()
        return deepcopy(dict(root)), tuple(deepcopy(dict(link)) for link in links)
