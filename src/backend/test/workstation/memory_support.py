"""Shared harness for the daily-mode memory tests (F132 Wave 8).

The memory doubles (SQLite seam, KV, index, detail store) are copied from
``test/memory/conftest.py`` in reduced form; that file is not imported so these
tests do not depend on its fixture set. The stream harness patches everything
around ``_agent_stream_chat_completion`` and leaves the generator body real, the
same way ``test_stream_interrupt_persist.py`` does. The model is a scripted fake
agent that really invokes the tools it is given.
"""

from __future__ import annotations

import fnmatch
import json
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily
from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.ports import IndexHit, MemoryContext, detail_object_key

TENANT_A = 1
USER_1 = 101
CHAT_ID = "daily-chat-1"


# --------------------------------------------------------------------------- doubles
class InMemoryKV:
    def __init__(self):
        self.data: dict[str, object] = {}
        self.expiry: dict[str, float] = {}

    def _alive(self, key):
        exp = self.expiry.get(key)
        if exp is not None and exp < time.monotonic():
            self.data.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.data

    async def get(self, key):
        return self.data.get(key) if self._alive(key) else None

    async def set(self, key, value, ttl_seconds=None):
        self.data[key] = str(value)
        if ttl_seconds:
            self.expiry[key] = time.monotonic() + ttl_seconds

    async def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)
            self.expiry.pop(k, None)

    async def hincrby(self, key, field, amount=1):
        h = self.data.setdefault(key, {})
        h[field] = h.get(field, 0) + amount

    async def hgetall(self, key):
        return dict(self.data.get(key, {}))

    async def sadd(self, key, *members):
        self.data.setdefault(key, set()).update(members)

    async def smembers(self, key):
        return set(self.data.get(key, set()))

    async def keys(self, pattern):
        return [k for k in list(self.data) if self._alive(k) and fnmatch.fnmatch(k, pattern)]


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    chars = [c for c in text if not c.isspace()]
    return set(text.split()) | {a + b for a, b in zip(chars, chars[1:])}


class InMemoryIndex:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.model_id = "emb-1"

    async def upsert(self, ctx, item_id, content):
        self.docs[item_id] = {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "content": content}
        return self.model_id

    async def delete(self, ctx, item_ids):
        for i in item_ids:
            self.docs.pop(i, None)

    async def delete_user(self, ctx):
        for k in [k for k, d in self.docs.items() if (d["tenant_id"], d["user_id"]) == (ctx.tenant_id, ctx.user_id)]:
            self.docs.pop(k)

    def _search(self, scope, query, limit):
        q = _tokens(query)
        hits = []
        for item_id, d in self.docs.items():
            if d["tenant_id"] != scope["tenant_id"] or d["user_id"] != scope["user_id"]:
                continue
            score = len(q & _tokens(d["content"]))
            if score:
                hits.append(IndexHit(item_id=item_id, score=float(score)))
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    async def keyword_search(self, scope, query, limit):
        return self._search(scope, query, limit)

    async def vector_search(self, ctx, scope, query, limit):
        return list(reversed(self._search(scope, query, limit)))

    async def current_model_id(self, ctx):
        return self.model_id


class InMemoryDetailStore:
    def __init__(self):
        self.objects: dict[str, str] = {}

    async def put(self, ctx, item_id, text):
        key = detail_object_key(ctx.tenant_id, ctx.user_id, item_id)
        self.objects[key] = text
        return key

    async def get(self, key):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)

    async def delete_user(self, ctx):
        prefix = f"memory/{ctx.tenant_id}/{ctx.user_id}/"
        for k in [k for k in self.objects if k.startswith(prefix)]:
            self.objects.pop(k)

    async def list_keys(self, ctx):
        prefix = f"memory/{ctx.tenant_id}/{ctx.user_id}/"
        return [k for k in self.objects if k.startswith(prefix)]


# --------------------------------------------------------------------------- fixtures
MEMORY_TABLES = [
    MemoryItem.__table__,
    MemorySessionCursor.__table__,
    MemoryUserSetting.__table__,
    MemoryTurnRecord.__table__,
    MemoryResidentSnapshot.__table__,
    MemoryMetricDaily.__table__,
]


def _extra_tables():
    from bisheng.database.models.message import ChatMessage
    from bisheng.database.models.session import MessageSession
    from bisheng.user.domain.models.user import User

    return [MessageSession.__table__, ChatMessage.__table__, User.__table__]


