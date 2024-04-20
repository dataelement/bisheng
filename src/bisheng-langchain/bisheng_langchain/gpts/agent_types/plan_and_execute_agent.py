import operator
import os
import time
from copy import deepcopy
from textwrap import dedent
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
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.output_parsers import PydanticToolsParser
from langchain.prompts import PromptTemplate
from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import BasePromptTemplate
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


def create_structured_output_runnable(
    llm: Runnable,
    prompt: str,
    output_format: Type[BaseModel],
):
    output_parser = PydanticOutputParser(pydantic_object=output_format)
    output_format_instructions = output_parser.get_format_instructions()

    _prompt = PromptTemplate.from_template(
        prompt, partial_variables={'format_instructions': output_format_instructions}
    )
    return _prompt | llm | output_parser


def get_plan_and_solve_agent_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    system_message: str,
    interrupt_before_action: bool,
    **kwargs,
):
    avaliable_tools = "\n".join([f"- {tool.name}" for tool in tools])
    # todo: support system_message
    agent_prompt = hub.pull("hwchase17/openai-tools-agent")
    agent_runnable = create_openai_tools_agent(llm, tools, agent_prompt)
    # agent_executor = create_agent_executor(agent_runnable=agent_runnable, tools=tools)
    agent_executor = AgentExecutor(agent=agent_runnable, tools=tools, stream_runnable=False)
    # test the agent_executor
    # r1 = agent_executor.invoke(
    #     {'input': '调用工具查询现在的时间，并查询去年今天的重大新闻', 'chat_history': []}, debug=True
    # )
    # print(r1)

    # define the state
    class PlanExecute(TypedDict):
        input: str
        plan: List[str]
        unexecuted_steps: List[str]
        past_steps: Annotated[List[Tuple], operator.add]
        response: str
        observation: int

    class Plan(BaseModel):
        """Plan to follow in future"""

        steps: List[str] = Field(description="different steps to follow, should be in sorted order")

    plan_msg = dedent(
        """你是一个善于根据用户提问列出实施计划的专家。

## 可列入计划的工具
{avaliable_tools}

## 任务
1. 针对给定的用户提问，提出一个简单的分步计划；
2. 该计划应涉及单个任务，如果依次正确执行，就能得到正确答案。不要添加任何多余的步骤；
3. 执行完最后一步的结果应该是最终答案。确保每个步骤都包含所需的全部信息--不要跳过步骤；
4. 在"可列入计划的工具"中选择合适的工具放入你的执行计划，或许能帮你更好地列出计划；
5. 计划中的步骤应该按照执行顺序排列；
6. 计划描述应该清晰明了，不要使用模糊的语言，不要指代不明确的对象。

## 用户提问
{objective}

## format_instructions
{format_instructions}
"""
    )
    planner = create_structured_output_runnable(llm=llm, prompt=plan_msg, output_format=Plan)
    # test the planner
    # res = planner.invoke(
    #     {
    #         "objective": "帮我查询去年今天的新闻",
    #         "avaliable_tools": avaliable_tools,
    #     }
    # )
    # print(res)

    class NextStep(BaseModel):
        """next step to follow"""

        next_step: int = Field(
            description="0 for reschedule, 1 for continue execution, 2 for direct output", enum=[0, 1, 2]
        )

    decide_next_step_msg = dedent(
        """你是一个善于根据用户提问列出计划的智能助手。
    
## 规则
1. 请根据"用户提问"，"原始计划"，以及"已执行的步骤和结果"，来决定是否需要重新计划或者继续执行计划，或者直接输出；
2. 如果你认为继续执行"原始计划"并不能得到最终的答案，则需要重新计划，返回0（重新计划）；
3. 如果你认为总结"已执行的步骤和结果"后，足够回答用户问题了，则返回2（直接输出）；
4. 如果你认为"原始计划"不需要再做调整了，需要继续执行"还未执行的步骤"就能回答用户提问了，则返回1（继续执行）；

## 用户提问
{input}

## 原始计划
{plan}

## 还未执行的步骤
{unexecuted_steps}

## 已执行的步骤和结果
{past_steps}

## format_instructions
{format_instructions}
"""
    )
    observer = create_structured_output_runnable(llm=llm, prompt=decide_next_step_msg, output_format=NextStep)
    # test case
    # res = observer.invoke(
    #     {
    #         "input": "帮我查询去年今天的新闻",
    #         "plan": ["通过时间查询工具确定去年今天的时间", "查询前年今天的新闻"],
    #         "unexecuted_steps": ['查询前年今天的新闻'],
    #         "past_steps": [
    #             ("通过时间查询工具确定去年今天的时间", "去年今天的时间为2023-04-18"),
    #             # ("查询去年今天的新闻内容", "新闻内容为NBA冠军是湖人队"),
    #         ],
    #     }
    # )
    # print(res)

    class Response(BaseModel):
        """Response to user."""

        response: str = Field(description="the final response to user.")

    response_msg = dedent(
        """
## 你的任务
1. 你需要根据"用户提问"以及"已执行的步骤和结果"，进行总结，将最终结果返回给用户；
2. 请务必遵守format_instructions。

## 用户提问
{input}

## 已执行的步骤和结果
{past_steps}

## format_instructions
{format_instructions} 
"""
    )
    responser = create_structured_output_runnable(llm=llm, prompt=response_msg, output_format=Response)
    # test case
    # print(
    #     responser.invoke(
    #         {
    #             "input": "帮我查询去年今天的重大新闻",
    #             "plan": ["通过时间查询工具确定去年今天的时间", "查询去年今天的新闻内容"],
    #             "past_steps": [
    #                 ("通过时间查询工具确定去年今天的时间", "去年今天的时间为2023-04-18"),
    #                 ("查询去年今天的新闻内容", "新闻内容为NBA冠军是湖人队"),
    #             ],
    #         }
    #     )
    # )

    replan_msg = """你是一个善于根据用户提问制定计划的智能助手。

    ## 任务
    1. 请根据用户提问，原始计划，以及已经执行的计划和该计划的结果，重新制定计划；
    2. 如果原始计划中，未执行的计划描述不完整或者信息缺失，则需要对该计划进行信息的补充；
    3. 不要重复制定没有意义的计划，如果你认为已经不需要制定制定新的计划了，则返回原计划即可；
    4. 你一定要按照format_instructions的格式回复。

    ## 用户提问
    {input}

    ## 原始计划
    {plan}

    ## 已执行的步骤和结果
    {past_steps}
    
    ## format_instructions
    {format_instructions}
    """
    replanner = create_structured_output_runnable(llm=llm, prompt=replan_msg, output_format=Plan)
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

    # create the graph
    def plan_step(state: PlanExecute):
        plan: Plan = planner.invoke(
            {
                "objective": state["input"],
                'avaliable_tools': avaliable_tools,
            }
        )
        return {"plan": plan.steps, 'unexecuted_steps': deepcopy(plan.steps)}

    def execute_step(state: PlanExecute):
        chat_round = 5
        cur_task = state['unexecuted_steps'].pop(0)
        chat_history = []
        past_steps = state['past_steps']
        if past_steps and len(past_steps) > 1:
            if len(past_steps) > chat_round * 2:
                past_steps = past_steps[-chat_round * 2 :]
            for i in range(0, len(past_steps), 2):
                chat_history.append(HumanMessage(content=past_steps[i]))
                chat_history.append(AIMessage(content=past_steps[i + 1]))
        agent_response = agent_executor.invoke({"input": cur_task, "chat_history": chat_history}, debug=True)
        # return {"past_steps": (cur_task, agent_response['agent_outcome'].return_values['output'])}
        return {"past_steps": (f"**{cur_task}**", agent_response['output'])}

    def observation_step(state: PlanExecute):
        output: NextStep = observer.invoke(
            {
                'input': state['input'],
                'plan': state["plan"],
                'past_steps': state['past_steps'],
                'unexecuted_steps': state['unexecuted_steps'],
            }
        )
        return {'observation': output.next_step}

    def replan_step(state: PlanExecute):
        output = replanner.invoke(state)
        return {'unexecuted_steps': output.steps}

    def response_step(state: PlanExecute):
        answer = responser.invoke(
            {
                "input": state["input"],
                # "plan": state["plan"],
                "past_steps": state["past_steps"],
            }
        )
        return {"response": answer.response}

    def next_step(state: PlanExecute):
        return state["observation"]

    workflow = StateGraph(PlanExecute)

    workflow.add_node("planner", plan_step)
    workflow.add_node("agent", execute_step)
    workflow.add_node("replanner", replan_step)
    workflow.add_node("observer", observation_step)
    workflow.add_node("responser", response_step)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "agent")
    workflow.add_edge("agent", "observer")
    workflow.add_edge("replanner", "agent")
    workflow.add_edge("responser", END)

    workflow.add_conditional_edges(
        "observer",
        next_step,
        {
            0: "replanner",
            1: "agent",
            2: "responser",
        },
    )
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

    llm = ChatOpenAI(
        model='qwen1.5',
        base_url='http://34.87.129.78:9300/v1',
        temperature=0,
    )
    # print(llm.invoke('你好'))
    # llm = ChatOpenAI(
    #     model="command-r-plus-104b", base_url='http://34.87.129.78:9100/v1', streaming=False, temperature=0.1
    # )

    # llm = ChatOpenAI(
    #     model='gpt-4-0125-preview',
    #     api_key=os.getenv('OPENAI_API_KEY'),
    #     http_client=httpx_client,
    #     streaming=False,
    #     temperature=0.1,
    # )
    app = get_plan_and_solve_agent_executor(
        tools=tools,
        llm=llm,
        system_message='You are a helpful assistant.',
        interrupt_before_action=False,
    )

    start = time.time()
    app.invoke({"input": "帮我查一下前年的NBA总冠军是哪支队伍"}, debug=True)
    print(time.time() - start)
