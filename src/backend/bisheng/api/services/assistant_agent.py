import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, ArgsSchema
from langchain_core.utils.function_calling import format_tool_to_openai_tool
from langgraph.prebuilt import create_react_agent
from loguru import logger
from pydantic import Field, SkipValidation
from typing_extensions import Annotated

from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_PROMPT_RULES,
    CitationRegistryCollector,
    annotate_rag_documents_with_citations,
    annotate_web_results_with_citations,
    cache_citation_registry_items,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
    collect_web_citation_registry_items,
)
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.assistant import AssistantModelEmptyError, AssistantModelNotConfigError, \
    AssistantAutoLLMError
from bisheng.database.models.assistant import Assistant, AssistantLink, AssistantLinkDao
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.auto_optimization import (generate_breif_description,
                                                      generate_opening_dialog,
                                                      optimize_assistant_prompt)
from bisheng_langchain.gpts.auto_tool_selected import ToolInfo, ToolSelector
from bisheng_langchain.gpts.prompts import ASSISTANT_PROMPT_OPT

ASSISTANT_CITATION_PROMPT_RULES = f"""{CITATION_PROMPT_RULES}

When the tool's results already contain the aforementioned private section reference markers, the final answer must retain these markers as is; they must not be deleted, rewritten, or interpreted.

Do not output this rule."""


def _without_callbacks(config: RunnableConfig | None) -> RunnableConfig | None:
    if not config:
        return config
    inner_config = dict(config)
    inner_config.pop('callbacks', None)
    return inner_config


def _invoke_tool_without_callbacks(tool: BaseTool, query: str, config: RunnableConfig | None) -> Any:
    if hasattr(tool, '_run'):
        return tool._run(query=query, config=_without_callbacks(config), run_manager=None)
    return tool.invoke({'query': query}, config=_without_callbacks(config))


async def _ainvoke_tool_without_callbacks(tool: BaseTool, query: str, config: RunnableConfig | None) -> Any:
    if hasattr(tool, '_arun'):
        return await tool._arun(query=query, config=_without_callbacks(config), run_manager=None)
    return await tool.ainvoke({'query': query}, config=_without_callbacks(config))


