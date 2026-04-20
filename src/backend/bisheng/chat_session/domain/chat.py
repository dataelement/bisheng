from typing import List, Optional

from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.schema.base_schema import PageList
from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import ChatList
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData, DeleteMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.mark_record import MarkRecordDao, MarkRecordStatus
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.message import ChatMessageDao, ChatMessage
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.database.models.user_group import UserGroupDao
from bisheng.chat_session.domain.services.chat_message_service import _resolve_leaf_tenant_id
from bisheng.chat_session.utils import get_session_app_type
from bisheng.user.domain.models.user import UserDao


class ChatSessionService:
    """Chat session lifecycle services."""

    @staticmethod
    async def get_chat_history(chat_id: str, flow_id: str, message_id: Optional[str] = None,
                               page_size: Optional[int] = 20) -> List['ChatMessageHistoryResponse']:
        """Retrieve chat history for a user."""
        from bisheng.api.v1.schema.chat_schema import ChatMessageHistoryResponse

        if not chat_id or not flow_id:
            return []
        session_info = await MessageSessionDao.async_get_one(chat_id=chat_id)
        if not session_info or session_info.flow_id != flow_id:
            return []

        history = await ChatMessageDao.afilter_message_by_chat_id(chat_id=chat_id, flow_id=flow_id,
                                                                  message_id=message_id, page_size=page_size)
        if history:
            user_info = await UserDao.aget_user(user_id=session_info.user_id)
            history = ChatMessageHistoryResponse.from_chat_message_objs(history, user_info, session_info)
        return history

    @staticmethod
    async def get_session_info(chat_id: str) -> Optional[MessageSession]:
        """Get session details with logo URL resolved."""
        res = await MessageSessionDao.async_get_one(chat_id)
        if res:
            res.flow_logo = WorkFlowService.get_logo_share_link(res.flow_logo)
        return res

    @staticmethod
    async def rename_session(conversation_id: str, name: str) -> None:
        """Rename a chat session."""
        await MessageSessionDao.update_session_name(conversation_id, name)

    @staticmethod
    async def delete_session(chat_id: str, login_user: UserPayload, request_ip: str) -> None:
        """Delete a session with audit logging and telemetry."""
        session_chat = await MessageSessionDao.async_get_one(chat_id)

        if not session_chat or session_chat.is_delete:
            return

        if session_chat.flow_type == FlowType.ASSISTANT.value:
            assistant_info = await AssistantDao.aget_one_assistant(session_chat.flow_id)
            if assistant_info:
                await AuditLogService.delete_chat_assistant(login_user, request_ip, assistant_info)
        elif session_chat.flow_type == FlowType.WORKSTATION.value:
            await AuditLogService.delete_chat_message(login_user, request_ip, session_chat)
        else:
            flow_info = await FlowDao.aget_flow_by_id(session_chat.flow_id)
            if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
                await AuditLogService.delete_chat_workflow(login_user, request_ip, flow_info)

        await MessageSessionDao.delete_session(chat_id)

        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.DELETE_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=DeleteMessageSessionEventData(session_id=chat_id),
        )

    @staticmethod
    def get_app_chat_list(
        *,
        login_user: UserPayload,
        keyword: Optional[str] = None,
        mark_user: Optional[str] = None,
        mark_status: Optional[int] = None,
        task_id: Optional[int] = None,
        flow_type: Optional[int] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> PageList:
        """Get app chat list with mark/annotation filtering for admin tasks."""
        group_flow_ids: list = []
        flow_ids: list = []
        user_ids: list = []

        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)

        if task_id:
            if not login_user.is_admin():
                task = MarkTaskDao.get_task_byid(task_id)
                if str(login_user.user_id) not in task.process_users.split(','):
                    raise UnAuthorizedError()
                if user_groups:
                    task = MarkTaskDao.get_task_byid(task_id)
                    group_flow_ids = task.app_id.split(',')
                    if not group_flow_ids:
                        return PageList(list=[], total=0)
                else:
                    task = MarkTaskDao.get_task_byid(task_id)
                    if str(login_user.user_id) not in task.process_users.split(','):
                        raise UnAuthorizedError()
                    group_flow_ids = MarkTaskDao.get_task_byid(task_id).app_id.split(',')
            else:
                group_flow_ids = MarkTaskDao.get_task_byid(task_id).app_id.split(',')

        if keyword:
            flows = FlowDao.get_flow_list_by_name(name=keyword)
            assistants, _ = AssistantDao.get_all_assistants(name=keyword, page=0, limit=0)
            users = UserDao.search_user_by_name(user_name=keyword)
            if flows:
                flow_ids = [flow.id for flow in flows]
            if assistants:
                flow_ids.extend([assistant.id for assistant in assistants])
            if user_ids:
                user_ids = [user.user_id for user in users]
            if not flow_ids and not user_ids:
                return PageList(list=[], total=0)

        if group_flow_ids:
            if flow_ids and keyword:
                flow_ids = flow_ids
            else:
                flow_ids = group_flow_ids

        res = MessageSessionDao.filter_session(flow_ids=flow_ids, user_ids=user_ids)
        total = len(res)

        chat_status_ids = [one.chat_id for one in res]
        chat_status_ids = MarkRecordDao.filter_records(task_id=task_id, chat_ids=chat_status_ids)
        chat_status_ids = {one.session_id: one for one in chat_status_ids}

        result = []
        for one in res:
            tmp = AppChatList(
                chat_id=one.chat_id,
                flow_id=one.flow_id,
                flow_name=one.flow_name,
                flow_type=one.flow_type,
                user_id=one.user_id,
                user_name=str(one.user_id),
                create_time=one.create_time,
                like_count=one.like,
                dislike_count=one.dislike,
                copied_count=one.copied,
                mark_status=MarkRecordStatus.DEFAULT.value,
                mark_user=None,
            )
            if mark_info := chat_status_ids.get(one.chat_id):
                tmp.mark_id = mark_info.create_id
                tmp.mark_status = mark_info.status if mark_info.status is not None else 1
                tmp.mark_user = mark_info.create_user
            if mark_status:
                if mark_status != tmp.mark_status:
                    continue
            if mark_user:
                users = [int(u) for u in mark_user.split(',')]
                if tmp.mark_id not in users:
                    continue
            result.append(tmp)

        result = result[(page_num - 1) * page_size: page_num * page_size]
        return PageList(list=result, total=total)

    @staticmethod
    def get_user_session_list(user_id: int, page: int = 1, limit: int = 10) -> List[ChatList]:
        """List daily chat and linsight sessions for a user, sorted by update_time descending."""
        allowed_flow_types = [FlowType.WORKSTATION.value, FlowType.LINSIGHT.value]

        res = MessageSessionDao.filter_session(
            user_ids=[user_id],
            flow_type=allowed_flow_types,
            page=page,
            limit=limit,
            include_delete=False,
            order_by_update_time=True,
        )

        if not res:
            return []

        chat_ids = [one.chat_id for one in res]
        latest_messages = ChatMessageDao.get_latest_message_by_chat_ids(
            chat_ids,
            exclude_category=WorkflowEventType.UserInput.value,
        )
        latest_messages = {one.chat_id: one for one in latest_messages}

        return [
            ChatList(
                chat_id=one.chat_id,
                flow_id=one.flow_id,
                flow_name=one.flow_name,
                flow_type=one.flow_type,
                name=one.name,
                logo=BaseService.get_logo_share_link(one.flow_logo) if one.flow_logo else '',
                latest_message=latest_messages.get(one.chat_id, None),
                create_time=one.create_time,
                update_time=one.update_time,
            )
            for one in res
        ]

    @staticmethod
    def get_or_create_session(
        chat_id: str,
        flow_id: str,
        login_user: UserPayload,
        request_ip: str,
    ) -> Optional[MessageSession]:
        """Get existing session or create a new one with audit log and telemetry.

        Used when adding messages to ensure a session exists.

        F017 §5.4: new MessageSession rows carry ``tenant_id = user's leaf
        tenant`` (NOT the resource tenant) per INV-T13. Refuse to persist
        a session if neither the ContextVar nor login_user carries a
        tenant — that is AC-11's guard against NULL-tenant derived data.
        """
        session_info = MessageSessionDao.get_one(chat_id=chat_id)
        if session_info:
            return session_info

        # F017 AC-11: resolve leaf tenant; raise 19504 if unavailable.
        leaf_tenant_id = _resolve_leaf_tenant_id(login_user)

        flow_info = FlowDao.get_flow_by_id(flow_id)
        if flow_info:
            session_info = MessageSessionDao.insert_one(MessageSession(
                chat_id=chat_id,
                flow_id=flow_id,
                flow_type=flow_info.flow_type,
                flow_name=flow_info.name,
                user_id=login_user.user_id,
                sensitive_status=SensitiveStatus.VIOLATIONS.value,
                tenant_id=leaf_tenant_id,
            ))
            if flow_info.flow_type == FlowType.WORKFLOW.value:
                AuditLogService.create_chat_workflow(login_user, request_ip, flow_id, flow_info)
        else:
            assistant_info = AssistantDao.get_one_assistant(flow_id)
            if assistant_info:
                session_info = MessageSessionDao.insert_one(MessageSession(
                    chat_id=chat_id,
                    flow_id=flow_id,
                    flow_type=FlowType.ASSISTANT.value,
                    flow_name=assistant_info.name,
                    user_id=login_user.user_id,
                    sensitive_status=SensitiveStatus.VIOLATIONS.value,
                    tenant_id=leaf_tenant_id,
                ))
                AuditLogService.create_chat_assistant(login_user, request_ip, flow_id)

        if session_info:
            telemetry_service.log_event_sync(
                user_id=login_user.user_id,
                event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                trace_id=trace_id_var.get(),
                event_data=NewMessageSessionEventData(
                    session_id=session_info.chat_id,
                    app_id=flow_id,
                    source="platform",
                    app_name=session_info.flow_name,
                    app_type=get_session_app_type(session_info.flow_type),
                ),
            )

        return session_info
