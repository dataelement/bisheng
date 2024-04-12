import os

import httpx
from bisheng_langchain.chat_models import ChatQWen
from bisheng_langchain.gpts.auto_tool_selected import ToolInfo, ToolSelector
from dotenv import load_dotenv
from langchain.globals import set_debug
from langchain_openai import ChatOpenAI

set_debug(True)
load_dotenv('/app/.env', override=True)
httpx_client = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))
async_http_client = httpx.AsyncClient(proxies=os.getenv('OPENAI_PROXY'))


def test_select_tools():
    llm = ChatOpenAI(
        model='gpt-4-0125-preview',
        temperature=0.0,
        http_async_client=async_http_client,
        http_client=httpx_client,
    )
    # llm = ChatQWen(model="qwen1.5-72b-chat", temperature=0.0, api_key=os.getenv('QWEN_API_KEY'))
    tools = [
        ToolInfo(tool_name='get_current_time', tool_description='获取当前时间'),
        ToolInfo(tool_name='calculator', tool_description='计算器'),
        ToolInfo(tool_name='arxiv', tool_description='查找论文'),
        ToolInfo(tool_name='dalle_image_generator', tool_description='dalle_image_generator'),
        ToolInfo(tool_name='tianyancha.search_company', tool_description='tianyancha.search_company'),
        ToolInfo(tool_name='bing_search', tool_description='bing web search'),
    ]

    tool_selector = ToolSelector(llm=llm, tools=tools)

    task_name = '论文助手'
    task_description = """查找文献，查找论文"""
    print(tool_selector.select(task_name, task_description))


if __name__ == '__main__':
    test_select_tools()
