from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import jwt
from bisheng_langchain.utils.requests import Requests
from langchain.callbacks.manager import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain.chat_models.base import BaseChatModel
from langchain.schema import ChatGeneration, ChatResult
from langchain.schema.messages import (AIMessage, BaseMessage, ChatMessage, FunctionMessage,
                                       HumanMessage, SystemMessage)
from langchain.utils import get_from_dict_or_env
from langchain_core.pydantic_v1 import Field, root_validator
from tenacity import (before_sleep_log, retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

# if TYPE_CHECKING:
#     import jwt

logger = logging.getLogger(__name__)


def _import_pyjwt() -> Any:
    try:
        import jwt
    except ImportError:
        raise ValueError('Could not import jwt python package. '
                         'This is needed in order to calculate get_token_ids. '
                         'Please install it with `pip install PyJWT`.')
    return jwt


def encode_jwt_token(ak, sk):
    headers = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'iss': ak,
        'exp': int(time.time()) + 18000,  # 填写您期望的有效时间，此处示例代表当前时间+300分钟
        'nbf': int(time.time()) - 500  # 填写您期望的生效时间，此处示例代表当前时间-500秒
    }
    token = jwt.encode(payload, sk, headers=headers)
    return token


def _create_retry_decorator(llm):

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
        content = _dict['content'] or ''  # OpenAI returns None for tool invocations

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
    elif isinstance(message, SystemMessage):
        message_dict = {'role': 'system', 'content': message.content}
        # raise ValueError(f"not support system role {message}")

    elif isinstance(message, FunctionMessage):
        raise ValueError(f'not support funciton {message}')
    else:
        raise ValueError(f'Got unknown type {message}')

    # if "name" in message.additional_kwargs:
    #     message_dict["name"] = message.additional_kwargs["name"]
    return message_dict


def _convert_message_to_dict2(message: BaseMessage) -> List[dict]:
    if isinstance(message, ChatMessage):
        message_dict = {'role': message.role, 'content': message.content}
    elif isinstance(message, HumanMessage):
        message_dict = {'role': 'user', 'content': message.content}
    elif isinstance(message, AIMessage):
        message_dict = {'role': 'assistant', 'content': message.content}
    elif isinstance(message, SystemMessage):
        raise ValueError(f'not support system role {message}')

    elif isinstance(message, FunctionMessage):
        raise ValueError(f'not support funciton {message}')
    else:
        raise ValueError(f'Got unknown type {message}')

    return [message_dict]


url = 'https://api.sensenova.cn/v1/llm/chat-completions'


