from datetime import datetime
from typing import Any, List
from uuid import UUID

from bisheng.api.errcode.assistant import (AssistantInitError, AssistantNameRepeatError,
                                           AssistantNotEditError, AssistantNotExistsError)
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    StreamData, UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import (Assistant, AssistantDao, AssistantLinkDao,
                                               AssistantStatus)
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsToolsRead
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from loguru import logger


class AssistantService(AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user: UserPayload,
                      name: str = None,
                      status: int | None = None,
                      page: int = 1,
                      limit: int = 20) -> UnifiedResponseModel[List[AssistantSimpleInfo]]:
        """
        获取助手列表
        """
        data = []
        if user.is_admin():
            res, total = AssistantDao.get_all_assistants(name, page, limit)
        else:
            # 权限管理可见的助手信息
            assistant_ids_extra = []
            user_role = UserRoleDao.get_user_roles(user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.ASSISTANT_READ)
                if role_access:
                    assistant_ids_extra = [UUID(access.third_id).hex for access in role_access]
            res, total = AssistantDao.get_assistants(user.user_id, name, assistant_ids_extra, status, page, limit)

        for one in res:
            simple_dict = one.model_dump(include={
                'id', 'name', 'desc', 'logo', 'status', 'user_id', 'create_time', 'update_time'
            })
            if one.user_id == user.user_id or user.is_admin():
                simple_dict['write'] = True
            simple_dict['user_name'] = cls.get_user_name(one.user_id)
            data.append(AssistantSimpleInfo(**simple_dict))
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_assistant_info(cls, assistant_id: UUID, user_id: str):
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
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
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    # 创建助手
    @classmethod
    async def create_assistant(cls, assistant: Assistant) -> UnifiedResponseModel[AssistantInfo]:

        # 检查下是否有重名
        if cls.judge_name_repeat(assistant.name, assistant.user_id):
            return AssistantNameRepeatError.return_resp()

        # 保存数据到数据库, 补充用默认的模型
        llm_conf = cls.get_llm_conf(assistant.model_name)
        assistant.model_name = llm_conf['model_name']
        assistant.temperature = llm_conf['temperature']

        # 自动生成描述
        assistant, _, _ = await cls.get_auto_info(assistant)
        assistant = AssistantDao.create_assistant(assistant)

        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=[],
                                           flow_list=[],
                                           knowledge_list=[]))

    # 删除助手
    @classmethod
    def delete_assistant(cls, assistant_id: UUID, user_payload: UserPayload) -> UnifiedResponseModel:
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        # 判断授权
        if not user_payload.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_WRITE):
            return UnAuthorizedError.return_resp()

        AssistantDao.delete_assistant(assistant)
        return resp_200()

    @classmethod
    async def auto_update_stream(cls, assistant_id: UUID, prompt: str):
        """ 重新生成助手的提示词和工具选择, 只调用模型能力不修改数据库数据 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        assistant.prompt = prompt

        # 初始化llm
        auto_agent = AssistantAgent(assistant, '')
        await auto_agent.init_llm()

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
    async def update_assistant(cls, req: AssistantUpdateReq, user_payload: UserPayload) \
            -> UnifiedResponseModel[AssistantInfo]:
        """ 更新助手信息 """
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            return AssistantNotExistsError.return_resp()

        check_result = cls.check_update_permission(assistant, user_payload)
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
            flow_id_default = AssistantUtils.get_default_retrieval()
            AssistantLinkDao.update_assistant_knowledge(assistant.id,
                                                        knowledge_list=req.knowledge_list,
                                                        flow_id=flow_id_default)
        tool_list, flow_list, knowledge_list = cls.get_link_info(req.tool_list, req.flow_list,
                                                                 req.knowledge_list)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    @classmethod
    async def update_status(cls, assistant_id: UUID, status: int, user_payload: UserPayload) -> UnifiedResponseModel:
        """ 更新助手的状态 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        # 判断权限
        if not user_payload.access_check(assistant.user_id, assistant.id.hex, AccessType.ASSISTANT_WRITE):
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
    def get_gpts_tools(cls, user_id: Any) -> List[GptsToolsRead]:
        """ 获取用户可见的工具列表 """
        return GptsToolsDao.get_list_by_user(user_id)

    @classmethod
    def get_models(cls) -> UnifiedResponseModel:
        llm_list = cls.get_gpts_conf('llms')
        res = []
        for one in llm_list:
            res.append({'id': one['model_name'], 'model_name': one['model_name']})
        return resp_200(data=res)

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
            return AssistantNotExistsError.return_resp()

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
        await auto_agent.init_llm()

        # 自动生成描述
        assistant.desc = auto_agent.generate_description(assistant.prompt)

        return assistant, [], []

    @classmethod
    def get_auto_tool_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[GptsToolsRead]:
        # 自动选择工具
        all_tool = cls.get_gpts_tools(user_id=assistant.user_id)
        tool_list = []
        all_tool_dict = {}
        for one in all_tool:
            all_tool_dict[one.name] = one
            tool_list.append({
                'name': one.name,
                'description': one.desc if one.desc else '',
            })
        tool_list = auto_agent.choose_tools(tool_list, assistant.prompt)
        tool_info = []
        for one in tool_list:
            if all_tool_dict.get(one):
                tool_info.append(all_tool_dict[one])
        return tool_info

    @classmethod
    def get_auto_flow_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[Flow]:
        # 自动选择技能, 挑选前50个技能用来做自动选择
        all_flow = FlowDao.get_user_access_online_flows(assistant.user_id, 50)
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
