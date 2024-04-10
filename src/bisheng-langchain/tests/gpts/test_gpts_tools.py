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
from pydantic import BaseModel

set_debug(True)
dotenv.load_dotenv('/app/.env', override=True)

# dalle-3
openai_api_key = os.getenv('OPENAI_API_KEY')
openai_proxy = os.getenv('OPENAI_PROXY')
HTTP_ASYNC_CLIENT = httpx.AsyncClient(proxies=openai_proxy)
HTTP_CLIENT = httpx.Client(proxies=openai_proxy)

# code interpreter
bearly_api_key = os.getenv("BEARLY_API_KEY")

# tian yan cha
tyc_api_key = os.getenv("TIAN_YAN_CHA_API_KEY")


def test_all_tools():
    tool_params = {
        "get_current_time": {},
        "calculator": {},
        "arxiv": {},
        "dalle_image_generator": {
            "openai_api_key": openai_api_key,
            "openai_proxy": openai_proxy,
        },
        "tianyancha.search_company": {
            "api_key": tyc_api_key,
        },
        "bing_search": {
            "bing_subscription_key": os.getenv("BING_SUBSCRIPTION_KEY"),
            "bing_search_url": os.getenv("BING_SEARCH_URL"),
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

    querys = [
        "帮我生成一个小女孩画画的图片",  # delle
        "请告诉我现在巴拿马的时间",  # get_current_time
        "请问11除以3等于多少",  # calculator
        "帮我找一篇关于人工智能论文",  # arxiv
        "佛山电翰是什么梗？",  # bing_search
        "查询云南白药公司的信息",  # tianyancha
    ]
    for query in querys:
        inputs = [HumanMessage(content=query)]
        result = asyncio.run(agent.ainvoke(inputs))
    # print(result)


def test_tianyancha():
    tool_params = {
        "tianyancha.search_company": {
            "api_key": tyc_api_key,
        },
    }

    tools = load_tools(tool_params)
    sys_msg = "You are a helpful assistant."
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我查询云南白药公司的基本信息")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_bisheng_code_interpreter_1():
    """
    仅执行代码
    """
    tool_params = {
        "native_code_interpreter": {"files": None},
    }

    tools = load_tools(tool_params)
    sys_msg = "You are a helpful assistant."
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我在一个txt文件中写入“你好”保存下来，并把保存路径发给我")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_bisheng_code_interpreter_2():
    """
    涉及文件操作
    """

    class FileInfo(BaseModel):
        """Information about a file to be uploaded."""

        source_path: str
        description: str

    tool_params = {
        "native_code_interpreter": {
            'files': {
                'temp_test': FileInfo(
                    source_path='/app/bisheng/README.md',
                    description='This is a md file',
                )
            },
        },
    }

    tools = load_tools(tool_params)
    sys_msg = "You are a helpful assistant."
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(model_name='gpt-4-0125-preview', http_client=HTTP_ASYNC_CLIENT)

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        system_message=sys_msg,
    )

    inputs = [HumanMessage(content="请问这个md文件的最后一行内容是什么")]
    result = asyncio.run(agent.ainvoke(inputs))


def list_tools_info():
    import pandas as pd
    from bisheng_langchain.gpts.load_tools import _API_TOOLS

    tool_params = {
        "get_current_time": {},
        "calculator": {},
        "arxiv": {},
        "dalle_image_generator": {
            "openai_api_key": openai_api_key,
            "openai_proxy": openai_proxy,
        },
        "bing_search": {
            "bing_subscription_key": os.getenv("BING_SUBSCRIPTION_KEY"),
            "bing_search_url": os.getenv("BING_SEARCH_URL"),
        },
        "native_code_interpreter": {"files": None},
    }
    exclude_method = {'tianyancha.build_header', 'tianyancha.validate_environment'}
    api_tools = list(_API_TOOLS.keys())
    tool_params.update({tool: {'api_key': tyc_api_key} for tool in api_tools if tool not in exclude_method})
    tools = load_tools(tool_params)

    df = pd.DataFrame(columns=['tool_name', 'tool_description', 'tool_args'])
    for tool in tools:
        # print(tool.name)
        # print(tool.description)
        # print(tool.args_schema.schema()['properties'])

        new_row = pd.DataFrame(
            {
                'tool_name': [tool.name],
                'tool_description': [tool.description],
                'tool_args': [tool.args_schema.schema()['properties']],
            }
        )

        df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel('./024工具列表.xlsx')


if __name__ == '__main__':
    # test_all_tools()
    # test_tianyancha()
    # test_bisheng_code_interpreter_1()
    # test_bisheng_code_interpreter_2()
    # list_tools_info()
    pass
