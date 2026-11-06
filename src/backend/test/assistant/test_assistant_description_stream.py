"""Creating an assistant must not wait on (or fail because of) the model that
writes its description; the config page streams the description afterwards."""

import json
from types import SimpleNamespace

import pytest

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService


class _FakeAgent:
    chunks = ["  A helper ", "for tests."]

    def __init__(self, *_args, **_kwargs):
        pass

    async def init_auto_update_llm(self):
        return None

    async def astream_description(self, _prompt):
        for one in self.chunks:
            yield one


@pytest.fixture
def stubbed(monkeypatch):
    rows = {}
    saved = []

    async def aget_one_assistant(assistant_id):
        row = rows.get(assistant_id)
        return SimpleNamespace(**vars(row)) if row else None

    def update_assistant(data):
        rows[data.id] = data
        saved.append(data.desc)
        return data

    async def allow(*_args, **_kwargs):
        return None

    monkeypatch.setattr(assistant_module.AssistantDao, "aget_one_assistant", aget_one_assistant)
    monkeypatch.setattr(assistant_module.AssistantDao, "update_assistant", update_assistant)
    monkeypatch.setattr(AssistantService, "check_update_permission_async", allow)
    monkeypatch.setattr(assistant_module, "AssistantAgent", _FakeAgent)
    return rows, saved


async def _collect(assistant_id):
    events = []
    async for raw in AssistantService.description_stream(assistant_id, SimpleNamespace(user_id=1)):
        events.append(json.loads(raw.split("data:", 1)[1]))
    return events


async def test_streams_chunks_and_stores_trimmed_description(stubbed):
    rows, saved = stubbed
    rows["a1"] = SimpleNamespace(id="a1", desc="", prompt="be helpful")

    events = await _collect("a1")

    assert [e["message"] for e in events if e["type"] == "description"] == _FakeAgent.chunks
    assert saved == ["A helper for tests."]


async def test_completes_a_prefix_saved_mid_stream(stubbed, monkeypatch):
    rows, saved = stubbed
    rows["a1"] = SimpleNamespace(id="a1", desc="", prompt="be helpful")

    class _SavingAgent(_FakeAgent):
        async def astream_description(self, _prompt):
            yield "A helper "
            rows["a1"].desc = "A helper"  # the page saved while streaming
            yield "for tests."

    monkeypatch.setattr(assistant_module, "AssistantAgent", _SavingAgent)
    await _collect("a1")

    assert saved == ["A helper for tests."]


async def test_keeps_the_owners_own_description(stubbed, monkeypatch):
    rows, saved = stubbed
    rows["a1"] = SimpleNamespace(id="a1", desc="", prompt="be helpful")

    class _OwnerEditsAgent(_FakeAgent):
        async def astream_description(self, _prompt):
            yield "A helper"
            rows["a1"].desc = "My own words"

    monkeypatch.setattr(assistant_module, "AssistantAgent", _OwnerEditsAgent)
    await _collect("a1")

    assert saved == []


async def test_skips_when_description_or_prompt_already_decided(stubbed):
    rows, saved = stubbed
    rows["has_desc"] = SimpleNamespace(id="has_desc", desc="exists", prompt="p")
    rows["no_prompt"] = SimpleNamespace(id="no_prompt", desc="", prompt="")

    assert await _collect("has_desc") == []
    assert await _collect("no_prompt") == []
    assert saved == []


def test_create_assistant_no_longer_calls_the_model():
    import inspect

    source = inspect.getsource(AssistantService.create_assistant)
    assert "AssistantAgent" not in source and "get_auto_info" not in source


def test_create_request_accepts_an_empty_role():
    from bisheng.api.v1.schemas import AssistantCreateReq

    assert AssistantCreateReq(name="a", logo="").prompt == ""
    assert AssistantCreateReq(name="a", prompt="翻译助手", logo="").prompt == "翻译助手"
