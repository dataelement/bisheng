import asyncio
import os

import dotenv
import httpx
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools
from langchain.globals import set_debug
from langchain.tools import tool
from langchain_community.chat_models.openai import ChatOpenAI
from langchain_core.messages import HumanMessage

dotenv.load_dotenv('/app/.env', override=True)
set_debug(True)

HTTP_ASYNC_CLIENT = httpx.AsyncClient(proxies=os.getenv('OPENAI_PROXY'))
HTTP_CLIENT = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))


def test_agent():

    tools = load_tools(tool_params={"tianyancha.search_company": {"api_key": "224d0cd7-b87d-4f92-8dc6-132632c2d50a"}})
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message="You are a helpful assistant.",
    )

    inputs = [HumanMessage(content="帮我查询云南白药公司的基本信息")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_tools():
    tools = load_tools(
        tool_params={"sina.realtime_info": {}, "sina.history_KLine": {}},
    )
    params = {"query": "sh600036", "date": "2024-03-01"}
    tools[1].run(params)


test_agent()
# test_tools()
