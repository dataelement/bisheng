import asyncio
import csv
from datetime import datetime
from tempfile import NamedTemporaryFile
from typing import Any, List, Optional, Dict, Union, Tuple

from loguru import logger
from sqlalchemy import func
from sqlmodel import col, or_, and_, select

from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.config_service import settings
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync, get_minio_storage
from bisheng.database.models.assistant import AssistantDao, Assistant
from bisheng.database.models.audit_log import AuditLog, SystemId, EventType, ObjectType, AuditLogDao
from bisheng.database.models.flow import FlowDao, Flow, FlowType
from bisheng.database.models.group import Group
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.message import ChatMessageDao, LikedType
from bisheng.database.models.role import Role
from bisheng.database.models.session import MessageSessionDao, SensitiveStatus, MessageSession
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, Knowledge
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.user.domain.models.user import UserDao, User
from bisheng.utils import generate_uuid


# todo change to async or submit thread pool
class AuditLogService:

    @classmethod
    async def get_audit_log(cls, login_user: UserPayload, group_ids, operator_ids, start_time, end_time,
                            system_id, event_type, page, limit) -> Any:
        groups = group_ids
        if not login_user.is_admin():
            groups = [one.group_id for one in await UserGroupDao.aget_user_admin_group(login_user.user_id)]
            # Not an administrator of any user groups
            if not groups:
                return UnAuthorizedError.return_resp()
            # Filter bygroup_idand administrator permissionsgroupsDoing Intersections
            if group_ids:
                groups = list(set(groups) & set(group_ids))
                if not groups:
                    return UnAuthorizedError.return_resp()

        data, total = await AuditLogDao.get_audit_logs(groups, operator_ids, start_time, end_time,
                                                       system_id,
                                                       event_type,
                                                       page, limit)
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_all_operators(cls, login_user: UserPayload) -> List[Dict]:
        groups = []
        if not login_user.is_admin():
            groups = [one.group_id for one in UserGroupDao.get_user_admin_group(login_user.user_id)]
            # not any group admin
            if not groups:
                raise UnAuthorizedError()

        data = AuditLogDao.get_all_operators(groups)
        res = {}
        for one in data:
            if not one[1]:
                continue
            res[one[0]] = {'user_id': one[0], 'user_name': one[1]}
        return list(res.values())

    @classmethod
    def _chat_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                  object_id: str, object_name: str, resource_type: ResourceTypeEnum):
        # Get the group to which the resource belongs
        groups = GroupResourceDao.get_resource_group(resource_type, object_id)
        group_ids = [one.group_id for one in groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    async def _chat_log_async(cls, user: UserPayload, ip_address: str, event_type: EventType,
                              object_type: ObjectType,
                              object_id: str, object_name: str, resource_type: ResourceTypeEnum,
                              group_ids: List[int] = None):
        # Get the group to which the resource belongs
        if group_ids is None:
            groups = await GroupResourceDao.aget_resource_group(resource_type, object_id)
            group_ids = [one.group_id for one in groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    def create_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        New Audit Log for Assistant Session
        """
        logger.info(f"act=create_chat_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        # Getting Assistant Details
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.ASSISTANT,
                      assistant_id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def create_chat_flow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_info=None):
        """
        New Skill Session Audit Log
        """
        logger.info(f"act=create_chat_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        if not flow_info:
            flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.FLOW,
                      flow_id, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def create_chat_workflow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_info=None):
        """
        New Workflow Session Audit Log
        """
        logger.info(f"act=create_chat_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
        if not flow_info:
            flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.WORK_FLOW,
                      flow_id, flow_info.name, ResourceTypeEnum.WORK_FLOW)

    @classmethod
    async def delete_chat_flow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        Delete Audit Log for Skill Session
        """
        logger.info(f"act=delete_chat_flow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        await cls._chat_log_async(user, ip_address, EventType.DELETE_CHAT, ObjectType.FLOW,
                                  flow_info.id, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    async def delete_chat_workflow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        Delete Audit Log for Skill Session
        """
        logger.info(f"act=delete_chat_workflow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        await cls._chat_log_async(user, ip_address, EventType.DELETE_CHAT, ObjectType.WORK_FLOW,
                                  flow_info.id, flow_info.name, ResourceTypeEnum.WORK_FLOW)

    @classmethod
    async def delete_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_info: Assistant):
        """
        Delete audit log for assistant session
        """
        logger.info(f"act=delete_assistant_flow user={user.user_name} ip={ip_address} assistant={assistant_info.id}")
        await cls._chat_log_async(user, ip_address, EventType.DELETE_CHAT, ObjectType.ASSISTANT,
                                  assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def _build_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                   object_id: str,
                   object_name: str, resource_type: ResourceTypeEnum):
        """
        Build Module Audit Log
        """
        # Get which user groups the resource belongs to
        groups = GroupResourceDao.get_resource_group(resource_type, object_id)
        group_ids = [one.group_id for one in groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.BUILD.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    async def _build_log_async(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                               object_id: str,
                               object_name: str, resource_type: ResourceTypeEnum):
        """
        Build Module Audit Log
        """
        # Get which user groups the resource belongs to
        groups = await GroupResourceDao.aget_resource_group(resource_type, object_id)
        group_ids = [one.group_id for one in groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.BUILD.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    def create_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_type: Optional[int] = None):
        """
        New Skill Audit Log
        """
        obj_type = ObjectType.FLOW
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW.value:
            obj_type = ObjectType.WORK_FLOW
            rs_type = ResourceTypeEnum.WORK_FLOW
        logger.info(f"act=create_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(user, ip_address, EventType.CREATE_BUILD, obj_type,
                       flow_info.id, flow_info.name, rs_type)

    @classmethod
    async def update_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_type: Optional[int] = None):
        """
        Update Skill Audit Log
        """
        obj_type = ObjectType.FLOW
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW.value:
            obj_type = ObjectType.WORK_FLOW
            rs_type = ResourceTypeEnum.WORK_FLOW
        logger.info(f"act=update_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        await cls._build_log_async(user, ip_address, EventType.UPDATE_BUILD, obj_type, flow_info.id, flow_info.name,
                                   rs_type)

    @classmethod
    def delete_build_flow(cls, user: UserPayload, ip_address: str, flow_info: Flow, flow_type: Optional[int] = None):
        """
        Delete Skill Audit Log
        """
        obj_type = ObjectType.FLOW
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW.value:
            obj_type = ObjectType.WORK_FLOW
            rs_type = ResourceTypeEnum.WORK_FLOW
        logger.info(f"act=delete_build_flow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._build_log(user, ip_address, EventType.DELETE_BUILD, obj_type,
                       flow_info.id, flow_info.name, rs_type)

    @classmethod
    def create_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        New Assistant Audit Log
        """
        logger.info(f"act=create_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._build_log(user, ip_address, EventType.CREATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def update_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        Update the assistant's audit log
        """
        logger.info(f"act=update_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(user, ip_address, EventType.UPDATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def delete_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        Delete Audit Log for Assistant
        """
        logger.info(f"act=delete_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(user, ip_address, EventType.DELETE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    async def create_chat_message(cls, user: UserPayload, ip_address: str, message: Union[str, MessageSession]):
        """
        New Chat Message Audit Log for Build Module
        """
        if isinstance(message, MessageSession):
            message_session = message
        else:
            message_session = await MessageSessionDao.async_get_one(message)

        logger.info(f"act=create_chat_message user={user.user_name} ip={ip_address} session={message_session.chat_id}")

        user_groups = await UserGroupDao.aget_user_group(message_session.user_id)
        group_ids = [ug.group_id for ug in user_groups]

        await cls._chat_log_async(user, ip_address, EventType.CREATE_CHAT, ObjectType.WORKSTATION,
                                  message_session.chat_id, message_session.flow_name, ResourceTypeEnum.WORKSTATION,
                                  group_ids)

    @classmethod
    async def delete_chat_message(cls, user: UserPayload, ip_address: str, message: Union[str, MessageSession]):
        """
        Delete Chat Message Audit Log for Build Module
        """
        if isinstance(message, MessageSession):
            message_session = message
        else:
            message_session = await MessageSessionDao.async_get_one(message)

        logger.info(f"act=delete_chat_message user={user.user_name} ip={ip_address} session={message_session.chat_id}")

        await cls._chat_log_async(user, ip_address, EventType.DELETE_CHAT, ObjectType.WORKSTATION,
                                  message_session.chat_id, message_session.flow_name, ResourceTypeEnum.WORKSTATION)

    @classmethod
    def _knowledge_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                       object_id: str, object_name: str, resource_type: ResourceTypeEnum, resource_id: str):
        """
        Logs of Knowledge Base Modules
        """
        # Get which user groups the resource belongs to
        groups = GroupResourceDao.get_resource_group(resource_type, resource_id)
        group_ids = [one.group_id for one in groups]

        # Insert Audit Log
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.KNOWLEDGE.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def create_knowledge(cls, user: UserPayload, ip_address: str, knowledge_id: int):
        """
        New Knowledge Base Audit Log
        """
        logger.info(f"act=create_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge_id}")
        knowledge_info = KnowledgeDao.query_by_id(knowledge_id)
        cls._knowledge_log(user, ip_address, EventType.CREATE_KNOWLEDGE, ObjectType.KNOWLEDGE,
                           str(knowledge_id), knowledge_info.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge(cls, user: UserPayload, ip_address: str, knowledge: Knowledge):
        """
        Delete Knowledge Base Audit Log
        """
        logger.info(f"act=delete_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge.id}")
        cls._knowledge_log(user, ip_address, EventType.DELETE_KNOWLEDGE, ObjectType.KNOWLEDGE,
                           str(knowledge.id), knowledge.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge.id))

    @classmethod
    def upload_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        Audit Logs for Knowledge Base Upload Files
        """
        logger.info(f"act=upload_knowledge_file user={user.user_name} ip={ip_address}"
                    f" knowledge={knowledge_id} file={file_name}")
        cls._knowledge_log(user, ip_address, EventType.UPLOAD_FILE, ObjectType.FILE,
                           str(knowledge_id), file_name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        Audit Logs for Knowledge Base Deletion Files
        """
        logger.info(f"act=delete_knowledge_file user={user.user_name} ip={ip_address}"
                    f" knowledge={knowledge_id} file={file_name}")
        cls._knowledge_log(user, ip_address, EventType.DELETE_FILE, ObjectType.FILE,
                           str(knowledge_id), file_name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def _system_log(cls, user: UserPayload, ip_address: str, group_ids: List[int], event_type: EventType,
                    object_type: ObjectType, object_id: str, object_name: str, note: str = ''):

        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.SYSTEM.value,
            event_type=event_type.value,
            object_type=object_type.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
            note=note,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def update_user(cls, user: UserPayload, ip_address: str, user_id: int, group_ids: List[int], note: str):
        """
        Modify a user's user groups and roles
        """
        logger.info(f"act=update_system_user user={user.user_name} ip={ip_address} user_id={user_id} note={note}")
        user_info = UserDao.get_user(user_id)
        cls._system_log(user, ip_address, group_ids, EventType.UPDATE_USER,
                        ObjectType.USER_CONF, str(user_id), user_info.user_name, note)

    @classmethod
    def forbid_user(cls, user: UserPayload, ip_address: str, user_info: User):
        """
        user: Action User
        user_info: Operated by user
        """
        logger.info(f"act=forbid_user user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # Get the group to which the user belongs
        user_group = UserGroupDao.get_user_group(user_info.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.FORBID_USER,
                        ObjectType.USER_CONF, str(user_info.user_id), user_info.user_name)

    @classmethod
    def recover_user(cls, user: UserPayload, ip_address: str, user_info: User):
        logger.info(f"act=recover_user user={user.user_name} ip={ip_address} user_id={user_info.user_id}")
        # Get the group to which the user belongs
        user_group = UserGroupDao.get_user_group(user_info.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.RECOVER_USER,
                        ObjectType.USER_CONF, str(user_info.user_id), user_info.user_name)

    @classmethod
    def create_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=create_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        cls._system_log(user, ip_address, [group_info.id], EventType.CREATE_USER_GROUP,
                        ObjectType.USER_GROUP_CONF, str(group_info.id), group_info.group_name)

    @classmethod
    def update_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=update_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        # Get user group information
        cls._system_log(user, ip_address, [group_info.id], EventType.UPDATE_USER_GROUP,
                        ObjectType.USER_GROUP_CONF, str(group_info.id), group_info.group_name)

    @classmethod
    def delete_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=delete_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        # Get user group information
        cls._system_log(user, ip_address, [group_info.id], EventType.DELETE_USER_GROUP,
                        ObjectType.USER_GROUP_CONF, str(group_info.id), group_info.group_name)

    @classmethod
    def create_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=create_role user={user.user_name} ip={ip_address} role_id={role.id}")

        cls._system_log(user, ip_address, [role.group_id], EventType.CREATE_ROLE,
                        ObjectType.ROLE_CONF, str(role.id), role.role_name)

    @classmethod
    def update_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=update_role user={user.user_name} ip={ip_address} role_id={role.id}")

        cls._system_log(user, ip_address, [role.group_id], EventType.UPDATE_ROLE,
                        ObjectType.ROLE_CONF, str(role.id), role.role_name)

    @classmethod
    def delete_role(cls, user: UserPayload, ip_address: str, role: Role):
        logger.info(f"act=delete_role user={user.user_name} ip={ip_address} role_id={role.id}")

        cls._system_log(user, ip_address, [role.group_id], EventType.DELETE_ROLE,
                        ObjectType.ROLE_CONF, str(role.id), role.role_name)

    @classmethod
    def create_tool(cls, user: UserPayload, ip_address: str, group_ids: List[int], tool_type: GptsToolsType):
        logger.info(f"act=create_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")

        cls._system_log(user, ip_address, group_ids, EventType.ADD_TOOL, ObjectType.TOOL, str(tool_type.id),
                        tool_type.name)

    @classmethod
    def update_tool(cls, user: UserPayload, ip_address: str, group_ids: List[int], tool_type: GptsToolsType):
        logger.info(f"act=update_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")

        cls._system_log(user, ip_address, group_ids, EventType.UPDATE_TOOL, ObjectType.TOOL, str(tool_type.id),
                        tool_type.name)

    @classmethod
    def delete_tool(cls, user: UserPayload, ip_address: str, group_ids: List[int], tool_type: GptsToolsType):
        logger.info(f"act=delete_tool user={user.user_name} ip={ip_address} tool_type_id={tool_type.id}")
        cls._system_log(user, ip_address, group_ids, EventType.DELETE_TOOL, ObjectType.TOOL, str(tool_type.id),
                        tool_type.name)

    @classmethod
    def user_login(cls, user: UserPayload, ip_address: str):
        logger.info(f"act=user_login user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # Get the group to which the user belongs
        user_group = UserGroupDao.get_user_group(user.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.USER_LOGIN,
                        ObjectType.NONE, '', '')

    @classmethod
    async def _dashboard_log(cls, user: UserPayload, ip_address: str, group_ids: List[int], event_type: EventType,
                             object_id: str, object_name: str):

        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.DASHBOARD.value,
            event_type=event_type.value,
            object_type=ObjectType.DASHBOARD.value,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        await AuditLogDao.ainsert_audit_logs([audit_log])

    @classmethod
    async def create_dashboard(cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str,
                               group_ids: List[int]):
        logger.info(f"act=create_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.CREATE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def update_dashboard(cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str,
                               group_ids: List[int]):
        logger.info(f"act=update_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.UPDATE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def delete_dashboard(cls, user: UserPayload, ip_address: str, dashboard_id: str, dashboard_name: str,
                               group_ids: List[int]):
        logger.info(f"act=delete_dashboard user={user.user_name} ip={ip_address} dashboard_id={dashboard_id}")
        await cls._dashboard_log(user, ip_address, group_ids, EventType.DELETE_DASHBOARD, dashboard_id, dashboard_name)

    @classmethod
    async def get_filter_flow_ids(cls, user: UserPayload, flow_ids: List[str], group_ids: List[int]) -> (bool, List):
        """ Setujuflow_idsAndgroup_idsGet the final SkillidFilters false: Show Back to Empty List"""
        flow_ids = [one for one in flow_ids]
        group_admins = []
        if not user.is_admin():
            user_groups = await UserGroupDao.aget_user_admin_group(user.user_id)
            # Not a user group administrator, no permissions
            if not user_groups:
                raise UnAuthorizedError.http_exception()
            group_admins = [one.group_id for one in user_groups]
        # GroupingidDoing Intersections
        if group_ids:
            if group_admins:
                # Query user group not belonging to user management, return empty
                group_admins = list(set(group_admins) & set(group_ids))
                if len(group_admins) == 0:
                    return False, []
            else:
                group_admins = group_ids

        # Get all apps under groupingID
        group_flows = []
        if group_admins:
            group_flows = await GroupResourceDao.get_groups_resource(group_admins,
                                                                     resource_types=[ResourceTypeEnum.FLOW,
                                                                                     ResourceTypeEnum.WORK_FLOW,
                                                                                     ResourceTypeEnum.ASSISTANT,
                                                                                     ResourceTypeEnum.WORKSTATION])
            # User group under user management has no resources
            if not group_flows:
                return False, []
            group_flows = [one.third_id for one in group_flows]

        # Acquire the final skillIDRestrict to list
        filter_flow_ids = []
        if flow_ids and group_flows:
            filter_flow_ids = list(set(group_flows) & set(flow_ids))
            if not filter_flow_ids:
                return False, []
        elif flow_ids:
            filter_flow_ids = flow_ids
        elif group_flows:
            filter_flow_ids = group_flows
        return True, filter_flow_ids

    @classmethod
    async def get_session_list(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int], group_ids: List[int],
                               start_date: datetime, end_date: datetime,
                               feedback: str, sensitive_status: int, page: int, page_size: int) -> Tuple[
        List[AppChatList], int]:

        if user.is_admin():
            # Administrator: The frontend sends out what it needs to retrieve; if nothing is sent, it retrieves all (an empty list usually means there are no restrictions or the decision is made by the business logic in subsequent logic).
            search_group_ids = group_ids or []
        else:
            # Regular users: Administrative privileges must be verified
            user_managed_groups = await UserGroupDao.aget_user_admin_group(user.user_id)
            if not user_managed_groups:
                raise UnAuthorizedError.http_exception()

            managed_group_ids = {one.group_id for one in user_managed_groups}

            if group_ids:
                # Find the intersection: the intersection of the frontend requests
                valid_group_ids = list(set(group_ids) & managed_group_ids)
                if not valid_group_ids:
                    return [], 0
                search_group_ids = valid_group_ids
            else:
                # Default: All managed groups
                search_group_ids = list(managed_group_ids)

        conditions = []

        # Basic equality/range filtering
        if sensitive_status:
            conditions.append(MessageSession.sensitive_status == sensitive_status)

        if user_ids:
            conditions.append(col(MessageSession.user_id).in_(user_ids))

        if start_date:
            conditions.append(col(MessageSession.create_time) >= start_date)
        if end_date:
            conditions.append(col(MessageSession.create_time) <= end_date)

        if flow_ids:
            conditions.append(col(MessageSession.flow_id).in_(flow_ids))

        # Process type filtering (fixed enumeration)
        conditions.append(col(MessageSession.flow_type).in_([
            FlowType.FLOW.value,
            FlowType.WORKFLOW.value,
            FlowType.ASSISTANT.value,
            FlowType.WORKSTATION.value
        ]))

        # Feedback status filtering
        feedback_map = {
            'like': col(MessageSession.like) > 0,
            'dislike': col(MessageSession.dislike) > 0,
            'copied': col(MessageSession.copied) > 0
        }
        if feedback in feedback_map:
            conditions.append(feedback_map[feedback])

        # Group membership filtering
        if search_group_ids:
            group_filters = [
                func.json_contains(MessageSession.group_ids, str(gid))
                for gid in search_group_ids
            ]
            conditions.append(or_(*group_filters))

        # build query statement
        statement = select(MessageSession).where(and_(*conditions)).order_by(col(MessageSession.create_time).desc())

        res_task = MessageSessionDao.get_statement_results(statement, page=page, limit=page_size)
        total_task = MessageSessionDao.get_statement_count(statement)

        res, total = await asyncio.gather(res_task, total_task)

        if not res:
            return [], total

        target_user_ids = set()
        target_flow_ids = set()  # Flow/Workflow
        target_assistant_ids = set()  # Assistant

        for session in res:
            target_user_ids.add(session.user_id)
            if session.flow_type in [FlowType.FLOW.value, FlowType.WORKFLOW.value, FlowType.WORKSTATION.value]:
                target_flow_ids.add(session.flow_id)
            elif session.flow_type == FlowType.ASSISTANT.value:
                target_assistant_ids.add(session.flow_id)

        target_user_ids_list = list(target_user_ids)

        async def get_users_groups_map(u_ids: List[int]):
            # get user groups for multiple users
            if not u_ids: return {}
            tasks = [user.get_user_groups(uid) for uid in u_ids]
            results = await asyncio.gather(*tasks)
            return dict(zip(u_ids, results))

        users_data, flows_data, assistants_data, user_groups_map = await asyncio.gather(
            UserDao.aget_user_by_ids(target_user_ids_list),
            FlowDao.aget_flow_by_ids(list(target_flow_ids)),
            AssistantDao.aget_assistants_by_ids(list(target_assistant_ids)),
            get_users_groups_map(target_user_ids_list)
        )

        user_map = {u.user_id: u.user_name for u in users_data}
        flow_map = {f.id: f.name for f in flows_data}
        assistant_map = {a.id: a.name for a in assistants_data}

        # Construct the return object
        result: List[AppChatList] = []

        for session in res:
            # Determine the current name
            current_name = session.flow_name
            if session.flow_type in [FlowType.FLOW.value, FlowType.WORKFLOW.value, FlowType.WORKSTATION.value]:
                current_name = flow_map.get(session.flow_id, current_name)
            elif session.flow_type == FlowType.ASSISTANT.value:
                current_name = assistant_map.get(session.flow_id, current_name)

            # Append to the result set
            result.append(AppChatList(
                **session.model_dump(exclude={'flow_name'}),
                flow_name=current_name,
                like_count=session.like,
                dislike_count=session.dislike,
                copied_count=session.copied,
                user_name=user_map.get(session.user_id, ""),  # get user name
                user_groups=user_groups_map.get(session.user_id, [])
            ))

        return result, total

    @classmethod
    async def get_session_messages(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int],
                                   group_ids: List[int],
                                   start_date: datetime, end_date: datetime, feedback: str,
                                   sensitive_status: int) -> List[AppChatList]:
        page = 1
        page_size = 50
        res = []
        while True:
            result, total = await cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date,
                                                       feedback,
                                                       sensitive_status, page, page_size)
            if not result:
                break
            page += 1
            res.extend(await cls.get_chat_messages(result))
        return res

    @classmethod
    async def export_session_messages(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int],
                                      group_ids: List[int],
                                      start_date: datetime, end_date: datetime,
                                      feedback: str, sensitive_status: int) -> str:
        page = 1
        page_size = 30
        excel_data = [
            ['Session ID', 'Application Name', 'Session creation time', 'Username', 'Message Role',
             'Message sending time',
             'Message text content',
             'Like',
             'Dislike', 'copy']]
        bisheng_pro = await settings.aget_system_login_method().bisheng_pro
        if bisheng_pro:
            excel_data[0].append('Does it meet the content security review requirements?')

        while True:
            result, total = await cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date,
                                                       feedback,
                                                       sensitive_status, page, page_size)
            if not result:
                break
            page += 1
            chat_list = await cls.get_chat_messages(result)
            for chat in chat_list:
                for message in chat.messages:
                    message_data = [chat.chat_id, chat.flow_name, chat.create_time.strftime('%Y/%m/%d %H:%M:%S'),
                                    chat.user_name,
                                    'User' if message.category == 'question' else 'AI',
                                    message.create_time.strftime('%Y/%m/%d %H:%M:%S'),
                                    message.message,
                                    'Yes' if message.liked == LikedType.LIKED.value else 'No',
                                    'Yes' if message.liked == LikedType.DISLIKED.value else 'No',
                                    'Yes' if message.copied else 'No']
                    if bisheng_pro:
                        message_data.append(
                            'Yes' if message.sensitive_status == SensitiveStatus.VIOLATIONS.value else 'No')
                    excel_data.append(message_data)

        minio_client = await get_minio_storage()
        tmp_object_name = f'tmp/session/export_{generate_uuid()}.csv'
        with NamedTemporaryFile(mode='w', newline='') as tmp_file:
            csv_writer = csv.writer(tmp_file)
            csv_writer.writerows(excel_data)
            tmp_file.seek(0)
            await minio_client.put_object(object_name=tmp_object_name, file=tmp_file.name,
                                          content_type='application/text',
                                          bucket_name=minio_client.tmp_bucket)
        return await minio_client.get_share_link(tmp_object_name, minio_client.tmp_bucket)

    @classmethod
    async def get_chat_messages(cls, chat_list: List[AppChatList]) -> List[AppChatList]:
        chat_ids = [chat.chat_id for chat in chat_list]

        chat_messages = await ChatMessageDao.get_all_message_by_chat_ids(chat_ids)
        chat_messages_map = {}
        for one in chat_messages:
            if one.chat_id not in chat_messages_map:
                chat_messages_map[one.chat_id] = []
            chat_messages_map[one.chat_id].append(one)
        for chat in chat_list:
            chat_messages = chat_messages_map.get(chat.chat_id, [])
            # remove workflow input event, because it's not show in web
            chat.messages = [message for message in chat_messages
                             if message.category != WorkflowEventType.UserInput.value]
        return chat_list
