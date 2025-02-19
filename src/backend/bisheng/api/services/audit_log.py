import json
from typing import Any, List, Optional
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.knowledge_imp import extract_code_blocks
from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.audit import ReviewSessionConfig
from bisheng.api.v1.schema.chat_schema import AppChatList
from bisheng.api.v1.schemas import resp_200
from bisheng.database.models.assistant import AssistantDao, Assistant
from bisheng.database.models.audit_log import AuditLog, SystemId, EventType, ObjectType, AuditLogDao
from bisheng.database.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.flow import FlowDao, Flow, FlowType
from bisheng.database.models.group import Group
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeDao, Knowledge
from bisheng.database.models.message import MessageDao, ChatMessageDao
from bisheng.database.models.role import Role
from bisheng.database.models.session import MessageSessionDao, ReviewStatus
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
    def create_chat_workflow(cls, user: UserPayload, ip_address: str, flow_id: str):
        """
        新建工作流会话的审计日志
        """
        logger.info(f"act=create_chat_workflow user={user.user_name} ip={ip_address} flow={flow_id}")
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
                      flow_info.id.hex, flow_info.name, ResourceTypeEnum.FLOW)

    @classmethod
    def delete_chat_workflow(cls, user: UserPayload, ip_address: str, flow_info: Flow):
        """
        删除技能会话的审计日志
        """
        logger.info(f"act=delete_chat_workflow user={user.user_name} ip={ip_address} flow={flow_info.id}")
        cls._chat_log(user, ip_address, EventType.DELETE_CHAT, ObjectType.WORK_FLOW,
                      flow_info.id.hex, flow_info.name, ResourceTypeEnum.WORK_FLOW)

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
                       flow_info.id.hex, flow_info.name, rs_type)

    @classmethod
    def update_build_flow(cls, user: UserPayload, ip_address: str, flow_id: str, flow_type: Optional[int] = None):
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

    @classmethod
    def get_session_config(cls) -> ReviewSessionConfig:
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.REVIEW_SESSION_CONFIG)
        if config:
            ret = json.loads(config.value)
        return ReviewSessionConfig(**ret)

    @classmethod
    def update_session_config(cls, user: UserPayload, data: ReviewSessionConfig) -> ReviewSessionConfig:
        ConfigDao.insert_or_update(Config(key=ConfigKeyEnum.REVIEW_SESSION_CONFIG.value, value=json.dumps(data.dict())))
        return data

    @classmethod
    def get_session_list(cls, user: UserPayload, flow_ids, user_ids, group_ids, start_date, end_date,
                         feedback, review_status, page, page_size) -> (list, int):
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
                group_admins = list(set(group_admins) & set(group_ids))
                if len(group_admins) == 0:
                    return [], 0
            else:
                group_admins = group_ids

        # 获取分组下所有的应用ID
        group_flows = []
        if group_admins:
            group_flows = GroupResourceDao.get_groups_resource(group_admins)
            if not group_flows:
                return [], 0
            group_flows = [one.third_id for one in group_flows]

        # 获取最终的技能ID限制列表
        filter_flow_ids = []
        exclude_flow_ids = []
        if flow_ids and group_flows:
            filter_flow_ids = list(set(group_admins) & set(flow_ids))
            if not filter_flow_ids:
                return [], 0
        elif flow_ids:
            filter_flow_ids = flow_ids
        elif group_flows:
            filter_flow_ids = group_flows

        if review_status:
            # 未审查状态的，目前的实现需要采用过滤的形式来搜索，目前在表里的都是未审查的
            if review_status == ReviewStatus.DEFAULT.value:
                session_list = MessageSessionDao.filter_session()
                exclude_flow_ids = [one.flow_id for one in session_list]
            else:
                session_list = MessageSessionDao.filter_session(review_status=[review_status])
                if not session_list:
                    return [], 0
                if filter_flow_ids:
                    filter_flow_ids = list(set(filter_flow_ids) & set([one.flow_id for one in session_list]))
                    if not filter_flow_ids:
                        return [], 0
                else:
                    filter_flow_ids = [one.flow_id for one in session_list]

        res, total = MessageDao.app_list_group_by_chat_id(page_size, page, filter_flow_ids, user_ids, start_date,
                                                          end_date, feedback, exclude_flow_ids)

        res_users = []
        res_flows = []
        res_chats = []
        for one in res:
            res_users.append(one['user_id'])
            res_flows.append(one['flow_id'])
            res_chats.append(one['chat_id'])
        user_list = UserDao.get_user_by_ids(res_users)
        flow_list = FlowDao.get_flow_by_ids(res_flows)
        assistant_list = AssistantDao.get_assistants_by_ids(res_flows)
        session_list = MessageSessionDao.filter_session(chat_ids=res_chats)

        user_map = {user.user_id: user.user_name for user in user_list}
        flow_map = {flow.id: flow for flow in flow_list}
        assistant_map = {assistant.id: assistant for assistant in assistant_list}
        flow_map.update(assistant_map)
        session_map = {one.chat_id: one for one in session_list}

        result = []
        for one in res:
            if not flow_map.get(one['flow_id']):
                continue
            result.append(AppChatList(**one,
                                      user_name=user_map.get(one['user_id'], one['user_id']),
                                      user_groups=user.get_user_groups(one['user_id']),
                                      flow_name=flow_map[one['flow_id']].name if flow_map.get(one['flow_id']) else one[
                                          'flow_id'],
                                      flow_type=FlowType.ASSISTANT.value if assistant_map.get(one['flow_id'], None) else
                                      flow_map[one['flow_id']].flow_type,
                                      review_status=session_map[one['chat_id']].review_status if session_map.get(
                                          one['chat_id']) else ReviewStatus.DEFAULT.value
                                      )
                          )

        return result, total

    @classmethod
    def review_session_list(cls, user: UserPayload, flow_ids, user_ids, group_ids, start_date, end_date,
                            feedback, review_status):
        """ 重新审查符合条件的会话 """
        page = 1
        page_size = 10
        while True:
            res, total = cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date, feedback,
                                              review_status, page, page_size)
            if res.len() == 0:
                break
            for one in res:
                cls.review_one_session(one['chat_id'], all_message=True)

        return cls.get_session_list(user, flow_ids, user_ids, group_ids, start_date, end_date, feedback, review_status,
                                    1, 10)

    @classmethod
    def review_one_session(cls, chat_id: str, all_message: bool = False):
        """ 重新审查一个会话内的消息
        params:
            chat_id: 会话ID
            all_message: 是否审查所有消息，默认为False，会过滤掉已审查过的消息
        """
        logger.info(f"act=review_one_session chat_id={chat_id} all_message={all_message}")
        # 审查配置
        review_config = cls.get_session_config()
        if not review_config.flag:
            logger.info(f"act=review flag is close, skip session:{chat_id}")
            return
        # 审查模型
        review_llm = LLMService.get_audit_llm_object()

        all_message = ChatMessageDao.get_msg_by_chat_id(chat_id)
        # 审查通过的消息列表 {id: 1}
        update_pass_messages = []
        # 违规的消息列表 {id: 1, review_reason: []}
        update_reject_messages = []
        # 审查失败的消息列表 {id: 1, review_reason: []}
        update_failed_messages = []

        message_list = []
        message_content_len = 0
        # 大于1000个字符则去请求模型审查
        max_message_len = 1000
        session_status = ReviewStatus.PASS.value
        for one in all_message:
            if all_message or one.review_status == ReviewStatus.DEFAULT.value:
                # 需要审查的消息, 内容为空的消息默认通过审查
                message_content = one.message if one.message else one.intermediate_steps
                if not message_content:
                    update_pass_messages.append(one.id)
                    continue
                message_content_len += message_content.__len__()
                message_list.append({
                    'id': one.id,
                    'message': message_content
                })
                if message_content_len > max_message_len:
                    a, b, c = cls.review_some_message(review_llm, review_config, message_list)
                    update_pass_messages.extend(a)
                    update_reject_messages.extend(b)
                    update_failed_messages.extend(c)
                    message_list = []
                    message_content_len = 0

    @classmethod
    def review_some_message(cls, review_llm: BaseChatModel, review_config: ReviewSessionConfig,
                            message_list: List[dict]) -> (List[int], List[int], List[dict]):
        try:
            llm_prompt = review_config.prompt
            llm_prompt += f'\n{json.dumps(message_list, ensure_ascii=False, indent=2)}'

            llm_result = review_llm.invoke(llm_prompt)
            logger.debug(f'review message result: {llm_result.content}')

            # 解析模型的输出
            result = extract_code_blocks(llm_result.content)
            if result:
                result = json.loads(result[0])
            else:
                result = json.loads(llm_result.content)

            # 判断有哪些消息审查失败了
            reject_messages = {}
            for one in result.get('messages', []):
                if one.get('message_id') and one.get('violations'):
                    reject_messages[one['message_id']] = {
                        'id': one['message_id'],
                        'reason': one['violations']
                    }
            pass_message = []
            for one in message_list:
                if one['id'] not in reject_messages:
                    pass_message.append({
                        'id': one['id']
                    })
            return pass_message, list(reject_messages.values()), []
        except Exception as e:
            logger.exception(f'review_some_message {message_list} error')
            return [], [], [{'id': one['id'], 'reason': str(e)[-100:]} for one in message_list]
