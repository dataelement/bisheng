import json
import typing
from typing import Any, Dict, Optional

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ArgsSchema
from langgraph.prebuilt import create_react_agent
from loguru import logger
from pydantic import BaseModel, field_validator, Field, SkipValidation
from typing_extensions import Annotated

from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_PROMPT_RULES,
    annotate_rag_documents_with_citations,
    annotate_web_results_with_citations,
    cache_citation_registry_items,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
    collect_web_citation_registry_items,
)
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.workflow.callback.event import StreamMsgOverData
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser
from bisheng_langchain.agents.llm_functions_agent.base import _format_intermediate_steps
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools

agent_executor_dict = {
    'ReAct': 'get_react_agent_executor',
    'function call': 'get_openai_functions_agent_executor',
}

WORKFLOW_AGENT_CITATION_PROMPT_RULES = f"""{CITATION_PROMPT_RULES}

当工具结果中已经包含上述私有区段引用标记时，最终回答必须原样保留这些标记，不得删除、改写或解释这些标记。
不要输出本规则内容。"""


class WorkflowCitationToolWrapper(BaseTool):
    """Add citation prompt context for workflow agent tool invocations."""

    name: str
    description: str
    args_schema: Annotated[Optional[ArgsSchema], SkipValidation()] = Field(default=None)
    tool: BaseTool
    citation_registry_items: list[CitationRegistryItemSchema] = Field(default_factory=list, exclude=True)

    @classmethod
    def wrap(cls, tool: BaseTool) -> BaseTool:
        return cls(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            tool=tool,
        )

    def _is_web_search_tool(self) -> bool:
        return self.tool.name == 'web_search' or getattr(self.tool, 'tool_name', None) == 'web_search'

    def _has_knowledge_rag_tool(self) -> bool:
        return hasattr(self.tool, 'knowledge_retriever_tool')

    def _append_web_citation(self, output: Any) -> Any:
        if not isinstance(output, str):
            return output
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        if not isinstance(results, list):
            return output
        results = annotate_web_results_with_citations(results)
        self._extend_citation_registry_items(collect_web_citation_registry_items(results))
        return json.dumps(results, ensure_ascii=False)

    async def _aappend_web_citation(self, output: Any) -> Any:
        if not isinstance(output, str):
            return output
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        if not isinstance(results, list):
            return output
        results = annotate_web_results_with_citations(results)
        await self._aextend_citation_registry_items(collect_web_citation_registry_items(results))
        return json.dumps(results, ensure_ascii=False)

    def _build_knowledge_prompt(self) -> ChatPromptTemplate:
        messages = list(self.tool.chat_prompt.messages)
        citation_rules_message = SystemMessagePromptTemplate.from_template(CITATION_PROMPT_RULES)
        insert_index = 1 if messages and isinstance(messages[0], SystemMessagePromptTemplate) else 0
        messages.insert(insert_index, citation_rules_message)
        return ChatPromptTemplate.from_messages(messages)

    def _build_knowledge_inputs(self, query: str, retrieval_result: Any) -> dict:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        self._extend_citation_registry_items(collect_rag_citation_registry_items(source_documents))
        inputs = {'context': source_documents}
        if 'question' in self.tool.chat_prompt.input_variables:
            inputs['question'] = query
        return inputs

    async def _abuild_knowledge_inputs(self, query: str, retrieval_result: Any) -> dict:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        await self._aextend_citation_registry_items(collect_rag_citation_registry_items(source_documents))
        inputs = {'context': source_documents}
        if 'question' in self.tool.chat_prompt.input_variables:
            inputs['question'] = query
        return inputs

    def _extend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        cache_citation_registry_items_sync(items)
        self.citation_registry_items.extend(items)

    async def _aextend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        await cache_citation_registry_items(items)
        self.citation_registry_items.extend(items)

    def _run(self, query: str, config: RunnableConfig = None, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            return self._append_web_citation(self.tool.invoke({'query': query}, config=config))
        if not self._has_knowledge_rag_tool():
            return self.tool.invoke({'query': query}, config=config)

        retrieval_result = self.tool.knowledge_retriever_tool.invoke({'query': query}, config=config)
        llm_inputs = self._build_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return qa_chain.invoke(llm_inputs, config=config)

    async def _arun(self, query: str, config: RunnableConfig = None, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            return await self._aappend_web_citation(await self.tool.ainvoke({'query': query}, config=config))
        if not self._has_knowledge_rag_tool():
            return await self.tool.ainvoke({'query': query}, config=config)

        retrieval_result = await self.tool.knowledge_retriever_tool.ainvoke({'query': query}, config=config)
        llm_inputs = await self._abuild_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return await qa_chain.ainvoke(llm_inputs, config=config)


class SqlAgentParams(BaseModel):
    """ SQL Agent Param Model """
    database_engine: typing.Optional[str] = Field("mysql",
                                                  description="Database type, supportmysql, db2, postgres, gaussdb, oracle")
    db_username: str
    db_password: str
    db_address: str
    db_name: str
    open: bool = False

    @field_validator("database_engine")
    @classmethod
    def validate_database_engine(cls, v):
        # Convert to lowercase
        if v:
            v = v.lower()
            if v not in ['mysql', 'db2', 'postgres', 'gaussdb', 'oracle', 'postgresql']:
                raise ValueError(
                    "Unsupported database engine. Supported engines are: MySQL, DB2, PostgreSql, GaussDB, Oracle.")
        return v


class AgentNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Determine if it is a single or batch
        self._tab = self.node_data.tab['value']

        # analyzingprompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()

        self._image_prompt = self.node_params.get('image_prompt', [])

        self._batch_variable_list = []
        self._system_prompt_list = []
        self._user_prompt_list = []
        self._tool_invoke_list = []
        self._log_reasoning_content = []
        self._chat_history_messages: list[BaseMessage] = []

        # Chat Message
        self._chat_history_flag = self.node_params['chat_history_flag']['value'] > 0
        self._chat_history_num = self.node_params['chat_history_flag']['value']

        self._llm = LLMService.get_bisheng_llm_sync(model_id=self.node_params['model_id'],
                                                    temperature=self.node_params.get('temperature', 1),
                                                    app_id=self.workflow_id,
                                                    app_name=self.workflow_name,
                                                    app_type=ApplicationTypeEnum.WORKFLOW,
                                                    user_id=self.user_id)

        # Whether to output the results to the user
        self._output_user = self.node_params.get('output_user', False)

        # tools
        self._tools = self.node_params['tool_list']

        # knowledge
        # self._knowledge_ids = self.node_params['knowledge_id']
        # Determine whether it is a knowledge base or a temporary file list
        self._knowledge_type = self.node_params['knowledge_id']['type']
        self._knowledge_ids = [
            one['key'] for one in self.node_params['knowledge_id']['value']
        ]

        # Supported or notnl2sql
        self._sql_agent_params = self.node_params.get('sql_agent', None)
        self._sql_agent = SqlAgentParams.model_validate(self.node_params['sql_agent']) if (
                self._sql_agent_params and self._sql_agent_params.get("open", False)) else None
        self._sql_address = ''
        if self._sql_agent and self._sql_agent.open:
            self._sql_address = self._init_sql_address()

        # agent
        self._agent_executor_type = 'React'
        self._agent = None
        self._citation_tools: list[WorkflowCitationToolWrapper] = []

    def _get_chat_history_messages(self) -> list[BaseMessage]:
        if not self._chat_history_flag:
            return []
        if not self._chat_history_num:
            return list(self._chat_history_messages)
        return self._chat_history_messages[-self._chat_history_num:]

    def _append_chat_history_messages(self, messages: list[BaseMessage]) -> None:
        if not messages:
            return
        self._chat_history_messages.extend(messages)

    def _init_agent(self, system_prompt: str):
        # Get a list of configured helper models
        assistant_llm = LLMService.sync_get_assistant_llm()
        if not assistant_llm.llm_list:
            raise Exception('Assistant reasoning model list is empty')
        default_llm = [
            one for one in assistant_llm.llm_list if one.model_id == self.node_params['model_id']
        ]
        if not default_llm:
            raise Exception('The selected inference model is not in the list of assistant inference models')
        default_llm = default_llm[0]
        self._agent_executor_type = default_llm.agent_executor_type
        knowledge_retriever = {
            'max_content': default_llm.knowledge_max_content,
            'sort_by_source_and_index': default_llm.knowledge_sort_index
        }

        func_tools = self._init_tools()
        knowledge_tools = self._init_knowledge_tools(knowledge_retriever)
        sql_agent_tools = self.init_sql_agent_tool()
        func_tools.extend(knowledge_tools)
        func_tools.extend(sql_agent_tools)
        func_tools = self._wrap_citation_tools(func_tools)
        self._citation_tools = [tool for tool in func_tools if isinstance(tool, WorkflowCitationToolWrapper)]
        if self._has_citation_tools(func_tools):
            system_prompt = f'{system_prompt}\n\n{WORKFLOW_AGENT_CITATION_PROMPT_RULES}'
        if self._agent_executor_type == 'ReAct':
            self._agent = ConfigurableAssistant(
                agent_executor_type=agent_executor_dict.get(self._agent_executor_type),
                tools=func_tools,
                llm=self._llm,
                assistant_message=system_prompt,
            )
        else:
            self._agent = create_react_agent(self._llm, func_tools, prompt=system_prompt, checkpointer=False)

    @classmethod
    def _wrap_citation_tools(cls, tools: list[BaseTool]) -> list[BaseTool]:
        return [cls._wrap_citation_tool(tool) for tool in tools]

    @staticmethod
    def _wrap_citation_tool(tool: BaseTool) -> BaseTool:
        if tool.name == 'web_search' or hasattr(tool, 'knowledge_retriever_tool'):
            return WorkflowCitationToolWrapper.wrap(tool)
        return tool

    @staticmethod
    def _has_citation_tools(tools: list[BaseTool]) -> bool:
        return any(isinstance(tool, WorkflowCitationToolWrapper) for tool in tools)

    def _init_tools(self):
        if self._tools:
            tool_ids = [int(one['key']) for one in self._tools]
            return ToolExecutor.init_by_tool_ids_sync(tool_ids, app_id=self.workflow_id, app_name=self.workflow_name,
                                                      app_type=ApplicationTypeEnum.WORKFLOW,
                                                      user_id=self.user_id)
        else:
            return []

    def init_sql_agent_tool(self):
        if not self._sql_address:
            return []
        tool_params = {
            'sql_agent': {
                'llm': self._llm,
                'sql_address': self._sql_address
            }
        }
        return load_tools(tool_params=tool_params, llm=self._llm)

    def _init_knowledge_tools(self, knowledge_retriever: dict):
        if not self._knowledge_ids:
            return []
        tools = []
        for index, knowledge_id in enumerate(self._knowledge_ids):
            if self._knowledge_type == 'knowledge':
                knowledge_tool = ToolExecutor.init_knowledge_tool_sync(self.user_id, knowledge_id,
                                                                       llm=self._llm,
                                                                       **knowledge_retriever)
                tools.append(knowledge_tool)
            else:
                file_metadata_list = self.get_other_node_variable(knowledge_id)
                if not file_metadata_list:
                    # Do not retrieve if no file has been uploaded
                    continue
                description = ''
                for one in file_metadata_list:
                    description += f'<{one.get("document_name")}>:<{one.get("abstract")}>; '
                tool_init_params = {
                    "name": f'{knowledge_id.split(".")[-1].replace("#", "")}_knowledge_{index}',
                    "description": description,
                    "vector_retriever": self.init_file_milvus(file_metadata_list[0]),
                    "elastic_retriever": self.init_file_es(file_metadata_list[0]),
                    "llm": self._llm,
                    **knowledge_retriever
                }
                tmp_file_tool = ToolExecutor.init_tmp_knowledge_tool_sync(**tool_init_params)
                tools.append(tmp_file_tool)
        return tools

    def init_file_milvus(self, file_metadata: Dict) -> BaseRetriever:
        """ Initialize the temporary file selected by the usermilvus """
        embeddings = LLMService.get_knowledge_default_embedding(self.user_id)
        if not embeddings:
            raise Exception('No default configuredembeddingModels')
        file_ids = [file_metadata['document_id']]
        collection_name = self.get_milvus_collection_name(getattr(embeddings, 'model_id'))
        vector_client = KnowledgeRag.init_milvus_vectorstore(collection_name=collection_name, embeddings=embeddings)
        return vector_client.as_retriever(
            search_kwargs={"expr": f'document_id in {file_ids}'})

    def init_file_es(self, file_metadata: Dict):
        es_client = KnowledgeRag.init_es_vectorstore_sync(index_name=self.tmp_collection_name)
        return es_client.as_retriever(
            search_kwargs={"filter": [{"term": {"metadata.document_id": file_metadata['document_id']}}]})

    def _init_sql_address(self) -> str:
        """ Inisialisasi SQL Database Address """
        if not self._sql_agent:
            return ''
        if self._sql_agent.database_engine == 'mysql':
            try:
                pass
            except ImportError:
                raise ImportError('Please install pymysql and sqlalchemy to use mysql database')
            return f'mysql+pymysql://{self._sql_agent.db_username}:{self._sql_agent.db_password}@{self._sql_agent.db_address}/{self._sql_agent.db_name}?charset=utf8mb4'
        elif self._sql_agent.database_engine == 'db2':
            try:
                pass
            except ImportError:
                raise ImportError('Please install ibm_db and ibm_db_sa to use db2 database')
            return f'db2+ibm_db://{self._sql_agent.db_username}:{self._sql_agent.db_password}@{self._sql_agent.db_address}/{self._sql_agent.db_name}'
        elif self._sql_agent.database_engine in ['postgres', 'postgresql']:
            try:
                pass
            except ImportError:
                raise ImportError('Please install psycopg2 and sqlalchemy to use postgresql database')
            return f'postgresql+psycopg2://{self._sql_agent.db_username}:{self._sql_agent.db_password}@{self._sql_agent.db_address}/{self._sql_agent.db_name}'
        elif self._sql_agent.database_engine == 'gaussdb':
            try:
                pass
            except ImportError:
                raise ImportError('Please install psycopg2 and opengauss_sqlalchemy to use gaussdb database')
            return f'opengauss+psycopg2://{self._sql_agent.db_username}:{self._sql_agent.db_password}@{self._sql_agent.db_address}/{self._sql_agent.db_name}'
        elif self._sql_agent.database_engine == 'oracle':
            try:
                pass
            except ImportError:
                raise ImportError('Please install oracledb and sqlalchemy to use oracle database')
            return f'oracle+oracledb://{self._sql_agent.db_username}:{self._sql_agent.db_password}@{self._sql_agent.db_address}?service_name={self._sql_agent.db_name}'
        else:
            raise ValueError(f'Unsupported database engine: {self._sql_agent.database_engine}')

    def _run(self, unique_id: str):
        ret = {}
        variable_map = {}

        self._batch_variable_list = []
        self._system_prompt_list = []
        self._user_prompt_list = []
        self._tool_invoke_list = []
        self._log_reasoning_content = []

        for one in self._system_variables:
            variable_map[one] = self.get_other_node_variable(one)
        system_prompt = self._system_prompt.format(variable_map)
        self._system_prompt_list.append(system_prompt)
        self._init_agent(system_prompt)

        if self._tab == 'single':
            self._tool_invoke_list.append([])
            ret['output'], reasoning_content, citation_items = self._run_once(
                None,
                unique_id,
                'output',
                self._tool_invoke_list[0],
            )
            self._log_reasoning_content.append(reasoning_content)
            if self._output_user:
                self.callback_manager.on_stream_over(StreamMsgOverData(node_id=self.id,
                                                                       name=self.name,
                                                                       msg=ret['output'],
                                                                       reasoning_content=reasoning_content,
                                                                       unique_id=unique_id,
                                                                       output_key='output',
                                                                       citation_registry_items=citation_items))
        else:
            for index, one in enumerate(self.node_params['batch_variable']):
                self._batch_variable_list.append(self.get_other_node_variable(one))
                output_key = self.node_params['output'][index]['key']
                self._tool_invoke_list.append([])
                ret[output_key], reasoning_content, citation_items = self._run_once(
                    one,
                    unique_id,
                    output_key,
                    self._tool_invoke_list[index],
                )
                self._log_reasoning_content.append(reasoning_content)
                if self._output_user:
                    self.callback_manager.on_stream_over(StreamMsgOverData(node_id=self.id,
                                                                           name=self.name,
                                                                           msg=ret[output_key],
                                                                           reasoning_content=reasoning_content,
                                                                           unique_id=unique_id,
                                                                           output_key=output_key,
                                                                           citation_registry_items=citation_items))

        logger.debug('agent_over result={}', ret)
        if self._output_user:
            # Nonstream Mode, processing results
            for k, v in ret.items():
                answer = v
                self.graph_state.save_context(content=answer, msg_sender='AI')

        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        index = 0
        for k, v in result.items():
            one_ret = [
                {"key": "system_prompt", "value": self._system_prompt_list[0], "type": "params"},
                {"key": "user_prompt", "value": self._user_prompt_list[index], "type": "params"},
            ]
            if self._batch_variable_list:
                one_ret.insert(0,
                               {"key": "batch_variable", "value": self._batch_variable_list[index], "type": "variable"})

            # Handler Call Log
            one_ret.extend(self.parse_tool_log(self._tool_invoke_list[index]))
            if self._log_reasoning_content[index]:
                one_ret.append(
                    {"key": "Thinking about content", "value": self._log_reasoning_content[index], "type": "params"})
            one_ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
            ret.append(one_ret)
            index += 1
        return ret

    def parse_tool_log(self, tool_invoke_list: list) -> list:
        ret = []
        tool_invoke_info = {}
        for one in tool_invoke_list:
            if one['run_id'] not in tool_invoke_info:
                tool_invoke_info[one['run_id']] = {}
            if one['type'] == 'start':
                tool_invoke_info[one['run_id']].update({
                    'name': one['name'],
                    'input': one['input']
                })
            elif one['type'] == 'end':
                tool_invoke_info[one['run_id']].update({
                    'output': one['output']
                })
            elif one['type'] == 'error':
                tool_invoke_info[one['run_id']].update({
                    'output': f'Error: {one["error"]}'
                })
        if tool_invoke_info:
            tool_logs = list(tool_invoke_info.values())
            tool_logs = self._dedupe_web_search_tool_logs(tool_logs)
            for one in tool_logs:
                # knowledge_retriever_tool belong into rag logic，not show in tool log
                if one["name"] == "knowledge_retriever_tool":
                    continue
                ret.append({
                    "key": one["name"],
                    "value": f"Tool Input:\n {one['input']}, Tool Output:\n {one['output']}",
                    "type": "tool"
                })
        return ret

    @staticmethod
    def _is_web_search_log(tool_log: dict) -> bool:
        name = tool_log.get('name')
        return name == 'web_search' or name == '联网搜索'

    @staticmethod
    def _has_citation_key(output: Any) -> bool:
        return isinstance(output, str) and '"citation_key"' in output

    @classmethod
    def _dedupe_web_search_tool_logs(cls, tool_logs: list[dict]) -> list[dict]:
        web_search_indexes = [
            index for index, item in enumerate(tool_logs)
            if cls._is_web_search_log(item)
        ]
        if len(web_search_indexes) <= 1:
            return tool_logs

        cited_indexes = [
            index for index in web_search_indexes
            if cls._has_citation_key(tool_logs[index].get('output'))
        ]
        if not cited_indexes:
            return tool_logs

        keep_index = cited_indexes[-1]
        return [
            item for index, item in enumerate(tool_logs)
            if index == keep_index or index not in web_search_indexes
        ]

    def _run_once(self, input_variable: str = None, unique_id: str = None, output_key: str = None,
                  tool_invoke_list: list = None) -> (str, str, list[CitationRegistryItemSchema]):
        """
        params:
            input_variable: Input variables, if yesbatchthen you need to pass in a variablekey, otherwiseNone
            unique_id: Node Execute Uniqueid
            output_key: Output Variableskey
            tool_invoke_list: Tool Call Log
        return:
            0: Output results to user
            1: Process of model thinking
        """
        # Description is a variable that references a batch, The value of the variable needs to be replaced with the variable selected by the user
        special_variable = f'{self.id}.batch_variable'
        variable_map = {}
        for one in self._user_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.get_other_node_variable(input_variable)
                continue
            variable_map[one] = self.get_other_node_variable(one)
        user = self._user_prompt.format(variable_map)
        self._user_prompt_list.append(user)

        chat_history: list[BaseMessage] = []
        if self._chat_history_flag:
            chat_history = self._get_chat_history_messages()

        llm_callback = LLMNodeCallbackHandler(callback=self.callback_manager,
                                              unique_id=unique_id,
                                              node_id=self.id,
                                              node_name=self.name,
                                              output=self._output_user,
                                              output_key=output_key,
                                              tool_list=tool_invoke_list,
                                              cancel_llm_end=True)
        config = RunnableConfig(callbacks=[llm_callback])
        human_message = HumanMessage(content=[{
            'type': 'text',
            'text': user
        }])
        human_message = self.contact_file_into_prompt(human_message, self._image_prompt)
        chat_history.append(human_message)
        logger.debug(f'agent invoke chat_history: {chat_history}')
        self._reset_citation_registry_items()

        if self._agent_executor_type == 'ReAct':
            result = self._agent.invoke({
                'input': chat_history[-1].content,
                'chat_history': chat_history[:-1],
            }, config=config)
            output = result['agent_outcome'].return_values['output']
            if isinstance(output, dict):
                output = list(output.values())[0]
            round_messages = [human_message]
            round_messages.extend(_format_intermediate_steps(result.get('intermediate_steps', [])))
            round_messages.append(AIMessage(content=output))
            self._append_chat_history_messages(round_messages)
            return output, llm_callback.reasoning_content, self._collect_citation_registry_items()
        else:
            result = self._agent.invoke({'messages': chat_history}, config=config)
            result_messages = result['messages']
            new_messages = [human_message]
            if len(result_messages) > len(chat_history):
                new_messages.extend(result_messages[len(chat_history):])
            self._append_chat_history_messages(new_messages)
            return result_messages[-1].content, llm_callback.reasoning_content, self._collect_citation_registry_items()

    def _reset_citation_registry_items(self) -> None:
        for tool in self._citation_tools:
            tool.citation_registry_items = []

    def _collect_citation_registry_items(self) -> list[CitationRegistryItemSchema]:
        items: list[CitationRegistryItemSchema] = []
        for tool in self._citation_tools:
            items.extend(tool.citation_registry_items)
        return items
