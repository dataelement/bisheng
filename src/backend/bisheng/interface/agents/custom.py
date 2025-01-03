from typing import Any, List, Optional, Sequence, Tuple, Union

from bisheng.interface.base import CustomAgentExecutor
from langchain.agents import (AgentExecutor, AgentType, BaseSingleActionAgent, Tool, ZeroShotAgent,
                              initialize_agent)
from langchain.agents.agent_toolkits.vectorstore.prompt import PREFIX as VECTORSTORE_PREFIX
from langchain.agents.agent_toolkits.vectorstore.prompt import \
    ROUTER_PREFIX as VECTORSTORE_ROUTER_PREFIX
from langchain.agents.agent_toolkits.vectorstore.toolkit import (VectorStoreInfo,
                                                                 VectorStoreRouterToolkit,
                                                                 VectorStoreToolkit)
from langchain.agents.mrkl.prompt import FORMAT_INSTRUCTIONS
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent
from langchain.agents.openai_tools.base import create_openai_tools_agent
from langchain.base_language import BaseLanguageModel
from langchain.chains import LLMChain
from langchain.memory.buffer import ConversationBufferMemory
from langchain.memory.chat_memory import BaseChatMemory
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.agent_toolkits.json.prompt import JSON_PREFIX, JSON_SUFFIX
from langchain_community.agent_toolkits.json.toolkit import JsonToolkit
from langchain_community.agent_toolkits.sql.prompt import SQL_PREFIX, SQL_SUFFIX
from langchain_community.tools.sql_database.prompt import QUERY_CHECKER
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.callbacks import BaseCallbackManager, Callbacks
from langchain_core.memory import BaseMemory
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.prompts.chat import (BaseMessagePromptTemplate, ChatPromptTemplate,
                                         HumanMessagePromptTemplate, MessagesPlaceholder)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_experimental.agents.agent_toolkits.pandas.prompt import PREFIX as PANDAS_PREFIX
from langchain_experimental.agents.agent_toolkits.pandas.prompt import \
    SUFFIX_WITH_DF as PANDAS_SUFFIX
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from pydantic import Field

history_prompt = """Below is a transcript of your chats:
{history}
"""


