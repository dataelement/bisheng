"""Module implements an agent that uses OpenAI's APIs function enabled API."""
import json
from json import JSONDecodeError
from typing import Any, List, Optional, Sequence, Tuple, Union

from pydantic import model_validator

from bisheng_langchain.chat_models.host_llm import HostQwenChat
from bisheng_langchain.chat_models.proxy_llm import ProxyChatLLM
from langchain.agents import BaseSingleActionAgent
from langchain.callbacks.base import BaseCallbackManager
from langchain.callbacks.manager import Callbacks
from langchain.prompts.chat import (BaseMessagePromptTemplate, ChatPromptTemplate,
                                    HumanMessagePromptTemplate, MessagesPlaceholder)
from langchain.schema import AgentAction, AgentFinish, BasePromptTemplate, OutputParserException
from langchain.schema.language_model import BaseLanguageModel
from langchain.schema.messages import AIMessage, BaseMessage, FunctionMessage, SystemMessage
from langchain.tools import BaseTool
from langchain.tools.convert_to_openai import format_tool_to_openai_function
from langchain_core.agents import AgentActionMessageLog
from langchain_openai import ChatOpenAI


def _convert_agent_action_to_messages(agent_action: AgentAction,
                                      observation: str) -> List[BaseMessage]:
    """Convert an agent action to a message.

    This code is used to reconstruct the original AI message from the agent action.

    Args:
        agent_action: Agent action to convert.

    Returns:
        AIMessage that corresponds to the original tool invocation.
    """
    if isinstance(agent_action, AgentActionMessageLog):
        return list(
            agent_action.message_log) + [_create_function_message(agent_action, observation)]
    else:
        return [AIMessage(content=agent_action.log)]


def _create_function_message(agent_action: AgentAction, observation: str) -> FunctionMessage:
    """Convert agent action and observation into a function message.
    Args:
        agent_action: the tool invocation request from the agent
        observation: the result of the tool invocation
    Returns:
        FunctionMessage that corresponds to the original tool invocation
    """
    if not isinstance(observation, str):
        try:
            content = json.dumps(observation, ensure_ascii=False)
        except Exception:
            content = str(observation)
    else:
        content = observation
    return FunctionMessage(
        name=agent_action.tool,
        content=content,
    )


def _format_intermediate_steps(
    intermediate_steps: List[Tuple[AgentAction, str]], ) -> List[BaseMessage]:  # noqa
    """Format intermediate steps.
    Args:
        intermediate_steps: Steps the LLM has taken to date, along with observations
    Returns:
        list of messages to send to the LLM for the next prediction
    """
    messages = []

    for intermediate_step in intermediate_steps:
        agent_action, observation = intermediate_step
        messages.extend(_convert_agent_action_to_messages(agent_action, observation))

    return messages


def _parse_ai_message(message: BaseMessage) -> Union[AgentAction, AgentFinish]:
    """Parse an AI message."""
    if not isinstance(message, AIMessage):
        raise TypeError(f'Expected an AI message got {type(message)}')

    function_call = message.additional_kwargs.get('tool_calls', {})

    if function_call:
        function_name = function_call['name']
        try:
            _tool_input = json.loads(function_call['arguments'])
        except JSONDecodeError:
            raise OutputParserException(f'Could not parse tool input: {function_call} because '
                                        f'the `arguments` is not valid JSON.')

        # HACK HACK HACK:
        # The code that encodes tool input into Open AI uses a special variable
        # name called `__arg1` to handle old style tools that do not expose a
        # schema and expect a single string argument as an input.
        # We unpack the argument here if it exists.
        # Open AI does not support passing in a JSON array as an argument.
        if '__arg1' in _tool_input:
            tool_input = _tool_input['__arg1']
        else:
            tool_input = _tool_input

        content_msg = 'responded: {content}\n' if message.content else '\n'
        log = f'\nInvoking: `{function_name}` with `{tool_input}`\n{content_msg}\n'
        return AgentActionMessageLog(
            tool=function_name,
            tool_input=tool_input,
            log=log,
            message_log=[message],
        )

    return AgentFinish(return_values={'output': message.content}, log=message.content)


