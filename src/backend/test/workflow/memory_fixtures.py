"""F132 Wave 10 fixtures shared by the workflow memory tests.

Reuses the in-memory doubles of ``test/memory/conftest.py`` (imported as plain
classes) and defines its own fixtures, because the workflow tests do not live
under ``test/memory/``. Differences from the memory suite:

* the async engine uses ``NullPool``: the retriever node is synchronous and runs
  its search on the ``run_async_safe`` bridge loop, so a pooled aiosqlite
  connection must never be shared between the pytest loop and that loop;
* ``wired`` puts the doubles into ``memory.domain.services.factory`` so the
  production code paths (node, worker task) pick them up.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from test.memory.conftest import (
    MEMORY_TABLES,
    TENANT_A,
    USER_1,
    USER_2,
    InMemoryDetailStore,
    InMemoryIndex,
    InMemoryKV,
    _extra_tables,
    make_message,
)

__all__ = [
    "TENANT_A",
    "USER_1",
    "USER_2",
    "details",
    "graph",
    "index",
    "kv",
    "make_message",
    "memory_db",
    "memory_runtime_config",
    "register_chat",
    "retriever_node",
    "seed_user",
    "service",
    "start_node",
    "wired",
]


@pytest.fixture(autouse=True)
def memory_runtime_config(monkeypatch):
    """Runtime config from code defaults (settings is a MagicMock under the test premock)."""
    from bisheng.common.services.config_service import settings

    cls = type(settings)

    async def _aget(self, key):
        return {}

    monkeypatch.setattr(cls, "aget_from_db", _aget, raising=False)
    monkeypatch.setattr(cls, "get_from_db", lambda self, key: {}, raising=False)


@pytest.fixture
async def memory_db(tmp_path, monkeypatch):
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.memory.domain.repositories import _db

    path = tmp_path / "memory.sqlite"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=MEMORY_TABLES + _extra_tables())
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)

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


@pytest.fixture
def kv():
    return InMemoryKV()


@pytest.fixture
def index():
    idx = InMemoryIndex()
    # keyword path only: ranking is then the plain keyword score, which keeps
    # the relevance-order assertions deterministic
    idx.vector_unconfigured = True
    return idx


@pytest.fixture
def details():
    return InMemoryDetailStore()


@pytest.fixture
def service(memory_db, index, details, kv):
    from bisheng.memory.domain.services.audit import MemoryAudit
    from bisheng.memory.domain.services.memory_service import MemoryService
    from bisheng.memory.domain.services.metrics import MemoryMetrics

    async def _writer(**kwargs):
        return None

    return MemoryService(
        index=index, details=details, kv=kv, audit=MemoryAudit(writer=_writer), metrics=MemoryMetrics(kv)
    )


@pytest.fixture
def wired(service, index, details, kv, monkeypatch):
    """Production factory returns the in-memory doubles."""
    from bisheng.memory.domain.services import factory
    from bisheng.memory.domain.services.metrics import MemoryMetrics
    from bisheng.memory.domain.services.search import SearchService

    metrics = MemoryMetrics(kv)
    monkeypatch.setitem(factory._instances, "kv", kv)
    monkeypatch.setitem(factory._instances, "index", index)
    monkeypatch.setitem(factory._instances, "details", details)
    monkeypatch.setitem(factory._instances, "metrics", metrics)
    monkeypatch.setitem(factory._instances, "service", service)
    monkeypatch.setitem(factory._instances, "search", SearchService(index=index, details=details, metrics=metrics))
    return SimpleNamespace(service=service, index=index, details=details, kv=kv)


def seed_user(memory_db, user_id=USER_1):
    from bisheng.user.domain.models.user import User

    with memory_db.session() as s:
        if s.get(User, user_id) is None:
            s.add(User(user_id=user_id, user_name=f"u{user_id}", password="x"))
            s.commit()


def register_chat(memory_db, chat_id, user_id=USER_1, tenant_id=TENANT_A):
    """A logged-in registration row, as ``MemoryGate.open`` leaves it."""
    seed_user(memory_db, user_id)
    with memory_db.session() as s:
        s.add(
            MemorySessionCursor(
                chat_id=chat_id,
                tenant_id=tenant_id,
                user_id=user_id,
                eligible=True,
                timezone="Asia/Shanghai",
                last_message_id=0,
                watermark_message_id=0,
            )
        )
        s.commit()


def start_node(memory_enabled: bool | None = None, node_id: str = "start_1") -> dict:
    groups = [
        {"name": "开场引导", "params": [{"key": "guide_word", "value": ""}, {"key": "guide_question", "value": []}]},
        {
            "name": "全局变量",
            "params": [
                {"key": "chat_history", "value": 10},
                {"key": "preset_question", "value": []},
                {"key": "custom_variables", "value": []},
            ],
        },
    ]
    if memory_enabled is not None:
        groups.append(
            {"name": "记忆", "params": [{"key": "memory_enabled", "value": memory_enabled, "type": "switch"}]}
        )
    return {"id": node_id, "data": {"id": node_id, "type": "start", "name": "开始", "v": "3", "group_params": groups}}


def retriever_node(node_id: str = "memory_retriever_1", query="{{#start_1.user_info#}}", limit=20) -> dict:
    params = [{"key": "query", "value": query, "type": "var_textarea", "required": True}]
    if limit is not ...:
        params.append({"key": "limit", "value": limit, "type": "number"})
    params.append({"key": "retrieved_memory", "value": "", "type": "var"})
    return {
        "id": node_id,
        "data": {
            "id": node_id,
            "type": "memory_retriever",
            "name": "记忆检索",
            "group_params": [{"name": "检索", "params": params}],
        },
    }


def graph(*middle: dict, memory_enabled: bool | None = None) -> dict:
    """start -> middle... -> end, chained with edges."""
    nodes = [
        start_node(memory_enabled),
        *middle,
        {"id": "end_1", "data": {"id": "end_1", "type": "end", "name": "结束"}},
    ]
    edges = []
    for a, b in zip(nodes, nodes[1:]):
        edges.append(
            {
                "id": f"e_{a['id']}_{b['id']}",
                "source": a["id"],
                "sourceHandle": "right_handle",
                "target": b["id"],
                "targetHandle": "left_handle",
            }
        )
    return {"nodes": nodes, "edges": edges}
