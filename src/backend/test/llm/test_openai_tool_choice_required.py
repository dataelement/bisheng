from types import SimpleNamespace

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.llm.llm import BishengLLM


def _make_llm(server_type: str = LLMServerType.OPENAI.value) -> BishengLLM:
    return BishengLLM.model_construct(
        model_id=1,
        model_name='gpt-4o',
        app_id='test',
        app_type=ApplicationTypeEnum.MODEL_TEST,
        app_name='test',
        user_id=1,
        server_info=SimpleNamespace(type=server_type),
    )


def _tool_schema() -> dict:
    return {
        'type': 'function',
        'function': {
            'name': 'lookup',
            'description': 'lookup data',
            'parameters': {
                'type': 'object',
                'properties': {},
            },
        },
    }


def test_bind_tools_requires_openai_tool_call():
    bound = _make_llm().bind_tools([_tool_schema()])

    assert bound.kwargs['tool_choice'] == 'required'


def test_bind_with_tools_requires_openai_tool_call():
    bound = _make_llm().bind(tools=[_tool_schema()])

    assert bound.kwargs['tool_choice'] == 'required'


def test_direct_openai_tool_call_kwargs_require_tool_choice():
    _, kwargs = _make_llm().parse_kwargs([], {'tools': [_tool_schema()]})

    assert kwargs['tool_choice'] == 'required'


def test_non_openai_tool_call_kwargs_are_not_changed():
    _, kwargs = _make_llm(LLMServerType.QWEN.value).parse_kwargs([], {'tools': [_tool_schema()]})

    assert 'tool_choice' not in kwargs