class JsonAgent(CustomAgentExecutor):
    """Json agent"""

    @staticmethod
    def function_name():
        return 'JsonAgent'

    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls.from_toolkit_and_llm(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_toolkit_and_llm(cls, toolkit: JsonToolkit, llm: BaseLanguageModel):
        tools = toolkit if isinstance(toolkit, list) else toolkit.get_tools()
        tool_names = {tool.name for tool in tools}
        prompt = ZeroShotAgent.create_prompt(
            tools,
            prefix=JSON_PREFIX,
            suffix=JSON_SUFFIX,
            format_instructions=FORMAT_INSTRUCTIONS,
            input_variables=None,
        )
        llm_chain = LLMChain(
            llm=llm,
            prompt=prompt,
        )
        agent = ZeroShotAgent(
            llm_chain=llm_chain,
            allowed_tools=tool_names  # type: ignore
        )
        return cls.from_agent_and_tools(agent=agent, tools=tools, verbose=True)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class CSVAgent(CustomAgentExecutor):
    """CSV agent"""

    @staticmethod
    def function_name():
        return 'CSVAgent'

    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls.from_toolkit_and_llm(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_toolkit_and_llm(
            cls,
            path: str,
            llm: BaseLanguageModel,
            pandas_kwargs: Optional[dict] = None,
            prefix: str = PANDAS_PREFIX,
            suffix: str = PANDAS_SUFFIX,
            format_instructions: str = FORMAT_INSTRUCTIONS,
            input_variables: Optional[List[str]] = ['df_head', 'input', 'agent_scratchpad'],
            **kwargs: Any):
        import pandas as pd  # type: ignore

        _kwargs = pandas_kwargs or {}
        df = pd.read_csv(path, **_kwargs)

        tools = [PythonAstREPLTool(locals={'df': df})]  # type: ignore
        prompt = ZeroShotAgent.create_prompt(
            tools,
            prefix=prefix,
            suffix=suffix,
            format_instructions=format_instructions,
            input_variables=input_variables,
        )
        partial_prompt = prompt.partial(df_head=str(df.head()))
        llm_chain = LLMChain(
            llm=llm,
            prompt=partial_prompt,
        )
        tool_names = {tool.name for tool in tools}
        agent = ZeroShotAgent(
            llm_chain=llm_chain,
            allowed_tools=tool_names,
            **kwargs  # type: ignore
        )

        return cls.from_agent_and_tools(agent=agent, tools=tools, verbose=True)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class VectorStoreAgent(CustomAgentExecutor):
    """Vector store agent"""

    @staticmethod
    def function_name():
        return 'VectorStoreAgent'

    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls.from_toolkit_and_llm(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_toolkit_and_llm(cls, llm: BaseLanguageModel, vectorstoreinfo: VectorStoreInfo,
                             **kwargs: Any):
        """Construct a vectorstore agent from an LLM and tools."""

        toolkit = VectorStoreToolkit(vectorstore_info=vectorstoreinfo, llm=llm)

        tools = toolkit.get_tools()
        prompt = ZeroShotAgent.create_prompt(tools, prefix=VECTORSTORE_PREFIX)
        llm_chain = LLMChain(
            llm=llm,
            prompt=prompt,
        )
        tool_names = {tool.name for tool in tools}
        agent = ZeroShotAgent(
            llm_chain=llm_chain,
            allowed_tools=tool_names,
            **kwargs  # type: ignore
        )
        return AgentExecutor.from_agent_and_tools(agent=agent,
                                                  tools=tools,
                                                  verbose=True,
                                                  handle_parsing_errors=True)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class SQLAgent(CustomAgentExecutor):
    """SQL agent"""

    @staticmethod
    def function_name():
        return 'SQLAgent'

    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls.from_toolkit_and_llm(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_toolkit_and_llm(cls,
                             llm: BaseLanguageModel,
                             database_uri: str,
                             top_k: int = 10,
                             prefix: str = SQL_PREFIX,
                             suffix: str = SQL_SUFFIX,
                             format_instructions: str = FORMAT_INSTRUCTIONS,
                             input_variables: Optional[List[str]] = ['input', 'agent_scratchpad'],
                             **kwargs: Any):
        """Construct an SQL agent from an LLM and tools."""
        db = SQLDatabase.from_uri(database_uri)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        # The right code should be this, but there is a problem with tools = toolkit.get_tools()
        # related to `OPENAI_API_KEY`
        # return create_sql_agent(llm=llm, toolkit=toolkit, verbose=True)
        from langchain.prompts import PromptTemplate
        from langchain.tools.sql_database.tool import (
            InfoSQLDatabaseTool,
            ListSQLDatabaseTool,
            QuerySQLCheckerTool,
            QuerySQLDataBaseTool,
        )

        llmchain = LLMChain(
            llm=llm,
            prompt=PromptTemplate(template=QUERY_CHECKER, input_variables=['query', 'dialect']),
        )

        tools = [
            QuerySQLDataBaseTool(db=db),  # type: ignore
            InfoSQLDatabaseTool(db=db),  # type: ignore
            ListSQLDatabaseTool(db=db),  # type: ignore
            QuerySQLCheckerTool(db=db, llm_chain=llmchain, llm=llm),  # type: ignore
        ]

        prefix = prefix.format(dialect=toolkit.dialect, top_k=top_k)
        prompt = ZeroShotAgent.create_prompt(
            tools=tools,  # type: ignore
            prefix=prefix,
            suffix=suffix,
            format_instructions=format_instructions,
            input_variables=input_variables,
        )
        llm_chain = LLMChain(
            llm=llm,
            prompt=prompt,
        )
        tool_names = {tool.name for tool in tools}  # type: ignore
        agent = ZeroShotAgent(
            llm_chain=llm_chain,
            allowed_tools=tool_names,
            **kwargs  # type: ignore
        )
        return AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,  # type: ignore
            verbose=True,
            max_iterations=15,
            early_stopping_method='force',
            handle_parsing_errors=True,
        )

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class VectorStoreRouterAgent(CustomAgentExecutor):
    """Vector Store Router Agent"""

    @staticmethod
    def function_name():
        return 'VectorStoreRouterAgent'

    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls.from_toolkit_and_llm(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def from_toolkit_and_llm(cls, llm: BaseLanguageModel,
                             vectorstoreroutertoolkit: VectorStoreRouterToolkit, **kwargs: Any):
        """Construct a vector store router agent from an LLM and tools."""

        tools = (vectorstoreroutertoolkit if isinstance(vectorstoreroutertoolkit, list) else
                 vectorstoreroutertoolkit.get_tools())
        prompt = ZeroShotAgent.create_prompt(tools, prefix=VECTORSTORE_ROUTER_PREFIX)
        llm_chain = LLMChain(
            llm=llm,
            prompt=prompt,
        )
        tool_names = {tool.name for tool in tools}
        agent = ZeroShotAgent(
            llm_chain=llm_chain,
            allowed_tools=tool_names,
            **kwargs  # type: ignore
        )
        return AgentExecutor.from_agent_and_tools(agent=agent,
                                                  tools=tools,
                                                  verbose=True,
                                                  handle_parsing_errors=True)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class OpenAIToolsAgent(OpenAIFunctionsAgent):
    """OpenAI Tools Agent"""

    memory: BaseMemory = Field(default_factory=ConversationBufferMemory)
    agent: Any

    @property
    def input_keys(self) -> List[str]:
        """Get input keys. Input refers to user input here."""
        return ['input', 'history']

    def plan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        with_functions: bool = True,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        input_dict = {'intermediate_steps': intermediate_steps}
        selected_inputs = {
            k: kwargs[k]
            for k in self.prompt.input_variables if k != 'agent_scratchpad'
        }
        input_dict.update(selected_inputs)
        return self.agent.invoke(input_dict, config=RunnableConfig(callbacks=callbacks))

    async def aplan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        input_dict = {'intermediate_steps': intermediate_steps}
        selected_inputs = {
            k: kwargs[k]
            for k in self.prompt.input_variables if k != 'agent_scratchpad'
        }
        input_dict.update(selected_inputs)
        return await self.agent.ainvoke(input_dict, config=RunnableConfig(callbacks=callbacks))

    @classmethod
    def create_prompt(
        cls,
        system_message: Optional[SystemMessage] = SystemMessage(
            content='You are a helpful AI assistant.'),
        extra_prompt_messages: Optional[List[BaseMessagePromptTemplate]] = None,
    ) -> ChatPromptTemplate:
        """Create prompt for this agent.

        Args:
            system_message: Message to use as the system message that will be the
                first in the prompt.
            extra_prompt_messages: Prompt messages that will be placed between the
                system message and the new human input.

        Returns:
            A prompt template to pass into this agent.
        """
        _prompts = extra_prompt_messages or []
        messages: List[Union[BaseMessagePromptTemplate, BaseMessage]]
        if system_message:
            messages = [system_message]
        else:
            messages = []

        messages.extend([
            *_prompts,
            MessagesPlaceholder(variable_name='agent_scratchpad'),
        ])
        return ChatPromptTemplate(messages=messages)  # type: ignore[arg-type, call-arg]

    @classmethod
    def from_llm_and_tools(
        cls,
        llm: BaseLanguageModel,
        tools: Sequence[BaseTool],
        callback_manager: Optional[BaseCallbackManager] = None,
        extra_prompt: str = history_prompt,
        human_prompt: str = '{input}',
        system_message: str = 'You are a helpful AI assistant.',
        **kwargs: Any,
    ) -> BaseSingleActionAgent:
        """Construct an agent from an LLM and tools.

        Args:
            llm: The LLM to use as the agent.
            tools: The tools to use.
            callback_manager: The callback manager to use. Defaults to None.
            extra_prompt_messages: Extra prompt messages to use. Defaults to None.
            system_message: The system message to use.
                Defaults to a default system message.
            kwargs: Additional parameters to pass to the agent.
        """
        system_message_prompt = SystemMessage(content=system_message)
        extra_prompt_messages = [HumanMessagePromptTemplate.from_template(extra_prompt)]
        extra_prompt_messages.extend([HumanMessagePromptTemplate.from_template(human_prompt)])
        prompt = cls.create_prompt(system_message=system_message_prompt,
                                   extra_prompt_messages=extra_prompt_messages)
        agent = create_openai_tools_agent(llm, tools, prompt)
        return cls(  # type: ignore[call-arg]
            llm=llm,
            agent=agent,
            prompt=prompt,
            tools=tools,
            callback_manager=callback_manager,
            **kwargs,
        )

    @classmethod
    def initialize(
        cls,
        llm: BaseLanguageModel,
        tools: Sequence[BaseTool],
        callback_manager: Optional[BaseCallbackManager] = None,
        extra_prompt: str = history_prompt,
        human_prompt: str = '{input}',
        system_message: str = 'You are a helpful AI assistant.',
        memory: Optional[BaseChatMemory] = None,
        **kwargs: Any,
    ):
        agent = cls.from_llm_and_tools(
            llm,
            tools,
            callback_manager,
            extra_prompt,
            human_prompt,
            system_message,
            memory=memory,
            **kwargs,
        )
        return AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            verbose=True,
            memory=memory,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
        )


class InitializeAgent(CustomAgentExecutor):
    """Implementation of AgentInitializer function"""

    @staticmethod
    def function_name():
        return 'AgentInitializer'

    @classmethod
    def initialize(
        cls,
        llm: BaseLanguageModel,
        tools: List[Tool],
        agent: str,
        memory: Optional[BaseChatMemory] = None,
    ):
        # Find which value in the AgentType enum corresponds to the string
        # passed in as agent
        if agent == 'openai-tools':
            agent = OpenAIToolsAgent.from_llm_and_tools(
                llm,
                tools,
                memory=memory,
                return_intermediate_steps=True,
                handle_parsing_errors=True,
            )
            return AgentExecutor.from_agent_and_tools(
                agent=agent,
                tools=tools,
                memory=memory,
                return_intermediate_steps=True,
                handle_parsing_errors=True,
            )
        agent = AgentType(agent)
        return initialize_agent(
            tools=tools,
            llm=llm,
            # LangChain now uses Enum for agent, but we still support string
            agent=agent,  # type: ignore
            memory=memory,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


# custom agents must initialize with initialize method
CUSTOM_AGENTS = {
    'JsonAgent': JsonAgent,
    'CSVAgent': CSVAgent,
    'AgentInitializer': InitializeAgent,
    'VectorStoreAgent': VectorStoreAgent,
    'VectorStoreRouterAgent': VectorStoreRouterAgent,
    'SQLAgent': SQLAgent,
    'OpenAIToolsAgent': OpenAIToolsAgent,
}
