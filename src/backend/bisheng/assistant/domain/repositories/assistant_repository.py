"""Assistant writes in the business/reference use case's external transaction."""

from collections.abc import Iterable

from sqlalchemy import delete, inspect
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum


class AssistantRepository:
    """No session factory or commit: bindings and business rows commit together."""

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = _resolve_tenant_id()
        if is_tenant_filter_bypassed() or type(tenant_id) is not int or tenant_id <= 0:
            raise AssistantNotExistsError()
        return tenant_id

    async def aget(self, session: AsyncSession, assistant_id: str, *, for_update: bool = False) -> Assistant | None:
        tenant_id = self._tenant_id()
        query = select(Assistant).where(Assistant.id == assistant_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = (await session.exec(query)).one_or_none()
        return row if row is not None and row.tenant_id == tenant_id else None

    async def alist_links(self, session: AsyncSession, assistant_id: str) -> tuple[AssistantLink, ...]:
        if await self.aget(session, assistant_id) is None:
            raise AssistantNotExistsError()
        with strict_tenant_filter():
            rows = await session.exec(
                select(AssistantLink).where(AssistantLink.assistant_id == assistant_id).order_by(AssistantLink.id)
            )
        return tuple(row for row in rows if row.tenant_id == self._tenant_id())

    async def alock_knowledge_kinds(self, session: AsyncSession, knowledge_ids: Iterable[int]) -> dict[int, int]:
        """Read types of new IDs whose target locks the reference runtime holds.

        A container reference uses a common target type for documents, QA and
        spaces. Permission resource types must instead follow the real row.
        Column projections avoid identity-map values from an earlier snapshot.
        """
        tenant_id = self._tenant_id()
        ids = self._numeric_ids(knowledge_ids) or ()
        if not ids:
            return {}
        with strict_tenant_filter():
            result = await session.exec(
                select(Knowledge.id, Knowledge.type, Knowledge.tenant_id)
                .where(Knowledge.id.in_(ids))
                .order_by(Knowledge.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        rows = result.all()
        supported = {KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value, KnowledgeTypeEnum.SPACE.value}
        if {row.id for row in rows} != set(ids) or any(
            row.tenant_id != tenant_id or row.type not in supported for row in rows
        ):
            raise ResourceReferenceInvalidError(reason="reference_target_invalid")
        return {row.id: row.type for row in rows}

    async def ainsert(self, session: AsyncSession, assistant: Assistant) -> Assistant:
        tenant_id = self._tenant_id()
        if assistant.tenant_id not in (None, tenant_id) or inspect(assistant).persistent:
            raise AssistantNotExistsError()
        assistant.tenant_id = tenant_id
        session.add(assistant)
        await session.flush()
        return assistant

    def _assert_bound(self, session: AsyncSession, assistant: Assistant) -> None:
        state = inspect(assistant)
        if (
            assistant.tenant_id != self._tenant_id()
            or not state.persistent
            or state.session is not session.sync_session
            or state.attrs.tenant_id.history.has_changes()
            or state.attrs.id.history.has_changes()
        ):
            raise AssistantNotExistsError()

    async def asave(self, session: AsyncSession, assistant: Assistant) -> Assistant:
        self._assert_bound(session, assistant)
        await session.flush()
        return assistant

    async def asoft_delete(self, session: AsyncSession, assistant: Assistant) -> None:
        self._assert_bound(session, assistant)
        assistant.is_delete = 1
        await session.flush()

    @staticmethod
    def _numeric_ids(values: Iterable[int] | None) -> tuple[int, ...] | None:
        if values is None:
            return None
        result = set()
        for value in values:
            if type(value) is not int or value < 0:
                raise ValueError("assistant link IDs must be non-negative integers")
            if value:
                result.add(value)
        return tuple(sorted(result))

    @staticmethod
    def _flow_ids(values: Iterable[str] | None) -> tuple[str, ...] | None:
        if values is None:
            return None
        result = set()
        for value in values:
            if not isinstance(value, str):
                raise TypeError("assistant flow IDs must be strings")
            if value:
                result.add(value)
        return tuple(sorted(result))

    async def areplace_links(
        self,
        session: AsyncSession,
        assistant_id: str,
        *,
        tool_ids: Iterable[int] | None = None,
        flow_ids: Iterable[str] | None = None,
        knowledge_ids: Iterable[int] | None = None,
    ) -> None:
        """None retains a category; an empty sequence explicitly clears it."""
        tools = self._numeric_ids(tool_ids)
        flows = self._flow_ids(flow_ids)
        knowledge = self._numeric_ids(knowledge_ids)
        tenant_id = self._tenant_id()
        if await self.aget(session, assistant_id, for_update=True) is None:
            raise AssistantNotExistsError()
        categories = (
            (tools, AssistantLink.tool_id != 0, "tool_id"),
            (flows, (AssistantLink.flow_id != "") & (AssistantLink.knowledge_id == 0), "flow_id"),
            (knowledge, AssistantLink.knowledge_id != 0, "knowledge_id"),
        )
        for values, predicate, attribute in categories:
            if values is None:
                continue
            # Bulk deletes do not receive the automatic SELECT tenant filter.
            await session.execute(
                delete(AssistantLink)
                .where(
                    AssistantLink.tenant_id == tenant_id,
                    AssistantLink.assistant_id == assistant_id,
                    predicate,
                )
                .execution_options(synchronize_session=False)
            )
            session.add_all(
                [
                    AssistantLink(assistant_id=assistant_id, tenant_id=tenant_id, **{attribute: value})
                    for value in values
                ]
            )
        await session.flush()