@pytest.fixture
async def memory_db(tmp_path, monkeypatch):
    """SQLite file DB shared by sync and async sessions; patches the memory DB seam."""
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.memory.domain.repositories import _db

    path = tmp_path / "memory.sqlite"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=MEMORY_TABLES + _extra_tables())
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @asynccontextmanager
    async def async_session():
        with bypass_tenant_filter():
            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                yield session

    @contextmanager
    def sync_session():
        with bypass_tenant_filter():
            with Session(engine, expire_on_commit=False) as session:
                yield session

    monkeypatch.setattr(_db, "async_session", async_session)
    monkeypatch.setattr(_db, "sync_session", sync_session)
    yield SimpleNamespace(engine=engine, session=sync_session)
    await async_engine.dispose()
    engine.dispose()


@pytest.fixture(autouse=True)
def memory_runtime_config(monkeypatch):
    """Runtime config from code defaults (settings is a MagicMock under the test premock)."""
    from bisheng.common.services.config_service import settings

    cls = type(settings)

    async def _aget(self, key):
        return {}

    monkeypatch.setattr(cls, "aget_from_db", _aget)
    monkeypatch.setattr(cls, "get_from_db", lambda self, key: {})


@pytest.fixture
def memory(memory_db):
    """Memory services wired with in-memory doubles into the production factory."""
    from bisheng.memory.domain.services import factory
    from bisheng.memory.domain.services.audit import MemoryAudit
    from bisheng.memory.domain.services.memory_service import MemoryService
    from bisheng.memory.domain.services.metrics import MemoryMetrics
    from bisheng.memory.domain.services.resident import ResidentService
    from bisheng.memory.domain.services.search import SearchService

    kv, index, details = InMemoryKV(), InMemoryIndex(), InMemoryDetailStore()
    metrics = MemoryMetrics(kv)
    audit_rows: list = []

    async def _writer(**kwargs):
        audit_rows.append(kwargs)

    service = MemoryService(index=index, details=details, kv=kv, audit=MemoryAudit(writer=_writer), metrics=metrics)
    factory.reset()
    factory._instances.update(
        kv=kv,
        index=index,
        details=details,
        metrics=metrics,
        service=service,
        search=SearchService(index=index, details=details, metrics=metrics),
        resident=ResidentService(kv=kv, metrics=metrics),
    )
    seed_user(memory_db)
    # Pin the tenant: registration reads the current tenant, and other suites can
    # leave a different tenant ContextVar behind in the same process.
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(TENANT_A)
    yield SimpleNamespace(db=memory_db, kv=kv, index=index, service=service, metrics=metrics)
    try:
        current_tenant_id.reset(token)
    except ValueError:
        pass  # reset from a different context copy; the test's copy is gone anyway
    factory.reset()


def make_ctx(scene="daily", chat_id="other-chat", **kw) -> MemoryContext:
    kw.setdefault("timezone", "Asia/Shanghai")
    kw.setdefault("turn_id", uuid.uuid4().hex)
    return MemoryContext(tenant_id=TENANT_A, user_id=USER_1, scene=scene, chat_id=chat_id, **kw)


def login_user():
    return SimpleNamespace(user_id=USER_1, tenant_id=TENANT_A, user_name="u101")


def seed_user(memory_db, user_id=USER_1):
    from bisheng.user.domain.models.user import User

    with memory_db.session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, user_name=f"u{user_id}", password="x"))
            s.commit()


async def register(memory_db, chat_id=CHAT_ID):
    """What the login-state endpoint does for a conversation."""
    from bisheng.memory.domain.services.gate import MemoryGate

    seed_user(memory_db)
    await MemoryGate.open(chat_id, login_user())


async def disable_my_memory():
    from bisheng.memory.domain.repositories.setting_repository import SettingRepository

    await SettingRepository.set_enabled(make_ctx(), False)


def cursor(memory_db, chat_id=CHAT_ID):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


def turn_rows(memory_db, chat_id=CHAT_ID):
    with memory_db.session() as s:
        return list(s.exec(select(MemoryTurnRecord).where(MemoryTurnRecord.chat_id == chat_id)).all())


async def metric_total(kv, metric):
    from bisheng.memory.domain.services.metrics import _COUNTER_KEY, _today

    h = await kv.hgetall(_COUNTER_KEY.format(day=_today(), tenant=TENANT_A))
    return sum(v for k, v in h.items() if k.endswith("|" + metric))


