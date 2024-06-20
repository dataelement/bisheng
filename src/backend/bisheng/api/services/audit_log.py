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
        logger.info(f"act=create_chat_assistant user={user.user_name} assistant={assistant_id}")

    @classmethod
    def create_chat_flow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        新建技能会话的审计日志
        """
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
        logger.info(f"act=create_chat_flow user={user.user_name} flow={flow_id}")
