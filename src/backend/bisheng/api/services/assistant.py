from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Union

from fastapi import Request
from loguru import logger

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq, StreamData
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import (
    AssistantInitError,
    AssistantNameRepeatError,
    AssistantNotEditError,
    AssistantNotExistsError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.schemas.telemetry.event_data_schema import NewApplicationEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.cache import InMemoryCache
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import Assistant, AssistantDao, AssistantLinkDao, AssistantStatus
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.llm.domain.services import LLMService
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    check_business_action,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import get_request_ip

from .f048_application_permission import ApplicationPermissionRecord

if TYPE_CHECKING:
    from bisheng.common.schemas.api import PageInfiniteCursorData

# F040/F027: keyset scan batch size for the assistant cursor list. A batch
# shrunk by fine-grained ReBAC filtering is refilled from the next keyset
# window, so this only bounds per-round DB/FGA fan-out, not the page size.
_ASSISTANT_PERMISSION_SCAN_BATCH_SIZE = 200
_AUTO_FLOW_PERMISSION_SCAN_BATCH_SIZE = 100


class AssistantResourceAuthorizationPort:
    """Bind the shared application adapter to assistant resources."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor,
        action: str,
    ):
        return await self._adapter.resolve_permission_target(
            resource_type="assistant",
            resource_id=resource_id,
            actor=actor,
            action=action,
        )


class AssistantService(BaseService, AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    async def get_assistant(
        cls,
        user: UserPayload,
        name: str | None = None,
        status: int | None = None,
        tag_id: int | None = None,
        page: int = 1,
        limit: int = 20,
        action: str = "use",
    ) -> (list[AssistantSimpleInfo], int):
        """
        Get list of assistants
        """
        assistant_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.ASSISTANT)
            assistant_ids = [one.resource_id for one in ret]
            if not assistant_ids:
                return [], 0

        data = []
        res, _ = AssistantDao.get_all_assistants(
            name,
            0,
            0,
            assistant_ids,
            status,
        )
        permission_map = await batch_check_business_actions(
            user,
            resource_type="assistant",
            resource_ids=(one.id for one in res),
            actions=(action, "edit"),
        )
        res = [one for one in res if action in permission_map.get(str(one.id), frozenset())]
        total = len(res)
        start_index = (page - 1) * limit
        end_index = start_index + limit
        res = res[start_index:end_index]
        editable_ids = {resource_id for resource_id, actions in permission_map.items() if "edit" in actions}

        assistant_ids = [one.id for one in res]

        # Get assistant-associatedtag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.ASSISTANT, assistant_ids)

        # F008: removed group_ids (AC-08)
        for one in res:
            one.logo = cls.get_logo_share_link(one.logo)
            simple_assistant = cls.return_simple_assistant_info(one)
            simple_assistant.write = str(one.id) in editable_ids
            simple_assistant.tags = flow_tags.get(one.id, [])
            data.append(simple_assistant)
        return data, total

    @classmethod
    async def _scan_visible_assistants_cursor(
        cls,
        *,
        user: UserPayload,
        name: str | None,
        status: int | None,
        assistant_ids: list[str] | None,
        cursor: Sequence | None,
        page_size: int,
        action: str,
    ) -> tuple[list[Assistant], bool, set[str]]:
        """F040/F027 cursor-paginated scan mirroring ``_scan_visible_flows_cursor``:
        keep fetching DB batches via keyset, apply the SAME ReBAC fine-grained
        filter through concrete F048 actions, accumulate
        until ``page_size + 1`` visible rows (the +1 probes ``has_more``) or the
        DB is exhausted.

        Returns ``(visible[:page_size], has_more, editable_ids)`` where
        ``editable_ids`` (``edit`` grants) drives the ``write`` flag. Advancing
        the batch cursor on the LAST DB row (not last visible) keeps rows
        filtered out between keyset windows from being re-emitted.
        """
        visible: list[Assistant] = []
        editable_ids: set[str] = set()
        batch_cursor: list | None = list(cursor) if cursor else None

        while True:
            batch, db_has_more = await AssistantDao.aget_all_assistants_cursor(
                name,
                status,
                assistant_ids,
                batch_cursor,
                _ASSISTANT_PERMISSION_SCAN_BATCH_SIZE,
            )
            if not batch:
                return visible[:page_size], False, editable_ids

            permission_map = await batch_check_business_actions(
                user,
                resource_type="assistant",
                resource_ids=(one.id for one in batch),
                actions=(action, "edit"),
            )
            kept = [one for one in batch if action in permission_map.get(str(one.id), frozenset())]
            editable_ids |= {
                resource_id for resource_id, action_codes in permission_map.items() if "edit" in action_codes
            }

            for item in kept:
                visible.append(item)
                if len(visible) > page_size:
                    # Got the +1 probe — done scanning.
                    return visible[:page_size], True, editable_ids

            if not db_has_more:
                return visible[:page_size], False, editable_ids

            last_db = batch[-1]
            batch_cursor = [last_db.update_time, last_db.id]

    @classmethod
    async def aget_assistant_envelope(
        cls,
        user: UserPayload,
        name: str | None = None,
        status: int | None = None,
        tag_id: int | None = None,
        cursor: str | None = None,
        page_size: int = 10,
        action: str = "use",
    ) -> "PageInfiniteCursorData":
        """F040/F027 cursor envelope for ``GET /api/v1/assistant``.

        Replaces the fetch-all → ReBAC-filter → Python-slice anti-pattern of
        ``get_assistant``: decodes the cursor, runs the keyset scan loop (so a
        batch shrunk by fine-grained filtering is refilled from the next
        window), enriches the page (logo / tags / ``write``), and wraps it in
        ``PageInfiniteCursorData`` with ``next_cursor`` from the last visible
        row's ``(update_time, id)``. ``total`` is intentionally dropped (INV-6).
        """
        from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
        from bisheng.common.errcode.flow import AppInvalidCursorError
        from bisheng.common.schemas.api import PageInfiniteCursorData

        context = f"assistant|sort=update_time|action={action}"
        try:
            decoded = decode_cursor(cursor, expected_key_len=2, expected_context=context)
        except CursorDecodeError as exc:
            raise AppInvalidCursorError(exception=exc)

        # Tag prefilter: an empty match short-circuits to an empty page (mirrors
        # the legacy `return [], 0`).
        assistant_ids: list[str] | None = None
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.ASSISTANT)
            assistant_ids = [one.resource_id for one in ret]
            if not assistant_ids:
                return PageInfiniteCursorData(
                    data=[],
                    page_size=page_size,
                    has_more=False,
                    next_cursor=None,
                )

        rows, has_more, editable_ids = await cls._scan_visible_assistants_cursor(
            user=user,
            name=name,
            status=status,
            assistant_ids=assistant_ids,
            cursor=decoded,
            page_size=page_size,
            action=action,
        )

        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.ASSISTANT, [one.id for one in rows])
        data: list[AssistantSimpleInfo] = []
        for one in rows:
            one.logo = cls.get_logo_share_link(one.logo)
            simple_assistant = cls.return_simple_assistant_info(one)
            simple_assistant.write = str(one.id) in editable_ids
            simple_assistant.tags = flow_tags.get(one.id, [])
            data.append(simple_assistant)

        next_cursor: str | None = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor((last.update_time, last.id), context=context)
        return PageInfiniteCursorData(
            data=data,
            page_size=page_size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    @classmethod
    def return_simple_assistant_info(cls, one: Assistant) -> AssistantSimpleInfo:
        """
        Put the database's assistantmodelSimplified After processing, it returns to the front-end format
        """
        simple_dict = one.model_dump(
            include={"id", "name", "desc", "logo", "status", "user_id", "create_time", "update_time"}
        )
        simple_dict["user_name"] = cls.get_user_name(one.user_id)
        return AssistantSimpleInfo(**simple_dict)

    @classmethod
    async def get_assistant_info(
        cls, assistant_id: str, login_user: UserPayload, share_link: Union["ShareLink", None] = None
    ) -> AssistantInfo:
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        if not assistant or assistant.is_delete:
            raise AssistantNotExistsError()
        # A valid share-token grants view access to any logged-in recipient
        # who lacks a direct app permission grant. Assistant chat shares
        # generated by ShareChat.tsx store the conversation id in resource_id
        # and the actual assistant id under meta_data.flowId; direct
        # assistant shares store the assistant id in resource_id. Try
        # meta_data.flowId first, then fall back to resource_id so both
        # shapes work.
        has_share_grant = False
        if share_link is not None:
            meta_data = share_link.meta_data or {}
            share_assistant_id = str(meta_data.get("flowId") or share_link.resource_id or "")
            has_share_grant = share_assistant_id == str(assistant_id)
        # Check if you have permission to access the information
        if not has_share_grant and not await check_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant.id,
            action="visible",
        ):
            raise UnAuthorizedError()

        tool_list = []
        flow_list = []
        knowledge_list = []

        links = await AssistantLinkDao.get_assistant_link(assistant_id)
        for one in links:
            if one.tool_id:
                tool_list.append(one.tool_id)
            elif one.knowledge_id:
                knowledge_list.append(one.knowledge_id)
            elif one.flow_id:
                flow_list.append(one.flow_id)
            else:
                logger.error(f"not expect link info: {one.model_dump()}")
        tool_list, flow_list, knowledge_list = cls.get_link_info(tool_list, flow_list, knowledge_list)
        assistant.logo = await cls.get_logo_share_link_async(assistant.logo)
        can_share = await check_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant_id,
            action="share",
        )
        return AssistantInfo(
            **assistant.model_dump(),
            tool_list=tool_list,
            flow_list=flow_list,
            knowledge_list=knowledge_list,
            can_share=can_share,
        )

    @classmethod
    async def get_one_assistant(cls, assistant_id: str) -> Assistant | None:
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        return assistant

    # Create Assistant
    @classmethod
    async def create_assistant(
        cls,
        request: Request,
        login_user: UserPayload,
        assistant: Assistant,
    ) -> AssistantInfo:
        # Check if there are any duplicate names under
        if cls.judge_name_repeat(assistant.name, assistant.user_id):
            raise AssistantNameRepeatError()

        logger.info(f"assistant original prompt id: {assistant.id}, desc: {assistant.prompt}")

        # Automatically replenish default model configurations
        assistant_llm = await LLMService.get_assistant_llm()
        if assistant_llm.llm_list:
            for one in assistant_llm.llm_list:
                if one.default:
                    assistant.model_name = str(one.model_id)
                    break

        # Autogenerate Descriptions
        assistant, _, _ = await cls.get_auto_info(assistant, login_user)
        assistant = AssistantDao.create_assistant(assistant)

        # RecordTelemetryJournal
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_APPLICATION,
            trace_id=trace_id_var.get(),
            event_data=NewApplicationEventData(
                app_id=assistant.id, app_name=assistant.name, app_type=ApplicationTypeEnum.ASSISTANT
            ),
        )

        await cls.create_assistant_hook_async(request, assistant, login_user)

        can_share = await check_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant.id,
            action="share",
        )
        return AssistantInfo(
            **assistant.model_dump(), tool_list=[], flow_list=[], knowledge_list=[], can_share=can_share
        )

    @classmethod
    async def create_assistant_hook_async(
        cls, request: Request, assistant: Assistant, user_payload: UserPayload
    ) -> bool:
        """
        Async variant for async FastAPI handlers; avoids sync-to-async bridge usage
        on the running event loop.
        """
        record = cls._new_permission_record(assistant)
        adapter = await get_f048_resource_adapter("assistant")
        await adapter.authorize_created(
            record=record,
            actor=await resolve_permission_actor(user_payload),
        )

        AuditLogService.create_build_assistant(user_payload, get_request_ip(request), assistant.id)
        cls.get_logo_share_link(assistant.logo)
        return True

    # Delete Assistant
    @classmethod
    async def delete_assistant(
        cls,
        request: Request,
        login_user: UserPayload,
        assistant_id: str,
    ) -> bool:
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        await require_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant.id,
            action="delete",
        )
        adapter = await get_f048_resource_adapter("assistant")
        record = await adapter.load_permission_record(
            resource_type="assistant",
            resource_id=str(assistant.id),
        )
        if record is None:
            raise AssistantNotExistsError()
        await adapter.project_delete(
            record=record,
            actor=await resolve_permission_actor(login_user),
        )

        AssistantDao.delete_assistant(assistant)
        telemetry_service.log_event_sync(
            user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.DELETE_APPLICATION, trace_id=trace_id_var.get()
        )
        cls.delete_assistant_hook(request, login_user, assistant)
        return True

    @classmethod
    def delete_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """Clean up associated assistant resources"""
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")
        # Write Audit Log
        AuditLogService.delete_build_assistant(login_user, get_request_ip(request), assistant.id)

        # Update session information
        MessageSessionDao.update_session_info_by_flow(
            assistant.name, assistant.desc, assistant.logo, assistant.id, FlowType.ASSISTANT.value
        )
        return True

    @classmethod
    async def auto_update_stream(cls, assistant_id: str, prompt: str, login_user: UserPayload):
        """Regenerate Assistant Prompts and Tool Selection, Only call the model capability without modifying the database data"""
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()
        await cls.check_update_permission_async(assistant, login_user)
        assistant.prompt = prompt

        # Inisialisasillm
        auto_agent = AssistantAgent(assistant, "", login_user.user_id)
        await auto_agent.init_auto_update_llm()

        # Streaming Generation Prompts
        final_prompt = ""
        async for one_prompt in auto_agent.optimize_assistant_prompt():
            if one_prompt.content in ("```", "markdown"):
                continue
            yield str(StreamData(event="message", data={"type": "prompt", "message": one_prompt.content}))
            final_prompt += one_prompt.content
        # Append the citation rules block so the generated (user-visible, editable) prompt
        # carries them; the runtime backstop then detects them and won't duplicate.

        assistant.prompt = final_prompt
        yield str(StreamData(event="message", data={"type": "end", "message": ""}))

        # Generate opening remarks and opening questions
        guide_info = auto_agent.generate_guide(assistant.prompt)
        yield str(StreamData(event="message", data={"type": "guide_word", "message": guide_info["opening_lines"]}))
        yield str(StreamData(event="message", data={"type": "end", "message": ""}))
        yield str(StreamData(event="message", data={"type": "guide_question", "message": guide_info["questions"]}))
        yield str(StreamData(event="message", data={"type": "end", "message": ""}))

        # Automatic selection of tools and skills
        tool_info = cls.get_auto_tool_info(assistant, auto_agent)
        tool_info = [one.model_dump() for one in tool_info]
        yield str(StreamData(event="message", data={"type": "tool_list", "message": tool_info}))
        yield str(StreamData(event="message", data={"type": "end", "message": ""}))

        flow_info = await cls.get_auto_flow_info(
            assistant,
            auto_agent,
            login_user,
        )
        flow_info = [one.model_dump() for one in flow_info]
        yield str(StreamData(event="message", data={"type": "flow_list", "message": flow_info}))

    @classmethod
    async def update_assistant(
        cls, request: Request, login_user: UserPayload, req: AssistantUpdateReq
    ) -> AssistantInfo:
        """Update Assistant Information"""
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            raise AssistantNotExistsError()

        await cls.check_update_permission_async(assistant, login_user)

        # Update Assistant Data
        if req.name and req.name != assistant.name:
            # Check if there are any duplicate names under
            if cls.judge_name_repeat(req.name, assistant.user_id):
                raise AssistantNameRepeatError()
            assistant.name = req.name
        assistant.desc = req.desc
        assistant.logo = req.logo if req.logo else assistant.logo
        assistant.prompt = req.prompt
        assistant.guide_word = req.guide_word
        assistant.guide_question = req.guide_question
        assistant.model_name = req.model_name
        assistant.temperature = req.temperature
        assistant.update_time = datetime.now()
        assistant.max_token = req.max_token
        # F041: persist the 用户知识库权限校验 toggle (None = untouched, keep current value)
        if req.knowledge_auth is not None:
            assistant.knowledge_auth = req.knowledge_auth
        AssistantDao.update_assistant(assistant)
        await telemetry_service.log_event(
            user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )

        # Update assistant association information
        if req.tool_list is not None:
            AssistantLinkDao.update_assistant_tool(assistant.id, tool_list=req.tool_list)
        if req.flow_list is not None:
            AssistantLinkDao.update_assistant_flow(assistant.id, flow_list=req.flow_list)
        if req.knowledge_list is not None:
            # Using Configuredflow Perform skill replenishment
            AssistantLinkDao.update_assistant_knowledge(assistant.id, knowledge_list=req.knowledge_list, flow_id="")
        tool_list, flow_list, knowledge_list = cls.get_link_info(req.tool_list, req.flow_list, req.knowledge_list)
        cls.update_assistant_hook(request, login_user, assistant)
        can_share = await check_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant.id,
            action="share",
        )
        return AssistantInfo(
            **assistant.model_dump(),
            tool_list=tool_list,
            flow_list=flow_list,
            knowledge_list=knowledge_list,
            can_share=can_share,
        )

    @classmethod
    def update_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """Update Assistant's Hook"""
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")

        # Write Audit Log
        AuditLogService.update_build_assistant(login_user, get_request_ip(request), assistant.id)

        # Write cache
        cls.get_logo_share_link(assistant.logo)
        return True

    @classmethod
    async def update_status(cls, request: Request, login_user: UserPayload, assistant_id: str, status: int) -> bool:
        """Update Assistant Status"""
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()
        required_action = "publish" if status == AssistantStatus.ONLINE.value else "unpublish"
        await require_business_action(
            login_user,
            resource_type="assistant",
            resource_id=assistant.id,
            action=required_action,
        )
        # Equal status without modification
        if assistant.status == status:
            return True

        # Try to initializeagent, go online if initialization is successful, otherwise not go online
        if status == AssistantStatus.ONLINE.value:
            tmp_agent = AssistantAgent(assistant, "", login_user.user_id)
            try:
                await tmp_agent.init_assistant()
            except Exception as e:
                logger.exception("online agent init failed")
                raise AssistantInitError(exception=e, msg=f"Assistant onboarding failed: {e}") from e
        assistant.status = status
        AssistantDao.update_assistant(assistant)
        await telemetry_service.log_event(
            user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        cls.update_assistant_hook(request, login_user, assistant)
        return True

    @classmethod
    async def update_prompt(cls, assistant_id: str, prompt: str, user_payload: UserPayload) -> bool:
        """Update assistant prompts"""
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        await cls.check_update_permission_async(assistant, user_payload)

        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        await telemetry_service.log_event(
            user_id=user_payload.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        return True

    @classmethod
    async def update_flow_list(cls, assistant_id: str, flow_list: list[str], user_payload: UserPayload) -> bool:
        """Update Assistant Skills List"""
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        await cls.check_update_permission_async(assistant, user_payload)

        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return True

    @classmethod
    async def update_tool_list(cls, assistant_id: str, tool_list: list[int], user_payload: UserPayload) -> bool:
        """Update Assistant Tool List"""
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        await cls.check_update_permission_async(assistant, user_payload)

        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return True

    @classmethod
    async def check_update_permission_async(cls, assistant: Assistant, user_payload: UserPayload) -> Any:
        await require_business_action(
            user_payload,
            resource_type="assistant",
            resource_id=assistant.id,
            action="edit",
        )

        if assistant.status == AssistantStatus.ONLINE.value:
            raise AssistantNotEditError()
        return None

    @staticmethod
    def _new_permission_record(
        assistant: Assistant,
    ) -> ApplicationPermissionRecord:
        context_version = sha256(
            (f"assistant|{assistant.id}|{assistant.tenant_id}|{assistant.user_id}|{assistant.status}").encode()
        ).hexdigest()
        return ApplicationPermissionRecord(
            tenant_id=int(assistant.tenant_id or 0),
            resource_type="assistant",
            resource_id=str(assistant.id),
            status=AssistantStatus(assistant.status).name,
            owner_user_id=int(assistant.user_id or 0),
            permission_version=0,
            context_version=context_version,
        )

    @classmethod
    def get_link_info(
        cls,
        tool_list: list[int],
        flow_list: list[str],
        knowledge_list: list[int] | None = None,
    ):
        tool_list = GptsToolsDao.get_list_by_ids(tool_list) if tool_list else []
        flow_list = FlowDao.get_flow_by_ids(flow_list) if flow_list else []
        knowledge_list = KnowledgeDao.get_list_by_ids(knowledge_list) if knowledge_list else []
        return tool_list, flow_list, knowledge_list

    @classmethod
    def get_user_name(cls, user_id: int):
        if not user_id:
            return "system"
        user = cls.UserCache.get(user_id)
        if user:
            return user.user_name
        user = UserDao.get_user(user_id)
        if not user:
            return f"{user_id}"
        cls.UserCache.set(user_id, user)
        return user.user_name

    @classmethod
    def judge_name_repeat(cls, name: str, user_id: int) -> bool:
        """Determine if the assistant name is a duplicate"""
        assistant = AssistantDao.get_assistant_by_name_user_id(name, user_id)
        if assistant:
            return True
        return False

    @classmethod
    async def get_auto_info(cls, assistant: Assistant, login_user: UserPayload) -> (Assistant, list[int], list[int]):
        """
        Auto Generate Assistant'sprompt, Automatically select tools and skills
        return: Assistant Information, ToolsIDList, SkillsIDVertical
        """
        # Inisialisasiagent
        auto_agent = AssistantAgent(assistant, "", login_user.user_id)
        await auto_agent.init_auto_update_llm()

        # Autogenerate Descriptions
        assistant.desc = auto_agent.generate_description(assistant.prompt)

        return assistant, [], []

    @classmethod
    def get_auto_tool_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> list[GptsTools]:
        # Pagination Auto-Select Tool
        res = []
        page = 1
        page_num = 50
        while True:
            all_tool = GptsToolsDao.get_list_by_user(assistant.user_id, page, page_num)
            if len(all_tool) == 0:
                break
            logger.info(f"auto select tools: page: {page}, number: {len(all_tool)}")
            tool_list = []
            all_tool_dict = {}
            for one in all_tool:
                all_tool_dict[one.name] = one
                tool_list.append(
                    {
                        "name": one.name,
                        "description": one.desc if one.desc else "",
                    }
                )
            tool_info = []
            tool_list = auto_agent.choose_tools(tool_list, assistant.prompt)
            for one in tool_list:
                if all_tool_dict.get(one):
                    tool_info.append(all_tool_dict[one])
            res += tool_info
            page += 1
        return res

    @classmethod
    async def get_auto_flow_info(
        cls,
        assistant: Assistant,
        auto_agent: AssistantAgent,
        login_user: UserPayload,
    ) -> list[Flow]:
        """Select at most 50 online workflows from business candidates.

        The business Service owns candidate/status pagination; F048 only
        evaluates the concrete ``visible`` action for each bounded batch.
        """

        visible_ids: list[str] = []
        candidate_cursor: list | None = None
        while len(visible_ids) < 50:
            candidates, has_more = await FlowDao.aget_all_apps(
                status=FlowStatus.ONLINE.value,
                flow_type=FlowType.WORKFLOW.value,
                limit=_AUTO_FLOW_PERMISSION_SCAN_BATCH_SIZE,
                cursor=candidate_cursor,
            )
            if not candidates:
                break
            action_map = await batch_check_business_actions(
                login_user,
                resource_type="workflow",
                resource_ids=[str(row["id"]) for row in candidates],
                actions=("visible",),
            )
            visible_ids.extend(
                str(row["id"]) for row in candidates if "visible" in action_map.get(str(row["id"]), frozenset())
            )
            if len(visible_ids) >= 50 or not has_more:
                break
            last = candidates[-1]
            candidate_cursor = [last["update_time"], last["id"]]

        ordered_ids = visible_ids[:50]
        flow_by_id = {str(flow.id): flow for flow in await FlowDao.aget_flow_by_ids(ordered_ids)}
        all_flow = [flow_by_id[flow_id] for flow_id in ordered_ids if flow_id in flow_by_id]
        flow_dict = {}
        flow_list = []
        for one in all_flow:
            flow_dict[one.name] = one
            flow_list.append(
                {
                    "name": one.name,
                    "description": one.description if one.description else "",
                }
            )

        flow_list = auto_agent.choose_tools(flow_list, assistant.prompt)
        flow_info = []
        for one in flow_list:
            if flow_dict.get(one):
                flow_info.append(flow_dict[one])
        return flow_info
