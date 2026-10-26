"""Fixtures for the F052 unified retrieval facade tests.

Everything the facade touches outside itself is faked here: the retrieval
engine, the permission batch check, the visible-object enumeration and the
knowledge-row lookup. That leaves the facade's own decisions — identity
fail-closed, scope resolution, reachability, whitelist semantics, clamping —
as the only thing under test.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

_PROXY_ENV_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    """A SOCKS proxy in the environment makes httpx fail for want of socksio.

    The failure looks like a broken test rather than a broken environment, so
    clear it here instead of leaving it to whoever runs the suite next.
    """
    for name in _PROXY_ENV_VARS:
        if name in os.environ:
            monkeypatch.delenv(name, raising=False)


def make_knowledge_row(knowledge_id: int, knowledge_type: int, *, name: str | None = None, user_id: int = 3):
    row = MagicMock()
    row.id = knowledge_id
    row.type = knowledge_type
    row.name = name or f"kb-{knowledge_id}"
    row.description = f"desc-{knowledge_id}"
    row.user_id = user_id
    return row


def make_document(content: str, *, document_id: int, chunk_index: int = 0) -> Document:
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "document_name": f"{document_id}.pdf",
            "chunk_index": chunk_index,
            "document_update_time": "",
        },
    )


class FakeEngine:
    """Programmable stand-in for ``RetrievalEngine``.

    ``docs_by_knowledge`` maps a knowledge id to the documents it yields;
    ``raises`` makes ``retrieve_many`` blow up so fail-closed can be observed.
    """

    def __init__(self, login_user, *, version_repo=None):
        self.login_user = login_user
        self.version_repo = version_repo
        self.calls: list[dict] = []
        self.docs_by_knowledge: dict[int, list[Document]] = FakeEngine.docs_by_knowledge_default
        self.raises: BaseException | None = FakeEngine.raises_default

    docs_by_knowledge_default: dict[int, list[Document]] = {}
    raises_default: BaseException | None = None
    instances: list[FakeEngine] = []

    async def retrieve_many(self, targets, *, query, tag_filters=None, max_content):
        self.calls.append(
            {
                "target_ids": [target.id for target in targets],
                "query": query,
                "tag_filters": tag_filters,
                "max_content": max_content,
            }
        )
        if self.raises is not None:
            raise self.raises
        results: list[tuple[int, Document]] = []
        for target in targets:
            for doc in self.docs_by_knowledge.get(target.id, []):
                results.append((target.id, doc))
        return results

    async def attach_document_update_time(self, results) -> None:
        for _, doc in results:
            doc.metadata.setdefault("document_update_time", "")


@pytest.fixture
def fake_engine(monkeypatch):
    """Install ``FakeEngine`` in place of ``RetrievalEngine`` in the facade."""

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    FakeEngine.docs_by_knowledge_default = {}
    FakeEngine.raises_default = None
    FakeEngine.instances = []

    created: list[FakeEngine] = []

    def factory(login_user, *, version_repo=None):
        engine = FakeEngine(login_user, version_repo=version_repo)
        created.append(engine)
        FakeEngine.instances = created
        return engine

    monkeypatch.setattr(facade_mod, "RetrievalEngine", factory)
    return FakeEngine


@pytest.fixture
def knowledge_rows(monkeypatch):
    """Control what ``KnowledgeDao.aget_list_by_ids`` finds."""

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    table: dict[int, object] = {}

    async def aget_list_by_ids(ids):
        return [table[key] for key in ids if key in table]

    monkeypatch.setattr(facade_mod.KnowledgeDao, "aget_list_by_ids", aget_list_by_ids)

    def register(knowledge_id: int, knowledge_type: int = KnowledgeTypeEnum.SPACE.value, **kwargs):
        row = make_knowledge_row(knowledge_id, knowledge_type, **kwargs)
        table[knowledge_id] = row
        return row

    register.table = table
    return register


@pytest.fixture
def fake_visibility(monkeypatch):
    """Control ``batch_check_business_actions`` per resource type and id."""

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    granted: dict[str, set[int]] = {"knowledge_space": set(), "knowledge_library": set()}
    seen: list[dict] = []

    async def batch_check(login_user, *, resource_type, resource_ids, actions):
        seen.append(
            {
                "login_user": login_user,
                "resource_type": resource_type,
                "resource_ids": [int(one) for one in resource_ids],
                "actions": tuple(actions),
            }
        )
        allowed = granted.get(resource_type, set())
        return {
            str(resource_id): frozenset(actions) if int(resource_id) in allowed else frozenset()
            for resource_id in resource_ids
        }

    monkeypatch.setattr(facade_mod, "batch_check_business_actions", batch_check)
    granted_holder = MagicMock()
    granted_holder.granted = granted
    granted_holder.seen = seen
    return granted_holder


@pytest.fixture
def fake_visible_objects(monkeypatch):
    """Control ``F048PermissionRuntime.list_visible_objects``."""

    from bisheng.knowledge.domain.services import retrieval_facade_service as facade_mod

    by_type: dict[str, list[int]] = {}
    calls: list[dict] = []

    async def list_visible_objects(actor, *, resource_type, max_results):
        calls.append({"actor": actor, "resource_type": resource_type, "max_results": max_results})
        result = MagicMock()
        result.object_ids = tuple(str(one) for one in by_type.get(resource_type, []))
        return result

    runtime = MagicMock()
    runtime.list_visible_objects = list_visible_objects
    monkeypatch.setattr(facade_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    holder = MagicMock()
    holder.by_type = by_type
    holder.calls = calls
    return holder
