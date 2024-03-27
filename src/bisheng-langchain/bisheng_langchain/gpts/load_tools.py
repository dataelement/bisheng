import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple

from bisheng_langchain.gpts.tools.bing_search.tool import BingSearchRun
from bisheng_langchain.gpts.tools.calculator.tool import calculater
from bisheng_langchain.gpts.tools.dalle_image_generator.tool import DallEImageGenerator
from bisheng_langchain.gpts.tools.get_current_time.tool import get_current_time
from bisheng_langchain.gpts.tools.tianyancha import TIAN_YAN_CHA_TOOLS
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
    return calculater


_BASE_TOOLS: Dict[str, Callable[[], BaseTool]] = {
    'get_current_time': _get_current_time,
    'calculator': _get_calculator,
}


_LLM_TOOLS: Dict[str, Callable[[BaseLanguageModel], BaseTool]] = {}

_EXTRA_LLM_TOOLS: Dict[
    str,
    Tuple[Callable[[Arg(BaseLanguageModel, "llm"), KwArg(Any)], BaseTool], List[str]],  # type: ignore
] = {}


def _get_arxiv(**kwargs: Any) -> BaseTool:
    return ArxivQueryRun(api_wrapper=ArxivAPIWrapper(**kwargs))


def _get_bing_search(**kwargs: Any) -> BaseTool:
    return BingSearchRun(api_wrapper=BingSearchAPIWrapper(**kwargs))


def _get_dalle_image_generator(**kwargs: Any) -> Tool:
    return DallEImageGenerator(api_wrapper=DallEAPIWrapper(**kwargs))


def _get_code_interpreter(**kwargs: Any) -> Tool:
    return BearlyInterpreterTool(**kwargs).as_tool()


_EXTRA_OPTIONAL_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {  # type: ignore
    "arxiv": (_get_arxiv, ["top_k_results", "load_max_docs", "load_all_available_meta"]),
    "dalle-image-generator": (_get_dalle_image_generator, ["model_name", "openai_api_key", 'http_client']),
    "bing-search": (_get_bing_search, ["bing_subscription_key", "bing_search_url"]),
    "code-interpreter": (_get_code_interpreter, ["api_key", 'files']),
}


_API_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {}  # type: ignore
_API_TOOLS.update(TIAN_YAN_CHA_TOOLS)


def _handle_callbacks(callback_manager: Optional[BaseCallbackManager], callbacks: Callbacks) -> Callbacks:
    if callback_manager is not None:
        warnings.warn(
            "callback_manager is deprecated. Please use callbacks instead.",
            DeprecationWarning,
        )
        if callbacks is not None:
            raise ValueError("Cannot specify both callback_manager and callbacks arguments.")
        return callback_manager
    return callbacks


def load_tools(
    tool_params: Dict[str, Dict[str, Any]],
    llm: Optional[BaseLanguageModel] = None,
    callbacks: Callbacks = None,
    **kwargs: Any,
) -> List[BaseTool]:
    tools = []
    callbacks = _handle_callbacks(callback_manager=kwargs.get("callback_manager"), callbacks=callbacks)
    for name, pramas in tool_params.items():
        if name in _BASE_TOOLS:
            tools.append(_BASE_TOOLS[name]())
        elif name in _LLM_TOOLS:
            if llm is None:
                raise ValueError(f"Tool {name} requires an LLM to be provided")
            tool = _LLM_TOOLS[name](llm)
            tools.append(tool)
        elif name in _EXTRA_LLM_TOOLS:
            if llm is None:
                raise ValueError(f"Tool {name} requires an LLM to be provided")
            _get_llm_tool_func, extra_keys = _EXTRA_LLM_TOOLS[name]
            missing_keys = set(extra_keys).difference(pramas)
            if missing_keys:
                raise ValueError(f"Tool {name} requires some parameters that were not " f"provided: {missing_keys}")
            sub_kwargs = {k: pramas[k] for k in extra_keys}
            tool = _get_llm_tool_func(llm=llm, **sub_kwargs)
            tools.append(tool)
        elif name in _EXTRA_OPTIONAL_TOOLS:
            _get_tool_func, extra_keys = _EXTRA_OPTIONAL_TOOLS[name]
            sub_kwargs = {k: pramas[k] for k in extra_keys if k in pramas}
            tool = _get_tool_func(**sub_kwargs)
            tools.append(tool)
        elif name in _API_TOOLS:
            _get_api_tool_func, extra_keys = _API_TOOLS[name]
            missing_keys = set(extra_keys).difference(pramas)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            mini_kwargs = {k: pramas[k] for k in extra_keys}
            tool = _get_api_tool_func(name=name.split('.')[-1], **mini_kwargs)
            tools.append(tool)
        else:
            raise ValueError(f"Got unknown tool {name}")
    if callbacks is not None:
        for tool in tools:
            tool.callbacks = callbacks
    return tools


def get_all_tool_names() -> List[str]:
    """Get a list of all possible tool names."""
    return list(_BASE_TOOLS) + list(_EXTRA_OPTIONAL_TOOLS) + list(_EXTRA_LLM_TOOLS) + list(_LLM_TOOLS) + list(_API_TOOLS)

