import json
import os
import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import pandas as pd
import pymysql
from bisheng_langchain.gpts.tools.api_tools import ALL_API_TOOLS
from bisheng_langchain.gpts.tools.bing_search.tool import BingSearchRun
from bisheng_langchain.gpts.tools.calculator.tool import calculator
from bisheng_langchain.gpts.tools.code_interpreter.tool import CodeInterpreterTool

# from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from bisheng_langchain.gpts.tools.dalle_image_generator.tool import (
    DallEAPIWrapper,
    DallEImageGenerator,
)
from bisheng_langchain.gpts.tools.get_current_time.tool import get_current_time
from dotenv import load_dotenv
from langchain_community.tools.arxiv.tool import ArxivQueryRun
from langchain_community.tools.bearly.tool import BearlyInterpreterTool
from langchain_community.utilities.arxiv import ArxivAPIWrapper
from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from langchain_core.callbacks import BaseCallbackManager, Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool, Tool
from mypy_extensions import Arg, KwArg
from bisheng_langchain.rag import BishengRAGTool
from bisheng_langchain.utils.azure_dalle_image_generator import AzureDallEWrapper


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
    str, Tuple[Callable[[Arg(BaseLanguageModel, 'llm'), KwArg(Any)], BaseTool], List[str]]  # noqa  # noqa #type: ignore
] = {}


def _get_bing_search(**kwargs: Any) -> BaseTool:
    return BingSearchRun(api_wrapper=BingSearchAPIWrapper(**kwargs))


def _get_dalle_image_generator(**kwargs: Any) -> Tool:
    if kwargs.get('openai_proxy'):
        kwargs['http_async_client'] = httpx.AsyncClient(proxies=kwargs.get('openai_proxy'))
        kwargs['http_client'] = httpx.Client(proxies=kwargs.get('openai_proxy'))

    # 说明是azure的openai配置
    if kwargs.get("azure_endpoint"):
        kwargs['api_key'] = kwargs.pop('openai_api_key')
        kwargs['api_version'] = kwargs.pop('openai_api_version')
        return DallEImageGenerator(
            api_wrapper=AzureDallEWrapper(**kwargs)
        )

    return DallEImageGenerator(
        api_wrapper=DallEAPIWrapper(
            model='dall-e-3',
            **kwargs
        )
    )


def _get_bearly_code_interpreter(**kwargs: Any) -> Tool:
    return BearlyInterpreterTool(**kwargs).as_tool()


def _get_native_code_interpreter(**kwargs: Any) -> Tool:
    return CodeInterpreterTool(**kwargs).as_tool()


# 第二个list内填必填参数，第三个list内填可选参数
_EXTRA_PARAM_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[Optional[str]], List[Optional[str]]]] = {
    # type: ignore
    'dalle_image_generator': (_get_dalle_image_generator,
                              ['openai_api_key'],
                              ['openai_api_base', 'openai_proxy', 'azure_deployment', 'azure_endpoint', 'openai_api_version']),
    'bing_search': (_get_bing_search, ['bing_subscription_key', 'bing_search_url'], []),
    'bisheng_code_interpreter': (_get_native_code_interpreter, ["minio"], ['files']),
    'bisheng_rag': (BishengRAGTool.get_rag_tool, ['name', 'description'],
                    ['vector_store', 'keyword_store', 'llm', 'collection_name', 'max_content',
                     'sort_by_source_and_index']),
}

_API_TOOLS: Dict[str, Tuple[Callable[[KwArg(Any)], BaseTool], List[str]]] = {**ALL_API_TOOLS}  # type: ignore

_ALL_TOOLS = {
    **_BASE_TOOLS,
    **_LLM_TOOLS,
    **_EXTRA_LLM_TOOLS,
    **_EXTRA_PARAM_TOOLS,
    **_API_TOOLS,
}


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
            _get_tool_func, extra_keys, optional_keys = _EXTRA_PARAM_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            extra_kwargs = {k: params[k] for k in extra_keys}
            optional_kwargs = {k: params[k] for k in optional_keys if k in params}
            all_kwargs = {**extra_kwargs, **optional_kwargs}
            tool = _get_tool_func(**all_kwargs)
            tools.append(tool)
        elif name in _API_TOOLS:
            _get_api_tool_func, extra_keys = _API_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f'Tool {name} requires some parameters that were not ' f'provided: {missing_keys}')
            mini_kwargs = {k: params[k] for k in extra_keys}
            tool = _get_api_tool_func(name=name, **mini_kwargs)
            tools.append(tool)
        else:
            raise ValueError(f'Got unknown tool {name}')
    if callbacks is not None:
        for tool in tools:
            tool.callbacks = callbacks
    return tools


def get_all_tool_names() -> List[str]:
    """Get a list of all possible tool names."""
    return list(_ALL_TOOLS.keys())


def get_tool_table():
    load_dotenv('.sql_env', override=True)
    db = pymysql.connect(
        host=os.getenv('MYSQL_HOST'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DATABASE'),
        port=int(os.getenv('MYSQL_PORT')),
    )
    cursor = db.cursor()
    cursor.execute("SELECT name, t.desc, tool_key, extra FROM t_gpts_tools as t;")
    results = cursor.fetchall()
    db.close()

    df = pd.DataFrame(
        columns=[
            '前端工具名',
            '前端工具描述',
            'tool_key',
            'tool参数配置',
            'function_name',
            'function_description',
            'function_args',
        ]
    )
    for i, result in enumerate(results):
        name, desc, tool_key, extra = result
        if not extra:
            extra = '{}'
        tool_func = load_tools({tool_key: json.loads(extra)})[0]

        df.loc[i, '前端工具名'] = name
        df.loc[i, '前端工具描述'] = desc
        df.loc[i, 'tool_key'] = tool_key
        df.loc[i, 'tool参数配置'] = extra
        df.loc[i, 'function_name'] = tool_func.name
        df.loc[i, 'function_description'] = tool_func.description
        df.loc[i, 'function_args'] = f"{tool_func.args_schema.schema()['properties']}"

    return df
