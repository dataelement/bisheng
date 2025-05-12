import operator
from typing import Annotated, Sequence, TypedDict, Union

from bisheng_langchain.gpts.prompts.react_agent_prompt import react_agent_prompt
from langchain.agents import create_structured_chat_agent
from langchain.tools import BaseTool
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.utils.runnable import RunnableCallable


def get_react_agent_executor(tools: list[BaseTool], llm: LanguageModelLike, system_message: str,
                             interrupt_before_action: bool, **kwargs):
    prompt = react_agent_prompt
    prompt = prompt.partial(assistant_message=system_message)
    agent = create_structured_chat_agent(llm, tools, prompt)
    agent_executer = create_agent_executor(agent, tools)
    return agent_executer


def _get_agent_state(input_schema=None):
    if input_schema is None:

        class AgentState(TypedDict):
            # The input string
            input: str
            # The list of previous messages in the conversation
            chat_history: Sequence[BaseMessage]
            # The outcome of a given call to the agent
            # Needs `None` as a valid type, since this is what this will start as
            agent_outcome: Union[AgentAction, AgentFinish, None]
            # List of actions and corresponding observations
            # Here we annotate this with `operator.add` to indicate that operations to
            # this state should be ADDED to the existing values (not overwrite it)
            intermediate_steps: Annotated[list[tuple[AgentAction, str]], operator.add]

    else:

        class AgentState(input_schema):
            # The outcome of a given call to the agent
            # Needs `None` as a valid type, since this is what this will start as
            agent_outcome: Union[AgentAction, AgentFinish, None]
            # List of actions and corresponding observations
            # Here we annotate this with `operator.add` to indicate that operations to
            # this state should be ADDED to the existing values (not overwrite it)
            intermediate_steps: Annotated[list[tuple[AgentAction, str]], operator.add]

    return AgentState


def create_agent_executor(agent_runnable, tools, input_schema=None) -> CompiledStateGraph:
    """This is a helper function for creating a graph that works with LangChain Agents.

    Args:
        agent_runnable (RunnableLike): The agent runnable.
        tools (list): A list of tools to be used by the agent.
        input_schema (dict, optional): The input schema for the agent. Defaults to None.

    Returns:
        The `CompiledStateGraph` object.
    """

    tool_executor = ToolNode(tools=tools)

    state = _get_agent_state(input_schema)

    # Define logic that will be used to determine which conditional edge to go down

    def should_continue(data):
        # If the agent outcome is an AgentFinish, then we return `exit` string
        # This will be used when setting up the graph to define the flow
        if isinstance(data['agent_outcome'], AgentFinish):
            return 'end'
        # Otherwise, an AgentAction is returned
        # Here we return `continue` string
        # This will be used when setting up the graph to define the flow
        else:
            return 'continue'

    def run_agent(data, config):
        agent_outcome = agent_runnable.invoke(data, config)
        return {'agent_outcome': agent_outcome}

    async def arun_agent(data, config):
        agent_outcome = await agent_runnable.ainvoke(data, config)
        return {'agent_outcome': agent_outcome}

    # Define the function to execute tools
    def execute_tools(data, config):
        # Get the most recent agent_outcome - this is the key added in the `agent` above
        agent_action = data['agent_outcome']
        if not isinstance(agent_action, list):
            agent_action = [agent_action]
        output = tool_executor.batch(agent_action, config, return_exceptions=True)
        return {
            'intermediate_steps': [(action, str(out)) for action, out in zip(agent_action, output)]
        }

    async def aexecute_tools(data, config):
        # Get the most recent agent_outcome - this is the key added in the `agent` above
        agent_action = data['agent_outcome']
        if not isinstance(agent_action, list):
            agent_action = [agent_action]
        output = await tool_executor.abatch(agent_action, config, return_exceptions=True)
        return {
            'intermediate_steps': [(action, str(out)) for action, out in zip(agent_action, output)]
        }

    # Define a new graph
    workflow = StateGraph(state)

    # Define the two nodes we will cycle between
    workflow.add_node('agent', RunnableCallable(run_agent, arun_agent))
    workflow.add_node('tools', RunnableCallable(execute_tools, aexecute_tools))

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
            'continue': 'tools',
            # Otherwise we finish.
            'end': END,
        },
    )

    # We now add a normal edge from `tools` to `agent`.
    # This means that after `tools` is called, `agent` node is called next.
    workflow.add_edge('tools', 'agent')

    # Finally, we compile it!
    # This compiles it into a LangChain Runnable,
    # meaning you can use it as you would any other runnable
    return workflow.compile(checkpointer=False)


if __name__ == '__main__':
    pass