class AssistantCitationToolWrapper(BaseTool):
    """Add citation prompt context for assistant tool invocations."""

    name: str
    description: str
    args_schema: Annotated[Optional[ArgsSchema], SkipValidation()] = Field(default=None)
    tool: BaseTool
    citation_registry_items: List[CitationRegistryItemSchema] = Field(default_factory=list, exclude=True)
    citation_collector: Optional[CitationRegistryCollector] = Field(default=None, exclude=True)

    @classmethod
    def wrap(cls, tool: BaseTool, citation_collector: CitationRegistryCollector) -> BaseTool:
        return cls(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            tool=tool,
            citation_collector=citation_collector,
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

    def _extend_citation_registry_items(self, items: List[CitationRegistryItemSchema]) -> None:
        cache_citation_registry_items_sync(items)
        self.citation_registry_items.extend(items)
        if self.citation_collector:
            self.citation_collector.extend(items)

    async def _aextend_citation_registry_items(self, items: List[CitationRegistryItemSchema]) -> None:
        await cache_citation_registry_items(items)
        self.citation_registry_items.extend(items)
        if self.citation_collector:
            self.citation_collector.extend(items)

    def _run(self, query: str, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            return self._append_web_citation(
                _invoke_tool_without_callbacks(self.tool, query, kwargs.get('config'))
            )
        if not self._has_knowledge_rag_tool():
            return self.tool.invoke({'query': query}, config=kwargs.get('config'))

        retrieval_result = self.tool.knowledge_retriever_tool.invoke({'query': query})
        llm_inputs = self._build_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return qa_chain.invoke(llm_inputs)

    async def _arun(self, query: str, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            output = await _ainvoke_tool_without_callbacks(self.tool, query, kwargs.get('config'))
            return await self._aappend_web_citation(output)
        if not self._has_knowledge_rag_tool():
            return await self.tool.ainvoke({'query': query}, config=kwargs.get('config'))

        retrieval_result = await self.tool.knowledge_retriever_tool.ainvoke({'query': query})
        llm_inputs = await self._abuild_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return await qa_chain.ainvoke(llm_inputs)


class AssistantAgent(AssistantUtils):
    # cohereThe special needs of the model prompt
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
    - When there is time information involved in a question, such as recently6Months, yesterday, last year, etc., you need to use the time tool to query the time information.
    """  # noqa

    def __init__(self, assistant_info: Assistant, chat_id: str, invoke_user_id: int):
        self.assistant = assistant_info

        # To record the data tracking points
        self.invoke_user_id = invoke_user_id

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
        # Knowledge Base Retrieval Related Parameters
        self.knowledge_retriever = {'max_content': 15000, 'sort_by_source_and_index': False}
        self.citation_registry_collector = CitationRegistryCollector()

    async def init_assistant(self, callbacks: Callbacks = None):
        await self.init_llm()
        await self.init_tools(callbacks)
        await self.init_agent()

    async def init_llm(self):
        # Get a list of configured helper models
        assistant_llm = await LLMService.get_assistant_llm()
        if not assistant_llm.llm_list:
            raise AssistantModelEmptyError()
        default_llm = None
        for one in assistant_llm.llm_list:
            if str(one.model_id) == self.assistant.model_name:
                default_llm = one
                break
            elif not default_llm and one.default:
                default_llm = one
        if not default_llm:
            raise AssistantModelNotConfigError()

        self.llm_agent_executor = default_llm.agent_executor_type
        self.knowledge_retriever = {
            'max_content': default_llm.knowledge_max_content,
            'sort_by_source_and_index': default_llm.knowledge_sort_index
        }

        # Inisialisasillm
        self.llm = await LLMService.get_bisheng_llm(model_id=default_llm.model_id,
                                                    temperature=self.assistant.temperature,
                                                    streaming=default_llm.streaming,
                                                    app_id=self.assistant.id,
                                                    app_name=self.assistant.name,
                                                    app_type=ApplicationTypeEnum.ASSISTANT,
                                                    user_id=self.invoke_user_id)

    async def init_auto_update_llm(self):
        """ Initialize Automatic Optimization prompt and other information.llmInstances """
        assistant_llm = await LLMService.get_assistant_llm()
        if not assistant_llm.auto_llm:
            raise AssistantAutoLLMError()

        self.llm = await LLMService.get_bisheng_llm(model_id=assistant_llm.auto_llm.model_id,
                                                    temperature=self.assistant.temperature,
                                                    streaming=assistant_llm.auto_llm.streaming,
                                                    app_id=self.assistant.id,
                                                    app_name=self.assistant.name,
                                                    app_type=ApplicationTypeEnum.ASSISTANT,
                                                    user_id=self.invoke_user_id)

    async def init_tools(self, callbacks: Callbacks = None):
        """Get by nametool Vertical
           tools_name_param:: {name: params}
        """
        links: List[AssistantLink] = await AssistantLinkDao.get_assistant_link(
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
            tools = await ToolExecutor.init_by_tool_ids(tool_ids,
                                                        app_id=self.assistant.id,
                                                        app_name=self.assistant.name,
                                                        app_type=ApplicationTypeEnum.ASSISTANT,
                                                        user_id=self.invoke_user_id,
                                                        llm=self.llm,
                                                        callbacks=callbacks)

        for link in flow_links:
            knowledge_id = link.knowledge_id
            if knowledge_id:
                knowledge_tool = await ToolExecutor.init_knowledge_tool(self.invoke_user_id, knowledge_id, llm=self.llm,
                                                                        callbacks=callbacks,
                                                                        **self.knowledge_retriever)
                tools.append(knowledge_tool)
        self.tools = [self.wrap_citation_tool(tool) for tool in tools]

    def wrap_citation_tool(self, tool: BaseTool) -> BaseTool:
        if tool.name == 'web_search' or hasattr(tool, 'knowledge_retriever_tool'):
            return AssistantCitationToolWrapper.wrap(tool, self.citation_registry_collector)
        return tool

    def has_citation_tools(self) -> bool:
        return any(isinstance(tool, AssistantCitationToolWrapper) for tool in self.tools)

    def reset_citation_registry_items(self) -> None:
        """Clear citation items before one assistant run."""
        self.citation_registry_collector.clear()
        for tool in self.tools:
            if isinstance(tool, AssistantCitationToolWrapper):
                tool.citation_registry_items = []

    def collect_citation_registry_items(self) -> List[CitationRegistryItemSchema]:
        """Collect citation items emitted by wrapped tools."""
        items: List[CitationRegistryItemSchema] = []
        seen_keys: set[tuple[str, str | None]] = set()
        candidate_items = self.citation_registry_collector.list_items()
        for tool in self.tools:
            if isinstance(tool, AssistantCitationToolWrapper):
                candidate_items.extend(tool.citation_registry_items)
        for item in candidate_items:
            item_key = (item.citationId, item.itemId)
            if item_key in seen_keys:
                continue
            seen_keys.add(item_key)
            items.append(item)
        return items

    async def init_agent(self):
        """
        Initialize agentagent
        """
        # Introductionagentexecution parameter
        agent_executor_type = self.llm_agent_executor
        self.current_agent_executor = agent_executor_type
        # Do the Conversion
        agent_executor_type = self.agent_executor_dict.get(agent_executor_type,
                                                           agent_executor_type)

        prompt = self.assistant.prompt
        if getattr(self.llm, 'model_name', '').startswith('command-r'):
            prompt = self.ASSISTANT_PROMPT_COHERE.format(preamble=prompt)
        if self.has_citation_tools():
            prompt = f'{prompt}\n\n{ASSISTANT_CITATION_PROMPT_RULES}'
        if self.current_agent_executor == 'ReAct':
            # Inisialisasiagent
            self.agent = ConfigurableAssistant(agent_executor_type=agent_executor_type,
                                               tools=self.tools,
                                               llm=self.llm,
                                               assistant_message=prompt)
        else:
            # function-callingpattern, but also add recursive constraints
            logger.info(f'Creating LangGraph agent with {len(self.tools)} tools, llm type: {type(self.llm)}')
            logger.info(f'LLM streaming capability: {getattr(self.llm, "streaming", "unknown")}')

            self.agent = create_react_agent(self.llm, self.tools, prompt=prompt, checkpointer=False)
            logger.info(f'LangGraph agent created: {type(self.agent)}')

            # areagentAdd Recursive Limit Configuration
            self.agent = self.agent.with_config({'recursion_limit': 100})
            logger.info(f'Agent config applied: recursion_limit=100')

    async def optimize_assistant_prompt(self):
        """ Automatically optimize generationprompt """
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
        """ Generate opening dialogue and opening questions """
        return generate_opening_dialog(self.llm, prompt)

    def generate_description(self, prompt: str):
        """ Generate description dialog """
        return generate_breif_description(self.llm, prompt)

    def choose_tools(self, tool_list: List[Dict[str, str]], prompt: str) -> List[str]:
        """
         Choose A Tool
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
        # False callback to call back skills that are offline to the front-end
        for one in self.offline_flows:
            run_id = uuid.uuid4()
            await callback[0].on_tool_start({
                'name': one,
            },
                input_str='flow is offline',
                run_id=run_id)
            await callback[0].on_tool_end(output='flow is offline', name=one, run_id=run_id)

    async def record_chat_history(self, message: List[Any]):
        # Record Assistant Chat History
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

    async def trim_messages(self, messages: List[Any]) -> List[Any]:
        # Dapatkanencoding
        enc = self.cl100k_base()

        def get_finally_message(new_messages: List[Any]) -> List[Any]:
            # No more processing until only one record has been trimmed
            if len(new_messages) == 1:
                return new_messages
            total_count = 0
            for one in new_messages:
                if isinstance(one, HumanMessage):
                    total_count += len(enc.encode(one.content))
                elif isinstance(one, AIMessage):
                    total_count += len(enc.encode(one.content))
                    if 'tool_calls' in one.additional_kwargs:
                        total_count += len(
                            enc.encode(json.dumps(one.additional_kwargs['tool_calls'], ensure_ascii=False))
                        )
                else:
                    total_count += len(enc.encode(str(one.content)))
            if total_count > self.assistant.max_token:
                return get_finally_message(new_messages[1:])
            return new_messages

        return get_finally_message(messages)

    async def run(self, query: str, chat_history: List = None, callback: Callbacks = None) -> List[BaseMessage]:
        """
        Run Agent Conversation
        """
        await self.fake_callback(callback)

        if chat_history:
            chat_history.append(HumanMessage(content=query))
            inputs = chat_history
        else:
            inputs = [HumanMessage(content=query)]

        # trim message
        inputs = await self.trim_messages(inputs)

        if self.current_agent_executor == 'ReAct':
            result = await self.react_run(inputs, callback)
        else:
            result = await self.agent.ainvoke({'messages': inputs}, config=RunnableConfig(callbacks=callback))
            result = result['messages']

        # Record Chat History
        await self.record_chat_history([one.to_json() for one in result])

        return result

    async def astream(self, query: str, chat_history: List = None, callback: Callbacks = None):
        """
        Run Agent Conversation - Streaming version
        """
        await self.fake_callback(callback)

        if chat_history:
            chat_history.append(HumanMessage(content=query))
            inputs = chat_history
        else:
            inputs = [HumanMessage(content=query)]

        # trim message
        inputs = await self.trim_messages(inputs)

        if self.current_agent_executor == 'ReAct':
            # ReActMode temporarily does not support streaming, downgrade to non streaming
            result = await self.react_run(inputs, callback)
            # Record Chat History
            await self.record_chat_history([one.to_json() for one in result])
            yield result
        else:
            # Use Streaming Calls
            config = RunnableConfig(callbacks=callback)
            final_messages = []

            logger.info(f'Using function-calling mode, starting astream...')

            chunk_count = 0

            try:
                # UsemessagesPatternedLangGraph streamingattaintokenLevel of Streaming Output
                async for chunk in self.agent.astream({'messages': inputs}, config=config, stream_mode="messages"):
                    chunk_count += 1

                    # stream_mode="messages" Return (message, metadata) Meta Group
                    message = None
                    if isinstance(chunk, tuple) and len(chunk) >= 2:
                        message, metadata = chunk[:2]
                    elif hasattr(chunk, 'content'):
                        # Directly to the message object
                        message = chunk

                    if message:
                        # stream_mode="messages"Returns Independencechunk, use its content directly
                        final_messages = [message]  # Save message for history
                        yield [message]

            except Exception as astream_error:
                logger.exception(f'Error in astream async for loop: {str(astream_error)}')
                raise astream_error

            logger.info(f'Function calling astream completed, total chunks: {chunk_count}')

            if chunk_count == 0:
                logger.warning(f'No chunks received from agent.astream()! This indicates a streaming issue.')

            # Record Chat History
            if final_messages:
                await self.record_chat_history([one.to_json() for one in final_messages])

    async def react_run(self, inputs: List, callback: Callbacks = None):
        """ react Mode input and execution """
        result = await self.agent.ainvoke({
            'input': inputs[-1].content,
            'chat_history': inputs[:-1],
        }, config=RunnableConfig(callbacks=callback))
        logger.debug(f"react_run result: {result}")
        output = result['agent_outcome'].return_values['output']
        if isinstance(output, dict):
            output = list(output.values())[0]
        for one in result['intermediate_steps']:
            inputs.append(one[0])
        inputs.append(AIMessage(content=output))
        return inputs
