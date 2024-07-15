import asyncio
import logging
from enum import Enum
from functools import lru_cache
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

import httpx
import yaml
from bisheng_langchain.gpts.load_tools import get_all_tool_names, load_tools
from bisheng_langchain.gpts.utils import import_by_type, import_class
from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableBinding

logger = logging.getLogger(__name__)


class ConfigurableAssistant(RunnableBinding):
    agent_executor_type: str
    tools: Sequence[BaseTool]
    llm: LanguageModelLike
    assistant_message: str
    interrupt_before_action: bool = False
    recursion_limit: int = 50

    def __init__(
        self,
        *,
        agent_executor_type: str,
        tools: Sequence[BaseTool],
        llm: LanguageModelLike,
        assistant_message: str,
        interrupt_before_action: bool = False,
        recursion_limit: int = 50,
        kwargs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        **others: Any,
    ) -> None:
        others.pop("bound", None)
        agent_executor_object = import_class(f'bisheng_langchain.gpts.agent_types.{agent_executor_type}')

        _agent_executor = agent_executor_object(tools, llm, assistant_message, interrupt_before_action)
        agent_executor = _agent_executor.with_config({"recursion_limit": recursion_limit})
        super().__init__(
            agent_executor_type=agent_executor_type,
            tools=tools,
            llm=llm,
            assistant_message=assistant_message,
            bound=agent_executor,
            kwargs=kwargs or {},
            config=config or {},
        )


class BishengAssistant:

    def __init__(self, yaml_path) -> None:
        self.yaml_path = yaml_path
        with open(self.yaml_path, 'r') as f:
            self.params = yaml.safe_load(f)

        self.assistant_params = self.params['assistant']

        # init assistant prompt
        prompt_type = self.assistant_params['prompt_type']
        assistant_message = import_class(f'bisheng_langchain.gpts.prompts.{prompt_type}')

        # init llm or agent
        llm_params = self.assistant_params['llm']
        llm_object = import_by_type(_type='llms', name=llm_params['type'])
        if llm_params['type'] == 'ChatOpenAI' and llm_params['openai_proxy']:
            llm_params.pop('type')
            llm = llm_object(
                http_client=httpx.Client(proxies=llm_params['openai_proxy']),
                http_async_client=httpx.AsyncClient(proxies=llm_params['openai_proxy']),
                **llm_params,
            )
        else:
            llm_params.pop('type')
            llm = llm_object(**llm_params)

        # init tools
        available_tools = get_all_tool_names()
        tools = []
        for tool in self.assistant_params['tools']:
            tool_type = tool.pop('type')
            tool_config = tool if tool else {}
            if tool_type not in available_tools:
                raise ValueError(f"Tool type {tool_type} not found in TOOLS")
            _returned_tools = load_tools({tool_type: tool_config})
            if isinstance(_returned_tools, list):
                tools.extend(_returned_tools)
            else:
                tools.append(_returned_tools)

        # init agent executor
        agent_executor_params = self.assistant_params['agent_executor']
        self.agent_executor_type = agent_executor_params.pop('type')
        self.assistant = ConfigurableAssistant(
            agent_executor_type=self.agent_executor_type, 
            tools=tools, 
            llm=llm, 
            assistant_message=assistant_message, 
            **agent_executor_params
        )

    def run(self, query, chat_history=[], chat_round=5):
        if len(chat_history) % 2 != 0:
            raise ValueError("chat history should be even")
        
        # 限制chat_history轮数
        if len(chat_history) > chat_round * 2:
            chat_history = chat_history[-chat_round*2:]

        inputs = []
        for i in range(0, len(chat_history), 2):
            inputs.append(HumanMessage(content=chat_history[i]))
            inputs.append(AIMessage(content=chat_history[i+1]))
        inputs.append(HumanMessage(content=query))
        if self.agent_executor_type == 'get_react_agent_executor':
            result = asyncio.run(self.assistant.ainvoke({"input": inputs[-1].content, "chat_history": inputs[:-1]}))
        else:
            result = asyncio.run(self.assistant.ainvoke(inputs))
        return result


if __name__ == "__main__":
    from langchain.globals import set_debug

    # set_debug(True)
    # chat_history = []
    # query = "分析当日市场行情"
    chat_history = ['你好', '你好，有什么可以帮助你吗？', '福蓉科技股价多少?', '福蓉科技（股票代码：300049）的当前股价为48.67元。']
    query = '今天是什么时候？去年这个时候的股价是多少？'
    bisheng_assistant = BishengAssistant("config/base_scene.yaml")
    # bisheng_assistant = BishengAssistant("config/knowledge_scene.yaml")
    # bisheng_assistant = BishengAssistant("config/rag_scene.yaml")
    result = bisheng_assistant.run(query, chat_history=chat_history)
    print(result)
