import json
import re
from datetime import datetime
from typing import Literal

from fastapi import HTTPException

from bisheng.chat_session.domain.models.answer_correction import AnswerCorrection, CorrectionState
from bisheng.chat_session.domain.repositories.answer_correction import AnswerCorrectionRepository
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.database.models.assistant import AssistantDao, AssistantLinkDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSessionDao, SensitiveStatus
from bisheng.database.models.tenant import UserTenantDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.permission.application.access import get_f048_resource_registry, get_f048_runtime
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.user.domain.models.user import UserDao
from bisheng.workflow.common.node import NodeType


def workflow_knowledge_ids(graph: dict) -> set[int]:
    result = set()
    for node in graph.get("nodes", []):
        data = node.get("data", {})
        params = {
            param["key"]: param.get("value")
            for group in (data.get("group_params") or [])
            for param in group.get("params", [])
            if "key" in param
        }
        node_type = data.get("type")
        if node_type == NodeType.QA_RETRIEVER.value:
            entries = params.get("qa_knowledge_id") or []
        elif node_type in (NodeType.KNOWLEDGE_RETRIEVER.value, NodeType.AGENT.value):
            key = "knowledge" if node_type == NodeType.KNOWLEDGE_RETRIEVER.value else "knowledge_id"
            selection = params.get(key) or {}
            if selection.get("type", "knowledge") not in ("knowledge", "space"):
                continue
            entries = selection.get("value") or []
        else:
            continue
        for entry in entries:
            raw_id = str(entry.get("key", "")) if isinstance(entry, dict) else ""
            if raw_id.isascii() and raw_id.isdecimal():
                result.add(int(raw_id))
    return result


def answer_text(answer: ChatMessage) -> str:
    body = answer.message or ""
    if answer.category in ("output_msg", "stream_msg"):
        try:
            payload = json.loads(body)
        except ValueError:
            payload = body
        if isinstance(payload, dict):
            body = payload.get("msg", "")
    if not isinstance(body, str):
        return ""
    return re.sub(r"<think>.*?</think>|:::web.*?:::", "", body, flags=re.DOTALL)


