"""Canonical assistant-reference and in-band session authorization."""

from bisheng.assistant.domain.repositories.assistant_boundary_repository import AssistantBoundaryRepository
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.permission.application.business_authorization import require_business_action


class AssistantBoundaryService:
    @classmethod
    async def authorize_knowledge_bindings(cls, user, knowledge_ids):
        ids = list(dict.fromkeys(knowledge_ids))
        if not ids:
            return
        tenant_id = get_current_tenant_id()
        if tenant_id is None or any(
            type(item) is not int or item <= 0 for item in ids
        ):  # exact type, bool must not pass as int
            raise NotFoundError.http_exception()
        rows = await AssistantBoundaryRepository.knowledge(ids)
        by_id = {row.id: row for row in rows}
        # Validate the entire set before any caller mutates the assistant/links.
        for item in ids:
            row = by_id.get(item)
            if row is None or row.type not in {0, 1, 2, 3} or not cls._visible_resource(row, tenant_id):
                raise NotFoundError.http_exception()
        for item in ids:
            row = by_id[item]
            await require_business_action(
                user,
                resource_type="knowledge_space" if row.type == 3 else "knowledge_library",
                resource_id=item,
                action="visible",
            )

    @classmethod
    async def authorize_flow_bindings(cls, user, flow_ids):
        ids = list(dict.fromkeys(flow_ids))
        if not ids:
            return
        tenant_id = get_current_tenant_id()
        if tenant_id is None or any(not isinstance(item, str) or not item for item in ids):
            raise NotFoundError.http_exception()
        by_id = {row.id: row for row in await AssistantBoundaryRepository.flows(ids)}
        for item in ids:
            row = by_id.get(item)
            if row is None or row.flow_type != 10 or row.is_delete or not cls._visible_resource(row, tenant_id):
                raise NotFoundError.http_exception()
        for item in ids:
            await require_business_action(user, resource_type="workflow", resource_id=item, action="visible")

    @classmethod
    async def flow_views(cls, user, flow_ids):
        """Assistant responses do not grant workflow design/secret read rights."""
        if not flow_ids:
            return []
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise NotFoundError.http_exception()
        views = []
        for row in await AssistantBoundaryRepository.flows(flow_ids):
            if row.flow_type != 10 or row.is_delete or not cls._visible_resource(row, tenant_id):
                continue
            try:
                await require_business_action(user, resource_type="workflow", resource_id=row.id, action="visible")
            except UnAuthorizedError:
                continue
            views.append(
                {
                    key: getattr(row, key)
                    for key in ("id", "name", "description", "logo", "status", "flow_type")
                    if hasattr(row, key)
                }
            )
        return views

    @staticmethod
    def _visible_resource(row, tenant_id):
        if row.tenant_id == tenant_id:
            return True
        visible = get_visible_tenant_ids() or frozenset({tenant_id})
        return row.tenant_id == 1 and row.tenant_id in visible and bool(getattr(row, "is_shared", False))

    @classmethod
    async def authorize_chat_target(cls, user, assistant_id, chat_id, subject, *, original_assistant_id):
        tenant_id = get_current_tenant_id()
        if tenant_id is None or not isinstance(assistant_id, str) or not assistant_id:
            raise NotFoundError.http_exception()
        if subject is not None:
            if subject.tenant_id != tenant_id:
                raise NotFoundError.http_exception()
            # A guest's configured operator may be a super admin; its identity is
            # not authority to switch away from the published app in this channel.
            if subject.subject_type == "public_v3" and (
                assistant_id != subject.resource_id or assistant_id != original_assistant_id
            ):
                raise NotFoundError.http_exception()
        assistant = await AssistantBoundaryRepository.assistant(assistant_id)
        if assistant is None or assistant.is_delete or not cls._visible_resource(assistant, tenant_id):
            raise NotFoundError.http_exception()
        await require_business_action(user, resource_type="assistant", resource_id=assistant_id, action="visible")
        if chat_id and assistant.status != 2:
            raise NotFoundError.http_exception()
        if not chat_id:
            return
        if not isinstance(chat_id, str):
            raise NotFoundError.http_exception()
        session = await AssistantBoundaryRepository.session(chat_id)
        if session is None:
            return
        subject = subject or SessionSubject.natural_person(tenant_id=tenant_id, user_id=user.user_id)
        if not subject.matches(session) or session.flow_id != assistant_id:
            raise NotFoundError.http_exception()
