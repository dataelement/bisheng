"""Real loopback protocol tests for the test-only Provider; no actual tool runs.

Coverage AC: AC-23, AC-24, AC-28, AC-29, AC-30, AC-31.
Only synthetic tool-result messages are supplied here. Desktop read execution
requires independent real Harness evidence; this fixture never opens that file.
"""

import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.dsh_content_safety_provider import ProviderServer

MODES = [("chat", False), ("chat", True), ("responses", False), ("responses", True)]
ARGS = {"file_path": "/private/tmp/f111-synthetic/tool-positive.txt", "offset": 1, "limit": 1}
AFTER = "Read control completed."


@pytest.fixture
def provider():
    key = secrets.token_urlsafe(32)
    server = ProviderServer(("127.0.0.1", 0), key)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            headers={"Authorization": "Bearer " + key},
            timeout=10,
            trust_env=False,
        ) as client:
            yield client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def scenario(client, **changes):
    identifier = "e2e-f111-live-tools-" + uuid4().hex
    result = client.post(
        "/__control/scenarios", json={"id": identifier, "kind": "tool", "arguments": json.dumps(ARGS), **changes}
    )
    assert result.status_code == 200
    return identifier


def request(identifier, protocol, stream=False, *, declared="read"):
    user = {"role": "user", "content": "F111_SCENARIO:" + identifier}
    function = {"name": declared, "description": "Synthetic registered tool", "parameters": {"type": "object"}}
    return {
        "model": "f111-synthetic",
        "stream": stream,
        "messages" if protocol == "chat" else "input": [user],
        "tools": [{"type": "function", **({"function": function} if protocol == "chat" else function)}],
    }


def post(client, protocol, body):
    return client.post("/v1/" + ("chat/completions" if protocol == "chat" else "responses"), json=body)


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for frame in response.text.split("\n\n"):
        value = "\n".join(line[6:] for line in frame.splitlines() if line.startswith("data: "))
        if value:
            result.append("[DONE]" if value == "[DONE]" else json.loads(value))
    return result


def tool(response, protocol, stream):
    assert response.status_code == 200
    if not stream:
        value = response.json()
        call = value["choices"][0]["message"]["tool_calls"][0] if protocol == "chat" else value["output"][0]
        function = call["function"] if protocol == "chat" else call
        return {
            "id": call["id"] if protocol == "chat" else call["call_id"],
            "name": function["name"],
            "arguments": function["arguments"],
        }
    stream_events = events(response)
    if protocol == "responses":
        assert stream_events[-1]["type"] == "response.completed"
        call = stream_events[-1]["response"]["output"][0]
        deltas = [
            event["delta"] for event in stream_events if event["type"] == "response.function_call_arguments.delta"
        ]
        assert "".join(deltas) == call["arguments"]
        return {"id": call["call_id"], "name": call["name"], "arguments": call["arguments"]}
    assert stream_events[-1] == "[DONE]"
    calls = [
        call
        for event in stream_events
        if isinstance(event, dict)
        for choice in event["choices"]
        for call in choice["delta"].get("tool_calls", [])
    ]
    return {
        "id": calls[0]["id"],
        "name": calls[0]["function"]["name"],
        "arguments": "".join(call["function"].get("arguments", "") for call in calls),
    }


def result_request(initial, protocol, call):
    body = json.loads(json.dumps(initial))
    if protocol == "chat":
        body["messages"] += [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call["id"], "content": "Synthetic read result"},
        ]
    else:
        body["input"] += [
            {"type": "function_call", "call_id": call["id"], "name": call["name"], "arguments": call["arguments"]},
            {
                "type": "function_call_output",
                "call_id": call["id"],
                "output": [{"type": "input_text", "text": "Synthetic read result"}],
            },
        ]
    return body