class SenseChat(BaseChatModel):

    client: Optional[Any]  #: :meta private:
    model_name: str = Field(default='SenseChat', alias='model')
    """Model name to use."""
    temperature: float = 0.8
    top_p: float = 0.7
    """What sampling temperature to use."""
    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None

    repetition_penalty: float = 1.05
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

        _import_pyjwt()

        values['access_key_id'] = get_from_dict_or_env(values, 'access_key_id', 'ACCESS_KEY_ID')
        values['secret_access_key'] = get_from_dict_or_env(values, 'secret_access_key',
                                                           'SECRET_ACCESS_KEY')
        token = encode_jwt_token(values['access_key_id'], values['secret_access_key'])
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        try:
            header = {
                'Authorization': 'Bearer {}'.format(token),
                'Content-Type': 'application/json'
            }

            values['client'] = Requests(headers=header, )
        except AttributeError:
            raise ValueError('Try upgrading it with `pip install --upgrade requests`.')
        return values

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling ZhipuAI API."""
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
            # messages
            params = {
                'messages': messages,
                'model': self.model_name,
                'top_p': top_p,
                'temperature': temperature,
                'repetition_penalty': self.repetition_penalty,
                'n': self.n,
                'max_new_tokens': self.max_tokens,
                'stream': False  # self.streaming
            }

            token = encode_jwt_token(self.access_key_id, self.secret_access_key)
            if isinstance(token, bytes):
                token = token.decode('utf-8')
            self.client.headers.update({'Authorization': 'Bearer {}'.format(token)})

            response = self.client.post(url=url, json=params).json()
            return response

        rsp_dict = _completion_with_retry(**kwargs)
        if 'error' in rsp_dict:
            logger.error(f'sensechat_error resp={rsp_dict}')
            message = rsp_dict['error']['message']
            raise Exception(message)
        else:
            # return rsp_dict['data'], rsp_dict.get('usage', '')
            return rsp_dict, rsp_dict.get('usage', '')

    async def acompletion_with_retry(self, **kwargs: Any) -> Any:
        """Use tenacity to retry the async completion call."""
        retry_decorator = _create_retry_decorator(self)

        if self.streaming:
            self.client.headers.update({'Accept': 'text/event-stream'})
        else:
            self.client.headers.pop('Accept', '')

        @retry_decorator
        async def _acompletion_with_retry(**kwargs: Any) -> Any:
            messages = kwargs.pop('messages', '')

            inp = {
                'messages': messages,
                'model': self.model_name,
                'top_p': self.top_p,
                'temperature': self.temperature,
                'repetition_penalty': self.repetition_penalty,
                'n': self.n,
                'max_new_tokens': self.max_tokens,
                'stream': True
            }

            # Use OpenAI's async api https://github.com/openai/openai-python#async-api
            async with self.client.apost(url=url, json=inp) as response:

                async for line in response.content.iter_any():

                    if b'\n' in line:
                        for txt_ in line.split(b'\n'):
                            yield txt_.decode('utf-8').strip()
                    else:
                        yield line.decode('utf-8').strip()

        async for response in _acompletion_with_retry(**kwargs):
            is_error = False
            if response:
                if response.startswith('event:error'):
                    is_error = True
                elif response.startswith('data:'):
                    yield (is_error, response[len('data:'):])
                    if is_error:
                        break
                elif response.startswith('{'):
                    yield (is_error, response)
                else:
                    continue

    def _combine_llm_outputs(self, llm_outputs: List[Optional[dict]]) -> dict:
        overall_token_usage: dict = {}
        for output in llm_outputs:
            if output is None:
                # Happens in streaming
                continue
            token_usage = output['token_usage']
            for k, v in token_usage.items():
                if k in overall_token_usage:
                    overall_token_usage[k] += v
                else:
                    overall_token_usage[k] = v
        return {'token_usage': overall_token_usage, 'model_name': self.model_name}

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:

        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}
        response, usage = self.completion_with_retry(messages=message_dicts, **params)

        return self._create_chat_result(response)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}
        if self.streaming:

            inner_completion = ''
            role = 'user'
            params['stream'] = True
            function_call: Optional[dict] = None
            async for is_error, stream_resp in self.acompletion_with_retry(messages=message_dicts,
                                                                           **params):
                if str(stream_resp).startswith('[DONE]'):
                    continue
                output = json.loads(stream_resp)
                if is_error:
                    logger.error(stream_resp)
                    raise ValueError(stream_resp)
                if 'data' in output:
                    output = output['data']

                choices = None
                if 'choices' in output:
                    choices = output.get('choices')

                if choices:
                    for choice in choices:
                        token = choice['delta']

                        inner_completion += token or ''
                        _function_call = ''
                        if run_manager:
                            await run_manager.on_llm_new_token(token)
                        if _function_call:
                            if function_call is None:
                                function_call = _function_call
                            else:
                                function_call['arguments'] += _function_call['arguments']
            message = _convert_dict_to_message({
                'content': inner_completion,
                'role': role,
                'function_call': function_call,
            })
            return ChatResult(generations=[ChatGeneration(message=message)])
        else:
            return self._generate(messages, stop, run_manager, **kwargs)

    def _create_message_dicts(
            self, messages: List[BaseMessage],
            stop: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        params = dict(self._client_params)
        if stop is not None:
            if 'stop' in params:
                raise ValueError('`stop` found in both the input and default params.')
            params['stop'] = stop

        system_content = ''
        message_dicts = []
        for m in messages:
            if m.type == 'system':
                system_content += m.content
                continue
            message_dicts.extend(_convert_message_to_dict2(m))

        if system_content:
            message_dicts[-1]['content'] = system_content + message_dicts[-1]['content']

        return message_dicts, params

    def _create_chat_result(self, response: Mapping[str, Any]) -> ChatResult:
        generations = []

        def _norm_text(text):
            if text[0] == '"' and text[-1] == '"':
                out = eval(text)
            else:
                out = text
            return out

        for res in response['data']['choices']:
            res['content'] = _norm_text(res['message'])
            res['role'] = 'user'
            message = _convert_dict_to_message(res)
            gen = ChatGeneration(message=message)
            generations.append(gen)

        llm_output = {'token_usage': response['data']['usage'], 'model_name': self.model_name}
        return ChatResult(generations=generations, llm_output=llm_output)

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        return {**{'model_name': self.model_name}, **self._default_params}

    @property
    def _client_params(self) -> Mapping[str, Any]:
        """Get the parameters used for the openai client."""
        zhipu_creds: Dict[str, Any] = {
            'access_key_id': self.access_key_id,
            'secret_access_key': self.secret_access_key,
            'model': self.model_name,
        }
        return {**zhipu_creds, **self._default_params}

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
        return 'sense-chat'
