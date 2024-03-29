import json
from typing import List

from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.utils import set_flow_knowledge_id
from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import InputRequest
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantLinkDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools
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
        self.debug: bool = True

    async def init_assistant(self, callbacks: Callbacks = None):
        self.init_llm()
        await self.init_tools(callbacks)
        self.init_agent()

    def init_llm(self):
        llm_params = self.get_llm_conf(self.assistant.model_name)
        if not llm_params:
            logger.error(f'act=init_llm llm_params is None, model_name: {self.assistant.model_name}')
            raise Exception(f'act=init_llm llm_params is None, model_name: {self.assistant.model_name}')
        llm_object = import_by_type(_type='llms', name=llm_params['type'])

        if llm_params['type'] == 'ChatOpenAI':
            llm_params.pop('type')
            llm_params['model'] = llm_params.pop('model_name')
            # if 'openai_proxy' in llm_params:
            #     llm_params['http_client'] = httpx.AsyncClient(proxies=llm_params.pop('openai_proxy'))
            self.llm = llm_object(**llm_params)
        else:
            llm_params.pop('type')
            self.llm = llm_object(**llm_params)

    async def init_tools(self, callbacks: Callbacks = None):
        """通过名称获取tool 列表
           tools_name_param:: {name: params}
        """
        links: List[AssistantLink] = AssistantLinkDao.get_assistant_link(assistant_id=self.assistant.id)
        # tool
        tools: List[BaseTool] = []
        tool_ids = [link.tool_id for link in links if link.tool_id]
        if tool_ids:
            tools: List[GptsTools] = GptsToolsDao.get_list_by_ids(tool_ids)
            tool_name_param = {tool.tool_key: json.loads(tool.extra) for tool in tools}
            tool_langchain = load_tools(tool_params=tool_name_param, llm=self.llm)
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
                knowledge_id = flow2knowledge.get(flow.id.hex).knowledge_id
                try:
                    artifacts = {}
                    graph_data = set_flow_knowledge_id(graph_data, knowledge_id)
                    graph = await build_flow_no_yield(graph_data=graph_data,
                                                      artifacts=artifacts,
                                                      process_file=True,
                                                      flow_id=flow.id.hex,
                                                      chat_id=self.assistant.id)
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
        self.tools = tools

    def init_agent(self):
        """
        初始化智能体的agent
        """
        # 引入默认prompt
        prompt_type = self.get_prompt_type()
        assistant_message = import_class(f'bisheng_langchain.gpts.prompts.{prompt_type}')

        # 引入agent执行参数
        agent_executor_params = self.get_agent_executor()
        agent_executor_type = agent_executor_params.pop('type')

        # 初始化agent
        self.agent = ConfigurableAssistant(
            agent_executor_type=agent_executor_type,
            tools=self.tools,
            llm=self.llm,
            system_message=assistant_message,
            **agent_executor_params
        )

    async def run(self, query: str, callback: Callbacks = None):
        """
        运行智能体对话
        """
        inputs = [HumanMessage(content=query)]

        result = {}
        async for one in self.agent.astream_events(inputs, config=RunnableConfig(
                callbacks=callback
        ), version='v1'):
            if one['event'] == 'on_chain_end':
                result = one

        # 最后一次输出的event即最终答案
        result = result['data']['output']['__end__']
        return result
