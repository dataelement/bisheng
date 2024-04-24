import asyncio
import os

import dotenv
import httpx
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools
from langchain.globals import set_debug
from langchain.tools import tool

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

dotenv.load_dotenv('/app/.env', override=True)
set_debug(True)

HTTP_ASYNC_CLIENT = httpx.AsyncClient(proxies=os.getenv('OPENAI_PROXY'))
HTTP_CLIENT = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))

tyc_api_key = os.getenv("TIAN_YAN_CHA_API_KEY")


def test_agent():

    tools = load_tools(
        tool_params={
            "tianyancha.search_company": {"api_key": tyc_api_key},
            'dalle_image_generator': {
                "openai_api_key": os.getenv('OPENAI_API_KEY'),
                "openai_proxy": os.getenv('OPENAI_PROXY'),
            },
        }
    )
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_async_client=HTTP_ASYNC_CLIENT)

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        assistant_message="You are a helpful assistant.",
    )

    inputs = [HumanMessage(content="帮我生成一个小女孩画画的图片")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_tools():
    tools = load_tools(
        tool_params={"sina.realtime_info": {}, "sina.history_KLine": {}},
    )
    params = {"query": "sh600036", "date": "2024-03-01"}
    tools[1].run(params)


if __name__ == '__main__':
    test_agent()
    # test_tools()
