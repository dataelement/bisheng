import asyncio
import os
from urllib.parse import urlparse

import dotenv
import httpx
from bisheng_langchain.gpts.assistant import ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools
from langchain.globals import set_debug
from langchain.tools import tool
from langchain_community.chat_models.openai import ChatOpenAI
from langchain_core.messages import HumanMessage

set_debug(True)
dotenv.load_dotenv('/app/.env', override=True)

# dalle-3
HTTP_ASYNC_CLIENT = httpx.AsyncClient(proxies=os.getenv('OPENAI_PROXY'))
HTTP_CLIENT = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))

# code interpreter
bearly_api_key = os.getenv("BEARLY_API_KEY")

# tian yan cha
tyc_api_key = os.getenv("TIAN_YAN_CHA_API_KEY")


def test_all_tools():
    tool_params = {
        "arxiv": {},
        "code-interpreter": {
            "api_key": bearly_api_key,
        },
        "dalle-image-generator": {
            "model": "dalle-3",
            "http_client": HTTP_CLIENT,
        },
        "bing-search": {},
        "get_current_time": {},
        "tianyancha.search_company": {
            "api_key": tyc_api_key,
        },
    }
    tools = load_tools(tool_params)
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)
    sys_msg = "You are a helpful assistant."

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我生成一个小女孩画画的图片")]
    result = asyncio.run(agent.ainvoke(inputs))
    print(result)


def test_code_interpreter():
    from langchain_community.tools.bearly.tool import BearlyInterpreterTool

    file_url = "/app/bisheng/src/bisheng-langchain/version.txt"
    code_tool = BearlyInterpreterTool(api_key=bearly_api_key)
    code_tool.add_file(source_path=file_url, target_path="README_ENG.md", description="")
    tools = [code_tool.as_tool()]
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)
    sys_msg = "You are a helpful assistant."

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )
    inputs = [HumanMessage(content="这个文档的总字数是多少")]
    result = asyncio.run(agent.ainvoke(inputs))
    print(result)


def test_tianyancha():
    tool_params = {
        "tianyancha.search_company": {
            "api_key": tyc_api_key,
        },
    }

    tools = load_tools(tool_params)
    sys_msg = "You are a helpful assistant."
    inputs = [HumanMessage(content="查询云南白药公司的信息")]
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)
    sys_msg = "You are a helpful assistant."

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我查询云南白药公司的基本信息")]
    result = asyncio.run(agent.ainvoke(inputs))


if __name__ == '__main__':
    test_all_tools()
    # test_code_interpreter()
    # test_tianyancha()
