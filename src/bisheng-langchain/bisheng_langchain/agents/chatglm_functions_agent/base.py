import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from bisheng_langchain.chat_models.host_llm import HostChatGLM
from langchain.agents.agent import Agent, AgentOutputParser, BaseSingleActionAgent
from langchain.agents.structured_chat.output_parser import StructuredChatOutputParserWithRetries
from langchain.agents.structured_chat.prompt import FORMAT_INSTRUCTIONS, PREFIX, SUFFIX
from langchain.callbacks.base import BaseCallbackManager
from langchain.callbacks.manager import Callbacks
from langchain.prompts.chat import (ChatPromptTemplate, HumanMessagePromptTemplate,
                                    SystemMessagePromptTemplate)
from langchain.schema import AgentAction, AgentFinish, BasePromptTemplate
from langchain.schema.language_model import BaseLanguageModel
from langchain.schema.messages import ChatMessage
from langchain.tools import BaseTool, StructuredTool
from langchain_core.pydantic_v1 import Field, root_validator

HUMAN_MESSAGE_TEMPLATE = '{input}\n\n{agent_scratchpad}'


def format_tool_to_chatglm_function(tool: BaseTool):
    """Format tool into the chatglm function API."""
    if isinstance(tool, StructuredTool):
        schema_ = tool.args_schema.schema()
        # Bug with required missing for structured tools.
        required = sorted(schema_['properties'])  # BUG WORKAROUND
        return {
            'name': tool.name,
            'description': tool.description,
            'parameters': {
                'type': 'object',
                'properties': schema_['properties'],
                'required': required,
            },
        }
    else:
        if tool.args_schema:
            schema_ = tool.args_schema.schema()
            parameters = {
                'type': 'object',
                'properties': schema_['properties'],
                'required': list(schema_['properties'].keys()),
            }
        else:
            parameters = {
                # This is a hack to get around the fact that some tools
                # do not expose an args_schema, and expect an argument
                # which is a string.
                # And Open AI does not support an array type for the
                # parameters.
                'type': 'object',
                'properties': {
                    '__arg1': {
                        'type': 'string',
                        'title': '__arg1'
                    },
                },
                'required': ['__arg1'],
            }

        return {
            'name': tool.name,
            'description': tool.description,
            'parameters': parameters,
        }


