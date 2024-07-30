import typing as tp
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, Tool

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import InputRequest
from bisheng.cache.flow import InMemoryCache
from bisheng.cache.utils import CACHE_DIR
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantLinkDao
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.utils.logger import logger


class RtcAssistantAgent(AssistantAgent):
    PersistPath = Path(CACHE_DIR) / 'assistant'
    MemoryCache = InMemoryCache()

    def __init__(self, assistant: Assistant):
        super().__init__(assistant, '')

    async def async_init(self):
        await self.init_llm()
        await self.init_abilities()
        await self.init_agent()

    @classmethod
    async def create(cls, assistant: Assistant) -> "RtcAssistantAgent":
        if ins := cls.load(assistant.id.hex):
            return ins
        else:
            ins = cls(assistant)
            await ins.async_init()
            ins.save()
            return ins

    @classmethod
    def load(cls, assistant_id: str):
        return cls.MemoryCache.get(assistant_id)

    def save(self):
        self.MemoryCache.set(self.assistant.id.hex, self)

    async def init_abilities(self):
        """初始化能力"""
        # link要么是tool(非零)，要么是flow(非空)，要么是knowledge(非零)
        logger.info(f"start initialize agent abilities...")
        links = AssistantLinkDao.get_assistant_link(assistant_id=self.assistant.id)
        tool_links, flows_links, knowledge_links = self.split_tool_flow_knowledge(links)
        tools = await self.init_tools(tool_links)
        flows = await self.init_flows(flows_links)
        knowledge = await self.init_knowledge(knowledge_links)
        self.tools = tools + flows + knowledge  # init_agent用

    def split_tool_flow_knowledge(self, links: tp.List[AssistantLink]):
        """
        link要么是tool(非零)，要么是flow(非空)，要么是knowledge(非零)
        应考虑分表 todo
        """
        tools = []
        flows = []
        knowledge = []
        for link in links:
            if link.tool_id:
                tools.append(link)
            elif link.flow_id:
                flows.append(link)
            elif link.knowledge_id:
                knowledge.append(link)
        return tools, flows, knowledge

    def split_preset_personal(self, tools: tp.List[GptsTools]):
        """区分预定义tool和自定义tool"""
        preset_tools = []
        personal_tools = []
        for one in tools:
            if one.is_preset:
                preset_tools.append(one)
            else:
                personal_tools.append(one)
        return preset_tools, personal_tools

    async def init_tools(self, tool_links: tp.List[AssistantLink]) -> tp.List[BaseTool]:
        """初始化工具"""
        logger.info(f"start initialize agent abilities: tools...")
        tool_chains: tp.List[BaseTool] = []
        tool_ids = [one.tool_id for one in tool_links]
        instances = GptsToolsDao.get_list_by_ids(tool_ids)
        preset_tools, personal_tools = self.split_preset_personal(instances)
        if preset_tools:
            preset_langchain = await self.init_preset_tools(preset_tools)
            logger.info('act=build_preset_tools size={} return_tools={}', len(preset_tools), len(preset_langchain))
            tool_chains.extend(preset_langchain)
        if personal_tools:
            personal_langchain = await self.init_personal_tools(personal_tools)
            logger.info('act=build_personal_tools size={} return_tools={}', len(personal_tools),
                        len(personal_langchain))
            tool_chains.extend(personal_langchain)
        return tool_chains

    async def init_flows(self, flow_links: tp.List[AssistantLink]) -> tp.List[BaseTool]:
        """初始化技能"""
        logger.info(f"start initialize agent abilities: flows...")
        flow_chains = []
        flow_ids = [one.flow_id for one in flow_links]
        flow_data = FlowDao.get_flow_by_ids(flow_ids)
        for datum in flow_data:
            if datum.status != FlowStatus.ONLINE.value:
                logger.warning('act=init_tools skip not online flow_id: {}', datum.id)
                continue
            tool_description = f'{datum.name}:{datum.description}'
            fake_chat_id = self.assistant.id.hex
            graph = await build_flow_no_yield(graph_data=datum.data, artifacts={}, process_file=True, flow_id=datum.id,
                                              chat_id=fake_chat_id)
            built_obj = await graph.abuild()
            logger.info('act=init_flow_tool build_end')
            tool_name = f'flow_{datum.id}'
            chain = Tool(name=tool_name, func=built_obj, coroutine=built_obj.acall, description=tool_description,
                         args_schema=InputRequest)
            flow_chains.append(chain)
        return flow_chains

    async def init_knowledge(self, knowledge_links: tp.List[AssistantLink]) -> tp.List[BaseTool]:
        """初始化知识库"""
        logger.info(f"start initialize agent abilities: knowledge...")
        knowledge_chains = []
        knowledge_ids = [one.knowledge_id for one in knowledge_links]
        knowledge_data = KnowledgeDao.get_list_by_ids(knowledge_ids)
        for datum in knowledge_data:
            knowledge_tool = await self.init_knowledge_tool(datum)
            knowledge_chains.extend(knowledge_tool)
        return knowledge_chains

    async def run_agent(self, inputs: list):
        """运行智能体对话"""
        result = await self.agent.ainvoke(inputs, config=RunnableConfig())
        # result包含了history，最后一个是最后一次回答
        if isinstance(result[-1], AIMessage):
            return result[-1].content
        return ""
