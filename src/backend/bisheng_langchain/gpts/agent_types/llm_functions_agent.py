import json
import re

from bisheng_langchain.gpts.message_types import LiberalFunctionMessage, LiberalToolMessage
from langchain.tools import BaseTool
from langchain.tools.render import format_tool_to_openai_tool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import FunctionMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.graph.message import MessageGraph
from langgraph.prebuilt import ToolNode
from langgraph.utils.runnable import RunnableCallable


def get_openai_functions_agent_executor(tools: list[BaseTool], llm: LanguageModelLike,
                                        system_message: str, interrupt_before_action: bool,
                                        **kwargs):

    def _get_messages(messages):
        msgs = []
        for m in messages:
            if isinstance(m, LiberalToolMessage):
                _dict = m.dict()
                _dict['content'] = str(_dict['content'])
                m_c = ToolMessage(**_dict)
                msgs.append(m_c)
            else:
                msgs.append(m)

        return [SystemMessage(content=system_message)] + msgs

    if tools:
        llm_with_tools = llm.bind(tools=[format_tool_to_openai_tool(t) for t in tools])
    else:
        llm_with_tools = llm

    agent = _get_messages | llm_with_tools
    tool_nodes = ToolNode(tools=tools)

    # Define the function that determines whether to continue or not
    def should_continue(messages):
        last_message = messages[-1]
        # If there is no function call, then we finish
        if 'tool_calls' not in last_message.additional_kwargs:
            if '|<instruct>|' in system_message:
                # cohere model
                pattern = r'Answer:(.+)\nGrounded answer'
                match = re.search(pattern, last_message.content)
                if match:
                    last_message.content = match.group(1)
            return 'end'
        # Otherwise if there is, we continue
        else:
            return 'continue'

    # Define the function to execute tools
    async def acall_tool(messages):
        tool_messages = await tool_nodes.ainvoke(messages, None, store=None)
        return tool_messages

    def call_tool(messages):
        tool_messages = tool_nodes.invoke(messages, config=None, store=None)
        return tool_messages

    workflow = MessageGraph()

    # Define the two nodes we will cycle between
    workflow.add_node('agent', agent)
    workflow.add_node('action', RunnableCallable(call_tool, acall_tool))

    # Set the entrypoint as `agent`
    # This means that this node is the first one called
    workflow.set_entry_point('agent')

    # We now add a conditional edge
    workflow.add_conditional_edges(
        # First, we define the start node. We use `agent`.
        # This means these are the edges taken after the `agent` node is called.
        'agent',
        # Next, we pass in the function that will determine which node is called next.
        should_continue,
        # Finally we pass in a mapping.
        # The keys are strings, and the values are other nodes.
        # END is a special node marking that the graph should finish.
        # What will happen is we will call `should_continue`, and then the output of that
        # will be matched against the keys in this mapping.
        # Based on which one it matches, that node will then be called.
        {
            # If `tools`, then we call the tool node.
            'continue': 'action',
            # Otherwise we finish.
            'end': END,
        },
    )

    # We now add a normal edge from `tools` to `agent`.
    # This means that after `tools` is called, `agent` node is called next.
    workflow.add_edge('action', 'agent')

    # Finally, we compile it!
    # This compiles it into a LangChain Runnable,
    # meaning you can use it as you would any other runnable
    app = workflow.compile(checkpointer=False)
    if interrupt_before_action:
        app.interrupt = ['action:inbox']
    return app


def get_qwen_local_functions_agent_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    system_message: str,
    interrupt_before_action: bool,
    **kwargs,
):

    async def _get_messages(messages):
        msgs = []
        for m in messages:
            if isinstance(m, LiberalFunctionMessage):
                _dict = m.dict()
                _dict['content'] = str(_dict['content'])
                m_c = FunctionMessage(**_dict)
                msgs.append(m_c)
            else:
                msgs.append(m)

        return [SystemMessage(content=system_message)] + msgs

    if tools:
        llm_with_tools = llm.bind(
            functions=[format_tool_to_openai_tool(t)['function'] for t in tools])
    else:
        llm_with_tools = llm
    agent = _get_messages | llm_with_tools
    tool_nodes = ToolNode(tools=tools)

    # Define the function that determines whether to continue or not
    def should_continue(messages):
        last_message = messages[-1]
        # If there is no function call, then we finish
        if 'function_call' not in last_message.additional_kwargs:
            return 'end'
        # Otherwise if there is, we continue
        else:
            return 'continue'

    # Define the function to execute tools
    async def call_tool(messages):
        tool_messages = await tool_nodes.ainvoke(messages, config=None, store=None)
        return tool_messages

    workflow = MessageGraph()

    # Define the two nodes we will cycle between
    workflow.add_node('agent', agent)
    workflow.add_node('action', call_tool)

    # Set the entrypoint as `agent`
    # This means that this node is the first one called
    workflow.set_entry_point('agent')

    # We now add a conditional edge
    workflow.add_conditional_edges(
        # First, we define the start node. We use `agent`.
        # This means these are the edges taken after the `agent` node is called.
        'agent',
        # Next, we pass in the function that will determine which node is called next.
        should_continue,
        # Finally we pass in a mapping.
        # The keys are strings, and the values are other nodes.
        # END is a special node marking that the graph should finish.
        # What will happen is we will call `should_continue`, and then the output of that
        # will be matched against the keys in this mapping.
        # Based on which one it matches, that node will then be called.
        {
            # If `tools`, then we call the tool node.
            'continue': 'action',
            # Otherwise we finish.
            'end': END,
        },
    )

    # We now add a normal edge from `tools` to `agent`.
    # This means that after `tools` is called, `agent` node is called next.
    workflow.add_edge('action', 'agent')

    # Finally, we compile it!
    # This compiles it into a LangChain Runnable,
    # meaning you can use it as you would any other runnable
    app = workflow.compile()
    if interrupt_before_action:
        app.interrupt = ['action:inbox']
    return app
