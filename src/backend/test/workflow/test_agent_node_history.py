from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bisheng.workflow.nodes.agent.agent import AgentNode


def test_agent_node_keeps_internal_history_with_tool_messages():
    node = AgentNode.__new__(AgentNode)
    node._chat_history_flag = True
    node._chat_history_num = 10
    node._chat_history_messages = []

    tool_call_message = AIMessage(content='', additional_kwargs={
        'tool_calls': [{
            'id': 'call_1',
            'type': 'function',
            'function': {'name': 'calculator', 'arguments': '{"x":1}'},
        }]
    })
    tool_message = ToolMessage(content='1', tool_call_id='call_1')
    node._append_chat_history_messages([
        HumanMessage(content='hello'),
        tool_call_message,
        tool_message,
        AIMessage(content='done'),
    ])

    messages = node._get_chat_history_messages()

    assert messages[1].additional_kwargs['tool_calls'][0]['function']['name'] == 'calculator'
    assert isinstance(messages[2], ToolMessage)
    assert messages[3].content == 'done'


def test_agent_node_history_respects_window_size():
    node = AgentNode.__new__(AgentNode)
    node._chat_history_flag = True
    node._chat_history_num = 2
    node._chat_history_messages = [
        HumanMessage(content='q1'),
        AIMessage(content='a1'),
        HumanMessage(content='q2'),
        AIMessage(content='a2'),
    ]

    messages = node._get_chat_history_messages()

    assert len(messages) == 2
    assert messages[0].content == 'q2'
    assert messages[1].content == 'a2'


def test_agent_node_parse_log_keeps_only_real_tool_logs():
    node = AgentNode.__new__(AgentNode)
    node.id = 'agent_1'
    node._system_prompt_list = ['system']
    node._user_prompt_list = ['user']
    node._batch_variable_list = []
    node._log_reasoning_content = ['I called search_company with the user query.']
    node._tool_invoke_list = [[
        {
            'type': 'start',
            'run_id': 'run_1',
            'name': 'search_company',
            'input': {'query': 'baidu'},
        },
        {
            'type': 'end',
            'run_id': 'run_1',
            'name': 'search_company',
            'output': 'ok',
        },
    ]]

    logs = node.parse_log('exec_1', {'output': 'final answer'})[0]

    assert [item['key'] for item in logs] == [
        'system_prompt',
        'user_prompt',
        'search_company',
        'agent_1.output',
    ]
    assert len([item for item in logs if item['type'] == 'tool']) == 1
    assert all(item['key'] != 'Thinking about content' for item in logs)
