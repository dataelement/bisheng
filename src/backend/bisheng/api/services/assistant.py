import json
from typing import Any, List, Optional

from bisheng.api.errcode.assistant import AssistantNotExistsError
from bisheng.api.services.utils import set_flow_knowledge_id
from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    InputRequest, UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import (Assistant, AssistantDao, AssistantLink,
                                               AssistantLinkDao)
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.database.models.user import UserDao
from bisheng.settings import settings
from bisheng_langchain.gpts.load_tools import load_tools
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool, Tool
from loguru import logger


class AssistantService:
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls, user_id: int, name: str, page: int, limit: int) -> \
            UnifiedResponseModel[List[AssistantSimpleInfo]]:
        """
        获取助手列表
        """
        data = []
        res, total = AssistantDao.get_assistants(user_id, name, page, limit)
        # TODO zgq: 补充上权限管理可见的助手信息
        for one in res:
            simple_dict = one.model_dump(include={'id', 'name', 'desc', 'logo',
                                                  'user_id', 'create_time', 'update_time'})
            simple_dict['user_name'] = cls.get_user_name(one.user_id)
            data.append(AssistantSimpleInfo(**simple_dict))
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_assistant_info(cls, assistant_id: int, user_id: str):
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

        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    # 创建助手
    @classmethod
    def create_assistant(cls, assistant: Assistant) -> UnifiedResponseModel[AssistantInfo]:

        # 通过算法接口自动选择工具和技能
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)

        # 保存数据到数据库
        assistant = AssistantDao.create_assistant(assistant)
        # 保存大模型自动选择的工具和技能
        AssistantLinkDao.insert_batch(assistant.id, tool_list=tool_list, flow_list=flow_list)

        return resp_200(
            data=AssistantInfo(**assistant.dict(), tool_list=tool_list, flow_list=flow_list))

    @classmethod
    def auto_update(cls, assistant_id: int, prompt: str) -> UnifiedResponseModel[AssistantInfo]:
        """ 重新生成助手的提示词和工具选择, 只调用模型能力不修改数据库数据 """
        # todo zgq: 改为流式返回
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)
        return resp_200(
            data=AssistantInfo(**assistant.dict(), tool_list=tool_list, flow_list=flow_list))

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
        if req.temperature:
            assistant.temperature = req.temperature
        AssistantDao.update_assistant(assistant)

        # 更新助手关联信息
        if req.tool_list is not None and req.flow_list is not None and req.knowledge_list is not None:
            AssistantLinkDao.update_assistant_link(assistant.id,
                                                   tool_list=req.tool_list,
                                                   flow_list=req.flow_list,
                                                   knowledge_list=req.knowledge_list)
        elif req.tool_list is not None:
            AssistantLinkDao.update_assistant_tool(assistant.id, tool_list=req.tool_list)
        elif req.flow_list is not None:
            AssistantLinkDao.update_assistant_flow(assistant.id, flow_list=req.flow_list)
        elif req.knowledge_list is not None:
            AssistantLinkDao.update_assistant_knowledge(assistant.id,
                                                        knowledge_list=req.knowledge_list)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=req.tool_list,
                                           flow_list=req.flow_list,
                                           knowledge_list=req.knowledge_list))

    @classmethod
    def update_prompt(cls, assistant_id: int, prompt: str) -> UnifiedResponseModel:
        """ 更新助手的提示词 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        return resp_200()

    @classmethod
    def update_flow_list(cls, assistant_id: int, flow_list: List[str]) -> UnifiedResponseModel:
        """  更新助手的技能列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return resp_200()

    @classmethod
    def get_all_tool(cls, user_id: int) -> UnifiedResponseModel:
        tool_list = GptsToolsDao.get_list_by_user(user_id)
        return resp_200(data={'data': tool_list, 'total': len(tool_list)})

    @classmethod
    def update_tool_list(cls, assistant_id: int, tool_list: List[int]) -> UnifiedResponseModel:
        """  更新助手的工具列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return resp_200()

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
    def get_gpts_conf(cls, key=None):
        gpts_conf = settings.get_from_db('gpts')
        if key:
            return gpts_conf.get(key)
        return gpts_conf

    @classmethod
    def get_llm_conf(cls, llm_name: str) -> dict:
        llm_list = cls.get_gpts_conf('llms')
        for one in llm_list:
            if one['model_name'] == llm_name:
                return one.copy()
        return llm_list[0].copy()

    @classmethod
    def get_auto_info(cls, assistant: Assistant) -> (Assistant, List[int], List[int]):
        """
        自动生成助手的prompt，自动选择工具和技能
        return：助手信息，工具ID列表，技能ID列表
        """
        # todo zgq: 和算法联调自动生成prompt和工具列表
        # 根据助手 选择大模型配置
        llm_conf = cls.get_llm_conf(assistant.model_name)

        assistant.system_prompt = '临时生成的默认系统prompt'
        assistant.prompt = assistant.prompt or '用户可见的临时prompt'
        assistant.model_name = llm_conf['model_name']
        assistant.temperature = llm_conf['temperature']

        return assistant, [], []

    @classmethod
    def get_gpts_tools(cls, user: Any) -> List[GptsTools]:
        user_id = user.get('user_id')
        return GptsToolsDao.get_list_by_user(user_id)

    @classmethod
    async def init_tools(cls, assistant: Assistant,
                         llm: Optional[BaseLanguageModel]) -> List[BaseTool]:
        """通过名称获取tool 列表
           tools_name_param:: {name: params}
        """
        links: List[AssistantLink] = AssistantLinkDao.get_assistant_link(assistant_id=assistant.id)

        # tool
        tools = []
        tool_ids = [link.tool_id for link in links if link.tool_id]
        if tool_ids:
            tools: List[GptsTools] = GptsToolsDao.get_list_by_ids(tool_ids)
            tool_name_param = {tool.tool_key: json.loads(tool.extra) for tool in tools}
            tool_langchain = load_tools(tool_params=tool_name_param, llm=llm)
            tools = tools + tool_langchain
            logger.info('act=build_tools size={} return_tools={}', len(tools), len(tool_langchain))

        # flow
        flow_ids = [link.flow_id for link in links if link.flow_id]
        if flow_ids:
            flow2knowledge = {link.flow_id: link for link in links if link.flow_id}
            flow_data = FlowDao.get_flow_by_ids(flow_ids)
            # 先查找替换collection_id
            for flow in flow_data:
                graph_data = flow.data
                knowledge_id = flow2knowledge.get(flow.id).knowledge_id
                try:
                    artifacts = {}
                    graph_data = set_flow_knowledge_id(graph_data, knowledge_id)
                    graph = await build_flow_no_yield(graph_data=graph_data,
                                                      artifacts=artifacts,
                                                      process_file=True,
                                                      flow_id=flow.id.hex,
                                                      chat_id=assistant.id)
                    built_object = await graph.abuild()
                    logger.info('act=init_flow_tool build_end')
                    flow_tool = Tool(name=flow.name,
                                     func=built_object.call,
                                     coroutine=built_object.acall,
                                     description=flow.description,
                                     args_schema=InputRequest)
                    tools.append(flow_tool)
                except Exception as exc:
                    logger.error(f'Error processing tweaks: {exc}')
        return tools
