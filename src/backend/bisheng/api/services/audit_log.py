from typing import Any, List, Optional
from uuid import UUID

from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.audit_log import AuditLog, SystemId, EventType, ObjectType, AuditLogDao
from bisheng.database.models.assistant import AssistantDao, Assistant
from bisheng.database.models.flow import FlowDao, Flow, FlowType
from bisheng.database.models.group import GroupDao, Group
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.v1.schemas import resp_200
from bisheng.database.models.knowledge import KnowledgeDao, Knowledge
from bisheng.database.models.role import RoleDao, Role
from bisheng.database.models.user import UserDao, User
from bisheng.database.models.user_group import UserGroupDao


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
        res = []
        for one in data:
            res.append({'user_id': one[0], 'user_name': one[1]})
        return resp_200(data=res)

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
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.ASSISTANT,
                      assistant_id, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def create_chat_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        新建技能会话的审计日志
        """
        logger.info(f"act=create_chat_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._chat_log(user, ip_address, EventType.CREATE_CHAT, ObjectType.FLOW,
                      flow_id, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def delete_chat_flow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        删除技能会话的审计日志
        """
        logger.info(f"act=delete_chat_flow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.FLOW,
                      flow_info.id.hex, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def delete_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_info: Assistant):
        """
        删除助手会话的审计日志
        """
        logger.info(f"act=delete_assistant_flow user={user.user_name} ip={ip_address} assistant={assistant_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.ASSISTANT,
                      assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

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
    def create_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str,flow_type:Optional[int] = None):
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
                       flow_info.id.hex, flow_info.name, rs_type)

    @classmethod
    def update_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str,flow_type:Optional[int] = None):
        """
        更新技能的审计日志
        """
        obj_type = ObjectType.FLOW
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW.value:
            obj_type = ObjectType.WORK_FLOW
            rs_type = ResourceTypeEnum.WORK_FLOW
        logger.info(f"act=update_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(user, ip_address, EventType.UPDATE_BUILD, obj_type,
                       flow_info.id.hex, flow_info.name, rs_type)

    @classmethod
    def delete_build_flow(cls, user: UserPayload, ip_address: str, flow_info: Flow,flow_type:Optional[int] = None):
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
                       flow_info.id.hex, flow_info.name, rs_type)

    @classmethod
    def create_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        新建助手的审计日志
        """
        logger.info(f"act=create_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))
        cls._build_log(user, ip_address, EventType.CREATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def update_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        更新助手的审计日志
        """
        logger.info(f"act=update_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))

        cls._build_log(user, ip_address, EventType.UPDATE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def delete_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        删除助手的审计日志
        """
        logger.info(f"act=delete_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))

        cls._build_log(user, ip_address, EventType.DELETE_BUILD, ObjectType.ASSISTANT,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

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
    def user_login(cls, user: UserPayload, ip_address: str):
        logger.info(f"act=user_login user={user.user_name} ip={ip_address} user_id={user.user_id}")
        # 获取用户所属的分组
        user_group = UserGroupDao.get_user_group(user.user_id)
        user_group = [one.group_id for one in user_group]
        cls._system_log(user, ip_address, user_group, EventType.USER_LOGIN,
                        ObjectType.NONE, '', '')
