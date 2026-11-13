"""Shared fixtures for F132 long-term memory tests.

Provides an SQLite database with the six memory tables (plus the session,
message, user and assistant tables the gate and consolidation read), in-memory
doubles of the three memory ports and of the KV port, MemoryContext factories
and four identities: two tenants, two users, a "visible multi-tenant" user and a
global super admin.
"""

from __future__ import annotations

import fnmatch
import time
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily
from bisheng.memory.domain.models.memory_resident_snapshot import MemoryResidentSnapshot
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.ports import IndexHit, MemoryContext, VectorUnconfigured, detail_object_key

MEMORY_TABLES = [
    MemoryItem.__table__,
    MemorySessionCursor.__table__,
    MemoryUserSetting.__table__,
    MemoryTurnRecord.__table__,
    MemoryResidentSnapshot.__table__,
    MemoryMetricDaily.__table__,
]

TENANT_A = 1
TENANT_B = 2
USER_1 = 101
USER_2 = 102


def _extra_tables():
    from bisheng.database.models.assistant import Assistant
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion
    from bisheng.database.models.message import ChatMessage
    from bisheng.database.models.session import MessageSession
    from bisheng.user.domain.models.user import User

    return [
        MessageSession.__table__,
        ChatMessage.__table__,
        User.__table__,
        Assistant.__table__,
        Flow.__table__,
        FlowVersion.__table__,
    ]


@pytest.fixture
async def memory_db(tmp_path, monkeypatch):
    """SQLite file DB shared by sync and async sessions; patches the memory DB seam."""
    from bisheng.memory.domain.repositories import _db

    path = tmp_path / "memory.sqlite"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=MEMORY_TABLES + _extra_tables())
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    from bisheng.core.context.tenant import bypass_tenant_filter

    # Other suites register the global tenant-filter session events; memory
    # repositories filter tenant and user explicitly, so tests bypass the
    # automatic filter instead of depending on a tenant ContextVar.
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
    yield SimpleNamespace(engine=engine, async_engine=async_engine, session=sync_session, asession=async_session)
    await async_engine.dispose()
    engine.dispose()


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

    async def acquire(self, key, token, ttl_seconds):
        if self._alive(key):
            return False
        await self.set(key, token, ttl_seconds)
        return True

    async def renew(self, key, token, ttl_seconds):
        if self._alive(key) and self.data[key] == token:
            self.expiry[key] = time.monotonic() + ttl_seconds
            return True
        return False

    async def release(self, key, token):
        if self._alive(key) and self.data[key] == token:
            await self.delete(key)
            return True
        return False


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    words = set(text.split())
    # Chinese has no spaces: use character bigrams as well.
    chars = [c for c in text if not c.isspace()]
    words |= {a + b for a, b in zip(chars, chars[1:])}
    return words


