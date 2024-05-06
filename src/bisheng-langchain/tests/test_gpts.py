import asyncio
from langchain.globals import set_debug

import dotenv
from bisheng_langchain.gpts.load_tools import load_tools
# from bisheng_langchain.gpts.agent import ConfigurableAgent
from langchain.globals import set_debug
from langchain.tools import tool
from langchain_core.messages import HumanMessage

dotenv.load_dotenv('.env')
set_debug(True)


@tool('arxiv')
def fake_arxiv_tool(query: str):
    """A wrapper around Arxiv.org
    Useful for when you need to answer questions about Physics, Mathematics,
    Computer Science, Quantitative Biology, Quantitative Finance, Statistics,
    Electrical Engineering, and Economics
    from scientific articles on arxiv.org.
    Input should be a search query.
    """
    return "BERT论文发表时提及在11个NLP（Natural Language Processing，自然语言处理）任务中获得了新的state-of-the-art的结果，令人目瞪口呆。"


def test_agent():

    tools = load_tools(tool_params={"tianyancha.law_suit_case": {"api_key": ""}}, )
    model_name = "gpt-4-0125-preview"
    sys_msg = "You are a helpful assistant."
    agent = ConfigurableAgent(model_name=model_name, tools=tools, system_message=sys_msg)

    inputs = [HumanMessage(content="帮我查询云南白药的企业信息")]
    result = asyncio.run(agent.ainvoke(inputs))


def test_tools():
    tools = load_tools(tool_params={
        "sina_realtime_info": {},
        "sina_history_KLine": {},
        "macro_china_shrzgm": {},
    }, )
    tools[0].run({"stock_symbol": "399001", "stock_exchange": "sz"})


test_tools()
