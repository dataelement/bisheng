import os
import httpx
import logging
from urllib.parse import urlparse
from functools import lru_cache
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union

from langchain.chat_models import ChatOpenAI
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import (
    ConfigurableField,
    RunnableBinding,
)
from bisheng_langchain.gpts.agent_types import get_openai_functions_agent_executor
from bisheng_langchain.gpts.tools import (
    TOOLS,
    ActionServer,
    Arxiv,
    Connery,
    DDGSearch,
    PressReleases,
    PubMed,
    SecFilings,
    Tavily,
    TavilyAnswer,
    Wikipedia,
    YouSearch,
)

Tool = Union[
    ActionServer,
    Connery,
    DDGSearch,
    Arxiv,
    YouSearch,
    SecFilings,
    PressReleases,
    PubMed,
    Wikipedia,
    Tavily,
    TavilyAnswer,
]

logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_MESSAGE = "You are a helpful assistant."


@lru_cache(maxsize=4)
def get_openai_llm(model_name):
    proxy_url = os.getenv("OPENAI_PROXY")
    http_client = None
    if proxy_url:
        parsed_url = urlparse(proxy_url)
        if parsed_url.scheme and parsed_url.netloc:
            http_client = httpx.AsyncClient(proxies=proxy_url)
        else:
            logger.warn("Invalid proxy URL provided. Proceeding without proxy.")
    
    llm = ChatOpenAI(
        http_client=http_client,
        model=model_name,
        temperature=0,
        streaming=True,
    )
    return llm


def get_agent_executor(
    tools: list,
    model_name: str,
    system_message: str,
    interrupt_before_action: bool,
):
    llm = get_openai_llm(model_name)
    return get_openai_functions_agent_executor(tools, llm, system_message, interrupt_before_action)


class ConfigurableAgent(RunnableBinding):
    tools: Sequence[Tool]
    model_name: str
    system_message: str = DEFAULT_SYSTEM_MESSAGE
    interrupt_before_action: bool = False

    def __init__(
        self,
        *,
        tools: Sequence[Tool],
        model_name: str = "gpt-4-1106-preview",
        system_message: str = DEFAULT_SYSTEM_MESSAGE,
        interrupt_before_action: bool = False,
        kwargs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        **others: Any,
    ) -> None:
        others.pop("bound", None)
        _tools = []
        for _tool in tools:
            tool_config = _tool.config if _tool.config else {}
            _returned_tools = TOOLS[_tool.type](**tool_config)
            if isinstance(_returned_tools, list):
                _tools.extend(_returned_tools)
            else:
                _tools.append(_returned_tools)
        _agent = get_agent_executor(
            _tools, model_name, system_message, interrupt_before_action
        )
        agent_executor = _agent.with_config({"recursion_limit": 50})
        super().__init__(
            tools=tools,
            model_name=model_name,
            system_message=system_message,
            bound=agent_executor,
            kwargs=kwargs or {},
            config=config or {},
        )


if __name__ == "__main__":
    import asyncio
    arxiv = Arxiv()
    agent = ConfigurableAgent(model_name="gpt-4-1106-preview", tools=[arxiv], system_message=DEFAULT_SYSTEM_MESSAGE)

    inputs = [HumanMessage(content="帮我查找一下关于人工智能的文章。")]
    result = asyncio.run(agent.ainvoke(inputs))
    print(result)