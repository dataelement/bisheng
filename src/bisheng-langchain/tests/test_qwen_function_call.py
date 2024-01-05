import abc
from typing import Any, Type
from langchain.agents import AgentType, Tool, initialize_agent
from langchain.chat_models import ChatOpenAI
from langchain.utilities import SerpAPIWrapper
from langchain.agents.agent import AgentExecutor
from bisheng_langchain.chat_models.host_llm import HostQwenChat
from bisheng_langchain.agents import LLMFunctionsAgent
from langchain.tools import BaseTool
from pydantic import Field, BaseModel


class ArgSchema(BaseModel):
    formula: str = Field(..., description="the formula to be calculated")


class Calculator(BaseTool, abc.ABC):
    name = "Calculator"
    description = "Useful for when you need to answer questions about math"
    args_schema: Type[BaseModel] = ArgSchema

    def __init__(self):
        super().__init__()

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        # 用例中没有用到 arun 不予具体实现
        pass

    def _run(self, formula: str) -> str:
        formula = formula.replace("^", "**")
        if "sqrt" in formula:
            formula = formula.replace("sqrt", "math.sqrt")
        elif "log" in formula:
            formula = formula.replace("log", "math.log")
        return eval(formula)


cal = Calculator()
search = SerpAPIWrapper()
# llm = ChatOpenAI(temperature=0, model="gpt-3.5-turbo-0613")
llm = HostQwenChat(
    model_name='Qwen-1_8B-Chat',
    host_base_url='http://192.168.106.12:9001/v2.1/models', max_tokens=8192)


tools = [
    Tool(
        name="Search",
        func=search.run,
        description="useful for when you need to answer questions about current events. You should ask targeted questions",
    ),
    Tool(
        name="Calculator",
        func=cal.run,
        args_schema=cal.args_schema,
        description="useful for when you need to answer questions about math",
    ),
]

agent = LLMFunctionsAgent.from_llm_and_tools(
    llm=llm, tools=tools, verbose=True, handle_parsing_errors=True)
executor = AgentExecutor.from_agent_and_tools(agent=agent, tools=tools, verbose=True)
# print(executor.run("12 乘以 12 等于多少？3 + 3 等于多少"))
print(executor.run("今天上海天气怎么样？"))