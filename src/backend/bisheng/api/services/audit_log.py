from typing import Any
from uuid import UUID

from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.audit_log import AuditLog, SystemId, EventType, ObjectType, AuditLogDao
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.v1.schemas import resp_200
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.user_group import UserGroupDao


class AuditLogService:

    @classmethod
    def get_audit_log(cls, login_user: UserPayload, group_ids, operator_ids, start_time, end_time,
                      system_id, event_type, page, limit) -> Any:
        groups = group_ids
        if not login_user.is_admin():
            groups = [one.group_id for one in UserGroupDao.get_user_admin_group(login_user.user_id)]
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
    def create_chat_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        新建助手会话的审计日志
        """
        logger.info(f"act=create_chat_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        # 获取助手所属的分组
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))
        groups = GroupResourceDao.get_resource_group(ResourceTypeEnum.ASSISTANT, assistant_info.id.hex)
        group_ids = [one.group_id for one in groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=EventType.CREATE_CHAT.value,
            object_type=ObjectType.ASSISTANT.value,
            object_id=assistant_info.id.hex,
            object_name=assistant_info.name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def create_chat_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        新建技能会话的审计日志
        """
        logger.info(f"act=create_chat_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        groups = GroupResourceDao.get_resource_group(ResourceTypeEnum.FLOW, flow_info.id.hex)
        group_ids = [one.group_id for one in groups]
        audit_log = AuditLog(
            operator_id=user.user_id,
            operator_name=user.user_name,
            group_ids=group_ids,
            system_id=SystemId.CHAT.value,
            event_type=EventType.CREATE_CHAT.value,
            object_type=ObjectType.FLOW.value,
            object_id=flow_info.id.hex,
            object_name=flow_info.name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def _build_log(cls, user: UserPayload, ip_address: str, event_type: str, object_type: str, object_id: str,
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
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            ip_address=ip_address,
        )
        AuditLogDao.insert_audit_logs([audit_log])

    @classmethod
    def create_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        新建技能的审计日志
        """
        logger.info(f"act=create_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(user, ip_address, EventType.CREATE_BUILD.value, ObjectType.FLOW.value,
                       flow_info.id.hex, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def update_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        更新技能的审计日志
        """
        logger.info(f"act=update_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(user, ip_address, EventType.UPDATE_BUILD.value, ObjectType.FLOW.value,
                       flow_info.id.hex, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def delete_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        删除技能的审计日志
        """
        logger.info(f"act=delete_build_flow user={user.user_name} ip={ip_address} flow={flow_id}")
        flow_info = FlowDao.get_flow_by_id(flow_id)
        cls._build_log(user, ip_address, EventType.DELETE_BUILD.value, ObjectType.FLOW.value,
                       flow_info.id.hex, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def create_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        新建助手的审计日志
        """
        logger.info(f"act=create_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))
        cls._build_log(user, ip_address, EventType.CREATE_BUILD.value, ObjectType.ASSISTANT.value,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def update_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        更新助手的审计日志
        """
        logger.info(f"act=update_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))

        cls._build_log(user, ip_address, EventType.UPDATE_BUILD.value, ObjectType.ASSISTANT.value,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def delete_build_assistant(cls, user: UserPayload, ip_address: str, assistant_id: str):
        """
        删除助手的审计日志
        """
        logger.info(f"act=delete_build_assistant user={user.user_name} ip={ip_address} assistant={assistant_id}")
        assistant_info = AssistantDao.get_one_assistant(UUID(assistant_id))

        cls._build_log(user, ip_address, EventType.DELETE_BUILD.value, ObjectType.ASSISTANT.value,
                       assistant_info.id.hex, assistant_info.name, ResourceTypeEnum.ASSISTANT)

    @classmethod
    def _knowledge_log(cls, user: UserPayload, ip_address: str, event_type: str, object_type: str,
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
            event_type=event_type,
            object_type=object_type,
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
        cls._knowledge_log(user, ip_address, EventType.CREATE_KNOWLEDGE.value, ObjectType.KNOWLEDGE.value,
                           str(knowledge_id), knowledge_info.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge(cls, user: UserPayload, ip_address: str, knowledge_id: int):
        """
        删除知识库的审计日志
        """
        logger.info(f"act=delete_knowledge user={user.user_name} ip={ip_address} knowledge={knowledge_id}")
        knowledge_info = KnowledgeDao.query_by_id(knowledge_id)
        cls._knowledge_log(user, ip_address, EventType.DELETE_KNOWLEDGE.value, ObjectType.KNOWLEDGE.value,
                           str(knowledge_id), knowledge_info.name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def upload_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        知识库上传文件的审计日志
        """
        logger.info(f"act=upload_knowledge_file user={user.user_name} ip={ip_address}"
                    f" knowledge={knowledge_id} file={file_name}")
        cls._knowledge_log(user, ip_address, EventType.UPLOAD_FILE.value, ObjectType.FILE.value,
                           str(knowledge_id), file_name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))

    @classmethod
    def delete_knowledge_file(cls, user: UserPayload, ip_address: str, knowledge_id: int, file_name: str):
        """
        知识库删除文件的审计日志
        """
        logger.info(f"act=delete_knowledge_file user={user.user_name} ip={ip_address}"
                    f" knowledge={knowledge_id} file={file_name}")
        cls._knowledge_log(user, ip_address, EventType.DELETE_FILE.value, ObjectType.FILE.value,
                           str(knowledge_id), file_name, ResourceTypeEnum.KNOWLEDGE, str(knowledge_id))
