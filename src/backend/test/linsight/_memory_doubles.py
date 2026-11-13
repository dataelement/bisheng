"""F132 Wave 11: memory test doubles for the deep-research integration tests.

A trimmed copy of ``test/memory/conftest.py`` (SQLite seam, KV / index / detail
doubles, runtime config) so the linsight tests do not depend on another
directory's conftest. Test modules import the fixtures they use by name.
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
from bisheng.memory.domain.ports import IndexHit, detail_object_key

TENANT_A = 1
USER_1 = 101
USER_2 = 102
CHAT = "chat-lin-1"


def _tables():
    from bisheng.database.models.message import ChatMessage
    from bisheng.database.models.session import MessageSession
    from bisheng.user.domain.models.user import User

    return [
        MemoryItem.__table__,
        MemorySessionCursor.__table__,
        MemoryUserSetting.__table__,
        MemoryTurnRecord.__table__,
        MemoryResidentSnapshot.__table__,
        MemoryMetricDaily.__table__,
        MessageSession.__table__,
        ChatMessage.__table__,
        User.__table__,
    ]


@pytest.fixture
def memory_runtime_config(monkeypatch):
    """Memory runtime config from code defaults (settings is premocked in tests)."""
    from bisheng.common.services.config_service import settings

    cls = type(settings)

    async def _aget(self, key):
        return {}

    monkeypatch.setattr(cls, "aget_from_db", _aget, raising=False)
    monkeypatch.setattr(cls, "get_from_db", lambda self, key: {}, raising=False)


@pytest.fixture
async def memory_db(tmp_path, monkeypatch, memory_runtime_config):
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.memory.domain.repositories import _db

    path = tmp_path / "memory.sqlite"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=_tables())
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


class InMemoryKV:
    def __init__(self):
        self.data: dict = {}
        self.expiry: dict = {}

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
        return self._alive(key) and self.data[key] == token

    async def release(self, key, token):
        if self._alive(key) and self.data[key] == token:
            await self.delete(key)
            return True
        return False


class InMemoryIndex:
    def __init__(self):
        self.docs: dict = {}
        self.down = False

    async def upsert(self, ctx, item_id, content):
        self.docs[item_id] = {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "content": content}
        return None

    async def delete(self, ctx, item_ids):
        for i in item_ids:
            self.docs.pop(i, None)

    async def delete_user(self, ctx):
        self.docs.clear()

    def _search(self, scope, query, limit):
        hits = []
        for item_id, d in self.docs.items():
            if d["tenant_id"] != scope["tenant_id"] or d["user_id"] != scope["user_id"]:
                continue
            common = set(query) & set(d["content"])
            if common:
                hits.append(IndexHit(item_id=item_id, score=float(len(common))))
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    async def keyword_search(self, scope, query, limit):
        if self.down:
            raise ConnectionError("es down")
        return self._search(scope, query, limit)

    async def vector_search(self, ctx, scope, query, limit):
        from bisheng.memory.domain.ports import VectorUnconfigured

        raise VectorUnconfigured()

    async def current_model_id(self, ctx):
        return None


class InMemoryDetailStore:
    def __init__(self):
        self.objects: dict = {}

    async def put(self, ctx, item_id, text):
        key = detail_object_key(ctx.tenant_id, ctx.user_id, item_id)
        self.objects[key] = text
        return key

    async def get(self, key):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)

    async def delete_user(self, ctx):
        self.objects.clear()

    async def list_keys(self, ctx):
        return list(self.objects)


@pytest.fixture
def memory_services(memory_db, monkeypatch):
    """Wire the production factory with in-memory doubles; returns the doubles."""
    from bisheng.memory.domain.services import factory
    from bisheng.memory.domain.services.audit import MemoryAudit
    from bisheng.memory.domain.services.memory_service import MemoryService
    from bisheng.memory.domain.services.metrics import MemoryMetrics
    from bisheng.memory.domain.services.resident import ResidentService
    from bisheng.memory.domain.services.search import SearchService

    kv, index, details = InMemoryKV(), InMemoryIndex(), InMemoryDetailStore()
    metrics = MemoryMetrics(kv)
    audit_rows: list = []

    async def _audit_writer(**kwargs):
        audit_rows.append(kwargs)

    service = MemoryService(
        index=index, details=details, kv=kv, audit=MemoryAudit(writer=_audit_writer), metrics=metrics
    )
    instances = {
        "kv": kv,
        "index": index,
        "details": details,
        "metrics": metrics,
        "service": service,
        "search": SearchService(index=index, details=details, metrics=metrics),
        "resident": ResidentService(kv=kv, metrics=metrics),
    }
    monkeypatch.setattr(factory, "_instances", dict(instances))
    return SimpleNamespace(**instances)


async def counter(kv, tenant_id, metric):
    from bisheng.memory.domain.services.metrics import _COUNTER_KEY, _today

    h = await kv.hgetall(_COUNTER_KEY.format(day=_today(), tenant=tenant_id))
    return sum(v for k, v in h.items() if k.endswith("|" + metric))


def seed_session(memory_db, chat_id=CHAT, user_id=USER_1, registered=True, enabled=True, tenant_id=TENANT_A):
    """A daily conversation (flow_type 15) owned by ``user_id``, optionally registered."""
    from bisheng.database.models.session import MessageSession
    from bisheng.user.domain.models.user import User

    with memory_db.session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, user_name=f"u{user_id}", password="x"))
        if s.get(MessageSession, chat_id) is None:
            s.add(MessageSession(chat_id=chat_id, flow_id="", flow_type=15, user_id=user_id, name="c"))
        if registered:
            s.add(MemorySessionCursor(chat_id=chat_id, tenant_id=tenant_id, user_id=user_id))
        if not enabled:
            s.add(MemoryUserSetting(tenant_id=tenant_id, user_id=user_id, enabled=False))
        s.commit()


def add_task_message(memory_db, chat_id=CHAT, user_id=USER_1, svid="sv-1", text="") -> int:
    """The bot task turn row of one round (category='task', extra carries the svid)."""
    import json

    from bisheng.database.models.message import ChatMessage

    with memory_db.session() as s:
        msg = ChatMessage(
            chat_id=chat_id,
            user_id=user_id,
            message=text,
            category="task",
            is_bot=True,
            flow_id="",
            type="over",
            extra=json.dumps({"linsight_session_version_id": svid}),
        )
        s.add(msg)
        s.commit()
        s.refresh(msg)
        return msg.id


def turn_rows(memory_db, kind=None):
    from sqlmodel import select

    with memory_db.session() as s:
        stmt = select(MemoryTurnRecord).order_by(MemoryTurnRecord.id)
        if kind:
            stmt = stmt.where(MemoryTurnRecord.kind == kind)
        return list(s.exec(stmt).all())


def cursor_row(memory_db, chat_id=CHAT):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)
