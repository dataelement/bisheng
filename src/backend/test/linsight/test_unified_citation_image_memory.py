"""F004 T058: citations, image reading and long-term memory on the unified factory.

AC-41 (one numbering table for both profiles), AC-48 (answers carry citations
that resolve to their source), AC-49 (retrieved knowledge images reach the model
in both profiles), AC-50 (memory tools and resident memory in both profiles, one
wiring implementation, earlier memories still found).

The REAL graph from ``create_linsight_agent`` runs with a scripted model. Redis
is an in-memory fake, nothing reads a database or object storage.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from bisheng.citation.domain.services import citation_handle_service as handle_svc
from bisheng.citation.domain.services import linsight_citation_scope as linsight_scope_mod
from bisheng.citation.domain.services.citation_handle_service import assign_handles
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_START_MARKER,
    CitationRegistryCollector,
)
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.citation.domain.services.linsight_citation_scope import LinsightCitationScope
from bisheng.linsight.domain.services import agent_factory, kb_image_middleware, memory_turns
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.tool_assembly import ToolAssembly
from bisheng.memory.domain.ports import MemoryContext
from bisheng.workstation.domain.services import daily_memory, direct_run, direct_run_turn
from bisheng.workstation.domain.services.daily_citation import handles_for_chunks
from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "conv-cite-1"
TENANT = 3
USER = 7
IMAGE_URL = "http://minio.local/bisheng/knowledge/images/12/chart.png"
DATA_URI = "data:image/png;base64,AAAA"
RESIDENT = "【常驻记忆】用户常驻台北，报告默认用繁体中文。"
OLD_MEMORY = "用户的项目代号是青鸟"
DIRECT_KB = "search_knowledge_bases"
PLANNED_KB = "search_knowledge_base"


def _call(name: str, args: dict[str, Any], call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class _ScriptedModel(BaseChatModel):
    """Replays a script and records every request and the tools bound to it."""

    script: list[Any]
    calls: int = 0
    inputs: list[list[BaseMessage]] = Field(default_factory=list)
    bound: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17).
        return {"ls_provider": "f004-cite-image-memory", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _ScriptedModel:
        for item in tools:
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if name and name not in self.bound:
                self.bound.append(name)
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        raise AssertionError("the agent must call the model asynchronously")

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> Any:
        if not any(isinstance(m, SystemMessage) for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage("summary"))])
        self.inputs.append(list(messages))
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=item)])

    def system_text(self, index: int = 0) -> str:
        return "\n".join(_text(m) for m in self.inputs[index] if isinstance(m, SystemMessage))


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def _image_blocks(message: BaseMessage) -> list[dict]:
    if not isinstance(message.content, list):
        return []
    return [b for b in message.content if isinstance(b, dict) and b.get("type") == "image_url"]


class FakeHashRedis:
    """The async hash API of ``RedisClient`` that the handle table uses."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}

    def _h(self, name: str) -> dict[str, str]:
        return self.store.setdefault(name, {})

    async def ahget(self, name, key):
        return self._h(name).get(key)

    async def ahgetall(self, name):
        return dict(self._h(name))

    async def ahincrby(self, name, key, amount=1):
        h = self._h(name)
        h[key] = str(int(h.get(key, "0")) + amount)
        return int(h[key])

    async def ahsetnx(self, name, key, value):
        h = self._h(name)
        if key in h:
            return False
        h[key] = value
        return True

    async def ahset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        h = self._h(name)
        if mapping:
            h.update(mapping)
        if key is not None:
            h[key] = value
        return 1

    async def aexpire_key(self, key, expiration):
        return None


