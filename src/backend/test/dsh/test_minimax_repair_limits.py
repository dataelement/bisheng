"""Format recovery cannot execute partial calls, replay transport or lose usage."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from bisheng.common.errcode.dsh import DshUpstreamErrorError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.infrastructure.chat_adapter import ChatExecution


def reply(args, *, usage=True, name="f"):
    return AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}]
        },
        response_metadata={"finish_reason": "tool_calls"},
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12} if usage else None,
    )


class Supplier:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0
        self.choices = []

    async def ainvoke(self, messages, **parameters):
        self.calls += 1
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result

    def bind(self, **parameters):
        self.choices.append(parameters["tool_choice"])
        return self


def execution(replies):
    llm = Supplier(replies)
    call = ChatExecution(llm, [], {}, ChatCapabilities(tool_streaming=False))
    call.allowed_tool_names = {"f"}
    return call, llm


async def test_recovery_retains_attempt_evidence_and_all_measured_usage(capsys):
    call, llm = execution([reply('{"private-secret":'), reply('{"x":1}')])
    output = []
    call.capture = SimpleNamespace(entered=lambda units: None, output=output.append, terminal=lambda result: None)
    deltas = [delta async for delta in call.stream()]
    assert len(deltas) == 1 and deltas[0]["tool_calls"][0]["function"]["arguments"] == '{"x":1}'
    assert llm.calls == 2 and llm.choices == ["required"]
    assert call.usage.total_tokens == 24
    assert output[0]["released_to_client"] is False
    assert output[1]["protocol_repair"]["additional_input"]["type"] == "human"
    assert call.messages == []
    assert "private-secret" not in capsys.readouterr().err


@pytest.mark.parametrize("at", [1, 2])
async def test_transport_failure_is_never_replayed(at):
    replies = [ConnectionError("offline")] if at == 1 else [reply('{"x":'), ConnectionError("offline")]
    call, llm = execution(replies)
    with pytest.raises(ConnectionError):
        _ = [delta async for delta in call.stream()]
    assert llm.calls == at
    assert call.messages == []
    assert call.usage.total_tokens is None


async def test_unknown_attempt_usage_cannot_be_counted_as_zero():
    call, llm = execution([reply('{"x":', usage=False), reply('{"x":1}')])
    _ = [delta async for delta in call.stream()]
    assert llm.calls == 2 and call.usage.total_tokens is None


async def test_forbidden_or_unknown_tools_do_not_trigger_format_correction():
    call, llm = execution([reply('{"x":')])
    call.repair_tool_choice = None
    with pytest.raises(DshUpstreamErrorError):
        _ = [delta async for delta in call.stream()]
    assert llm.calls == 1
    call, llm = execution([reply('{"x":1}', name="not-allowed")])
    with pytest.raises(DshUpstreamErrorError):
        _ = [delta async for delta in call.stream()]
    assert llm.calls == 1


async def test_selected_tool_constraint_is_preserved_during_correction():
    call, llm = execution([reply('{"x":'), reply('{"x":1}')])
    call.repair_tool_choice = {"type": "function", "function": {"name": "f"}}
    _ = [delta async for delta in call.stream()]
    assert llm.choices == [{"type": "function", "function": {"name": "f"}}]