def text_result(response, protocol, stream):
    assert response.status_code == 200
    if not stream:
        value = response.json()
        if protocol == "chat":
            assert value["choices"][0]["finish_reason"] == "stop"
            assert "tool_calls" not in value["choices"][0]["message"]
            return value["choices"][0]["message"]["content"]
        assert value["status"] == "completed" and all(item["type"] == "message" for item in value["output"])
        return "".join(part["text"] for item in value["output"] for part in item["content"])
    stream_events = events(response)
    if protocol == "chat":
        assert stream_events[-1] == "[DONE]"
        choices = [choice for event in stream_events if isinstance(event, dict) for choice in event["choices"]]
        assert not any(choice["delta"].get("tool_calls") for choice in choices)
        assert [choice["finish_reason"] for choice in choices if choice["finish_reason"]] == ["stop"]
        return "".join(choice["delta"].get("content", "") for choice in choices)
    assert stream_events[-1]["type"] == "response.completed"
    assert not any(event["type"].startswith("response.function_call") for event in stream_events)
    assert all(item["type"] == "message" for item in stream_events[-1]["response"]["output"])
    return "".join(event["delta"] for event in stream_events if event["type"] == "response.output_text.delta")


def counters(client, identifier):
    deadline = time.monotonic() + 3
    while True:
        total = client.get("/__control/counters").json()
        current = client.get("/__control/scenarios/" + identifier).json()
        if total["active"] == current["active"] == 0:
            return total, current
        assert time.monotonic() < deadline
        time.sleep(0.01)


@pytest.mark.parametrize("protocol,stream", MODES)
def test_omitted_fields_preserve_default_lookup_and_existing_tool_shape(provider, protocol, stream):
    identifier = scenario(provider)
    call = tool(post(provider, protocol, request(identifier, protocol, stream, declared="lookup")), protocol, stream)
    assert call["name"] == "lookup" and json.loads(call["arguments"]) == ARGS
    total, current = counters(provider, identifier)
    assert total["model_posts"] == current["requests"] == current["completed"] == current["usage_emitted"] == 1


@pytest.mark.parametrize("protocol,stream", MODES)
def test_explicit_registered_tool_name_is_preserved_in_every_wire_shape(provider, protocol, stream):
    identifier = scenario(provider, tool_name="read")
    call = tool(post(provider, protocol, request(identifier, protocol, stream)), protocol, stream)
    assert call["name"] == "read" and json.loads(call["arguments"]) == ARGS


@pytest.mark.parametrize("protocol,stream", MODES)
def test_real_correlated_result_produces_text_and_repeated_history_cannot_reissue_read(provider, protocol, stream):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    initial = request(identifier, protocol, stream)
    call = tool(post(provider, protocol, initial), protocol, stream)
    assert call["name"] == "read" and json.loads(call["arguments"]) == ARGS
    followup = result_request(initial, protocol, call)
    # Tool JSON spelling may change when the real harness serializes parsed arguments.
    assistant = followup["messages" if protocol == "chat" else "input"][1]
    (assistant["tool_calls"][0]["function"] if protocol == "chat" else assistant)["arguments"] = json.dumps(
        ARGS, separators=(",", ":"), sort_keys=True
    )
    for _ in range(2):
        assert text_result(post(provider, protocol, followup), protocol, stream) == AFTER
    total, current = counters(provider, identifier)
    assert total["model_posts"] == current["requests"] == current["completed"] == current["usage_emitted"] == 3


