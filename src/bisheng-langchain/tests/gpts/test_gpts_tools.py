import asyncio
import os
from urllib.parse import urlparse

import dotenv
import httpx
from bisheng_langchain.gpts.agent import ConfigurableAgent
from bisheng_langchain.gpts.load_tools import load_tools
from langchain.globals import set_debug
from langchain.tools import tool
from langchain_core.messages import HumanMessage

set_debug(True)
dotenv.load_dotenv("../.env")

# dalle-3
http_client = httpx.Client(proxies=os.getenv("OPENAI_PROXY"))

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
            "http_client": http_client,
        },
        "bing-search": {},
        "get_current_time": {},
        "tianyancha.search_company": {
            "api_key": tyc_api_key,
        },
    }

    tools = load_tools(tool_params)

    # model_name = "gpt-4-0125-preview"
    model_name = "gpt-3.5-turbo-1106"
    sys_msg = "You are a helpful assistant."
    agent = ConfigurableAgent(model_name=model_name, tools=tools, system_message=sys_msg)

    inputs = [HumanMessage(content="佛山电翰是什么梗")]
    result = asyncio.run(agent.ainvoke(inputs))
    print(result)


def test_code_interpreter():
    from langchain_community.tools.bearly.tool import BearlyInterpreterTool

    file_url = "../data/test_doc.txt"
    code_tool = BearlyInterpreterTool(api_key=bearly_api_key)
    code_tool.add_file(source_path=file_url, target_path="README_ENG.md", description="")
    tool = code_tool.as_tool()
    print(tool.description)

    model_name = "gpt-4-1106-preview"
    # model_name = "gpt-3.5-turbo-1106"
    sys_msg = "You are a helpful assistant."
    agent = ConfigurableAgent(model_name=model_name, tools=[tool], system_message=sys_msg)

    inputs = [HumanMessage(content="这个文档的总字数是多少")]
    result = asyncio.run(agent.ainvoke(inputs))
    print(result)


# test_all_tools()
test_code_interpreter()
