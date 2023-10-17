"""proxy llm chat wrapper."""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

# import requests
from langchain.callbacks.manager import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain.chat_models.base import BaseChatModel
from langchain.schema import ChatGeneration, ChatResult
from langchain.schema.messages import (AIMessage, BaseMessage, ChatMessage, FunctionMessage,
                                       HumanMessage, SystemMessage)
from langchain.utils import get_from_dict_or_env
from pydantic import Field, root_validator
from tenacity import (before_sleep_log, retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from .interface import MinimaxChatCompletion
from .interface.types import ChatInput

if TYPE_CHECKING:
    import tiktoken

logger = logging.getLogger(__name__)


def _import_tiktoken() -> Any:
    try:
        import tiktoken
    except ImportError:
        raise ValueError('Could not import tiktoken python package. '
                         'This is needed in order to calculate get_token_ids. '
                         'Please install it with `pip install tiktoken`.')
    return tiktoken


def _create_retry_decorator(llm: ChatMinimaxAI) -> Callable[[Any], Any]:

    min_seconds = 1
    max_seconds = 20
    # Wait 2^x * 1 second between each retry starting with
    # 4 seconds, then up to 10 seconds, then 10 seconds afterwards
    return retry(
        reraise=True,
        stop=stop_after_attempt(llm.max_retries),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=(retry_if_exception_type(Exception)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def _convert_dict_to_message(_dict: Mapping[str, Any]) -> BaseMessage:
    role = _dict['role']
    if role == 'user':
        return HumanMessage(content=_dict['content'])
    elif role == 'assistant':
        content = _dict[
            'content'] or ''  # OpenAI returns None for tool invocations
        if _dict.get('function_call'):
            additional_kwargs = {'function_call': dict(_dict['function_call'])}
        else:
            additional_kwargs = {}
        return AIMessage(content=content, additional_kwargs=additional_kwargs)
    elif role == 'system':
        return SystemMessage(content=_dict['content'])
    elif role == 'function':
        return FunctionMessage(content=_dict['content'], name=_dict['name'])
    else:
        return ChatMessage(content=_dict['content'], role=role)


def _convert_message_to_dict(message: BaseMessage) -> dict:
    if isinstance(message, ChatMessage):
        message_dict = {'role': message.role, 'content': message.content}
    elif isinstance(message, HumanMessage):
        message_dict = {'role': 'user', 'content': message.content}
    elif isinstance(message, AIMessage):
        message_dict = {'role': 'assistant', 'content': message.content}
        if 'function_call' in message.additional_kwargs:
            message_dict['function_call'] = message.additional_kwargs[
                'function_call']
    elif isinstance(message, SystemMessage):
        message_dict = {'role': 'system', 'content': message.content}
    elif isinstance(message, FunctionMessage):
        message_dict = {
            'role': 'function',
            'content': message.content,
            'name': message.name,
        }
    else:
        raise ValueError(f'Got unknown type {message}')
    if 'name' in message.additional_kwargs:
        message_dict['name'] = message.additional_kwargs['name']
    return message_dict


class ChatMinimaxAI(BaseChatModel):
    """Wrapper around proxy Chat large language models.

    To use, the environment variable ``ELEMAI_API_KEY`` set with your API key.

    Example:
        .. code-block:: python

            from bisheng_langchain.chat_models import ChatMinimaxAI
            chat_miniamaxai = ChatMinimaxAI(model_name="abab5.5-chat")
    """

    client: Optional[Any]  #: :meta private:
    """Model name to use."""
    model_name: str = Field('abab5.5-chat', alias='model')

    temperature: float = 0.9
    top_p: float = 0.95
    """What sampling temperature to use."""
    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""
    minimaxai_api_key: Optional[str] = None
    minimaxai_group_id: Optional[str] = None

    headers: Optional[Dict[str, str]] = Field(default_factory=dict)

    request_timeout: Optional[Union[float, Tuple[float, float]]] = None
    """Timeout for requests to OpenAI completion API. Default is 600 seconds."""
    max_retries: Optional[int] = 6
    """Maximum number of retries to make when generating."""
    streaming: Optional[bool] = False
    """Whether to stream the results or not."""
    n: Optional[int] = 1
    """Number of chat completions to generate for each prompt."""
    max_tokens: Optional[int] = 1024
    """Maximum number of tokens to generate."""
    tiktoken_model_name: Optional[str] = None
    """The model name to pass to tiktoken when using this class.
    Tiktoken is used to count the number of tokens in documents to constrain
    them to be under a certain limit. By default, when set to None, this will
    be the same as the embedding model name. However, there are some cases
    where you may want to use this Embedding class with a model name not
    supported by tiktoken. This can include when using Azure embeddings or
    when using one of the many model providers that expose an OpenAI-like
    API but with different models. In those cases, in order to avoid erroring
    when tiktoken is called, you can specify a model name to use here."""

    verbose: Optional[bool] = False

    class Config:
        """Configuration for this pydantic object."""

        allow_population_by_field_name = True

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values['minimaxai_api_key'] = get_from_dict_or_env(
            values, 'minimaxai_api_key', 'MINIMAXAI_API_KEY')

        values['minimaxai_group_id'] = get_from_dict_or_env(
            values, 'minimaxai_group_id', 'MINIMAXAI_GROUP_ID')

        api_key = values['minimaxai_api_key']
        group_id = values['minimaxai_group_id']
        try:
            values['client'] = MinimaxChatCompletion(group_id, api_key)
        except AttributeError:
            raise ValueError(
                'Try upgrading it with `pip install --upgrade requests`.')
        return values

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling ChatMinimaxAI API."""
        return {
            'model': self.model_name,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'max_tokens': self.max_tokens,
            **self.model_kwargs,
        }

    def completion_with_retry(self, **kwargs: Any) -> Any:
        retry_decorator = _create_retry_decorator(self)

        @retry_decorator
        def _completion_with_retry(**kwargs: Any) -> Any:
            messages = kwargs.get('messages')
            temperature = kwargs.get('temperature')
            top_p = kwargs.get('top_p')
            max_tokens = kwargs.get('max_tokens')
            params = {
                'messages': messages,
                'model': self.model_name,
                'top_p': top_p,
                'temperature': temperature,
                'max_tokens': max_tokens
            }
            return self.client(ChatInput.parse_obj(params),
                               self.verbose).dict()

        return _completion_with_retry(**kwargs)

    def _combine_llm_outputs(self, llm_outputs: List[Optional[dict]]) -> dict:
        overall_token_usage: dict = {}
        for output in llm_outputs:
            if output is None:
                # Happens in streaming
                continue
            token_usage = output['token_usage']
            if token_usage is None:
                continue

            for k, v in token_usage.items():
                if k in overall_token_usage:
                    overall_token_usage[k] += v
                else:
                    overall_token_usage[k] = v
        return {
            'token_usage': overall_token_usage,
            'model_name': self.model_name
        }

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}
        response = self.completion_with_retry(messages=message_dicts, **params)
        return self._create_chat_result(response)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)

    def _create_message_dicts(
        self, messages: List[BaseMessage], stop: Optional[List[str]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        params = dict(self._client_params)
        if stop is not None:
            if 'stop' in params:
                raise ValueError(
                    '`stop` found in both the input and default params.')
            params['stop'] = stop

        message_dicts = [_convert_message_to_dict(m) for m in messages]

        return message_dicts, params

    def _create_chat_result(self, response: Mapping[str, Any]) -> ChatResult:
        generations = []
        for res in response['choices']:
            message = _convert_dict_to_message(res['message'])
            gen = ChatGeneration(message=message)
            generations.append(gen)

        llm_output = {
            'token_usage': response['usage'],
            'model_name': self.model_name
        }
        return ChatResult(generations=generations, llm_output=llm_output)

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        return {**{'model_name': self.model_name}, **self._default_params}

    @property
    def _client_params(self) -> Mapping[str, Any]:
        """Get the parameters used for the client."""
        minimaxai_creds: Dict[str, Any] = {
            'model': self.model_name,
        }
        return {**minimaxai_creds, **self._default_params}

    def _get_invocation_params(self,
                               stop: Optional[List[str]] = None,
                               **kwargs: Any) -> Dict[str, Any]:
        """Get the parameters used to invoke the model FOR THE CALLBACKS."""
        return {
            **super()._get_invocation_params(stop=stop, **kwargs),
            **self._default_params,
            'model': self.model_name,
            'function': kwargs.get('functions'),
        }

    @property
    def _llm_type(self) -> str:
        """Return type of chat model."""
        return 'minimaxai_chat'

    def _get_encoding_model(self) -> Tuple[str, tiktoken.Encoding]:
        tiktoken_ = _import_tiktoken()
        if self.tiktoken_model_name is not None:
            model = self.tiktoken_model_name
        else:
            model = self.model_name
            # model chatglm-std, chatglm-lite
        # Returns the number of tokens used by a list of messages.
        try:
            encoding = tiktoken_.encoding_for_model(model)
        except KeyError:
            logger.warning(
                'Warning: model not found. Using cl100k_base encoding.')
            model = 'cl100k_base'
            encoding = tiktoken_.get_encoding(model)
        return model, encoding

    def get_token_ids(self, text: str) -> List[int]:
        """Get the tokens present in the text with tiktoken package."""
        # tiktoken NOT supported for Python 3.7 or below
        if sys.version_info[1] <= 7:
            return super().get_token_ids(text)
        _, encoding_model = self._get_encoding_model()
        return encoding_model.encode(text)

    def get_num_tokens_from_messages(self, messages: List[BaseMessage]) -> int:
        """Calculate num tokens for chatglm with tiktoken package.

        todo: read chatglm document
        Official documentation: https://github.com/openai/openai-cookbook/blob/
        main/examples/How_to_format_inputs_to_ChatGPT_models.ipynb"""
        if sys.version_info[1] <= 7:
            return super().get_num_tokens_from_messages(messages)
        model, encoding = self._get_encoding_model()
        if model.startswith('chatglm'):
            # every message follows <im_start>{role/name}\n{content}<im_end>\n
            tokens_per_message = 4
            # if there's a name, the role is omitted
            tokens_per_name = -1
        else:
            raise NotImplementedError(
                f'get_num_tokens_from_messages() is not presently implemented '
                f'for model {model}.'
                'See https://github.com/openai/openai-python/blob/main/chatml.md for '
                'information on how messages are converted to tokens.')
        num_tokens = 0
        messages_dict = [_convert_message_to_dict(m) for m in messages]
        for message in messages_dict:
            num_tokens += tokens_per_message
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == 'name':
                    num_tokens += tokens_per_name
        # every reply is primed with <im_start>assistant
        num_tokens += 3
        return num_tokens
