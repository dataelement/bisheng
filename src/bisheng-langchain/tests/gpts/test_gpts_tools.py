import asyncio
import os
from urllib.parse import urlparse

import dotenv
import httpx
import yaml
from bisheng_langchain.gpts.assistant import BishengAssistant, ConfigurableAssistant
from bisheng_langchain.gpts.load_tools import load_tools
from langchain.globals import set_debug
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

set_debug(True)
dotenv.load_dotenv('/app/.env', override=True)


tool_config_path = '/app/bisheng/src/bisheng-langchain/bisheng_langchain/gpts/config/tools.yaml'
with open(tool_config_path, 'r') as f:
    TOOLS_CONFIG = {i.pop('type'): i for i in yaml.load(f, Loader=yaml.FullLoader)}

# dalle-3
openai_api_key = os.getenv('OPENAI_API_KEY')
openai_proxy = os.getenv('OPENAI_PROXY')
async_http_client = httpx.AsyncClient(proxies=openai_proxy)
httpx_client = httpx.Client(proxies=openai_proxy)

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
    llm = ChatOpenAI(
        model='gpt-4-0125-preview',
        temperature=0.0,
        http_async_client=async_http_client,
        http_client=httpx_client,
    )
    sys_msg = "You are a helpful assistant."

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        assistant_message=sys_msg,
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
    llm = ChatOpenAI(
        model='gpt-4-0125-preview',
        temperature=0.0,
        http_async_client=async_http_client,
        http_client=httpx_client,
    )

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        assistant_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我查询云南白药公司的基本信息")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_bisheng_code_interpreter_1():
    """
    仅执行代码
    """
    tool_params = {"code_interpreter": TOOLS_CONFIG['code_interpreter']}

    tools = load_tools(tool_params)
    sys_msg = "You are a helpful assistant."
    agent_type = "get_openai_functions_agent_executor"
    llm = ChatOpenAI(
        model='gpt-4-0125-preview',
        temperature=0.0,
        http_async_client=async_http_client,
        http_client=httpx_client,
    )

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        assistant_message=sys_msg,
    )

    inputs = [HumanMessage(content="帮我画一个折线图，横坐标是时间，纵坐标是销售额，数据请随意编造, 请使用中文")]
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
        "code_interpreter": {
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
    llm = ChatOpenAI(
        model='gpt-4-0125-preview',
        temperature=0.0,
        http_async_client=async_http_client,
        http_client=httpx_client,
    )

    agent = ConfigurableAssistant(
        agent_executor_type=agent_type,
        tools=tools,
        llm=llm,
        assistant_message=sys_msg,
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


def test_math():
    questions = [
        '已知椭圆的长轴长度为8，短轴长度为6，求椭圆的离心率，并计算其焦点坐标。',
        '考虑区域 $D$，它由曲线 $y = x^2$，$y = 4$，$x = 0$ 和 $x = 2$ 围成。计算二重积分∬D xydxdy的值',
        '考虑函数f(x)=(ln(x^2+1))/(x^3+2*x^2)在x=0处的极限',
    ]
    for query in questions:
        bisheng_assistant = BishengAssistant(
            "/app/bisheng/src/bisheng-langchain/bisheng_langchain/gpts/config/base_scene.yaml"
        )
        result = bisheng_assistant.run(query)
        for r in result:
            print(f'------------------')
            print(type(r), r)


if __name__ == '__main__':
    # test_all_tools()
    # test_tianyancha()
    test_bisheng_code_interpreter_1()
    # test_bisheng_code_interpreter_2()
    # list_tools_info()
    # test_math()
