import asyncio
from langchain.globals import set_debug
from bisheng_langchain.gpts.agent import ConfigurableAgent
from bisheng_langchain.gpts.tools import calculate_tool
import asyncio
from langchain_core.messages import HumanMessage
from langchain.tools import tool

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


model_name = "gpt-4-1106-preview"
tools = [calculate_tool, fake_arxiv_tool]
sys_msg = "You are a helpful assistant."

agent = ConfigurableAgent(model_name=model_name, tools=tools, system_message=sys_msg)

inputs = [HumanMessage(content="帮我找一下关于人工智能的文章，并帮我计算666/2")]
result = asyncio.run(agent.ainvoke(inputs))

from bisheng_langchain.gpts.load_tools import load_tools

tools = load_tools([
    "tianyancha.search_company",
], api_key="224d0cd7-b87d-4f92-8dc6-132632c2d50a")

tools
