import abc
import requests
from typing import Any, Type
from bisheng_langchain.agents import ChatglmFunctionsAgent
from bisheng_langchain.chat_models.host_llm import HostChatGLM
from langchain.schema.messages import ChatMessage
from langchain.tools import BaseTool
from langchain.agents.agent import AgentExecutor
from langchain.agents.tools import Tool
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


def init_calculator_by_tool() -> Tool:
    cal = Calculator()
    return Tool(
        name="Calculator",
        description="Useful for when you need to answer questions about math.",
        args_schema=ArgSchema,
        func=cal._run,
    )


def test_chatglm_functions_call():
    llm = HostChatGLM(model_name='chatglm3-6b', host_base_url='http://192.168.106.20:7001/v2.1/models', max_tokens=8192)
    messages = [
        {'role': 'system', 'content': 'Answer the following questions as best as you can. You have access to the following tools:', 'tools': [{'name': 'Calculator', 'description': 'Useful for when you need to answer questions about math', 'parameters': {'type': 'object', 'properties': {'formula': {'type': 'string', 'description': 'The formula to be calculated'}}, 'required': ['formula']}}]},
        {'role': 'user', 'content': '12345679乘以54等于多少？'},
        {'role': 'assistant', 'metadata': 'Calculator', 'content': " ```python\ntool_call(formula='12345679*54')\n```"},
        {'role': 'observation', 'content': '666666666'},
        {'role': 'user', 'content': ''},
        ]

    chat_messages = []
    for message in messages:
        additional_kwargs = dict()
        for key in message.keys():
            if key not in ['role', 'content']:
                additional_kwargs[key] = message[key]
        chat_messages.append(ChatMessage(role=message['role'], content=message['content'], additional_kwargs=additional_kwargs))

    predicted_message = llm.predict_messages(chat_messages)
    print(predicted_message, type(predicted_message))


def test_chatglm_functions_agent():
    # cal = Calculator()
    cal = init_calculator_by_tool()
    llm = HostChatGLM(model_name='chatglm3-6b', host_base_url='http://192.168.106.12:9001/v2.1/models', max_tokens=8192)
    agent = ChatglmFunctionsAgent.from_llm_and_tools(llm=llm, tools=[cal], verbose=True, handle_parsing_errors=True)
    executor = AgentExecutor.from_agent_and_tools(agent=agent, tools=[cal])
    print(executor.run("12 乘以 12 等于多少？3 + 3 等于多少"))


# test_chatglm_functions_call()
test_chatglm_functions_agent()