@pytest.fixture
def handle_redis(monkeypatch: pytest.MonkeyPatch) -> FakeHashRedis:
    fake = FakeHashRedis()
    monkeypatch.setattr(handle_svc, "get_redis_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(linsight_scope_mod, "get_redis_client", AsyncMock(return_value=fake))
    return fake


def _rag(citation_id: str, item_id: str, document_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        key=f"{citation_id}:{item_id}",
        citationId=citation_id,
        itemId=item_id,
        type=SimpleNamespace(value="rag"),
        sourcePayload=SimpleNamespace(
            documentId=document_id,
            documentName="差旅制度.docx",
            knowledgeName="制度库",
            items=[SimpleNamespace(itemId=item_id, page=2, chunkIndex=int(item_id))],
        ),
    )


def _session(conversation_id: str = CID) -> SimpleNamespace:
    return SimpleNamespace(
        id=conversation_id,
        session_id=conversation_id,
        tenant_id=TENANT,
        user_id=USER,
        question="",
        api_meta=None,
        skills=[],
        skill_snapshot=None,
    )


class _NoopInbox(AgentMiddleware):
    """Stands for the inbox middleware: its presence means the unified runtime is on."""

    def __init__(self) -> None:
        super().__init__()
        self.tools = []

    @property
    def name(self) -> str:
        return "TestInbox"


@pytest.fixture
def factory_env(monkeypatch: pytest.MonkeyPatch):
    """``build(profile, script, tools, visual=..., **kwargs)`` -> (agent, model)."""
    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    monkeypatch.setattr(agent_factory, "_resolve_vision_model", AsyncMock(return_value=None))

    async def build(profile: str, script: list[Any], tools: list, *, visual: bool = False, **kwargs: Any):
        model = _ScriptedModel(script=script)
        monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, visual)))
        agent = await agent_factory.create_linsight_agent(
            _session(), tools, checkpointer=InMemorySaver(), profile=profile, **kwargs
        )
        return agent, model

    return build


async def _invoke(agent: Any, text: str, thread: str = "t1") -> dict:
    return await asyncio.wait_for(
        agent.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config={"configurable": {"thread_id": thread}, "recursion_limit": 40},
        ),
        timeout=20,
    )


# --------------------------------------------------------------------------- #
# Citations (AC-41, AC-48)
# --------------------------------------------------------------------------- #


async def test_citation_handles_unique_across_profiles(handle_redis: FakeHashRedis):
    # A direct run numbers two sources.
    direct = direct_run_turn.DirectTurn(CID, "run-direct")
    await direct.load()
    first = await assign_handles(direct.scope, [_rag("kb_a", "0", 11), _rag("kb_a", "1", 11)])
    assert first == {"kb_a:0": "S1", "kb_a:1": "S2"}

    # A planned run of the same conversation: a new source and one seen before.
    planned = LinsightCitationScope(svid="sv-1", session_id=CID, enabled=True)
    await planned.load()
    second = await assign_handles(planned, [_rag("kb_b", "4", 22), _rag("kb_c", "0", 11)])
    assert second["kb_b:4"] == "S3"
    # Same chunk of the same document: the number it already has.
    assert second["kb_c:0"] == "S1"

    # A second direct run continues the same table.
    again = direct_run_turn.DirectTurn(CID, "run-direct-2")
    await again.load()
    third = await assign_handles(again.scope, [_rag("kb_d", "9", 33)])
    assert third == {"kb_d:9": "S4"}
    assert again.scope.handles["S3"] == "kb_b:4"

    numbers = [*first.values(), second["kb_b:4"], *third.values()]
    assert len(numbers) == len(set(numbers))
    # The direct run does not pin the deep-research contract; the planned run does.
    assert direct.scope.pins_contract is False


def _knowledge_tool(name: str, collector: Any, scope: Any, chunk_body: str = "差旅住宿标准为每晚 500 元。") -> Any:
    """What the daily knowledge tool does with its hits, without a vector store."""

    async def _search(query: str) -> str:
        items = [_rag("kb_trip", "0", 77)]
        collector.extend(items)
        chunks = await handles_for_chunks(
            scope, items, [f"<chunk_id>kb_trip:0</chunk_id><paragraph_content>{chunk_body}</paragraph_content>"]
        )
        return json.dumps(chunks, ensure_ascii=False)

    return StructuredTool.from_function(coroutine=_search, name=name, description="Search the knowledge bases.")


