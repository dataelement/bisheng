import csv
from datetime import datetime
from tempfile import NamedTemporaryFile
from typing import Any, List, Optional

from loguru import logger

from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.config_service import settings
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.models.assistant import AssistantDao, Assistant
from bisheng.database.models.audit_log import AuditLog, SystemId, EventType, ObjectType, AuditLogDao
from bisheng.database.models.flow import FlowDao, Flow, FlowType
from bisheng.database.models.gpts_tools import GptsToolsType
from bisheng.database.models.group import Group
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.message import ChatMessageDao, LikedType
from bisheng.database.models.role import Role
from bisheng.database.models.session import MessageSessionDao, SensitiveStatus
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, Knowledge
from bisheng.user.domain.models.user import UserDao, User
from bisheng.utils import generate_uuid


class AuditLogService:

    @classmethod
    def get_audit_log(cls, login_user: UserPayload, group_ids, operator_ids, start_time, end_time,
                      system_id, event_type, page, limit) -> Any:
        groups = group_ids
        if not login_user.is_admin():
            groups = [str(one.group_id) for one in UserGroupDao.get_user_admin_group(login_user.user_id)]
            # 不是任何用戶组的管理员
            if not groups:
                return UnAuthorizedError.return_resp()
            # 将筛选条件的group_id和管理员有权限的groups做交集
            if group_ids:
                groups = list(set(groups) & set(group_ids))
                if not groups:
                    return UnAuthorizedError.return_resp()
        data, total = AuditLogDao.get_audit_logs(groups, operator_ids, start_time, end_time, system_id, event_type,
                                                 page, limit)
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_all_operators(cls, login_user: UserPayload) -> Any:
        groups = []
        if not login_user.is_admin():
            groups = [one.group_id for one in UserGroupDao.get_user_admin_group(login_user.user_id)]

        data = AuditLogDao.get_all_operators(groups)
        res = {}
        for one in data:
            if not one[1]:
                continue
            res[one[0]] = {'user_id': one[0], 'user_name': one[1]}
        return resp_200(data=list(res.values()))

    @classmethod
    def _chat_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                  object_id: str, object_name: str, resource_type: ResourceTypeEnum):
        # 获取资源所属的分组
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
    def create_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        新建助手会话的审计日志
        """
        logger.info(f"act=create_chat_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        # 获取助手详情
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.ASSISTANT,
                      assistant_id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def create_chat_flow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_info=None):
        """
        新建技能会话的审计日志
        """
        logger.info(f"act=create_chat_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        if not flow_info:
            flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.FLOW,
                      flow_id, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def create_chat_workflow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_info=None):
        """
        新建工作流会话的审计日志
        """
        logger.info(f"act=create_chat_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
        if not flow_info:
            flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.WORK_FLOW,
                      flow_id, flow_info.name, ResourceTypeEnum.WORK_FLOW)

    @classmethod
    def delete_chat_flow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        删除技能会话的审计日志
        """
        logger.info(f"act=delete_chat_flow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.FLOW,
                      flow_info.id, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def delete_chat_workflow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        删除技能会话的审计日志
        """
        logger.info(f"act=delete_chat_workflow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.WORK_FLOW,
                      flow_info.id, flow_info.name, ResourceTypeEnum.WORK_FLOW)

    @classmethod
    def delete_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_info: Assistant):
        """
        删除助手会话的审计日志
        """
        logger.info(f"act=delete_assistant_flow user={user.user_name} ip={ip_address} assistant={assistant_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.ASSISTANT,
                      assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def _build_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                   object_id: str,
                   object_name: str, resource_type: ResourceTypeEnum):
        """
        构建模块的审计日志
        """
        # 获取资源属于哪些用户组
        groups = GroupResourceDao.get_resource_group(resource_type, object_id)
        group_ids = [one.group_id for one in groups]

        # 插入审计日志
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
        构建模块的审计日志
        """
        # 获取资源属于哪些用户组
        groups = await GroupResourceDao.aget_resource_group(resource_type, object_id)
        group_ids = [one.group_id for one in groups]

        # 插入审计日志
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
        新建技能的审计日志
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
        更新技能的审计日志
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
        删除技能的审计日志
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
        新建助手的审计日志
        """
        logger.info(f"act=create_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)
        cls._build_log(user, ip_address, EventType.CREATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def update_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        更新助手的审计日志
        """
        logger.info(f"act=update_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(user, ip_address, EventType.UPDATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def delete_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        删除助手的审计日志
        """
        logger.info(f"act=delete_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(assistant_id)

        cls._build_log(user, ip_address, EventType.DELETE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def _knowledge_log(cls, user: UserPayload, ip_address: str, event_type: EventType, object_type: ObjectType,
                       object_id: str, object_name: str, resource_type: ResourceTypeEnum, resource_id: str):
        """
        知识库模块的日志
        """
        # 获取资源属于哪些用户组
        groups = GroupResourceDao.get_resource_group(resource_type, resource_id)
        group_ids = [one.group_id for one in groups]

        # 插入审计日志
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
        新建知识库的审计日志
        """
        logger.info(f"act=create_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge_id}")
        knowledge_info = KnowledgeDao.query_by_id(knowledge_id)
        cls._knowledge_log(user, ip_address, EventType.CREATE_KNOWLEDGE, ObjectType.KNOWLEDGE,
                           str(knowledge_id), knowledge_info.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge(cls, user: UserPayload, ip_address: str, knowledge: Knowledge):
        """
        删除知识库的审计日志
        """
        logger.info(f"act=delete_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge.id}")
        cls._knowledge_log(user, ip_address, EventType.DELETE_KNOWLEDGE, ObjectType.KNOWLEDGE,
                           str(knowledge.id), knowledge.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge.id))

    @classmethod
    def upload_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        知识库上传文件的审计日志
        """
        logger.info(f"act=upload_knowledge_file user={user.user_name} ip={ip_address}"
                    f" knowledge={knowledge_id} file={file_name}")
        cls._knowledge_log(user, ip_address, EventType.UPLOAD_FILE, ObjectType.FILE,
                           str(knowledge_id), file_name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        知识库删除文件的审计日志
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
        修改用户的用户组和角色
        """
        logger.info(f"act=update_system_user user={user.user_name} ip={ip_address} user_id={user_id} note={note}")
        user_info = UserDao.get_user(user_id)
        cls._system_log(user, ip_address, group_ids, EventType.UPDATE_USER,
                        ObjectType.USER_CONF, str(user_id), user_info.user_name, note)

    @classmethod
    def forbid_user(cls, user: UserPayload, ip_address: str, user_info: User):
        """
        user: 操作用户
        user_info: 被操作用户
        """
        logger.info(f"act=forbid_user user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # 获取用户所属的分组
        user_group = UserGroupDao.get_user_group(user_info.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.FORBID_USER,
                        ObjectType.USER_CONF, str(user_info.user_id), user_info.user_name)

    @classmethod
    def recover_user(cls, user: UserPayload, ip_address: str, user_info: User):
        logger.info(f"act=recover_user user={user.user_name} ip={ip_address} user_id={user_info.user_id}")
        # 获取用户所属的分组
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
        # 获取用户组信息
        cls._system_log(user, ip_address, [group_info.id], EventType.UPDATE_USER_GROUP,
                        ObjectType.USER_GROUP_CONF, str(group_info.id), group_info.group_name)

    @classmethod
    def delete_user_group(cls, user: UserPayload, ip_address: str, group_info: Group):
        logger.info(f"act=delete_user_group user={user.user_name} ip={ip_address} group_id={group_info.id}")
        # 获取用户组信息
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
        # 获取用户所属的分组
        user_group = UserGroupDao.get_user_group(user.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.USER_LOGIN,
                        ObjectType.NONE, '', '')

    @classmethod
    def get_filter_flow_ids(cls, user: UserPayload, flow_ids: List[str], group_ids: List[int]) -> (bool, List):
        """ 通过flow_ids和group_ids获取最终的 技能id筛选条件 false: 表示返回空列表"""
        flow_ids = [one for one in flow_ids]
        group_admins = []
        if not user.is_admin():
            user_groups = UserGroupDao.get_user_admin_group(user.user_id)
            # 不是用户组管理员，没有权限
            if not user_groups:
                raise UnAuthorizedError.http_exception()
            group_admins = [one.group_id for one in user_groups]
        # 分组id做交集
        if group_ids:
            if group_admins:
                # 查询了不属于用户管理的用户组，返回为空
                group_admins = list(set(group_admins) & set(group_ids))
                if len(group_admins) == 0:
                    return False, []
            else:
                group_admins = group_ids

        # 获取分组下所有的应用ID
        group_flows = []
        if group_admins:
            group_flows = GroupResourceDao.get_groups_resource(group_admins,
                                                               resource_types=[ResourceTypeEnum.FLOW,
                                                                               ResourceTypeEnum.WORK_FLOW,
                                                                               ResourceTypeEnum.ASSISTANT])
            # 用户管理下的用户组没有资源
            if not group_flows:
                return False, []
            group_flows = [one.third_id for one in group_flows]

        # 获取最终的技能ID限制列表
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
    def get_session_list(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int], group_ids: List[int],
                         start_date: datetime, end_date: datetime,
                         feedback: str, sensitive_status: int, page: int, page_size: int) -> (list, int):
        flag, filter_flow_ids = cls.get_filter_flow_ids(user, flow_ids, group_ids)
        if not flag:
            return [], 0
        filter_status = []
        if sensitive_status:
            filter_status = [SensitiveStatus(sensitive_status)]

        filters = {
            'sensitive_status': filter_status,
            'feedback': feedback,
            'flow_ids': filter_flow_ids,
            'user_ids': user_ids,
            'start_date': start_date,
            'end_date': end_date,
            'flow_type': [FlowType.FLOW.value, FlowType.WORKFLOW.value,
                          FlowType.ASSISTANT.value]
        }
        res = MessageSessionDao.filter_session(**filters, page=page, limit=page_size)
        total = MessageSessionDao.filter_session_count(**filters)

        res_users = []
        for one in res:
            res_users.append(one.user_id)
        user_list = UserDao.get_user_by_ids(res_users)
        user_map = {user.user_id: user.user_name for user in user_list}
        result = []
        for one in res:
            result.append(AppChatList(**one.model_dump(),
                                      like_count=one.like,
                                      dislike_count=one.dislike,
                                      copied_count=one.copied,
                                      user_name=user_map.get(one.user_id, one.user_id),
                                      user_groups=user.get_user_groups(one.user_id)))

        return result, total

    @classmethod
    def get_session_messages(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int], group_ids: List[int],
                             start_date: datetime, end_date: datetime, feedback: str,
                             sensitive_status: int) -> List[AppChatList]:
        page = 1
        page_size = 50
        res = []
        while True:
            result, total = cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date, feedback,
                                                 sensitive_status, page, page_size)
            if not result:
                break
            page += 1
            res.extend(cls.get_chat_messages(result))
        return res

    @classmethod
    def export_session_messages(cls, user: UserPayload, flow_ids: List[str], user_ids: List[int],
                                group_ids: List[int],
                                start_date: datetime, end_date: datetime,
                                feedback: str, sensitive_status: int) -> str:
        page = 1
        page_size = 30
        excel_data = [
            ['会话ID', '应用名称', '会话创建时间', '用户名称', '消息角色', '消息发送时间', '消息文本内容', '点赞',
             '点踩', '复制']]
        bisheng_pro = settings.get_system_login_method().bisheng_pro
        if bisheng_pro:
            excel_data[0].append('是否命中内容安全审查')

        while True:
            result, total = cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date, feedback,
                                                 sensitive_status, page, page_size)
            if not result:
                break
            page += 1
            chat_list = cls.get_chat_messages(result)
            for chat in chat_list:
                for message in chat.messages:
                    message_data = [chat.chat_id, chat.flow_name, chat.create_time.strftime('%Y/%m/%d %H:%M:%S'),
                                    chat.user_name,
                                    '用户' if message.category == 'question' else 'AI',
                                    message.create_time.strftime('%Y/%m/%d %H:%M:%S'),
                                    message.message,
                                    '是' if message.liked == LikedType.LIKED.value else '否',
                                    '是' if message.liked == LikedType.DISLIKED.value else '否',
                                    '是' if message.copied else '否']
                    if bisheng_pro:
                        message_data.append(
                            '是' if message.sensitive_status == SensitiveStatus.VIOLATIONS.value else '否')
                    excel_data.append(message_data)

        minio_client = get_minio_storage_sync()
        tmp_object_name = f'tmp/session/export_{generate_uuid()}.csv'
        with NamedTemporaryFile(mode='w', newline='') as tmp_file:
            csv_writer = csv.writer(tmp_file)
            csv_writer.writerows(excel_data)
            tmp_file.seek(0)
            minio_client.put_object_sync(object_name=tmp_object_name, file=tmp_file.name,
                                         content_type='application/text',
                                         bucket_name=minio_client.tmp_bucket)
        share_url = minio_client.get_share_link(tmp_object_name, minio_client.tmp_bucket)
        return minio_client.clear_minio_share_host(share_url)

    @classmethod
    def get_chat_messages(cls, chat_list: List[AppChatList]) -> List[AppChatList]:
        chat_ids = [chat.chat_id for chat in chat_list]

        chat_messages = ChatMessageDao.get_all_message_by_chat_ids(chat_ids)
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