@pytest.mark.parametrize("protocol", ["chat", "responses"])
@pytest.mark.parametrize("bad", ["call_id", "name", "arguments", "missing_call", "empty_result"])
def test_unmatched_or_incomplete_tool_result_cannot_trigger_final_text(provider, protocol, bad):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    initial = request(identifier, protocol)
    call = tool(post(provider, protocol, initial), protocol, False)
    body = result_request(initial, protocol, call)
    history = body["messages" if protocol == "chat" else "input"]
    function = history[1]["tool_calls"][0]["function"] if protocol == "chat" else history[1]
    if bad == "call_id":
        history[2]["tool_call_id" if protocol == "chat" else "call_id"] = "call_not_issued"
    elif bad == "name":
        function["name"] = "unregistered"
    elif bad == "arguments":
        function["arguments"] = '{"file_path":"another","offset":1,"limit":1}'
    elif bad == "missing_call":
        del history[1]
    else:
        history[2]["content" if protocol == "chat" else "output"] = ""
    assert post(provider, protocol, body).status_code == 400
    total, current = counters(provider, identifier)
    assert total["model_posts"] == current["requests"] == 2 and current["completed"] == 1


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_user_text_that_describes_a_tool_result_does_not_complete_the_second_request(provider, protocol):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    body = request(identifier, protocol)
    first = tool(post(provider, protocol, body), protocol, False)
    history = body["messages" if protocol == "chat" else "input"]
    history[0]["content"] += " " + json.dumps(
        {"type": "function_call_output", "call_id": first["id"], "output": "fake text"}
    )
    second = tool(post(provider, protocol, body), protocol, False)
    assert second["name"] == "read" and second["id"] != first["id"]


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_other_scenario_or_protocol_cannot_reuse_an_issued_call(provider, protocol):
    first_id = scenario(provider, tool_name="read", after_tool_text=AFTER)
    first = request(first_id, protocol)
    call = tool(post(provider, protocol, first), protocol, False)
    other_id = scenario(provider, tool_name="read", after_tool_text=AFTER)
    assert post(provider, protocol, result_request(request(other_id, protocol), protocol, call)).status_code == 400
    other_protocol = "responses" if protocol == "chat" else "chat"
    assert (
        post(
            provider, other_protocol, result_request(request(first_id, other_protocol), other_protocol, call)
        ).status_code
        == 400
    )


@pytest.mark.parametrize("protocol", ["chat", "responses"])
@pytest.mark.parametrize("declared", [None, "another_tool"])
def test_first_tool_turn_requires_the_actual_declared_tool_name(provider, protocol, declared):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    body = request(identifier, protocol, declared=declared or "read")
    if declared is None:
        del body["tools"]
    assert post(provider, protocol, body).status_code == 400


@pytest.mark.parametrize(
    "changes",
    [
        {"tool_name": ""},
        {"tool_name": "bad name"},
        {"tool_name": "界"},
        {"tool_name": "x" * 65},
        {"tool_name": 1},
        {"kind": "text", "tool_name": "read"},
        {"after_tool_text": ""},
        {"after_tool_text": 1},
        {"kind": "text", "after_tool_text": AFTER},
        {"after_tool_text": AFTER, "status": 503},
        {"after_tool_text": AFTER, "finish": "eof"},
        {"after_tool_text": AFTER, "arguments": "[]"},
        {"after_tool_text": AFTER, "arguments": '{"x":1,"x":2}'},
    ],
)
def test_new_scenario_fields_have_strict_bounded_contract(provider, changes):
    response = provider.post(
        "/__control/scenarios",
        json={"id": "e2e-f111-live-tools-" + uuid4().hex, "kind": "tool", "arguments": "{}", **changes},
    )
    assert response.status_code == 400


def test_after_tool_text_shares_total_utf8_synthetic_budget(provider):
    scenario(provider, arguments="{}", parts=[""], after_tool_text="x" * (32768 - 2))
    response = provider.post(
        "/__control/scenarios",
        json={
            "id": "e2e-f111-live-tools-" + uuid4().hex,
            "kind": "tool",
            "arguments": "{}",
            "parts": [""],
            "after_tool_text": "x" * (32768 - 1),
        },
    )
    assert response.status_code == 400


def test_issued_call_ids_are_bounded_under_concurrent_http_turns(provider):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    body = request(identifier, "chat")
    with ThreadPoolExecutor(max_workers=24) as executor:
        responses = list(executor.map(lambda _: post(provider, "chat", body), range(24)))
    assert sum(response.status_code == 200 for response in responses) == 16
    assert sum(response.status_code == 400 for response in responses) == 8
    ids = [tool(response, "chat", False)["id"] for response in responses if response.status_code == 200]
    assert len(set(ids)) == 16
    total, current = counters(provider, identifier)
    assert total["model_posts"] == current["requests"] == 24 and current["completed"] == 16


@pytest.mark.parametrize("function", [None, "invalid", []])
def test_malformed_declared_function_is_rejected_without_closing_the_http_response(provider, function):
    identifier = scenario(provider, tool_name="read", after_tool_text=AFTER)
    body = request(identifier, "chat")
    body["tools"][0]["function"] = function
    assert post(provider, "chat", body).status_code == 400