# --------------------------------------------------------------------------- stream harness
class Chunk:
    """Minimal stand-in for a LangChain streaming chunk."""

    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


class FakeAgent:
    """Scripted ReAct agent: text steps stream, tool steps really invoke the tool."""

    def __init__(self, tool_node, script, after=None):
        self.tools = dict(tool_node.tools_by_name)
        self.script = script
        self.after = after

    async def astream_events(self, _inputs, version="v2", config=None):
        from langchain_core.messages import ToolMessage

        for step in self.script:
            if step[0] == "text":
                yield {"event": "on_chat_model_stream", "name": "model", "data": {"chunk": Chunk(step[1])}}
                continue
            _kind, name, args = step
            run_id = uuid.uuid4().hex
            yield {"event": "on_tool_start", "name": name, "run_id": run_id, "data": {"input": args}}
            out = await self.tools[name].ainvoke(args)
            yield {
                "event": "on_tool_end",
                "name": name,
                "run_id": run_id,
                "data": {"output": ToolMessage(content=out, tool_call_id=run_id, name=name)},
            }
        if self.after is not None:
            raise self.after


@pytest.fixture
def stream_env(monkeypatch):
    """Patch everything around the daily-mode generator; record prompts, tools and rows."""
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    inserted: list = []
    conversation = SimpleNamespace(chat_id=CHAT_ID, user_id=USER_1, name="已命名")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="你是助手。")
    model_info = SimpleNamespace(displayName="stub-model")
    state = SimpleNamespace(
        chunks=["好的。"],
        script=[("text", "好的。")],
        after=None,
        prompts=[],
        tool_names=[],
        llm_messages=[],
        user_tools=[],
    )

    class _LLM:
        async def astream(self, messages):
            state.llm_messages.append(list(messages))
            for text in state.chunks:
                yield Chunk(text)
            if state.after is not None:
                raise state.after

    async def _init(data, login_user, session_subject=None, *, skip_llm=False, memory_register=None):
        # Same call the real _agent_initialize_chat makes (failures are swallowed there).
        await chat_service.register_session(memory_register, conversation.chat_id)
        return ws_config, conversation, message, _LLM(), model_info, False

    def _create_react_agent(model, tool_node, prompt=None, **_kw):
        state.prompts.append(prompt)
        state.tool_names.append(sorted(tool_node.tools_by_name))
        return FakeAgent(tool_node, state.script, state.after)

    monkeypatch.setattr(chat_service, "_agent_initialize_chat", _init)
    monkeypatch.setattr("langgraph.prebuilt.create_react_agent", _create_react_agent)
    monkeypatch.setattr(chat_service, "VisionToolBindWrapper", lambda *a, **k: object())
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(chat_service.DailyCitationScope, "load", AsyncMock(return_value=None))

    async def _prepare_tools(**_kw):
        return list(state.user_tools), []

    monkeypatch.setattr(chat_service, "_prepare_tools", _prepare_tools)
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(chat_service.WorkStationService, "get_chat_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(0, None)))
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations_sync", MagicMock(return_value=None))

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        staticmethod(lambda *_a, **_k: False),
    )

    def data(text="今天喝什么"):
        return APIChatCompletion(clientTimestamp="2026-11-13T00:00:00Z", conversationId=CHAT_ID, model="m1", text=text)

    return SimpleNamespace(
        inserted=inserted, state=state, data=data, chat_service=chat_service, conversation=conversation
    )


def login_register():
    """The register callable a login-state endpoint hands to the service."""
    from bisheng.memory.domain.services.gate import MemoryGate

    async def _register(chat_id):
        await MemoryGate.open(chat_id, login_user())

    return _register


async def run_turn(env, *, registered=True):
    """Drive one daily-mode turn to completion; returns the SSE chunks."""
    kwargs = {"memory_register": login_register()} if registered else {}
    response = await env.chat_service._agent_stream_chat_completion(MagicMock(), env.data(), login_user(), **kwargs)
    return [chunk async for chunk in response.body_iterator]


def sse_events(chunks, category=None):
    out = []
    for c in chunks:
        if not c.startswith("event: message"):
            continue
        body = json.loads(c.split("data: ", 1)[1])
        if category is None or body.get("category") == category:
            out.append(body)
    return out


def answer_rows(inserted):
    return [r for r in inserted if r.category == "agent_answer"]