class ChatglmFunctionsAgent(BaseSingleActionAgent):
    """Chatglm Functions Agent."""

    llm: BaseLanguageModel
    tools: Sequence[BaseTool]
    prompt: BasePromptTemplate
    output_parser: AgentOutputParser = Field(default_factory=StructuredChatOutputParserWithRetries)
    """Output parser for the agent."""
    has_search: bool = False
    history: List = []

    def get_allowed_tools(self) -> List[str]:
        """Get allowed tools."""
        return list([t.name for t in self.tools])

    @root_validator
    def validate_llm(cls, values: dict) -> dict:
        if not isinstance(values['llm'], HostChatGLM):
            raise ValueError('Only supported with ChatGLM3 models.')
        return values

    @root_validator
    def validate_prompt(cls, values: dict) -> dict:
        prompt: BasePromptTemplate = values['prompt']
        if 'agent_scratchpad' not in prompt.input_variables:
            raise ValueError('`agent_scratchpad` should be one of the variables in the prompt, '
                             f'got {prompt.input_variables}')
        return values

    @property
    def input_keys(self) -> List[str]:
        """Get input keys. Input refers to user input here."""
        return ['input']

    @property
    def observation_prefix(self) -> str:
        """Prefix to append the observation with."""
        return 'Observation: '

    @property
    def llm_prefix(self) -> str:
        """Prefix to append the llm call with."""
        return 'Thought:'

    def _construct_scratchpad(self, intermediate_steps: List[Tuple[AgentAction, str]]) -> str:
        agent_scratchpad = ''
        for action, observation in intermediate_steps:
            agent_scratchpad += action.log
            agent_scratchpad += f'\n{self.observation_prefix}{observation}\n{self.llm_prefix}'
        if not isinstance(agent_scratchpad, str):
            raise ValueError('agent_scratchpad should be of type string.')
        if agent_scratchpad:
            return (f'This was your previous work '
                    f"(but I haven't seen any of it! I only see what "
                    f'you return as final answer):\n{agent_scratchpad}')
        else:
            return agent_scratchpad

    @classmethod
    def _validate_tools(cls, tools: Sequence[BaseTool]) -> None:
        pass

    @classmethod
    def _get_default_output_parser(cls,
                                   llm: Optional[BaseLanguageModel] = None,
                                   **kwargs: Any) -> AgentOutputParser:
        return StructuredChatOutputParserWithRetries.from_llm(llm=llm)

    @property
    def _stop(self) -> List[str]:
        return ['Observation:']

    def _tool_history(self, prompt: str):
        ans = []
        tools_json = []
        for i, tool in enumerate(self.tools):
            tool_config = format_tool_to_chatglm_function(tool)
            tools_json.append(tool_config)

        ans.append({
            'role': 'system',
            'content':
            'Answer the following questions as best as you can. You have access to the following tools:',
            'tools': tools_json
        })
        query = f"""{prompt.split("Human: ")[-1].strip()}"""
        return ans, query

    def _extract_observation(self, prompt: str):
        return_json = prompt.split('Observation: ')[-1].split('\nThought:')[0]
        self.history.append({'role': 'observation', 'content': return_json})
        return

    def _extract_tool(self):
        tool_names = list([t.name for t in self.tools])
        if self.history[-1]['metadata'] and len(self.history[-1]['metadata']) > 0:
            metadata = self.history[-1]['metadata']
            content = self.history[-1]['content']
            if 'tool_call' in content:
                for tool in tool_names:
                    if tool in metadata:
                        input_para = content.split("='")[-1].split("'")[0]
                        action_json = {'action': tool, 'action_input': input_para}
                        self.has_search = True
                        return f"""
Action:
```
{json.dumps(action_json, ensure_ascii=False)}
```"""

        final_answer_json = {'action': 'Final Answer', 'action_input': self.history[-1]['content']}
        self.has_search = False
        return f"""
Action:
```
{json.dumps(final_answer_json, ensure_ascii=False)}
```"""

    def get_full_inputs(self, intermediate_steps: List[Tuple[AgentAction, str]],
                        **kwargs: Any) -> Dict[str, Any]:
        """Create the full inputs for the LLMChain from intermediate steps."""
        thoughts = self._construct_scratchpad(intermediate_steps)
        new_inputs = {'agent_scratchpad': thoughts, 'stop': self._stop}
        full_inputs = {**kwargs, **new_inputs}
        return full_inputs

    def plan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        """Given input, decided what to do.

        Args:
            intermediate_steps: Steps the LLM has taken to date,
                along with observations
            callbacks: Callbacks to run.
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        full_inputs = self.get_full_inputs(intermediate_steps, **kwargs)
        prompt = self.prompt.format_prompt(**full_inputs)
        prompt = prompt.to_string()
        if not self.has_search:
            self.history, query = self._tool_history(prompt)
        else:
            self._extract_observation(prompt)
            query = ''
        self.history.append({'role': 'user', 'content': query})

        chat_messages = []
        for message in self.history:
            additional_kwargs = dict()
            for key in message.keys():
                if key not in ['role', 'content']:
                    additional_kwargs[key] = message[key]
            chat_messages.append(
                ChatMessage(role=message['role'],
                            content=message['content'],
                            additional_kwargs=additional_kwargs))

        predicted_message = self.llm.predict_messages(chat_messages, callbacks=callbacks)
        self.history.append({
            'role': 'assistant',
            'content': predicted_message.content,
            'metadata': predicted_message.additional_kwargs['metadata']
        })
        full_output = self._extract_tool()
        return self.output_parser.parse(full_output)

    async def aplan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        """Given input, decided what to do.

        Args:
            intermediate_steps: Steps the LLM has taken to date,
                along with observations
            callbacks: Callbacks to run.
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        full_inputs = self.get_full_inputs(intermediate_steps, **kwargs)
        prompt = self.prompt.format_prompt(**full_inputs)
        prompt = prompt.to_string()
        if not self.has_search:
            self.history, query = self._tool_history(prompt)
        else:
            self._extract_observation(prompt)
            query = ''
        self.history.append({'role': 'user', 'content': query})

        chat_messages = []
        for message in self.history:
            additional_kwargs = dict()
            for key in message.keys():
                if key not in ['role', 'content']:
                    additional_kwargs[key] = message[key]
            chat_messages.append(
                ChatMessage(role=message['role'],
                            content=message['content'],
                            additional_kwargs=additional_kwargs))

        predicted_message = await self.llm.apredict_messages(chat_messages, callbacks=callbacks)
        self.history.append({
            'role': 'assistant',
            'content': predicted_message.content,
            'metadata': predicted_message.additional_kwargs['metadata']
        })
        full_output = self._extract_tool()
        return self.output_parser.parse(full_output)

    @classmethod
    def create_prompt(
        cls,
        tools: Sequence[BaseTool],
        prefix: str = PREFIX,
        suffix: str = SUFFIX,
        human_message_template: str = HUMAN_MESSAGE_TEMPLATE,
        format_instructions: str = FORMAT_INSTRUCTIONS,
        input_variables: Optional[List[str]] = None,
        memory_prompts: Optional[List[BasePromptTemplate]] = None,
    ) -> BasePromptTemplate:
        tool_strings = []
        for tool in tools:
            args_schema = re.sub('}', '}}}}', re.sub('{', '{{{{', str(tool.args)))
            tool_strings.append(f'{tool.name}: {tool.description}, args: {args_schema}')
        formatted_tools = '\n'.join(tool_strings)
        tool_names = ', '.join([tool.name for tool in tools])
        format_instructions = format_instructions.format(tool_names=tool_names)
        template = '\n\n'.join([prefix, formatted_tools, format_instructions, suffix])
        if input_variables is None:
            input_variables = ['input', 'agent_scratchpad']
        _memory_prompts = memory_prompts or []
        messages = [
            SystemMessagePromptTemplate.from_template(template),
            *_memory_prompts,
            HumanMessagePromptTemplate.from_template(human_message_template),
        ]
        return ChatPromptTemplate(input_variables=input_variables, messages=messages)

    @classmethod
    def from_llm_and_tools(
        cls,
        llm: BaseLanguageModel,
        tools: Sequence[BaseTool],
        callback_manager: Optional[BaseCallbackManager] = None,
        output_parser: Optional[AgentOutputParser] = None,
        prefix: str = PREFIX,
        suffix: str = SUFFIX,
        human_message_template: str = HUMAN_MESSAGE_TEMPLATE,
        format_instructions: str = FORMAT_INSTRUCTIONS,
        input_variables: Optional[List[str]] = None,
        memory_prompts: Optional[List[BasePromptTemplate]] = None,
        **kwargs: Any,
    ) -> Agent:
        """Construct an agent from an LLM and tools."""
        cls._validate_tools(tools)
        prompt = cls.create_prompt(
            tools,
            prefix=prefix,
            suffix=suffix,
            human_message_template=human_message_template,
            format_instructions=format_instructions,
            input_variables=input_variables,
            memory_prompts=memory_prompts,
        )
        _output_parser = output_parser or cls._get_default_output_parser(llm=llm)
        return cls(
            llm=llm,
            prompt=prompt,
            tools=tools,
            output_parser=_output_parser,
            callback_manager=callback_manager,
            **kwargs,
        )

    @property
    def _agent_type(self) -> str:
        raise ValueError
