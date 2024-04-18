import operator
import os
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    Union,
)

import httpx
from bisheng_langchain.gpts.load_tools import load_tools
from langchain import hub
from langchain.agents import create_openai_functions_agent
from langchain.chains.openai_functions import (
    create_openai_fn_runnable,
    create_structured_output_runnable,
)
from langchain.output_parsers import PydanticToolsParser
from langchain.prompts import ChatPromptTemplate
from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai.chat_models import ChatOpenAI

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_agent_executor


def bisheng_create_openai_tools_runnable(
    tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable]],
    llm: Runnable,
    *,
    prompt: Optional[BasePromptTemplate],
) -> Runnable:
    oai_tools = [convert_to_openai_tool(t) for t in tools]
    llm_kwargs: Dict[str, Any] = {"tools": oai_tools}
    output_parser = PydanticToolsParser(tools=tools, first_tool_only=True)
    if prompt:
        return prompt | llm.bind(**llm_kwargs) | output_parser
        # return prompt | llm.bind(**llm_kwargs)
    else:
        return llm.bind(**llm_kwargs) | output_parser


def get_plan_and_solve_cute_agent_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    system_message: str,
    interrupt_before_action: bool,
    **kwargs,
):
    # todo: support system_message
    prompt = hub.pull("hwchase17/openai-functions-agent")
    agent_runnable = create_openai_functions_agent(llm, tools, prompt)
    agent_executor = create_agent_executor(agent_runnable, tools)
    # note: test the agent_executor
    # agent_executor.invoke({'input': 'Hello', 'chat_history': []}, debug=True)

    # define the state
    class PlanExecute(TypedDict):
        input: str
        plan: List[str]
        past_steps: Annotated[List[Tuple], operator.add]
        response: str

    class Plan(BaseModel):
        """Plan to follow in future"""

        steps: List[str] = Field(description="different steps to follow, should be in sorted order")

    planner_prompt = ChatPromptTemplate.from_messages(
        [
            (
                'system',
                """For the given objective, come up with a simple step by step plan. \
This plan should involve individual tasks, that if executed correctly will yield the correct answer. Do not add any superfluous steps. \
The result of the final step should be the final answer. Make sure that each step has all the information needed - do not skip steps.
You must call the function Plan.

{objective}""",
            )
        ]
    )
    planner = create_structured_output_runnable(Plan, llm, planner_prompt, enforce_function_usage=False)
    # note: test the planner
    # res = planner.invoke({"objective": "帮我查询去年今天的新闻"})
    # print(res)

    replanner_prompt = ChatPromptTemplate.from_messages(
        [
            (
                'system',
                """For the given objective, come up with a simple step by step plan. \
This plan should involve individual tasks, that if executed correctly will yield the correct answer. Do not add any superfluous steps. \
The result of the final step should be the final answer. Make sure that each step has all the information needed - do not skip steps.

Your objective was this:
{input}

Your original plan was this:
{plan}

You have currently done the follow steps:
{past_steps}

如果需要更新计划，请调用Plan。如果保持原计划，请调用Plan。如果不需要不需要更新计划了且已执行完所有步骤，那么请总结已执行的步骤，调用Response返回给用户。""",
            )
        ]
        # Update your plan accordingly. If no more steps are needed and you should summarise the results of the steps that have been performed and return them to the user, then respond with that. Otherwise, fill out the plan. Only add steps to the plan that still NEED to be done. Do not return previously done steps as part of the plan."""
    )

    class Response(BaseModel):
        """Response to user."""

        response: str

    # replanner = create_openai_fn_runnable(
    #     [Plan, Response],
    #     llm,
    #     replanner_prompt,
    # )
    replanner = bisheng_create_openai_tools_runnable([Plan, Response], llm, prompt=replanner_prompt)

    # res = replanner.invoke(
    #     {
    #         "input": "帮我查询去年今天的新闻",
    #         "plan": ["通过时间查询工具确定去年今天的时间", "查询去年今天的新闻内容"],
    #         "past_steps": [
    #             ("通过时间查询工具确定去年今天的时间", "去年今天的时间为2023-04-18"),
    #             # ("查询去年今天的新闻内容", "新闻内容为NBA冠军是湖人队"),
    #         ],
    #     }
    # )

    # print(res)

    # create the graph
    def execute_step(state: PlanExecute):
        task = state["plan"][0]
        agent_response = agent_executor.invoke({"input": task, "chat_history": []}, debug=True)
        return {"past_steps": (task, agent_response["agent_outcome"].return_values["output"])}

    def plan_step(state: PlanExecute):
        plan = planner.invoke({"objective": state["input"]})
        return {"plan": plan.steps}

    def replan_step(state: PlanExecute):
        output = replanner.invoke(state)
        if isinstance(output, Response):
            return {"response": output.response}
        else:
            return {"plan": output.steps}

    def should_end(state: PlanExecute):
        if "response" in state and state["response"]:
            return True
        else:
            return False

    workflow = StateGraph(PlanExecute)

    # Add the plan node
    workflow.add_node("planner", plan_step)

    # Add the execution step
    workflow.add_node("agent", execute_step)

    # Add a replan node
    workflow.add_node("replan", replan_step)

    workflow.set_entry_point("planner")

    # From plan we go to agent
    workflow.add_edge("planner", "agent")

    # From agent, we replan
    workflow.add_edge("agent", "replan")

    workflow.add_conditional_edges(
        "replan",
        # Next, we pass in the function that will determine which node is called next.
        should_end,
        {
            # If `tools`, then we call the tool node.
            True: END,
            False: "agent",
        },
    )

    # Finally, we compile it!
    # This compiles it into a LangChain Runnable,
    # meaning you can use it as you would any other runnable
    app = workflow.compile()
    return app


if __name__ == '__main__':
    from dotenv import load_dotenv

    load_dotenv('/app/.env', override=True)

    httpx_client = httpx.Client(proxies=os.getenv('OPENAI_PROXY'))
    tools = load_tools(
        {
            'get_current_time': {},
            'arxiv': {},
            'bing_search': {
                'bing_subscription_key': os.getenv('BING_SUBSCRIPTION_KEY'),
                'bing_search_url': 'https://api.bing.microsoft.com/v7.0/search',
            },
        }
    )

    """ qwen1.5 接口在多处不兼容，暂时不使用
     1. tool choice 有问题
     2. 仅支持传入tools参数，不支持传入functions参数
    # """
    # llm = ChatOpenAI(model='qwen1.5', base_url='http://34.87.129.78:9300/v1', streaming=False, temperature=0.1)

    llm = ChatOpenAI(
        model='gpt-4-turbo',
        api_key=os.getenv('OPENAI_API_KEY'),
        http_client=httpx_client,
        streaming=False,
        temperature=0.1,
    )

    app = get_plan_and_solve_cute_agent_executor(
        tools=tools,
        llm=llm,
        system_message='Hello',
        interrupt_before_action=False,
    )
    app.invoke({"input": "去年今天的重大事件"}, debug=True)
