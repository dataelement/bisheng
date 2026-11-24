"""Offline resource bounds for CustomKV polling."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from bisheng.core.ai.llm.chat_moonshot import ChatMoonshot
from bisheng_langchain.document_loaders import custom_kv


class SafetyAbort(Exception):
    """Keep the pre-fix exploit regression finite even without product guards."""


def result(reason="tool_calls", tools=True):
    return ChatResult(
        generations=[
            ChatGeneration(
                message=AIMessage(
                    content="",
                    tool_calls=[{"name": "$web_search", "args": {"q": "synthetic"}, "id": "t"}] if tools else [],
                ),
                generation_info={"finish_reason": reason},
            )
        ]
    )


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_moonshot_async_and_sync_success_preserve_input(monkeypatch, asynchronous):
    calls = []

    def respond(*args, **kwargs):
        calls.append(1)
        return result() if len(calls) == 1 else result("stop", False)

    async def arespond(*args, **kwargs):
        return respond(*args, **kwargs)

    monkeypatch.setattr(ChatOpenAI, "_generate", respond)
    monkeypatch.setattr(ChatOpenAI, "_agenerate", arespond)
    model = ChatMoonshot(model="synthetic", api_key="test", enable_web_search=True)
    messages = [HumanMessage("synthetic")]
    final = await model._agenerate(messages) if asynchronous else model._generate(messages)
    assert final.generations[0].generation_info["finish_reason"] == "stop"
    assert len(messages) == 1
    assert len(calls) == 2


async def test_moonshot_cancellation_propagates(monkeypatch):
    import asyncio

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ChatOpenAI, "_agenerate", cancel)
    model = ChatMoonshot(model="synthetic", api_key="test", enable_web_search=True)
    with pytest.raises(asyncio.CancelledError):
        await model._agenerate([])


def test_customkv_pending_stops_at_attempt_limit(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic")
    monkeypatch.setattr(custom_kv, "sleep", lambda seconds: None)
    loader = custom_kv.CustomKVLoader(str(path), "https://example.invalid", "test", "field", "s", "logic-job")
    loader.max_poll_attempts = 3
    loader.poll_timeout = 60
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if len(calls) > 10:
            raise SafetyAbort()
        return SimpleNamespace(json=lambda: {"data": {"status": 1}})

    loader.requests = SimpleNamespace(
        post=lambda **kwargs: SimpleNamespace(status_code=200, json=lambda: {"data": {"task_id": "t"}}), get=get
    )
    with pytest.raises(TimeoutError):
        loader.load()
    assert len(calls) <= 3


@pytest.mark.parametrize("state", [None, 0, 4, 3, "2"])
def test_customkv_unknown_and_failure_states_never_fetch_result(tmp_path, monkeypatch, state):
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic")
    loader = custom_kv.CustomKVLoader(str(path), "https://example.invalid", "test", "field", "s", "logic-job")
    calls = []

    def get(url):
        calls.append(url)
        return SimpleNamespace(json=lambda: {"data": {"status": state}})

    loader.requests = SimpleNamespace(
        post=lambda **kwargs: SimpleNamespace(status_code=200, json=lambda: {"data": {"task_id": "t"}}), get=get
    )
    with pytest.raises(RuntimeError):
        loader.load()
    assert len(calls) == 1
    assert "/status?" in calls[0]


@pytest.mark.parametrize("task_type", ["logic-job", "extraction-job"])
def test_customkv_success_fetches_result_once(tmp_path, monkeypatch, task_type):
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic")
    loader = custom_kv.CustomKVLoader(str(path), "https://example.invalid", "test", "field", "s", task_type)
    calls = []

    def get(url):
        calls.append(url)
        if "/status?" in url:
            return SimpleNamespace(json=lambda: {"data": {"status": 2}})
        return SimpleNamespace(
            json=lambda: {
                "data": [
                    {
                        "result": {
                            "independent_list": [{"element_name": "field", "entity_list": [{"words": "synthetic"}]}]
                        }
                    }
                ]
            }
        )

    loader.requests = SimpleNamespace(
        post=lambda **kwargs: SimpleNamespace(status_code=200, json=lambda: {"data": {"task_id": "t"}}), get=get
    )
    assert "synthetic" in loader.load()[0].page_content
    assert len(calls) == 2


def test_customkv_deadline_checked_after_status_response(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic")
    clock = [0.0]
    monkeypatch.setattr(custom_kv, "monotonic", lambda: clock[0])
    loader = custom_kv.CustomKVLoader(
        str(path), "https://example.invalid", "test", "field", "s", "logic-job", poll_timeout=1
    )

    def get(url):
        clock[0] = 2
        return SimpleNamespace(json=lambda: {"data": {"status": 2}})

    loader.requests = SimpleNamespace(
        post=lambda **kwargs: SimpleNamespace(status_code=200, json=lambda: {"data": {"task_id": "t"}}), get=get
    )
    with pytest.raises(TimeoutError):
        loader.load()


@pytest.mark.parametrize(
    "kwargs", [{"max_poll_attempts": 0}, {"max_poll_attempts": 301}, {"poll_timeout": 0}, {"poll_timeout": 601}]
)
def test_customkv_rejects_unbounded_configuration(tmp_path, kwargs):
    with pytest.raises(ValueError):
        custom_kv.CustomKVLoader(
            str(tmp_path / "unused"), "https://example.invalid", "test", "field", "s", "logic-job", **kwargs
        )