class InMemoryIndex:
    """MemoryIndex double with failure injection."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.keyword_down = False
        self.vector_down = False
        self.vector_unconfigured = False
        self.write_fail = False
        self.write_timeout = False
        self.model_id = "emb-1"
        self.filters: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def upsert(self, ctx, item_id, content):
        if self.write_timeout:
            raise TimeoutError("embedding timeout")
        if self.write_fail:
            raise RuntimeError("index write failed")
        self.docs[item_id] = {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "content": content}
        return None if self.vector_unconfigured else self.model_id

    async def delete(self, ctx, item_ids):
        for i in item_ids:
            self.docs.pop(i, None)
            self.deleted.append(i)

    async def delete_user(self, ctx):
        for k in [k for k, d in self.docs.items() if d["tenant_id"] == ctx.tenant_id and d["user_id"] == ctx.user_id]:
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
        self.filters.append(("keyword", dict(scope)))
        if self.keyword_down:
            raise ConnectionError("es down")
        return self._search(scope, query, limit)

    async def vector_search(self, ctx, scope, query, limit):
        self.filters.append(("vector", dict(scope)))
        if self.vector_unconfigured:
            raise VectorUnconfigured()
        if self.vector_down:
            raise ConnectionError("milvus down")
        return list(reversed(self._search(scope, query, limit)))

    async def current_model_id(self, ctx):
        return None if self.vector_unconfigured else self.model_id


class InMemoryDetailStore:
    def __init__(self):
        self.objects: dict[str, str] = {}
        self.read_fail = False

    async def put(self, ctx, item_id, text):
        key = detail_object_key(ctx.tenant_id, ctx.user_id, item_id)
        self.objects[key] = text
        return key

    async def get(self, key):
        if self.read_fail:
            raise ConnectionError("minio down")
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


class StubLLM:
    """MemoryLLM double: returns scripted consolidation answers or raises."""

    def __init__(self):
        self.answers: list = []
        self.prompts: list[str] = []
        self.calls: list[MemoryContext] = []

    async def consolidate(self, ctx, prompt):
        self.calls.append(ctx)
        self.prompts.append(prompt)
        if not self.answers:
            return '{"operations": []}'
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def embed(self, ctx, texts):
        return [[float(len(t))] for t in texts]


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
def kv():
    return InMemoryKV()


@pytest.fixture
def index():
    return InMemoryIndex()


@pytest.fixture
def details():
    return InMemoryDetailStore()


@pytest.fixture
def llm():
    return StubLLM()


@pytest.fixture
def make_ctx():
    def _make(tenant_id=TENANT_A, user_id=USER_1, **kw):
        kw.setdefault("timezone", "Asia/Shanghai")
        kw.setdefault("chat_id", "chat-1")
        kw.setdefault("turn_id", "turn-1")
        return MemoryContext(tenant_id=tenant_id, user_id=user_id, **kw)

    return _make


@pytest.fixture
def identities():
    """Logged-in user doubles; ``visible_tenants`` mimics the tenant filter IN list."""
    return SimpleNamespace(
        user1=SimpleNamespace(user_id=USER_1, tenant_id=TENANT_A, visible_tenants=[TENANT_A], is_global_super=False),
        user2=SimpleNamespace(user_id=USER_2, tenant_id=TENANT_A, visible_tenants=[TENANT_A], is_global_super=False),
        multi=SimpleNamespace(
            user_id=USER_1, tenant_id=TENANT_B, visible_tenants=[TENANT_A, TENANT_B], is_global_super=False
        ),
        superadmin=SimpleNamespace(user_id=1, tenant_id=TENANT_A, visible_tenants=None, is_global_super=True),
    )


@pytest.fixture
def tenant_ctx():
    """Set the tenant ContextVar for the duration of a test."""
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    tokens = []

    def _set(tenant_id):
        tokens.append(set_current_tenant_id(tenant_id))

    yield _set
    for t in reversed(tokens):
        try:
            current_tenant_id.reset(t)
        except ValueError:
            # Set inside an async test: that task's context copy is already gone.
            pass


def make_message(chat_id, user_id, message, category="question", is_bot=False, **kw):
    """A ChatMessage with the NOT NULL columns filled."""
    from bisheng.database.models.message import ChatMessage

    kw.setdefault("flow_id", "")
    kw.setdefault("type", "end" if is_bot else "human")
    return ChatMessage(chat_id=chat_id, user_id=user_id, message=message, category=category, is_bot=is_bot, **kw)


class FakeAuditWriter:
    def __init__(self):
        self.rows = []

    async def __call__(self, **kwargs):
        self.rows.append(kwargs)


@pytest.fixture
def audit_rows():
    return FakeAuditWriter()


@pytest.fixture
def service(memory_db, index, details, kv, audit_rows):
    """MemoryService wired with in-memory doubles."""
    from bisheng.memory.domain.services.audit import MemoryAudit
    from bisheng.memory.domain.services.memory_service import MemoryService
    from bisheng.memory.domain.services.metrics import MemoryMetrics

    return MemoryService(
        index=index, details=details, kv=kv, audit=MemoryAudit(writer=audit_rows), metrics=MemoryMetrics(kv)
    )


async def counter(kv, tenant_id, metric):
    """Sum of a metric across scenes/apps for today in the KV double."""
    from bisheng.memory.domain.services.metrics import _COUNTER_KEY, _today

    h = await kv.hgetall(_COUNTER_KEY.format(day=_today(), tenant=tenant_id))
    return sum(v for k, v in h.items() if k.endswith("|" + metric))
