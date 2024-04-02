import json
from typing import Dict, List
from uuid import UUID

import httpx
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.utils import set_flow_knowledge_id
from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import InputRequest
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantLinkDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.auto_optimization import (generate_breif_description,
                                                      generate_opening_dialog,
                                                      optimize_assistant_prompt)
from bisheng_langchain.gpts.auto_tool_selected import ToolInfo, ToolSelector
from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.prompts import ASSISTANT_PROMPT_OPT
from bisheng_langchain.gpts.utils import import_by_type, import_class
from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, Tool
from loguru import logger


class AssistantAgent(AssistantUtils):

    def __init__(self, assistant_info: Assistant, chat_id: str):
        self.assistant = assistant_info
        self.chat_id = chat_id
        self.tools: List[BaseTool] = []
        self.agent: ConfigurableAssistant | None = None
        self.llm: BaseLanguageModel | None = None
        self.llm_agent_executor = None

    async def init_assistant(self, callbacks: Callbacks = None):
        await self.init_llm()
        await self.init_tools(callbacks)
        await self.init_agent()

    async def init_llm(self):
        llm_params = self.get_llm_conf(self.assistant.model_name)
        if not llm_params:
            logger.error(
                f'act=init_llm llm_params is None, model_name: {self.assistant.model_name}')
            raise Exception(
                f'act=init_llm llm_params is None, model_name: {self.assistant.model_name}')

        if llm_params.get('agent_executor_type'):
            self.llm_agent_executor = llm_params.pop('agent_executor_type')

        if llm_params['type'] == 'ChatOpenAI':
            llm_object = import_class('langchain_openai.ChatOpenAI')
            llm_params.pop('type')
            llm_params['model'] = llm_params.pop('model_name')
            if 'openai_proxy' in llm_params:
                openai_proxy = llm_params.pop('openai_proxy')
                llm_params['http_client'] = httpx.Client(proxies=openai_proxy)
                llm_params['http_async_client'] = httpx.AsyncClient(proxies=openai_proxy)
            self.llm = llm_object(**llm_params)
        else:
            llm_object = import_by_type(_type='llms', name=llm_params['type'])
            llm_params.pop('type')
            self.llm = llm_object(**llm_params)

    async def init_tools(self, callbacks: Callbacks = None):
        """通过名称获取tool 列表
           tools_name_param:: {name: params}
        """
        links: List[AssistantLink] = AssistantLinkDao.get_assistant_link(
            assistant_id=self.assistant.id)
        # tool
        tools: List[BaseTool] = []
        tool_ids = []
        flow_links = []
        for link in links:
            if link.tool_id:
                tool_ids.append(link.tool_id)
            else:
                flow_links.append(link)
        if tool_ids:
            tools_model: List[GptsTools] = GptsToolsDao.get_list_by_ids(tool_ids)
            tool_name_param = {
                tool.tool_key: json.loads(tool.extra) if tool.extra else {}
                for tool in tools_model
            }
            tool_langchain = load_tools(tool_params=tool_name_param,
                                        llm=self.llm,
                                        callbacks=callbacks)
            tools += tool_langchain
            logger.info('act=build_tools size={} return_tools={}', len(tools), len(tool_langchain))

        # flow, 当知识库的时候，flow_id 会重复
        flow_data = FlowDao.get_flow_by_ids([link.flow_id for link in flow_links])
        flow_id2data = {flow.id: flow for flow in flow_data}

        for link in flow_links:
            flow_graph_data = flow_id2data.get(UUID(link.flow_id)).data
            # 先查找替换collection_id
            knowledge_id = link.knowledge_id
            tool_name = f'flow_{link.flow_id}'
            if knowledge_id:
                # 说明是关联的知识库，修改知识库检索技能的对应知识库ID参数
                tool_name = f'knowledge_{link.knowledge_id}'
                flow_graph_data = set_flow_knowledge_id(flow_graph_data, knowledge_id)
            try:
                artifacts = {}
                graph = await build_flow_no_yield(graph_data=flow_graph_data,
                                                  artifacts=artifacts,
                                                  process_file=True,
                                                  flow_id=link.flow_id,
                                                  chat_id=self.assistant.id)
                built_object = await graph.abuild()
                logger.info('act=init_flow_tool build_end')
                flow_tool = Tool(name=tool_name,
                                 func=built_object,
                                 coroutine=built_object.acall,
                                 description=flow_id2data.get(UUID(link.flow_id)).description,
                                 args_schema=InputRequest,
                                 callbacks=callbacks)
                tools.append(flow_tool)
            except Exception as exc:
                logger.error(f'Error processing tweaks: {exc}')
        self.tools = tools

    async def init_agent(self):
        """
        初始化智能体的agent
        """
        # 引入agent执行参数
        agent_executor_params = self.get_agent_executor()
        agent_executor_type = self.llm_agent_executor or agent_executor_params.pop('type')

        # 初始化agent
        self.agent = ConfigurableAssistant(agent_executor_type=agent_executor_type,
                                           tools=self.tools,
                                           llm=self.llm,
                                           system_message=self.assistant.prompt,
                                           **agent_executor_params)

    async def optimize_assistant_prompt(self):
        """ 自动优化生成prompt """
        chain = ({
                     'assistant_name': lambda x: x['assistant_name'],
                     'assistant_description': lambda x: x['assistant_description'],
                 }
                 | ASSISTANT_PROMPT_OPT
                 | self.llm)
        async for one in chain.astream({
            'assistant_name': self.assistant.name,
            'assistant_description': self.assistant.prompt,
        }):
            yield one

    def sync_optimize_assistant_prompt(self):
        return optimize_assistant_prompt(self.llm, self.assistant.name, self.assistant.desc)

    def generate_guide(self, prompt: str):
        """ 生成开场对话和开场问题 """
        return generate_opening_dialog(self.llm, prompt)

    def generate_description(self, prompt: str):
        """ 生成描述对话 """
        return generate_breif_description(self.llm, prompt)

    def choose_tools(self, tool_list: List[Dict[str, str]], prompt: str) -> List[str]:
        """
         选择工具
         tool_list: [{name: xxx, description: xxx}]
        """
        tool_list = [
            ToolInfo(tool_name=one['name'], tool_description=one['description'])
            for one in tool_list
        ]
        tool_selector = ToolSelector(llm=self.llm, tools=tool_list)
        return tool_selector.select(self.assistant.name, prompt)

    async def run(self, query: str, callback: Callbacks = None):
        """
        运行智能体对话
        """
        inputs = [HumanMessage(content=query)]

        result = {}
        async for one in self.agent.astream_events(inputs,
                                                   config=RunnableConfig(callbacks=callback),
                                                   version='v1'):
            if one['event'] == 'on_chain_end':
                result = one

        # 最后一次输出的event即最终答案
        result = result['data']['output']['__end__']
        return result