class LLMFunctionsAgent(BaseSingleActionAgent):
    """An Agent driven by function powered API.

    Args:
        llm: This should be an instance of ChatOpenAI, specifically a model
            that supports using `functions`.
        tools: The tools this agent has access to.
        prompt: The prompt for this agent, should support agent_scratchpad as one
            of the variables. For an easy way to construct this prompt, use
            `OpenAIFunctionsAgent.create_prompt(...)`
    """

    llm: BaseLanguageModel
    tools: Sequence[BaseTool]
    prompt: BasePromptTemplate

    def get_allowed_tools(self) -> List[str]:
        """Get allowed tools."""
        return list([t.name for t in self.tools])

    @model_validator(mode='before')
    @classmethod
    def validate_llm(cls, values: dict) -> dict:
        if ((not isinstance(values['llm'], ChatOpenAI))
                and (not isinstance(values['llm'], HostQwenChat))
                and (not isinstance(values['llm'], ProxyChatLLM))):
            raise ValueError(
                'Only supported with ChatOpenAI and HostQwenChat and ProxyChatLLM models.')
        return values

    @model_validator(mode='before')
    @classmethod
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
    def functions(self) -> List[dict]:
        return [dict(format_tool_to_openai_function(t)) for t in self.tools]

    def plan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        with_functions: bool = True,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        """Given input, decided what to do.

        Args:
            intermediate_steps: Steps the LLM has taken to date, along with observations
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        agent_scratchpad = _format_intermediate_steps(intermediate_steps)
        selected_inputs = {
            k: kwargs[k]
            for k in self.prompt.input_variables if k != 'agent_scratchpad'
        }
        full_inputs = dict(**selected_inputs, agent_scratchpad=agent_scratchpad)
        prompt = self.prompt.format_prompt(**full_inputs)
        messages = prompt.to_messages()
        # print(messages)
        if with_functions:
            predicted_message = self.llm.predict_messages(
                messages,
                functions=self.functions,
                callbacks=callbacks,
            )
        else:
            predicted_message = self.llm.predict_messages(
                messages,
                callbacks=callbacks,
            )
        agent_decision = _parse_ai_message(predicted_message)
        return agent_decision

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
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        agent_scratchpad = _format_intermediate_steps(intermediate_steps)
        selected_inputs = {
            k: kwargs[k]
            for k in self.prompt.input_variables if k != 'agent_scratchpad'
        }
        full_inputs = dict(**selected_inputs, agent_scratchpad=agent_scratchpad)
        prompt = self.prompt.format_prompt(**full_inputs)
        messages = prompt.to_messages()
        predicted_message = await self.llm.apredict_messages(messages,
                                                             functions=self.functions,
                                                             callbacks=callbacks)
        agent_decision = _parse_ai_message(predicted_message)
        return agent_decision

    def return_stopped_response(
        self,
        early_stopping_method: str,
        intermediate_steps: List[Tuple[AgentAction, str]],
        **kwargs: Any,
    ) -> AgentFinish:
        """Return response when agent has been stopped due to max iterations."""
        if early_stopping_method == 'force':
            # `force` just returns a constant string
            return AgentFinish({'output': 'Agent stopped due to iteration limit or time limit.'},
                               '')
        elif early_stopping_method == 'generate':
            # Generate does one final forward pass
            agent_decision = self.plan(intermediate_steps, with_functions=False, **kwargs)
            if type(agent_decision) == AgentFinish:
                return agent_decision
            else:
                raise ValueError(f'got AgentAction with no functions provided: {agent_decision}')
        else:
            raise ValueError('early_stopping_method should be one of `force` or `generate`, '
                             f'got {early_stopping_method}')

    @classmethod
    def create_prompt(
        cls,
        system_message: Optional[SystemMessage] = SystemMessage(
            content='You are a helpful AI assistant.'),
        extra_prompt_messages: Optional[List[BaseMessagePromptTemplate]] = None,
    ) -> BasePromptTemplate:
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
            HumanMessagePromptTemplate.from_template('{input}'),
            MessagesPlaceholder(variable_name='agent_scratchpad'),
        ])
        return ChatPromptTemplate(messages=messages)

    @classmethod
    def from_llm_and_tools(
        cls,
        llm: BaseLanguageModel,
        tools: Sequence[BaseTool],
        callback_manager: Optional[BaseCallbackManager] = None,
        extra_prompt_messages: Optional[List[BaseMessagePromptTemplate]] = None,
        system_message: Optional[SystemMessage] = SystemMessage(
            content='You are a helpful AI assistant.'),
        **kwargs: Any,
    ) -> BaseSingleActionAgent:
        """Construct an agent from an LLM and tools."""
        if ((not isinstance(llm, ChatOpenAI)) and (not isinstance(llm, HostQwenChat))
                and (not isinstance(llm, ProxyChatLLM))):
            raise ValueError(
                'Only supported with ChatOpenAI and HostQwenChat and ProxyChatLLM models.')
        prompt = cls.create_prompt(
            extra_prompt_messages=extra_prompt_messages,
            system_message=system_message,
        )
        return cls(
            llm=llm,
            prompt=prompt,
            tools=tools,
            callback_manager=callback_manager,
            **kwargs,
        )
