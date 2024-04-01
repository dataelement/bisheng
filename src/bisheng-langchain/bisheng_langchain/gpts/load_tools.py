import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from bisheng_langchain.gpts.tools.api_tools import ALL_API_TOOLS
from bisheng_langchain.gpts.tools.bing_search.tool import BingSearchRun
from bisheng_langchain.gpts.tools.calculator.tool import calculator
from bisheng_langchain.gpts.tools.code_interpreter.tool import CodeInterpreterTool
from bisheng_langchain.gpts.tools.dalle_image_generator.tool import DallEImageGenerator
from bisheng_langchain.gpts.tools.get_current_time.tool import get_current_time
from langchain_community.tools.arxiv.tool import ArxivQueryRun
from langchain_community.tools.bearly.tool import BearlyInterpreterTool
from langchain_community.utilities.arxiv import ArxivAPIWrapper
from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from langchain_core.callbacks import BaseCallbackManager, Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool, Tool
from mypy_extensions import Arg, KwArg


def _get_current_time() -> BaseTool:
    return get_current_time


def _get_calculator() -> BaseTool:
    return calculator


def _get_arxiv() -> BaseTool:
    return ArxivQueryRun(api_wrapper=ArxivAPIWrapper())


_BASE_TOOLS: Dict[str, Callable[[], BaseTool]] = {
    'get_current_time': _get_current_time,
    'calculator': _get_calculator,
    'arxiv': _get_arxiv,
}

_LLM_TOOLS: Dict[str, Callable[[BaseLanguageModel], BaseTool]] = {}

_EXTRA_LLM_TOOLS: Dict[
    str, Tuple[Callable[[Arg(BaseLanguageModel, 'llm'), KwArg(Any)], BaseTool], List[str]]  # noqa #type: ignore
] = {}


def _get_bing_search(**kwargs: Any) -> BaseTool:
    return BingSearchRun(api_wrapper=BingSearchAPIWrapper(**kwargs))


def _get_dalle_image_generator(**kwargs: Any) -> Tool:
    openai_api_key = kwargs.get('openai_api_key')
    http_client = httpx.Client(proxies=kwargs.get('openai_proxy'))
    return DallEImageGenerator(
        api_wrapper=DallEAPIWrapper(
            model='dall-e-3',
            api_key=openai_api_key,
            http_client=http_client,
        )
    )


def _get_bearly_code_interpreter(**kwargs: Any) -> Tool:
    return BearlyInterpreterTool(**kwargs).as_tool()


def _get_native_code_interpreter(**kwargs: Any) -> Tool:
    return CodeInterpreterTool(**kwargs).as_tool()


_EXTRA_PARAM_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {  # type: ignore
    'dalle_image_generator': (_get_dalle_image_generator, ['openai_api_key', 'openai_proxy']),
    'bing_search': (_get_bing_search, ['bing_subscription_key', 'bing_search_url']),
    'native_code_interpreter': (_get_native_code_interpreter, ['files']),
}

_API_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {}  # type: ignore
_API_TOOLS.update(ALL_API_TOOLS)


_ALL_TOOLS = {}
_ALL_TOOLS.update(_BASE_TOOLS)
_ALL_TOOLS.update(_LLM_TOOLS)
_ALL_TOOLS.update(_EXTRA_LLM_TOOLS)
_ALL_TOOLS.update(_EXTRA_PARAM_TOOLS)
_ALL_TOOLS.update(_API_TOOLS)

def _handle_callbacks(callback_manager: Optional[BaseCallbackManager], callbacks: Callbacks) -> Callbacks:
    if callback_manager is not None:
        warnings.warn(
            'callback_manager is deprecated. Please use callbacks instead.',
            DeprecationWarning,
        )
        if callbacks is not None:
            raise ValueError('Cannot specify both callback_manager and callbacks arguments.')
        return callback_manager
    return callbacks


def load_tools(
    tool_params: Dict[str, Dict[str, Any]],
    llm: Optional[BaseLanguageModel] = None,
    callbacks: Callbacks = None,
    **kwargs: Any,
) -> List[BaseTool]:
    tools = []
    callbacks = _handle_callbacks(callback_manager=kwargs.get('callback_manager'), callbacks=callbacks)
    for name, params in tool_params.items():
        if name in _BASE_TOOLS:
            tools.append(_BASE_TOOLS[name]())
        elif name in _LLM_TOOLS:
            if llm is None:
                raise ValueError(f'Tool {name} requires an LLM to be provided')
            tool = _LLM_TOOLS[name](llm)
            tools.append(tool)
        elif name in _EXTRA_LLM_TOOLS:
            if llm is None:
                raise ValueError(f'Tool {name} requires an LLM to be provided')
            _get_llm_tool_func, extra_keys = _EXTRA_LLM_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            sub_kwargs = {k: params[k] for k in extra_keys}
            tool = _get_llm_tool_func(llm=llm, **sub_kwargs)
            tools.append(tool)
        elif name in _EXTRA_PARAM_TOOLS:
            _get_tool_func, extra_keys = _EXTRA_PARAM_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            sub_kwargs = {k: params[k] for k in extra_keys if k in params}
            tool = _get_tool_func(**sub_kwargs)
            tools.append(tool)
        elif name in _API_TOOLS:
            _get_api_tool_func, extra_keys = _API_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            mini_kwargs = {k: params[k] for k in extra_keys}
            tool = _get_api_tool_func(name=name.split('.')[-1], **mini_kwargs)
            tools.append(tool)
        else:
            raise ValueError(f'Got unknown tool {name}')
    if callbacks is not None:
        for tool in tools:
            tool.callbacks = callbacks
    return tools


def get_all_tool_names() -> List[str]:
    """Get a list of all possible tool names."""
    return list(_BASE_TOOLS) + list(_EXTRA_PARAM_TOOLS) + list(_EXTRA_LLM_TOOLS) + list(_LLM_TOOLS) + list(_API_TOOLS)