class _DirectEnv:
    """One conversation driven by the real ``DirectRunner`` with the default agent builder."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path, script: list[Any]):
        from bisheng.core.config.settings import LinsightConf

        self.model = _ScriptedModel(script=script)
        monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(self.model, False)))
        monkeypatch.setattr(agent_factory, "_resolve_vision_model", AsyncMock(return_value=None))
        monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
        monkeypatch.setattr(direct_run, "_HOOK_FACTORIES", [])
        self.redis = fakeredis.aioredis.FakeRedis()
        self.lease = RunLeaseService(self.redis)
        self.dispatch = RunDispatchService(self.redis, enqueue_relay=AsyncMock())
        self.stream = RunEventStream(self.redis)
        self.store = SimpleNamespace(bucket="bisheng")
        self.file_dir = str(tmp_path / "cache" / CID)
        self.make_tools = lambda turn: []
        self.runner = DirectRunner(
            redis=self.redis,
            stream=self.stream,
            lease=self.lease,
            dispatch=self.dispatch,
            checkpointer=InMemorySaver(),
            admit=AsyncMock(),
            assemble=self._assemble,
            build_input=self._build_input,
            object_store=AsyncMock(return_value=self.store),
            file_dir_for=lambda ctx: self.file_dir,
            department_slot=self._slot,
            safety_scanner=lambda ctx: None,
            recursion_limit=40,
        )

    @staticmethod
    def _slot(ctx):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def slot():
            yield

        return slot()

    async def _assemble(self, ctx: DirectRunContext, file_dir: str, turn: Any = None) -> ToolAssembly:
        return ToolAssembly(tools=list(self.make_tools(turn)))

    @staticmethod
    async def _build_input(ctx: DirectRunContext) -> dict:
        return {"messages": [{"role": "user", "content": ctx.text}]}

    async def run(self, text: str, hooks: list | None = None, **ctx_fields: Any):
        result = await self.dispatch.submit(
            CID, {"text": text, "task_mode": False, "user_id": USER, "tenant_id": TENANT}
        )
        ctx = DirectRunContext(
            conversation_id=CID,
            run_id=result.run_id,
            tenant_id=TENANT,
            user_id=USER,
            message_id=result.message_id,
            text=text,
            **ctx_fields,
        )
        outcome = await asyncio.wait_for(
            direct_run.execute_direct_run(ctx, runner=self.runner, on_event=hooks or []), timeout=20
        )
        return ctx, outcome

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CID)]


async def test_citation_resolves_to_source(monkeypatch: pytest.MonkeyPatch, tmp_path, handle_redis: FakeHashRedis):
    from bisheng.workstation.domain.services import chat_service
    from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

    env = _DirectEnv(
        monkeypatch,
        tmp_path,
        [
            AIMessage(content="", tool_calls=[_call(DIRECT_KB, {"query": "住宿标准"}, "c1")]),
            AIMessage(content="住宿标准为每晚 500 元。[S1]"),
        ],
    )
    env.make_tools = lambda turn: [_knowledge_tool(DIRECT_KB, turn.collector, turn.scope)]

    saved: dict[str, Any] = {}

    async def insert(row):
        row.id = 501
        return row

    async def save_citations(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", insert)
    monkeypatch.setattr(chat_service, "save_message_citations", save_citations)
    monkeypatch.setattr(chat_service, "_promote_generated_files", AsyncMock(return_value=[]))

    projectors: list[DirectRunProjector] = []

    def projector_hook(event: dict):
        if not projectors:
            projectors.append(
                DirectRunProjector(
                    run_id=event["run_id"],
                    conversation_id=CID,
                    user_id=USER,
                    sender="scripted",
                    citation_items=lambda: direct_run_turn.collected_citations(event["run_id"]),
                )
            )
        return projectors[0].on_event(event)

    ctx, outcome = await env.run("住宿标准是多少", hooks=[projector_hook], knowledge=[{"id": 1, "name": "制度库"}])

    assert outcome.status == "finished"
    # The model saw the short handle, never the registry key.
    tool_result = next(m for m in env.model.inputs[1] if isinstance(m, ToolMessage))
    assert "<ref>S1</ref>" in tool_result.content
    assert "kb_trip:0" not in tool_result.content
    # Prompt and tool in lockstep: the bound knowledge tool is introduced by its
    # real name, together with the numbering rules.
    system = env.model.system_text()
    assert DIRECT_KB in system
    assert "# 来源编号" in system
    # The answer on the event stream carries the marker the frontend renders.
    text = "".join(e["data"]["text"] for e in await env.events() if e["type"] == "text")
    marker = f"{CITATION_START_MARKER}kb_trip:0{CITATION_END_MARKER}"
    assert text == f"住宿标准为每晚 500 元。{marker}"
    # The answer row stores the same text and is bound to the cited source.
    row = projectors[0].answer_row
    assert json.loads(row.message)["msg"] == text
    assert [item.citationId for item in saved["items"]] == ["kb_trip"]
    assert saved["message_id"] == 501
    assert [item.citationId for item in projectors[0].citations] == ["kb_trip"]
    # Nothing of the run is left in process memory.
    assert direct_run_turn.collected_citations(ctx.run_id) == []


async def test_direct_prompt_follows_the_bound_knowledge_tool(factory_env, handle_redis: FakeHashRedis):
    scope = DailyCitationScope(CID)
    kb = _knowledge_tool(DIRECT_KB, CitationRegistryCollector(), scope)

    agent, model = await factory_env("direct", [AIMessage(content="好的")], [kb], citation_scope=scope)
    await _invoke(agent, "你好")
    system = model.system_text()
    assert f"用 {DIRECT_KB} 检索" in system
    assert "# 来源编号" in system
    assert f"用 {PLANNED_KB} 检索" not in system

    # No knowledge tool bound: the prompt does not mention one and has no rules.
    agent, model = await factory_env("direct", [AIMessage(content="好的")], [], citation_scope=scope)
    await _invoke(agent, "你好")
    assert "search_knowledge_base" not in model.system_text()
    assert "# 来源编号" not in model.system_text()


# --------------------------------------------------------------------------- #
# Image reading (AC-49)
# --------------------------------------------------------------------------- #


def _image_knowledge_tool(name: str) -> Any:
    async def _search(query: str) -> str:
        return json.dumps(
            [f"<paragraph_content>2025 年销售走势如下：![走势图]({IMAGE_URL})</paragraph_content>"], ensure_ascii=False
        )

    return StructuredTool.from_function(coroutine=_search, name=name, description="Search the knowledge bases.")


@tool
def echo(text: str) -> str:
    """Repeat the text."""
    return f"echo:{text}"


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    fetched: list[str] = []

    async def fetch(url: str):
        fetched.append(url)
        return SimpleNamespace(ok=True, data_uri=DATA_URI, reason=None)

    monkeypatch.setattr(kb_image_middleware, "fetch_and_encode", fetch)
    return fetched


@pytest.mark.parametrize(("profile", "kb_name"), [("direct", DIRECT_KB), ("planned", PLANNED_KB)])
async def test_images_visible_in_both_profiles(factory_env, fake_fetch, profile: str, kb_name: str):
    script = [
        AIMessage(content="", tool_calls=[_call(kb_name, {"query": "销售走势"}, "c1")]),
        AIMessage(content="", tool_calls=[_call("view_image", {"image_ids": ["img#1"]}, "c2")]),
        AIMessage(content="走势逐季上升。"),
    ]
    agent, model = await factory_env(profile, script, [_image_knowledge_tool(kb_name)], visual=True, inbox=_NoopInbox())
    await _invoke(agent, "销售走势图里是什么")

    assert "view_image" in model.bound
    # After retrieval the model sees which pictures exist and how to look at them.
    retrieved = next(m for m in model.inputs[1] if isinstance(m, ToolMessage))
    assert "⟦img#1⟧" in retrieved.content
    assert "# 查看图片" in model.system_text(1)
    # After view_image the request carries the pixels.
    images = [block for message in model.inputs[2] for block in _image_blocks(message)]
    assert [block["image_url"]["url"] for block in images] == [DATA_URI]
    assert fake_fetch == [IMAGE_URL]
    # Pixels are never written to the checkpoint thread.
    state = await agent.aget_state({"configurable": {"thread_id": "t1"}})
    assert not any(_image_blocks(m) for m in state.values["messages"])


async def test_image_blocks_after_tool_batch(factory_env, fake_fetch):
    script = [
        AIMessage(content="", tool_calls=[_call(DIRECT_KB, {"query": "销售走势"}, "c1")]),
        AIMessage(
            content="",
            tool_calls=[_call("view_image", {"image_ids": ["img#1"]}, "c2"), _call("echo", {"text": "x"}, "c3")],
        ),
        AIMessage(content="走势逐季上升。"),
    ]
    agent, model = await factory_env("direct", script, [_image_knowledge_tool(DIRECT_KB), echo], visual=True)
    await _invoke(agent, "销售走势图里是什么")

    request = model.inputs[2]
    batch = [i for i, m in enumerate(request) if isinstance(m, ToolMessage) and m.tool_call_id in ("c2", "c3")]
    image_at = [i for i, m in enumerate(request) if _image_blocks(m)]
    assert len(batch) == 2 and len(image_at) == 1
    # The tool messages of one batch stay contiguous, right after their AI message.
    assert batch[1] == batch[0] + 1
    assert isinstance(request[batch[0] - 1], AIMessage)
    # The pictures ride on a user message placed after the whole batch.
    assert image_at[0] > batch[1]
    assert isinstance(request[image_at[0]], HumanMessage)
    # No tool message carries an image block (some endpoints reject that).
    assert not any(_image_blocks(m) for m in request if isinstance(m, ToolMessage))


async def test_image_reading_follows_the_model_and_the_switch(factory_env, fake_fetch):
    script = [AIMessage(content="好的")]
    # A model that cannot read images and no image-reading model: nothing is mounted.
    agent, model = await factory_env("direct", script, [_image_knowledge_tool(DIRECT_KB)], visual=False)
    await _invoke(agent, "你好")
    assert "view_image" not in model.bound
    # No knowledge tool: nothing to look at.
    agent, model = await factory_env("direct", script, [echo], visual=True)
    await _invoke(agent, "你好")
    assert "view_image" not in model.bound
    # Deep research with the unified runtime off (no inbox) is unchanged.
    agent, model = await factory_env("planned", script, [_image_knowledge_tool(PLANNED_KB)], visual=True)
    await _invoke(agent, "你好")
    assert "view_image" not in model.bound


async def test_image_reading_model_describes_pictures_for_a_text_model(
    monkeypatch: pytest.MonkeyPatch, factory_env, fake_fetch
):
    class _Vision:
        def __init__(self) -> None:
            self.requests: list[list[BaseMessage]] = []

        async def ainvoke(self, messages, **kwargs):
            self.requests.append(list(messages))
            return AIMessage(content="图中是逐季上升的折线。")

    vision = _Vision()
    script = [
        AIMessage(content="", tool_calls=[_call(DIRECT_KB, {"query": "销售走势"}, "c1")]),
        AIMessage(content="", tool_calls=[_call("view_image", {"image_ids": ["img#1"]}, "c2")]),
        AIMessage(content="走势逐季上升。"),
    ]
    monkeypatch.setattr(agent_factory, "_resolve_vision_model", AsyncMock(return_value=vision))
    agent, model = await factory_env("direct", script, [_image_knowledge_tool(DIRECT_KB)], visual=False)
    await _invoke(agent, "销售走势图里是什么")

    # The image-reading model received the pixels; the main model only its notes.
    assert any(_image_blocks(m) for m in vision.requests[0])
    assert not any(_image_blocks(m) for m in model.inputs[2])
    assert any("图中是逐季上升的折线。" in _text(m) for m in model.inputs[2] if isinstance(m, HumanMessage))


# --------------------------------------------------------------------------- #
# Long-term memory (AC-50)
# --------------------------------------------------------------------------- #


class _MemoryStore:
    """Stands for the memory service and the search service: items by (tenant, user)."""

    def __init__(self) -> None:
        self.items: dict[tuple[int, int], list[str]] = {(TENANT, USER): [OLD_MEMORY]}
        self.searches: list[tuple[int, int, str]] = []
        self.writes: list[tuple[str, str | None]] = []

    async def search(self, ctx: MemoryContext, query: str, limit: int = 10):
        self.searches.append((ctx.tenant_id, ctx.user_id, query))
        return [
            SimpleNamespace(
                item_id=f"m{i}",
                content=content,
                type="fact",
                recorded_at=datetime(2026, 9, 1),
                event_time=None,
                detail=None,
                has_detail=False,
            )
            for i, content in enumerate(self.items.get((ctx.tenant_id, ctx.user_id), []))
        ]

    async def write(self, ctx: MemoryContext, action: str, content: str | None = None, **kwargs: Any):
        self.writes.append((action, content))
        return SimpleNamespace(item_id="m-new", related_item_id=None)


@pytest.fixture
def memory_store(monkeypatch: pytest.MonkeyPatch) -> _MemoryStore:
    from bisheng.memory.domain.services import factory, tools

    store = _MemoryStore()
    monkeypatch.setattr(factory, "get_memory_service", lambda: store)
    monkeypatch.setattr(factory, "get_search_service", lambda: store)
    monkeypatch.setattr(tools.TurnRecordService, "add_retrieved", AsyncMock())
    return store


def _memory_ctx(scene: str = "daily") -> MemoryContext:
    return MemoryContext(tenant_id=TENANT, user_id=USER, chat_id=CID, turn_id="turn-1", scene=scene)


@pytest.mark.parametrize("profile", ["direct", "planned"])
async def test_memory_tools_in_both_profiles(factory_env, memory_store, profile: str):
    memory = agent_factory.wire_memory(_memory_ctx(), resident_text=RESIDENT)
    agent, model = await factory_env(profile, [AIMessage(content="好的")], [echo], memory=memory)
    await _invoke(agent, "你好")

    assert {"memory_write", "memory_search"} <= set(model.bound)
    system = model.system_text()
    assert RESIDENT in system
    assert memory_turns.MEMORY_TOOLS_GUIDE in system

    # Memory off: neither the tools nor the text.
    agent, model = await factory_env(profile, [AIMessage(content="好的")], [echo])
    await _invoke(agent, "你好")
    assert not {"memory_write", "memory_search"} & set(model.bound)
    assert memory_turns.MEMORY_PROMPT_HEADER not in model.system_text()


async def test_memory_wiring_has_one_implementation(monkeypatch: pytest.MonkeyPatch, memory_store):
    calls: list[MemoryContext] = []
    real = agent_factory.wire_memory

    def spy(ctx, **kwargs):
        calls.append(ctx)
        return real(ctx, **kwargs)

    monkeypatch.setattr(agent_factory, "wire_memory", spy)

    # Deep research: the round's tools and prompt come from the factory function.
    round_ = memory_turns.LinsightMemoryRound()
    round_.ctx = _memory_ctx("linsight")
    round_.resident_text = RESIDENT
    assert [t.name for t in round_.tools()] == ["memory_write", "memory_search"]
    assert round_.prompt() == agent_factory.build_memory_prompt(RESIDENT, "")

    # Daily chat on the unified runtime: the same function.
    turn = daily_memory.DailyMemoryTurn(CID)
    turn.ctx = _memory_ctx()
    wiring = turn.wiring(RESIDENT)
    assert [t.name for t in wiring.tools] == ["memory_write", "memory_search"]
    assert wiring.prompt == agent_factory.build_memory_prompt(RESIDENT, "")

    assert [c.scene for c in calls] == ["linsight", "daily"]
    # A turn without memory wires nothing.
    assert daily_memory.DailyMemoryTurn(CID).wiring("") is None


@pytest.mark.parametrize("profile", ["direct", "planned"])
async def test_existing_memories_searchable(factory_env, memory_store, profile: str):
    script = [
        AIMessage(content="", tool_calls=[_call("memory_search", {"query": "项目代号"}, "c1")]),
        AIMessage(content="项目代号是青鸟。"),
    ]
    scene = "daily" if profile == "direct" else "linsight"
    agent, model = await factory_env(profile, script, [], memory=agent_factory.wire_memory(_memory_ctx(scene)))
    await _invoke(agent, "我的项目代号是什么")

    # The search is scoped by tenant and user only: what was stored before the
    # unified runtime is found from either profile.
    assert memory_store.searches == [(TENANT, USER, "项目代号")]
    result = next(m for m in model.inputs[1] if isinstance(m, ToolMessage))
    assert OLD_MEMORY in result.content


async def test_direct_run_binds_memory_and_ends_the_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path, memory_store, handle_redis
):
    from bisheng.memory.domain.services.resident import ResidentBlock

    resolved: list[tuple[str, int | None]] = []

    async def resolve(chat_id, scene, actor_user_id=None, **kwargs):
        resolved.append((chat_id, actor_user_id))
        return _memory_ctx()

    resident = SimpleNamespace(resident=AsyncMock(return_value=ResidentBlock(text=RESIDENT, rev=4, day="2026-11-18")))
    add_summary, bind_turn, end_turn = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(daily_memory.MemoryGate, "resolve", resolve)
    monkeypatch.setattr(daily_memory, "get_resident_service", lambda: resident)
    monkeypatch.setattr(daily_memory.TurnRecordService, "add_summary", add_summary)
    monkeypatch.setattr(daily_memory.TurnRecordService, "bind_turn", bind_turn)
    monkeypatch.setattr(daily_memory.MemoryActivity, "end_turn", end_turn)

    env = _DirectEnv(
        monkeypatch,
        tmp_path,
        [
            AIMessage(
                content="",
                tool_calls=[_call("memory_write", {"action": "remember", "content": "生日是三月九日"}, "c1")],
            ),
            AIMessage(content="记下了。"),
        ],
    )
    signals: list[Any] = []

    async def on_terminal(event: dict):
        if event["type"] == "run_finished":
            # What the projector's on_persisted hook does with the saved row id.
            signals.append(await direct_run_turn.finish_memory_turn(event["run_id"], 77))

    ctx, outcome = await env.run("记一下我的生日是三月九日", hooks=[on_terminal], memory_registered=True)

    assert outcome.status == "finished"
    assert resolved == [(CID, USER)]
    assert {"memory_write", "memory_search"} <= set(env.model.bound)
    assert RESIDENT in env.model.system_text()
    assert memory_store.writes == [("remember", "生日是三月九日")]
    add_summary.assert_awaited_once()
    bind_turn.assert_awaited_once()
    assert bind_turn.await_args.args[1] == 77
    end_turn.assert_awaited_once_with(CID, 77, True)
    assert signals == [{"turn_id": "turn-1", "has_write": True, "has_attribution": False}]
    # The event stream never carries what was written to memory.
    frames = [e["data"] for e in await env.events() if e["type"] == "tool_call" and e["data"]["name"] == "memory_write"]
    assert frames and all(frame["params"].get("redacted") is True for frame in frames)
    assert "三月九日" not in json.dumps(frames, ensure_ascii=False)


async def test_direct_run_without_registration_has_no_memory(monkeypatch: pytest.MonkeyPatch, tmp_path, memory_store):
    resolve = AsyncMock(return_value=_memory_ctx())
    monkeypatch.setattr(daily_memory.MemoryGate, "resolve", resolve)
    env = _DirectEnv(monkeypatch, tmp_path, [AIMessage(content="好的")])

    ctx, outcome = await env.run("你好")

    assert outcome.status == "finished"
    resolve.assert_not_awaited()
    assert not {"memory_write", "memory_search"} & set(env.model.bound)
    assert await direct_run_turn.finish_memory_turn(ctx.run_id, 1) is None
