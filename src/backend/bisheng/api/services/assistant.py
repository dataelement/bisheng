from typing import Any, List
from uuid import UUID

from bisheng.api.errcode.assistant import AssistantNotExistsError
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    StreamData, UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import Assistant, AssistantDao, AssistantLinkDao
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsToolsRead
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role_access import AccessType, RoleAcessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from loguru import logger


class AssistantService(AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user_id: int,
                      name: str = None,
                      status: int | None = None,
                      page: int = 1,
                      limit: int = 20) -> UnifiedResponseModel[List[AssistantSimpleInfo]]:
        """
        获取助手列表
        """
        data = []
        # 权限管理可见的助手信息
        assistant_ids_extra = []
        user_role = UserRoleDao.get_user_roles(user_id)
        if user_role:
            role_ids = [role.id for role in user_role]
            role_access = RoleAcessDao.get_role_acess(role_ids, AccessType.ASSITANT_READ)
            if role_access:
                assistant_ids_extra = [access.third_id for access in role_access]

        res, total = AssistantDao.get_assistants(user_id, name, assistant_ids_extra, status, page, limit)

        for one in res:
            simple_dict = one.model_dump(include={
                'id', 'name', 'desc', 'logo', 'status', 'user_id', 'create_time', 'update_time'
            })
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
            elif one.flow_id:
                flow_list.append(one.flow_id)
            elif one.knowledge_id:
                knowledge_list.append(one.knowledge_id)
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

        # 通过算法接口自动选择工具和技能
        # assistant, tool_list, flow_list = await cls.get_auto_info(assistant)

        # 保存数据到数据库
        assistant = AssistantDao.create_assistant(assistant)
        # 保存大模型自动选择的工具和技能
        # AssistantLinkDao.insert_batch(assistant.id, tool_list=tool_list, flow_list=flow_list)
        # tool_list, flow_list, knowledge_list = cls.get_link_info(tool_list, flow_list)

        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=[],
                                           flow_list=[],
                                           knowledge_list=[]))

    # 删除助手
    @classmethod
    def delete_assistant(cls, assistant_id: UUID, user_id: int) -> bool:

        # 通过算法接口自动选择工具和技能
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if assistant and assistant.user_id == user_id:
            AssistantDao.delete_assistant(assistant)
            return True
        else:
            raise ValueError('不满足删除条件')

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

        # 生成开场白和开场问题
        guide_info = auto_agent.generate_guide(assistant.prompt)
        yield str(StreamData(event='message', data={'type': 'guide_word', 'message': guide_info['opening_lines']}))
        yield str(StreamData(event='message', data={'type': 'guide_question', 'message': guide_info['questions']}))

        # 自动选择工具和技能
        tool_info = cls.get_auto_tool_info(assistant, auto_agent)
        tool_info = [one.to_dict() for one in tool_info]
        yield str(StreamData(event='message', data={'type': 'tool_list', 'message': tool_info}))

        flow_info = cls.get_auto_flow_info(assistant, auto_agent)
        flow_info = [one.to_dict() for one in flow_info]
        yield str(StreamData(event='message', data={'type': 'flow_list', 'message': flow_info}))

    @classmethod
    def update_assistant(cls, req: AssistantUpdateReq) -> UnifiedResponseModel[AssistantInfo]:
        """ 更新助手信息 """
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        # 更新助手数据
        if req.name:
            assistant.name = req.name
        if req.desc:
            assistant.desc = req.desc
        if req.logo:
            assistant.logo = req.logo
        if req.prompt:
            assistant.prompt = req.prompt
        if req.guide_word:
            assistant.guide_word = req.guide_word
        if req.guide_question:
            assistant.guide_question = req.guide_question
        if req.model_name:
            assistant.model_name = req.model_name
        if req.temperature is not None:
            assistant.temperature = req.temperature
        if req.status is not None:
            assistant.status = req.status
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
    def update_prompt(cls, assistant_id: UUID, prompt: str) -> UnifiedResponseModel:
        """ 更新助手的提示词 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        return resp_200()

    @classmethod
    def update_flow_list(cls, assistant_id: UUID, flow_list: List[str]) -> UnifiedResponseModel:
        """  更新助手的技能列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
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
    def update_tool_list(cls, assistant_id: UUID, tool_list: List[int]) -> UnifiedResponseModel:
        """  更新助手的工具列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return resp_200()

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
    async def get_auto_info(cls, assistant: Assistant) -> (Assistant, List[int], List[int]):
        """
        自动生成助手的prompt，自动选择工具和技能
        return：助手信息，工具ID列表，技能ID列表
        """
        # 根据助手
        llm_conf = cls.get_llm_conf(assistant.model_name)
        if not llm_conf:
            raise Exception(f'未找到对应的llm配置: {assistant.model_name}')

        assistant.model_name = llm_conf['model_name']
        assistant.temperature = llm_conf['temperature']

        # 初始化llm
        auto_agent = AssistantAgent(assistant, '')
        await auto_agent.init_llm()

        # 根据llm初始化prompt
        auto_prompt = auto_agent.sync_optimize_assistant_prompt()
        assistant.prompt = auto_prompt

        # 自动生成开场白和问题
        guide_info = auto_agent.generate_guide(assistant.prompt)
        assistant.guide_word = guide_info['opening_lines']
        assistant.guide_question = guide_info['questions']

        # 自动生成描述
        assistant.desc = auto_agent.generate_description(assistant.prompt)

        # 自动选择工具
        tool_info = cls.get_auto_tool_info(assistant, auto_agent)

        # 自动选择技能
        flow_info = cls.get_auto_flow_info(assistant, auto_agent)
        return assistant, [one.id for one in tool_info], [one.id for one in flow_info]

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
        # 自动选择技能
        all_flow = FlowDao.get_user_access_online_flows(assistant.user_id)
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