class AnswerCorrectionService:
    @staticmethod
    async def eligible_answer(answer_id: int, user: UserPayload) -> ChatMessage | None:
        tenant_id = get_current_tenant_id()
        if tenant_id is None or tenant_id != user.tenant_id:
            return None
        with strict_tenant_filter():
            answer = await ChatMessageDao.aget_message_by_id(answer_id)
            if (
                answer is None
                or answer.tenant_id != tenant_id
                or answer.user_id != user.user_id
                or not answer.chat_id
                or not answer.is_bot
                or answer.category not in ("answer", "output_msg", "stream_msg")
                or answer.sensitive_status != SensitiveStatus.PASS.value
            ):
                return None
            session = await MessageSessionDao.async_get_one(answer.chat_id)
            if (
                session is None or session.user_id != user.user_id
                or session.tenant_id != tenant_id or session.flow_id != answer.flow_id
            ):
                return None
            _, knowledge_ids = await AnswerCorrectionService.app_knowledge(answer.flow_id, tenant_id)
            for knowledge_id in knowledge_ids:
                if await AnswerCorrectionService.knowledge(knowledge_id, tenant_id) is not None:
                    return answer
            return None

    @staticmethod
    async def app_knowledge(app_id: str, tenant_id: int) -> tuple[str, set[int]]:
        with strict_tenant_filter():
            assistant = await AssistantDao.aget_one_assistant(app_id)
            if assistant is not None and assistant.tenant_id == tenant_id:
                links = await AssistantLinkDao.get_assistant_link(app_id)
                return "assistant", {link.knowledge_id for link in links if link.knowledge_id}
            workflow = await FlowDao.aget_flow_by_id(app_id)
            if (
                workflow is not None
                and workflow.tenant_id == tenant_id
                and workflow.flow_type == FlowType.WORKFLOW.value
            ):
                return "workflow", workflow_knowledge_ids(workflow.data or {})
        return "", set()

    @classmethod
    async def submit(
        cls, answer_id: int, quote: str, correction: str, evidence: str, user: UserPayload,
    ) -> AnswerCorrection:
        answer = await cls.eligible_answer(answer_id, user)
        if answer is None or quote not in answer_text(answer):
            raise NotFoundError.http_exception()
        return await AnswerCorrectionRepository.create(AnswerCorrection(
            tenant_id=user.tenant_id,
            app_id=answer.flow_id,
            answer_id=answer_id,
            submitter_id=user.user_id,
            quote=quote,
            correction=correction,
            evidence=evidence,
        ))

    @staticmethod
    async def can(actor: PermissionActor, resource: str, resource_id: str, action: str) -> bool:
        if not resource:
            return False
        registry = await get_f048_resource_registry()
        try:
            target = await registry.resolve(
                resource_type=resource, resource_id=resource_id, action=action, actor=actor,
            )
        except PermissionInvalidResourceError:
            return False
        return await (await get_f048_runtime()).check_action(actor, target, action)

    @staticmethod
    async def knowledge(knowledge_id: int, tenant_id: int):
        with strict_tenant_filter():
            knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if knowledge is None or knowledge.tenant_id != tenant_id:
            return None
        return knowledge

    @classmethod
    async def can_maintain(cls, user_id: int, knowledge_id: int, tenant_id: int) -> bool:
        membership = await UserTenantDao.aget_active_user_tenant(user_id)
        if membership is None or membership.tenant_id != tenant_id or membership.status != "active":
            return False
        user = await UserDao.aget_user(user_id)
        if user is None or user.delete:
            return False
        knowledge = await cls.knowledge(knowledge_id, tenant_id)
        if knowledge is None:
            return False
        resource = "knowledge_space" if knowledge.type == KnowledgeTypeEnum.SPACE.value else "knowledge_library"
        actor = PermissionActor(subject_id=user_id, tenant_id=tenant_id)
        return await cls.can(actor, resource, str(knowledge_id), "edit")

    @classmethod
    async def allows(cls, record: AnswerCorrection, view: str, user: UserPayload) -> bool:
        if record.tenant_id != get_current_tenant_id() or record.tenant_id != user.tenant_id:
            return False
        if view == "mine":
            return record.submitter_id == user.user_id
        if view == "assigned":
            return (
                record.assignee_id == user.user_id
                and record.knowledge_id is not None
                and await cls.can_maintain(user.user_id, record.knowledge_id, record.tenant_id)
            )
        resource, _ = await cls.app_knowledge(record.app_id, record.tenant_id)
        return await cls.can(await resolve_permission_actor(user), resource, record.app_id, "manage_permission")

    @classmethod
    async def detail(cls, record_id: int, view: str, user: UserPayload) -> AnswerCorrection:
        record = await AnswerCorrectionRepository.get(record_id)
        if record is None or not await cls.allows(record, view, user):
            raise NotFoundError.http_exception()
        return record

    @classmethod
    async def change(
        cls,
        record_id: int,
        operation: Literal["assignment", "result", "reply"],
        user: UserPayload,
        *,
        knowledge_id: int | None = None,
        assignee_id: int | None = None,
        text: str | None = None,
    ) -> AnswerCorrection:
        record = await cls.detail(record_id, "assigned" if operation == "result" else "owner", user)
        now = datetime.now()
        if operation == "assignment":
            _, linked_ids = await cls.app_knowledge(record.app_id, record.tenant_id)
            if (
                knowledge_id is None or knowledge_id not in linked_ids or assignee_id is None
                or not await cls.can_maintain(assignee_id, knowledge_id, record.tenant_id)
            ):
                raise UnAuthorizedError.http_exception()
            expected, target = CorrectionState.PENDING_ASSIGNMENT, CorrectionState.PENDING_PROCESSING
            fields = {"knowledge_id": knowledge_id, "assignee_id": assignee_id, "assigned_by": user.user_id, "assigned_at": now}
        elif operation == "result":
            expected, target = CorrectionState.PENDING_PROCESSING, CorrectionState.PENDING_REPLY
            fields = {"result": text, "processed_by": user.user_id, "processed_at": now}
        else:
            expected, target = CorrectionState.PENDING_REPLY, CorrectionState.REPLIED
            fields = {"reply": text, "replied_by": user.user_id, "replied_at": now}
        if not await AnswerCorrectionRepository.transition(record, expected, target, **fields):
            raise HTTPException(409, "Feedback state has changed")
        updated = await AnswerCorrectionRepository.get(record_id)
        if updated is None:
            raise NotFoundError.http_exception()
        return updated

    @classmethod
    async def list_feedback(cls, view: str, user: UserPayload, page: int, page_size: int):
        if get_current_tenant_id() != user.tenant_id:
            return [], 0
        repository = AnswerCorrectionRepository
        if view == "mine":
            return await repository.list_for_actor(page=page, page_size=page_size, submitter_id=user.user_id)
        records = await repository.review_candidates(user.user_id if view == "assigned" else None)
        decisions = {}
        allowed = []
        for record in records:
            scope = record.app_id if view == "owner" else record.knowledge_id
            if scope not in decisions:
                decisions[scope] = await cls.allows(record, view, user)
            if decisions[scope]:
                allowed.append(record)
        start = (page - 1) * page_size
        return allowed[start:start + page_size], len(allowed)

    @classmethod
    async def knowledge_options(cls, record_id: int, user: UserPayload) -> list[dict]:
        record = await cls.detail(record_id, "owner", user)
        _, linked_ids = await cls.app_knowledge(record.app_id, record.tenant_id)
        options = []
        for knowledge_id in sorted(linked_ids):
            knowledge = await cls.knowledge(knowledge_id, record.tenant_id)
            if knowledge is not None:
                options.append({"id": knowledge_id, "name": knowledge.name})
        return options

    @classmethod
    async def assignee_options(
        cls, record_id: int, knowledge_id: int, user: UserPayload, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        record = await cls.detail(record_id, "owner", user)
        _, linked_ids = await cls.app_knowledge(record.app_id, record.tenant_id)
        if knowledge_id not in linked_ids:
            raise NotFoundError.http_exception()
        options = []
        batch_page = 1
        batch_size = 100
        while True:
            users, total = await UserTenantDao.aget_tenant_users(record.tenant_id, batch_page, batch_size)
            for candidate in users:
                if await cls.can_maintain(candidate["user_id"], knowledge_id, record.tenant_id):
                    options.append({"id": candidate["user_id"], "name": candidate["user_name"]})
            if batch_page * batch_size >= total:
                break
            batch_page += 1
        start = (page - 1) * page_size
        return options[start:start + page_size], len(options)
