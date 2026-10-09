import json
import os
import warnings
from collections.abc import Callable
from typing import Any, List, Tuple

import httpx
import pandas as pd
import pymysql
from dotenv import load_dotenv
from langchain_community.tools.arxiv.tool import ArxivQueryRun
from langchain_community.tools.bearly.tool import BearlyInterpreterTool
from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from langchain_core.callbacks import BaseCallbackManager, Callbacks
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool, Tool
from mypy_extensions import Arg, KwArg

from bisheng.common.services.config_service import settings
from bisheng_langchain.gpts.tools.api_tools import ALL_API_TOOLS
from bisheng_langchain.gpts.tools.bing_search.self_arxiv import ArxivAPIWrapperSelf
from bisheng_langchain.gpts.tools.bing_search.tool import BingSearchResults
from bisheng_langchain.gpts.tools.calculator.tool import calculator
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor
from bisheng_langchain.gpts.tools.code_interpreter.tool import CodeInterpreterTool

# from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from bisheng_langchain.gpts.tools.dalle_image_generator.tool import (
    DallEImageGenerator,
    ProxyDallEAPIWrapper,
)
from bisheng_langchain.gpts.tools.get_current_time.tool import get_current_time
from bisheng_langchain.gpts.tools.local_file.local_file import LocalFileTool
from bisheng_langchain.gpts.tools.sql_agent.tool import SqlAgentAPIWrapper, SqlAgentTool
from bisheng_langchain.gpts.tools.web_search.tool import SearchTool, WebSearchTool
from bisheng_langchain.rag import BishengRAGTool
from bisheng_langchain.utils.azure_dalle_image_generator import AzureDallEWrapper


def _get_current_time() -> BaseTool:
    return get_current_time


def _get_calculator() -> BaseTool:
    return calculator


def _get_arxiv() -> BaseTool:
    return ArxivQueryRun(
        api_wrapper=ArxivAPIWrapperSelf(top_k_results=5, load_max_docs=5, load_all_available_meta=True)
    )


_BASE_TOOLS: dict[str, Callable[[], BaseTool]] = {
    "get_current_time": _get_current_time,
    "calculator": _get_calculator,
    "arxiv": _get_arxiv,
}

_LLM_TOOLS: dict[str, Callable[[BaseLanguageModel], BaseTool]] = {}

_EXTRA_LLM_TOOLS: dict[
    str, Tuple[Callable[[Arg(BaseLanguageModel, "llm"), KwArg(Any)], BaseTool], List[str]]  # noqa  # noqa #type: ignore
] = {}


def _get_bing_search(**kwargs: Any) -> BaseTool:
    return BingSearchResults(api_wrapper=BingSearchAPIWrapper(**kwargs))


def _get_web_search(**kwargs: Any) -> BaseTool:
    """Get a web search tool."""
    tool_name = kwargs.get("type", "")
    tool_config = kwargs.get("config", {}).get(tool_name)
    search_tool = SearchTool.init_search_tool(tool_name, **tool_config)
    return WebSearchTool(api_wrapper=search_tool)


def _get_dalle_image_generator(**kwargs: Any) -> BaseTool:
    # 说明是azure的openai配置
    if kwargs.get("azure_endpoint"):
        kwargs["api_key"] = kwargs.pop("openai_api_key")
        kwargs["api_version"] = kwargs.pop("openai_api_version")
        return DallEImageGenerator(api_wrapper=AzureDallEWrapper(**kwargs))
    if kwargs.get("openai_proxy"):
        kwargs["http_async_client"] = httpx.AsyncClient(proxy=kwargs.get("openai_proxy"))
        kwargs["http_client"] = httpx.Client(proxy=kwargs.get("openai_proxy"))
    kwargs["api_key"] = kwargs.pop("openai_api_key")
    kwargs["base_url"] = kwargs.pop("openai_api_base", None)
    return DallEImageGenerator(api_wrapper=ProxyDallEAPIWrapper(model="dall-e-3", **kwargs))


def _get_sql_agent(**kwargs: Any) -> BaseTool:
    return SqlAgentTool(api_wrapper=SqlAgentAPIWrapper(**kwargs))


def _get_bearly_code_interpreter(**kwargs: Any) -> Tool:
    return BearlyInterpreterTool(**kwargs).as_tool()


# Isolation-environment access knobs live on Settings.sandbox_conf, never extra
# (AC-22 / pitfall 7). Runner-only keys are stripped so leftover tool config
# cannot override session TTL / slots / uid isolation.
_CONTAINER_POOL_KEYS = (
    "endpoints",
    "token",
    "discover_host_pattern",
    "discover_index_start",
    "discover_max",
    "discover_ttl_s",
    "discover_port",
    "pool_lease_ttl_s",
    "max_sessions_per_replica",
    "enable_uid_isolation",
    "pool_acquire_timeout_s",
    "max_copy_in_bytes",
    "code_node_enabled",
    "sandbox_conf",
)


def _get_native_code_interpreter(**kwargs: Any) -> BaseTool:
    executor_type = kwargs.pop("type", None) or "local"
    config = kwargs.pop("config", None) or {}
    backend_config = dict(config.get(executor_type) or {})
    # Pitfall 7: frontend stores config.e2b.type as private/official. That must
    # not become an executor constructor argument; domain empty/non-empty is the
    # real private vs official switch.
    backend_config.pop("type", None)
    if executor_type == "container":
        for key in _CONTAINER_POOL_KEYS:
            backend_config.pop(key, None)
    kwargs.update(backend_config)
    if executor_type == "local":
        executor = LocalExecutor(**kwargs)
    elif executor_type == "container":
        executor = ContainerExecutor(sandbox_conf=settings.sandbox_conf, **kwargs)
    elif executor_type == "e2b":
        executor = E2bCodeExecutor(**kwargs)
    else:
        raise ValueError(f"Unknown code interpreter type: {executor_type!r}")
    return CodeInterpreterTool(executor=executor, description=executor.description)


