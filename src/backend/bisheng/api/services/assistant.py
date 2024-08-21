import json
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import Request
from loguru import logger

from bisheng.api.errcode.assistant import (AssistantInitError, AssistantNameRepeatError,
                                           AssistantNotEditError, AssistantNotExistsError, ToolTypeRepeatError,
                                           ToolTypeEmptyError, ToolTypeNotExistsError, ToolTypeIsPresetError)
from bisheng.api.errcode.base import UnAuthorizedError, NotFoundError
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.base import BaseService
from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    StreamData, UnifiedResponseModel, resp_200, resp_500)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import (Assistant, AssistantDao, AssistantLinkDao,
                                               AssistantStatus)
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsToolsRead, GptsToolsTypeRead, GptsTools
from bisheng.database.models.group_resource import GroupResourceDao, GroupResource, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao


class AssistantService(BaseService, AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user: UserPayload,
                      name: str = None,
                      status: int | None = None,
                      tag_id: int | None = None,
                      page: int = 1,
                      limit: int = 20) -> UnifiedResponseModel[List[AssistantSimpleInfo]]:
        """
        获取助手列表
        """
        assistant_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.ASSISTANT)
            assistant_ids = [UUID(one.resource_id) for one in ret]
            if not assistant_ids:
                return resp_200(data={
                    'data': [],
                    'total': 0
                })

        data = []
        if user.is_admin():
            res, total = AssistantDao.get_all_assistants(name, page, limit, assistant_ids, status)
        else:
            # 权限管理可见的助手信息
            assistant_ids_extra = []
            user_role = UserRoleDao.get_user_roles(user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.ASSISTANT_READ)
                if role_access:
                    assistant_ids_extra = [UUID(access.third_id).hex for access in role_access]
            res, total = AssistantDao.get_assistants(user.user_id, name, assistant_ids_extra, status, page, limit,
                                                     assistant_ids)

        assistant_ids = [one.id.hex for one in res]
        # 查询助手所属的分组
        assistant_groups = GroupResourceDao.get_resources_group(ResourceTypeEnum.ASSISTANT, assistant_ids)
        assistant_group_dict = {}
        for one in assistant_groups:
            if one.third_id not in assistant_group_dict:
                assistant_group_dict[one.third_id] = []
            assistant_group_dict[one.third_id].append(one.group_id)

        # 获取助手关联的tag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.ASSISTANT, assistant_ids)

        for one in res:
            one.logo = cls.get_logo_share_link(one.logo)
            simple_assistant = cls.return_simple_assistant_info(one)
            if one.user_id == user.user_id or user.is_admin():
                simple_assistant.write = True
            simple_assistant.group_ids = assistant_group_dict.get(one.id.hex, [])
            simple_assistant.tags = flow_tags.get(one.id.hex, [])
            data.append(simple_assistant)
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def return_simple_assistant_info(cls, one: Assistant) -> AssistantSimpleInfo:
        """
        将数据库的 助手model简化 处理后成返回前端的格式
        """
        simple_dict = one.model_dump(include={
            'id', 'name', 'desc', 'logo', 'status', 'user_id', 'create_time', 'update_time'
        })
        simple_dict['user_name'] = cls.get_user_name(one.user_id)
        return AssistantSimpleInfo(**simple_dict)

    @classmethod
    def get_assistant_info(cls, assistant_id: UUID, login_user: UserPayload):
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        # 检查是否有权限获取信息
        if not login_user.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_READ):
            return UnAuthorizedError.return_resp()

        tool_list = []
        flow_list = []
        knowledge_list = []

        links = AssistantLinkDao.get_assistant_link(assistant_id)
        for one in links:
            if one.tool_id:
                tool_list.append(one.tool_id)
            elif one.knowledge_id:
                knowledge_list.append(one.knowledge_id)
            elif one.flow_id:
                flow_list.append(one.flow_id)
            else:
                logger.error(f'not expect link info: {one.dict()}')
        tool_list, flow_list, knowledge_list = cls.get_link_info(tool_list, flow_list,
                                                                 knowledge_list)
        assistant.logo = cls.get_logo_share_link(assistant.logo)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    # 创建助手
    @classmethod
    async def create_assistant(cls, request: Request, login_user: UserPayload, assistant: Assistant) \
            -> UnifiedResponseModel[AssistantInfo]:

        # 检查下是否有重名
        if cls.judge_name_repeat(assistant.name, assistant.user_id):
            return AssistantNameRepeatError.return_resp()

        logger.info(f"assistant original prompt id: {assistant.id}, desc: {assistant.prompt}")

        # 自动补充默认的模型配置
        assistant_llm = LLMService.get_assistant_llm()
        if assistant_llm.llm_list:
            for one in assistant_llm.llm_list:
                if one.default:
                    assistant.model_name = one.model_id
                    break

        # 自动生成描述
        assistant, _, _ = await cls.get_auto_info(assistant)
        assistant = AssistantDao.create_assistant(assistant)

        cls.create_assistant_hook(request, assistant, login_user)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=[],
                                           flow_list=[],
                                           knowledge_list=[]))

    @classmethod
    def create_assistant_hook(cls, request: Request, assistant: Assistant, user_payload: UserPayload) -> bool:
        """
        创建助手成功后的hook，执行一些其他业务逻辑
        """
        # 查询下用户所在的用户组
        user_group = UserGroupDao.get_user_group(user_payload.user_id)
        if user_group:
            # 批量将助手资源插入到关联表里
            batch_resource = []
            for one in user_group:
                batch_resource.append(GroupResource(
                    group_id=one.group_id,
                    third_id=assistant.id.hex,
                    type=ResourceTypeEnum.ASSISTANT.value))
            GroupResourceDao.insert_group_batch(batch_resource)

        # 写入审计日志
        AuditLogService.create_build_assistant(user_payload, get_request_ip(request), assistant.id.hex)

        # 写入logo缓存
        cls.get_logo_share_link(assistant.logo)
        return True

    # 删除助手
    @classmethod
    def delete_assistant(cls, request: Request, login_user: UserPayload, assistant_id: UUID) -> UnifiedResponseModel:
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        # 判断授权
        if not login_user.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_WRITE):
            return UnAuthorizedError.return_resp()

        AssistantDao.delete_assistant(assistant)
        cls.delete_assistant_hook(request, login_user, assistant)
        return resp_200()

    @classmethod
    def delete_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """ 清理关联的助手资源 """
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")
        # 写入审计日志
        AuditLogService.delete_build_assistant(login_user, get_request_ip(request), assistant.id.hex)

        # 清理和用户组的关联
        GroupResourceDao.delete_group_resource_by_third_id(assistant.id.hex, ResourceTypeEnum.ASSISTANT)
        return True

    @classmethod
    async def auto_update_stream(cls, assistant_id: UUID, prompt: str):
        """ 重新生成助手的提示词和工具选择, 只调用模型能力不修改数据库数据 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        assistant.prompt = prompt

        # 初始化llm
        auto_agent = AssistantAgent(assistant, '')
        await auto_agent.init_auto_update_llm()

        # 流式生成提示词
        final_prompt = ''
        async for one_prompt in auto_agent.optimize_assistant_prompt():
            if one_prompt.content in ('```', 'markdown'):
                continue
            yield str(StreamData(event='message', data={'type': 'prompt', 'message': one_prompt.content}))
            final_prompt += one_prompt.content
        assistant.prompt = final_prompt
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        # 生成开场白和开场问题
        guide_info = auto_agent.generate_guide(assistant.prompt)
        yield str(StreamData(event='message', data={'type': 'guide_word', 'message': guide_info['opening_lines']}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))
        yield str(StreamData(event='message', data={'type': 'guide_question', 'message': guide_info['questions']}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        # 自动选择工具和技能
        tool_info = cls.get_auto_tool_info(assistant, auto_agent)
        tool_info = [one.model_dump() for one in tool_info]
        yield str(StreamData(event='message', data={'type': 'tool_list', 'message': tool_info}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        flow_info = cls.get_auto_flow_info(assistant, auto_agent)
        flow_info = [one.model_dump() for one in flow_info]
        yield str(StreamData(event='message', data={'type': 'flow_list', 'message': flow_info}))

    @classmethod
    async def update_assistant(cls, request: Request, login_user: UserPayload, req: AssistantUpdateReq) \
            -> UnifiedResponseModel[AssistantInfo]:
        """ 更新助手信息 """
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        check_result = cls.check_update_permission(assistant, login_user)
        if check_result is not None:
            return check_result

        # 更新助手数据
        if req.name and req.name != assistant.name:
            # 检查下是否有重名
            if cls.judge_name_repeat(req.name, assistant.user_id):
                return AssistantNameRepeatError.return_resp()
            assistant.name = req.name
        assistant.desc = req.desc
        assistant.logo = req.logo
        assistant.prompt = req.prompt
        assistant.guide_word = req.guide_word
        assistant.guide_question = req.guide_question
        assistant.model_name = req.model_name
        assistant.temperature = req.temperature
        assistant.update_time = datetime.now()
        AssistantDao.update_assistant(assistant)

        # 更新助手关联信息
        if req.tool_list is not None:
            AssistantLinkDao.update_assistant_tool(assistant.id, tool_list=req.tool_list)
        if req.flow_list is not None:
            AssistantLinkDao.update_assistant_flow(assistant.id, flow_list=req.flow_list)
        if req.knowledge_list is not None:
            # 使用配置的flow 进行技能补充
            AssistantLinkDao.update_assistant_knowledge(assistant.id,
                                                        knowledge_list=req.knowledge_list,
                                                        flow_id='')
        tool_list, flow_list, knowledge_list = cls.get_link_info(req.tool_list, req.flow_list,
                                                                 req.knowledge_list)
        cls.update_assistant_hook(request, login_user, assistant)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    @classmethod
    def update_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """ 更新助手的钩子 """
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")

        # 写入审计日志
        AuditLogService.update_build_assistant(login_user, get_request_ip(request), assistant.id.hex)

        # 写入缓存
        cls.get_logo_share_link(assistant.logo)
        return True

    @classmethod
    async def update_status(cls, request: Request, login_user: UserPayload, assistant_id: UUID,
                            status: int) -> UnifiedResponseModel:
        """ 更新助手的状态 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        # 判断权限
        if not login_user.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_WRITE):
            return UnAuthorizedError.return_resp()
        # 状态相等不做改动
        if assistant.status == status:
            return resp_200()

        # 尝试初始化agent，初始化成功则上线、否则不上线
        if status == AssistantStatus.ONLINE.value:
            tmp_agent = AssistantAgent(assistant, '')
            try:
                await tmp_agent.init_assistant()
            except Exception as e:
                logger.exception('online agent init failed')
                return AssistantInitError.return_resp('助手编译报错：' + str(e))
        assistant.status = status
        AssistantDao.update_assistant(assistant)
        cls.update_assistant_hook(request, login_user, assistant)
        return resp_200()

    @classmethod
    def update_prompt(cls, assistant_id: UUID, prompt: str, user_payload: UserPayload) -> UnifiedResponseModel:
        """ 更新助手的提示词 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        check_result = cls.check_update_permission(assistant, user_payload)
        if check_result is not None:
            return check_result

        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        return resp_200()

    @classmethod
    def update_flow_list(cls, assistant_id: UUID, flow_list: List[str],
                         user_payload: UserPayload) -> UnifiedResponseModel:
        """  更新助手的技能列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        check_result = cls.check_update_permission(assistant, user_payload)
        if check_result is not None:
            return check_result

        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return resp_200()

    @classmethod
    def get_gpts_tools(cls, user: UserPayload, is_preset: Optional[bool] = None) -> List[GptsToolsTypeRead]:
        """ 获取用户可见的工具列表 """
        # 获取用户可见的工具类别
        tool_type_ids_extra = []
        if not is_preset:
            # 获取自定义工具列表时，需要包含用户可用的工具列表
            user_role = UserRoleDao.get_user_roles(user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.GPTS_TOOL_READ)
                if role_access:
                    tool_type_ids_extra = [int(access.third_id) for access in role_access]
        # 获取用户可见的所有工具列表
        if is_preset is None:
            all_tool_type = GptsToolsDao.get_user_tool_type(user.user_id, tool_type_ids_extra)
        elif is_preset:
            # 获取预置工具列表
            all_tool_type = GptsToolsDao.get_preset_tool_type()
        else:
            # 获取用户可见的自定义工具列表
            all_tool_type = GptsToolsDao.get_user_tool_type(user.user_id, tool_type_ids_extra, False)
        tool_type_id = [one.id for one in all_tool_type]
        res = []
        tool_type_children = {}
        for one in all_tool_type:
            tool_type_id.append(one.id)
            tool_type_children[one.id] = []
            res.append(one.model_dump())

        # 获取对应类别下的工具列表
        tool_list = GptsToolsDao.get_list_by_type(tool_type_id)
        for one in tool_list:
            tool_type_children[one.type].append(one)

        for one in res:
            if not user.is_admin():
                one['extra'] = ''
            one["children"] = tool_type_children.get(one["id"], [])

        return res

    @classmethod
    def update_tool_config(cls, login_user: UserPayload, tool_type_id: int, extra: dict) -> GptsToolsTypeRead:
        # 获取工具类别
        tool_type = GptsToolsDao.get_one_tool_type(tool_type_id)
        if not tool_type:
            raise NotFoundError.http_exception()

        # 更新工具类别下所有工具的配置
        tool_type.extra = json.dumps(extra, ensure_ascii=False)
        GptsToolsDao.update_tools_extra(tool_type_id, tool_type.extra)
        return tool_type

    @classmethod
    def add_gpts_tools(cls, user: UserPayload, req: GptsToolsTypeRead) -> UnifiedResponseModel:
        """ 添加自定义工具 """
        req.id = None
        if req.name.__len__() > 30 or req.name.__len__() == 0:
            return resp_500(message="名字不符合规范：至少1个字符，不能超过30个字符")
        # 判断类别是否已存在
        tool_type = GptsToolsDao.get_one_tool_type_by_name(user.user_id, req.name)
        if tool_type:
            return ToolTypeRepeatError.return_resp()
        if len(req.children) == 0:
            return ToolTypeEmptyError.return_resp()
        req.user_id = user.user_id

        for one in req.children:
            one.id = None
            one.user_id = user.user_id
            one.is_delete = 0
            one.is_preset = False

        # 添加工具类别和对应的 工具列表
        res = GptsToolsDao.insert_tool_type(req)

        cls.add_gpts_tools_hook(user, res)
        return resp_200(data=res)

    @classmethod
    def add_gpts_tools_hook(cls, user: UserPayload, gpts_tool_type: GptsToolsTypeRead) -> bool:
        """ 添加自定义工具后的hook函数 """
        # 查询下用户所在的用户组
        user_group = UserGroupDao.get_user_group(user.user_id)
        if user_group:
            # 批量将自定义工具插入到关联表里
            batch_resource = []
            for one in user_group:
                batch_resource.append(GroupResource(
                    group_id=one.group_id,
                    third_id=gpts_tool_type.id,
                    type=ResourceTypeEnum.GPTS_TOOL.value))
            GroupResourceDao.insert_group_batch(batch_resource)
        return True

    @classmethod
    def update_gpts_tools(cls, user: UserPayload, req: GptsToolsTypeRead) -> UnifiedResponseModel:
        """
        更新工具类别，包括更新工具类别的名称和删除、新增工具类别的API
        """
        exist_tool_type = GptsToolsDao.get_one_tool_type(req.id)
        if not exist_tool_type:
            return ToolTypeNotExistsError.return_resp()
        if len(req.children) == 0:
            return ToolTypeEmptyError.return_resp()
        if req.name.__len__() > 30 or req.name.__len__() == 0:
            return resp_500(message="名字不符合规范：最少一个字符，不能超过30个字符")

        # 判断工具类别名称是否重复
        tool_type = GptsToolsDao.get_one_tool_type_by_name(user.user_id, req.name)
        if tool_type and tool_type.id != exist_tool_type.id:
            return ToolTypeRepeatError.return_resp()
        # 判断是否有更新权限
        if not user.access_check(exist_tool_type.user_id, str(exist_tool_type.id), AccessType.GPTS_TOOL_WRITE):
            return UnAuthorizedError.return_resp()

        exist_tool_type.name = req.name
        exist_tool_type.logo = req.logo
        exist_tool_type.description = req.description
        exist_tool_type.server_host = req.server_host
        exist_tool_type.auth_method = req.auth_method
        exist_tool_type.api_key = req.api_key
        exist_tool_type.auth_type = req.auth_type
        exist_tool_type.openapi_schema = req.openapi_schema

        children_map = {}
        for one in req.children:
            save_key = GptsToolsDao.get_tool_key(exist_tool_type.id, one.tool_key)
            save_key_prefix = save_key.split("_")[0]
            if one.tool_key.startswith(save_key_prefix):
                # 说明api和数据库的一致，没有通过openapiSchema重新解析
                children_map[one.tool_key] = one
            else:
                children_map[save_key] = one

        # 获取此类别下旧的API列表
        old_tool_list = GptsToolsDao.get_list_by_type([exist_tool_type.id])
        # 需要被删除的工具列表
        delete_tool_id_list = []
        # 需要被更新的工具列表
        update_tool_list = []
        for one in old_tool_list:
            # 说明此工具 需要删除
            if children_map.get(one.tool_key) is None:
                delete_tool_id_list.append(one.id)
            else:
                # 说明此工具需要更新
                new_tool_info = children_map.pop(one.tool_key)
                one.name = new_tool_info.name
                one.desc = new_tool_info.desc
                one.extra = new_tool_info.extra
                one.api_params = new_tool_info.api_params
                update_tool_list.append(one)

        add_children = []
        for one in children_map.values():
            one.id = None
            one.user_id = user.user_id
            one.is_preset = False
            one.is_delete = 0
            add_children.append(one)

        GptsToolsDao.update_tool_type(exist_tool_type, delete_tool_id_list,
                                      add_children, update_tool_list)

        children = GptsToolsDao.get_list_by_type([exist_tool_type.id])
        res = GptsToolsTypeRead(**exist_tool_type.model_dump(), children=children)
        return resp_200(data=res)

    @classmethod
    def delete_gpts_tools(cls, user: UserPayload, tool_type_id: int) -> UnifiedResponseModel:
        """ 删除工具类别 """
        exist_tool_type = GptsToolsDao.get_one_tool_type(tool_type_id)
        if not exist_tool_type:
            return resp_200()
        if exist_tool_type.is_preset:
            return ToolTypeIsPresetError.return_resp()
        # 判断是否有更新权限
        if not user.access_check(exist_tool_type.user_id, str(exist_tool_type.id), AccessType.GPTS_TOOL_WRITE):
            return UnAuthorizedError.return_resp()

        GptsToolsDao.delete_tool_type(tool_type_id)
        cls.delete_gpts_tool_hook(user, exist_tool_type)
        return resp_200()

    @classmethod
    def delete_gpts_tool_hook(cls, user: UserPayload, gpts_tool_type) -> bool:
        """ 删除自定义工具后的hook函数 """
        logger.info(f"delete_gpts_tool_hook id: {gpts_tool_type.id}, user: {user.user_id}")
        GroupResourceDao.delete_group_resource_by_third_id(gpts_tool_type.id, ResourceTypeEnum.GPTS_TOOL)
        return True

    @classmethod
    def update_tool_list(cls, assistant_id: UUID, tool_list: List[int],
                         user_payload: UserPayload) -> UnifiedResponseModel:
        """  更新助手的工具列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        check_result = cls.check_update_permission(assistant, user_payload)
        if check_result is not None:
            return check_result

        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return resp_200()

    @classmethod
    def check_update_permission(cls, assistant: Assistant, user_payload: UserPayload) -> Any:
        # 判断权限
        if not user_payload.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_WRITE):
            return UnAuthorizedError.return_resp()

        # 已上线不允许改动
        if assistant.status == AssistantStatus.ONLINE.value:
            return AssistantNotEditError.return_resp()
        return None

    @classmethod
    def get_link_info(cls,
                      tool_list: List[int],
                      flow_list: List[str],
                      knowledge_list: List[int] = None):
        tool_list = GptsToolsDao.get_list_by_ids(tool_list) if tool_list else []
        flow_list = FlowDao.get_flow_by_ids(flow_list) if flow_list else []
        knowledge_list = KnowledgeDao.get_list_by_ids(knowledge_list) if knowledge_list else []
        return tool_list, flow_list, knowledge_list

    @classmethod
    def get_user_name(cls, user_id: int):
        if not user_id:
            return 'system'
        user = cls.UserCache.get(user_id)
        if user:
            return user.user_name
        user = UserDao.get_user(user_id)
        if not user:
            return f'{user_id}'
        cls.UserCache.set(user_id, user)
        return user.user_name

    @classmethod
    def judge_name_repeat(cls, name: str, user_id: int) -> bool:
        """ 判断助手名字是否重复 """
        assistant = AssistantDao.get_assistant_by_name_user_id(name, user_id)
        if assistant:
            return True
        return False

    @classmethod
    async def get_auto_info(cls, assistant: Assistant) -> (Assistant, List[int], List[int]):
        """
        自动生成助手的prompt，自动选择工具和技能
        return：助手信息，工具ID列表，技能ID列表
        """
        # 初始化agent
        auto_agent = AssistantAgent(assistant, '')
        await auto_agent.init_auto_update_llm()

        # 自动生成描述
        assistant.desc = auto_agent.generate_description(assistant.prompt)

        return assistant, [], []

    @classmethod
    def get_auto_tool_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[GptsTools]:
        # 分页自动选择工具
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
                tool_list.append({
                    'name': one.name,
                    'description': one.desc if one.desc else '',
                })
            tool_info = []
            tool_list = auto_agent.choose_tools(tool_list, assistant.prompt)
            for one in tool_list:
                if all_tool_dict.get(one):
                    tool_info.append(all_tool_dict[one])
            res += tool_info
            page += 1
        return res

    @classmethod
    def get_auto_flow_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[Flow]:
        # 自动选择技能, 挑选前50个技能用来做自动选择
        all_flow = FlowDao.get_user_access_online_flows(assistant.user_id, 1, 50)
        flow_dict = {}
        flow_list = []
        for one in all_flow:
            flow_dict[one.name] = one
            flow_list.append({
                'name': one.name,
                'description': one.description if one.description else '',
            })

        flow_list = auto_agent.choose_tools(flow_list, assistant.prompt)
        flow_info = []
        for one in flow_list:
            if flow_dict.get(one):
                flow_info.append(flow_dict[one])
        return flow_info
