import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.api.services.llm import LLMService
from bisheng.api.services.openapi import OpenApiSchema
from bisheng.api.utils import build_flow_no_yield
from bisheng.api.v1.schemas import InputRequest
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantLinkDao
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao
from bisheng.settings import settings
from bisheng.utils.embedding import decide_embeddings
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.auto_optimization import (generate_breif_description,
                                                      generate_opening_dialog,
                                                      optimize_assistant_prompt)
from bisheng_langchain.gpts.auto_tool_selected import ToolInfo, ToolSelector
from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.prompts import ASSISTANT_PROMPT_OPT
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, Tool
from langchain_core.utils.function_calling import format_tool_to_openai_tool
from langchain_core.vectorstores import VectorStoreRetriever
from loguru import logger


class AssistantAgent(AssistantUtils):
    # cohere的模型需要的特殊prompt
    ASSISTANT_PROMPT_COHERE = """{preamble}|<instruct>|Carefully perform the following instructions, in order, starting each with a new line.
    Firstly, You may need to use complex and advanced reasoning to complete your task and answer the question. Think about how you can use the provided tools to answer the question and come up with a high level plan you will execute.
    Write 'Plan:' followed by an initial high level plan of how you will solve the problem including the tools and steps required.
    Secondly, Carry out your plan by repeatedly using actions, reasoning over the results, and re-evaluating your plan. Perform Action, Observation, Reflection steps with the following format. Write 'Action:' followed by a json formatted action containing the "tool_name" and "parameters"
     Next you will analyze the 'Observation:', this is the result of the action.
    After that you should always think about what to do next. Write 'Reflection:' followed by what you've figured out so far, any changes you need to make to your plan, and what you will do next including if you know the answer to the question.
    ... (this Action/Observation/Reflection can repeat N times)
    Thirdly, Decide which of the retrieved documents are relevant to the user's last input by writing 'Relevant Documents:' followed by comma-separated list of document numbers. If none are relevant, you should instead write 'None'.
    Fourthly, Decide which of the retrieved documents contain facts that should be cited in a good answer to the user's last input by writing 'Cited Documents:' followed a comma-separated list of document numbers. If you dont want to cite any of them, you should instead write 'None'.
    Fifthly, Write 'Answer:' followed by a response to the user's last input. Use the retrieved documents to help you. Do not insert any citations or grounding markup.
    Finally, Write 'Grounded answer:' followed by a response to the user's last input in high quality natural english. Use the symbols <co: doc> and </co: doc> to indicate when a fact comes from a document in the search result, e.g <co: 4>my fact</co: 4> for a fact from document 4.

    Additional instructions to note:
    - If the user's question is in Chinese, please answer it in Chinese.
    - 当问题中有涉及到时间信息时，比如最近6个月、昨天、去年等，你需要用时间工具查询时间信息。
    """   # noqa

    def __init__(self, assistant_info: Assistant, chat_id: str):
        self.assistant = assistant_info
        self.chat_id = chat_id
        self.tools: List[BaseTool] = []
        self.offline_flows = []
        self.agent: ConfigurableAssistant | None = None
        self.agent_executor_dict = {
            'ReAct': 'get_react_agent_executor',
            'function call': 'get_openai_functions_agent_executor',
        }
        self.current_agent_executor = None
        self.llm: BaseLanguageModel | None = None
        self.llm_agent_executor = None
        self.knowledge_skill_path = str(Path(__file__).parent / 'knowledge_skill.json')
        self.knowledge_skill_data = None
        # 知识库检索相关参数
        self.knowledge_retriever = {'max_content': 15000, 'sort_by_source_and_index': False}

    async def init_assistant(self, callbacks: Callbacks = None):
        await self.init_llm()
        await self.init_tools(callbacks)
        await self.init_agent()

    async def init_llm(self):
        # 获取配置的助手模型列表
        assistant_llm = LLMService.get_assistant_llm()
        if not assistant_llm.llm_list:
            raise Exception('助手推理模型列表为空')
        default_llm = None
        for one in assistant_llm.llm_list:
            if str(one.model_id) == self.assistant.model_name:
                default_llm = one
                break
            elif not default_llm and one.default:
                default_llm = one
        if not default_llm:
            raise Exception('未配置助手推理模型')

        self.llm_agent_executor = default_llm.agent_executor_type
        self.knowledge_retriever = {
            'max_content': default_llm.knowledge_max_content,
            'sort_by_source_and_index': default_llm.knowledge_sort_index
        }

        # 初始化llm
        self.llm = LLMService.get_bisheng_llm(model_id=default_llm.model_id,
                                              temperature=self.assistant.temperature,
                                              streaming=default_llm.streaming)

    async def init_auto_update_llm(self):
        """ 初始化自动优化prompt等信息的llm实例 """
        assistant_llm = LLMService.get_assistant_llm()
        if not assistant_llm.auto_llm:
            raise Exception('未配置助手画像自动优化模型')

        self.llm = LLMService.get_bisheng_llm(model_id=assistant_llm.auto_llm.model_id,
                                              temperature=self.assistant.temperature,
                                              streaming=assistant_llm.auto_llm.streaming)

    @staticmethod
    def parse_tool_params(tool: GptsTools) -> Dict:
        """
        解析预置工具的初始化参数
        """
        # 特殊处理下bisheng_code_interpreter的参数
        if tool.tool_key == 'bisheng_code_interpreter':
            return {'minio': settings.get_knowledge().get('minio', {})}
        if not tool.extra:
            return {}
        params = json.loads(tool.extra)

        return params

    @staticmethod
    def sync_init_preset_tools(tool_list: List[GptsTools],
                               llm: BaseLanguageModel = None,
                               callbacks: Callbacks = None):
        """
        初始化预置工具列表
        """
        tool_name_param = {
            tool.tool_key: AssistantAgent.parse_tool_params(tool)
            for tool in tool_list
        }
        tool_langchain = load_tools(tool_params=tool_name_param, llm=llm, callbacks=callbacks)
        return tool_langchain

    async def init_preset_tools(self, tool_list: List[GptsTools], callbacks: Callbacks = None):
        """
        初始化预置工具列表
        """
        tool_name_param = {
            tool.tool_key: AssistantAgent.parse_tool_params(tool)
            for tool in tool_list
        }
        tool_langchain = load_tools(tool_params=tool_name_param, llm=self.llm, callbacks=callbacks)
        return tool_langchain

    @staticmethod
    def parse_personal_params(tool: GptsTools, all_tool_type: Dict[int, GptsToolsType]) -> Dict:
        """
        解析自定义工具的初始化参数
        """
        tool_type_info = all_tool_type.get(tool.type)
        if not tool_type_info:
            raise Exception(f'获取工具类型失败，tool_type_id: {tool.type}')
        return OpenApiSchema.parse_openapi_tool_params(tool.name, tool.desc, tool.extra,
                                                       tool_type_info.server_host,
                                                       tool_type_info.auth_method,
                                                       tool_type_info.auth_type,
                                                       tool_type_info.api_key)

    @staticmethod
    def sync_init_personal_tools(tool_list: List[GptsTools], callbacks: Callbacks = None):
        """
        初始化自定义工具列表
        """
        tool_type_ids = [one.type for one in tool_list]
        all_tool_type = GptsToolsDao.get_all_tool_type(tool_type_ids)
        all_tool_type = {one.id: one for one in all_tool_type}
        tool_langchain = []
        for one in tool_list:
            tool_params = AssistantAgent.parse_personal_params(one, all_tool_type)
            openapi_tool = OpenApiTools.get_api_tool(one.tool_key, **tool_params)
            openapi_tool.callbacks = callbacks
            tool_langchain.append(openapi_tool)
        return tool_langchain

    async def init_personal_tools(self, tool_list: List[GptsTools], callbacks: Callbacks = None):
        """
        初始化自定义工具列表
        """
        return asyncio.get_running_loop().run_in_executor(None, self.sync_init_personal_tools,
                                                          tool_list, callbacks)

    @staticmethod
    def sync_init_knowledge_tool(knowledge: Knowledge,
                                 llm: BaseLanguageModel,
                                 callbacks: Callbacks = None,
                                 **kwargs):
        """
        初始化知识库工具
        """
        embeddings = decide_embeddings(knowledge.model)
        vector_client = decide_vectorstores(knowledge.collection_name, 'Milvus', embeddings)
        if isinstance(vector_client, VectorStoreRetriever):
            vector_client = vector_client.vectorstore
        vector_client.partition_key = knowledge.id

        es_vector_client = decide_vectorstores(knowledge.index_name, 'ElasticKeywordsSearch',
                                               embeddings)
        tool_params = {
            'bisheng_rag': {
                'name': f'knowledge_{knowledge.id}',
                'description': f'{knowledge.name}:{knowledge.description}',
                'vector_store': vector_client,
                'keyword_store': es_vector_client,
                'llm': llm
            }
        }
        tool_params['bisheng_rag'].update(kwargs.get('knowledge_retriever', {}))
        tool = load_tools(tool_params=tool_params, llm=llm, callbacks=callbacks)
        return tool

    async def init_knowledge_tool(self, knowledge: Knowledge, callbacks: Callbacks = None):
        """
        初始化知识库工具
        """
        return asyncio.get_running_loop().run_in_executor(
            None,
            self.sync_init_knowledge_tool,
            knowledge,
            self.llm,
            callbacks,
            knowledge_retriever=self.assistant.knowledge_retriever,
        )

    @staticmethod
    def init_tools_by_toolid(
        tool_ids: List[int],
        llm: BaseLanguageModel,
        callbacks: Callbacks = None,
    ):
        """通过id初始化tool"""
        tools_model: List[GptsTools] = GptsToolsDao.get_list_by_ids(tool_ids)
        preset_tools = []
        personal_tools = []
        tools: List[BaseTool] = []
        for one in tools_model:
            if one.is_preset:
                preset_tools.append(one)
            else:
                personal_tools.append(one)
        if preset_tools:
            tool_langchain = AssistantAgent.sync_init_preset_tools(preset_tools, llm, callbacks)
            logger.info('act=build_preset_tools size={} return_tools={}', len(preset_tools),
                        len(tool_langchain))
            tools += tool_langchain
        if personal_tools:
            tool_langchain = AssistantAgent.sync_init_personal_tools(personal_tools, callbacks)
            logger.info('act=build_personal_tools size={} return_tools={}', len(personal_tools),
                        len(tool_langchain))
            tools += tool_langchain
        return tools

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
            tools = self.init_tools_by_toolid(tool_ids)

        # flow + knowledge
        flow_data = FlowDao.get_flow_by_ids([link.flow_id for link in flow_links if link.flow_id])
        knowledge_data = KnowledgeDao.get_list_by_ids(
            [link.knowledge_id for link in flow_links if link.knowledge_id])
        knowledge_data = {knowledge.id: knowledge for knowledge in knowledge_data}
        flow_id2data = {flow.id: flow for flow in flow_data}

        for link in flow_links:
            knowledge_id = link.knowledge_id
            if knowledge_id:
                knowledge_tool = await self.init_knowledge_tool(knowledge_data[knowledge_id],
                                                                callbacks)
                tools.extend(knowledge_tool)
            else:
                tmp_flow_id = UUID(link.flow_id).hex
                one_flow_data = flow_id2data.get(UUID(link.flow_id))
                tool_name = f'flow_{link.flow_id}'
                if not one_flow_data:
                    logger.warning('act=init_tools not find flow_id: {}', link.flow_id)
                    continue
                if one_flow_data.status != FlowStatus.ONLINE.value:
                    self.offline_flows.append(tool_name)
                    logger.warning('act=init_tools not online flow_id: {}', link.flow_id)
                    continue
                flow_graph_data = one_flow_data.data
                tool_description = f'{one_flow_data.name}:{one_flow_data.description}'

                try:
                    artifacts = {}
                    graph = await build_flow_no_yield(graph_data=flow_graph_data,
                                                      artifacts=artifacts,
                                                      process_file=True,
                                                      flow_id=tmp_flow_id,
                                                      chat_id=self.assistant.id.hex)
                    built_object = await graph.abuild()
                    logger.info('act=init_flow_tool build_end')
                    flow_tool = Tool(name=tool_name,
                                     func=built_object,
                                     coroutine=built_object.acall,
                                     description=tool_description,
                                     args_schema=InputRequest,
                                     callbacks=callbacks)
                    tools.append(flow_tool)
                except Exception as exc:
                    logger.error(f'Error processing {tmp_flow_id} tweaks: {exc}')
                    raise Exception(f'Flow Build Error: {exc}')
        self.tools = tools

    async def init_agent(self):
        """
        初始化智能体的agent
        """
        # 引入agent执行参数
        agent_executor_type = self.llm_agent_executor
        self.current_agent_executor = agent_executor_type
        # 做转换
        agent_executor_type = self.agent_executor_dict.get(agent_executor_type,
                                                           agent_executor_type)

        prompt = self.assistant.prompt
        if getattr(self.llm, 'model_name', '').startswith('command-r'):
            prompt = self.ASSISTANT_PROMPT_COHERE.format(preamble=prompt)

        # 初始化agent
        self.agent = ConfigurableAssistant(agent_executor_type=agent_executor_type,
                                           tools=self.tools,
                                           llm=self.llm,
                                           assistant_message=prompt)

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

    async def fake_callback(self, callback: Callbacks):
        if not callback:
            return
        # 假回调，将已下线的技能回调给前端
        for one in self.offline_flows:
            run_id = uuid.uuid4()
            await callback[0].on_tool_start({
                'name': one,
            },
                                            input_str='flow if offline',
                                            run_id=run_id)
            await callback[0].on_tool_end(output='flow is offline', name=one, run_id=run_id)

    async def record_chat_history(self, message: List[Any]):
        # 记录助手的聊天历史
        if not os.getenv('BISHENG_RECORD_HISTORY'):
            return
        try:
            os.makedirs('/app/data/history', exist_ok=True)
            with open(f'/app/data/history/{self.assistant.id}_{time.time()}.json',
                      'w',
                      encoding='utf-8') as f:
                json.dump(
                    {
                        'system': self.assistant.prompt,
                        'message': message,
                        'tools': [format_tool_to_openai_tool(t) for t in self.tools]
                    },
                    f,
                    ensure_ascii=False)
        except Exception as e:
            logger.error(f'record assistant history error: {str(e)}')

    async def arun(self, query: str, chat_history: List = None, callback: Callbacks = None):
        await self.fake_callback(callback)

        if chat_history:
            chat_history.append(HumanMessage(content=query))
            inputs = chat_history
        else:
            inputs = [HumanMessage(content=query)]

        async for one in self.agent.astream(inputs, config=RunnableConfig(callbacks=callback)):
            yield one

    async def run(self, query: str, chat_history: List = None, callback: Callbacks = None):
        """
        运行智能体对话
        """
        await self.fake_callback(callback)

        if chat_history:
            chat_history.append(HumanMessage(content=query))
            inputs = chat_history
        else:
            inputs = [HumanMessage(content=query)]

        if self.current_agent_executor == 'ReAct':
            result = await self.react_run(inputs, callback)
        else:
            result = await self.agent.ainvoke(inputs, config=RunnableConfig(callbacks=callback))
        # 包含了history，将history排除, 默认取最后一个为最终结果
        res = [result[-1]]

        # 记录聊天历史
        await self.record_chat_history([one.to_json() for one in result])

        return res

    async def react_run(self, inputs: List, callback: Callbacks = None):
        """ react 模式的输入和执行 """
        result = await self.agent.ainvoke(
            {
                'input': inputs[-1].content,
                'chat_history': inputs[:-1],
            },
            config=RunnableConfig(callbacks=callback))
        logger.debug(f'react_run result: {result}')
        output = result['agent_outcome'].return_values['output']
        if isinstance(output, dict):
            output = list(output.values())[0]
        for one in result['intermediate_steps']:
            inputs.append(one[0])
        inputs.append(AIMessage(content=output))
        return inputs