# 第二个list内填必填参数，第三个list内填可选参数
_EXTRA_PARAM_TOOLS: dict[str, tuple[Callable[[KwArg(Any)], BaseTool], list[str | None], list[str | None]]] = {
    # type: ignore
    "dalle_image_generator": (
        _get_dalle_image_generator,
        ["openai_api_key"],
        ["openai_api_base", "openai_proxy", "azure_deployment", "azure_endpoint", "openai_api_version"],
    ),
    "bing_search": (_get_bing_search, ["bing_subscription_key", "bing_search_url"], []),
    "bisheng_code_interpreter": (_get_native_code_interpreter, ["minio"], ["config", "type"]),
    "bisheng_rag": (
        BishengRAGTool.get_rag_tool,
        ["name", "description"],
        ["vector_store", "keyword_store", "llm", "collection_name", "max_content", "sort_by_source_and_index"],
    ),
    "sql_agent": (_get_sql_agent, ["llm", "sql_address"], []),
    "web_search": (_get_web_search, ["type", "config"], []),
}

_API_TOOLS: dict[str, tuple[Callable[..., BaseTool], list[str]]] = {**ALL_API_TOOLS}  # type: ignore

_API_TOOLS.update(
    {
        "list_files": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "get_file_details": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "search_files": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "search_text_in_file": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "read_text_file": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "add_text_to_file": (LocalFileTool.get_tool_by_name, ["root_path"]),
        "replace_file_lines": (LocalFileTool.get_tool_by_name, ["root_path"]),
    }
)

_ALL_TOOLS = {
    **_BASE_TOOLS,
    **_LLM_TOOLS,
    **_EXTRA_LLM_TOOLS,
    **_EXTRA_PARAM_TOOLS,
    **_API_TOOLS,
}


def _handle_callbacks(callback_manager: BaseCallbackManager | None, callbacks: Callbacks) -> Callbacks:
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
    tool_params: dict[str, dict[str, Any]],
    llm: BaseLanguageModel | None = None,
    callbacks: Callbacks = None,
    **kwargs: Any,
) -> list[BaseTool]:
    tools = []
    callbacks = _handle_callbacks(callback_manager=kwargs.get("callback_manager"), callbacks=callbacks)
    for name, params in tool_params.items():
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
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f"Tool {name} requires some parameters that were not provided: {missing_keys}")
            sub_kwargs = {k: params[k] for k in extra_keys}
            tool = _get_llm_tool_func(llm=llm, **sub_kwargs)
            tools.append(tool)
        elif name in _EXTRA_PARAM_TOOLS:
            _get_tool_func, extra_keys, optional_keys = _EXTRA_PARAM_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f"Tool {name} requires some parameters that were not provided: {missing_keys}")
            extra_kwargs = {k: params[k] for k in extra_keys}
            optional_kwargs = {k: params[k] for k in optional_keys if k in params}
            all_kwargs = {**extra_kwargs, **optional_kwargs}
            tool = _get_tool_func(**all_kwargs)
            tools.append(tool)
        elif name in _API_TOOLS:
            _get_api_tool_func, extra_keys = _API_TOOLS[name]
            missing_keys = set(extra_keys).difference(params)
            if missing_keys:
                raise ValueError(f"Tool {name} requires some parameters that were not provided: {missing_keys}")
            mini_kwargs = {k: params[k] for k in extra_keys}
            tool = _get_api_tool_func(name=name, **mini_kwargs)
            tools.append(tool)
        else:
            raise ValueError(f"Got unknown tool {name}")
    if callbacks is not None:
        for tool in tools:
            tool.callbacks = callbacks
    return tools


def get_all_tool_names() -> list[str]:
    """Get a list of all possible tool names."""
    return list(_ALL_TOOLS.keys())


def get_tool_table():
    load_dotenv(".sql_env", override=True)
    db = pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT")),
    )
    cursor = db.cursor()
    cursor.execute("SELECT name, t.desc, tool_key, extra FROM t_gpts_tools as t;")
    results = cursor.fetchall()
    db.close()

    df = pd.DataFrame(
        columns=[
            "前端工具名",
            "前端工具描述",
            "tool_key",
            "tool参数配置",
            "function_name",
            "function_description",
            "function_args",
        ]
    )
    for i, result in enumerate(results):
        name, desc, tool_key, extra = result
        if not extra:
            extra = "{}"
        tool_func = load_tools({tool_key: json.loads(extra)})[0]

        df.loc[i, "前端工具名"] = name
        df.loc[i, "前端工具描述"] = desc
        df.loc[i, "tool_key"] = tool_key
        df.loc[i, "tool参数配置"] = extra
        df.loc[i, "function_name"] = tool_func.name
        df.loc[i, "function_description"] = tool_func.description
        df.loc[i, "function_args"] = f"{tool_func.args_schema.schema()['properties']}"

    return df


if __name__ == "__main__":
    tool = load_tools({"sina_realtime_info": {}})[0]
    tool.invoke(input={"stock_symbol": "600519", "stock_exchange": "sh", "prefix": "s_"})
