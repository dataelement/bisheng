"""T027: local permission decisions; WeKnora read responses at its GET boundary."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.application.provider_wiki import WikiApplication, observe_revision
from bisheng.knowledge.domain.repositories.provider_wiki_repository import (
    WikiControl,
    WikiScope,
    WikiUnavailable,
    read_proof,
)


@pytest.fixture
def wiki():
    scope = WikiScope(7, 11, 1, 2, "tenant", "library", 4, 5, 5, None, "ready")
    control = AsyncMock()
    control.scope.return_value = scope
    control.source.side_effect = lambda scope, remote: 12 if remote == "doc" else None

    async def allow(user, *, resource_type, resource_id, action):
        return user != "OUT" if resource_type == "knowledge_space" else user == "LIN" and resource_id == 12

    async def get(scope, path, params):
        assert params["min_revision"] == 5
        if path == "source-revision":
            return {
                "success": True,
                "data": {"ready": True, "target_revision": 5, "applied_revision": 5, "empty": False},
            }
        if path == "pages/entity/a":
            return {
                "knowledge_base_id": "library",
                "slug": "entity/a",
                "title": "A",
                "page_type": "entity",
                "summary": "shared",
                "content": "shared body",
                "in_links": [],
                "out_links": ["concept/b"],
                "source_refs": ["doc|secret title", "unknown|hidden"],
            }
        if path == "graph":
            return {
                "nodes": [{"slug": "entity/a", "title": "A", "page_type": "entity", "link_count": 1}],
                "edges": [{"source": "entity/a", "target": "concept/b"}],
            }
        raise AssertionError(path)

    port = AsyncMock(side_effect=get)
    return WikiApplication(control=control, get=port, allowed=allow), control, port, scope


async def test_shared_graph_body_but_independent_original(wiki):
    app, _, _, _ = wiki
    pages = [await app.page(user, 11, generation=2, slug="entity/a") for user in ("LIN", "ZHOU")]
    assert pages[0]["sources"] == [{"file_id": 12}, {"restricted": True}]
    assert pages[1]["sources"] == [{"restricted": True}] * 2
    assert pages[0]["content"] == pages[1]["content"] == "shared body"
    assert "secret title" not in str(pages)
    assert await app.graph("LIN", 11) == await app.graph("ZHOU", 11)
    assert await app.source("LIN", 11, generation=2, remote_id="doc", action="download") == 12
    for user, remote in [("ZHOU", "doc"), ("LIN", "unknown")]:
        with pytest.raises(WikiUnavailable):
            await app.source(user, 11, generation=2, remote_id=remote, action="download")


async def test_outside_old_slug_and_pending_no_content(wiki):
    app, control, port, scope = wiki
    for call in [
        app.page("OUT", 11, generation=2, slug="entity/a"),
        app.search("OUT", 11, "A"),
        app.source("OUT", 11, generation=2, remote_id="doc", action="visible"),
        app.page("LIN", 11, generation=1, slug="entity/a"),
        app.page("LIN", 11, generation=2, slug="../secret"),
    ]:
        with pytest.raises(WikiUnavailable):
            await call
    port.assert_not_awaited()
    control.scope.return_value = replace(scope, pending="delete-op")
    assert await app.status("LIN", 11) == "updating"
    with pytest.raises(WikiUnavailable):
        await app.graph("LIN", 11)
    control.release.assert_not_awaited()
    assert all(c.args[1] == "source-revision" for c in port.await_args_list)


async def test_delete_arriving_during_page_read_discards_result(wiki):
    app, control, _, scope = wiki
    control.scope.side_effect = [scope, replace(scope, revision=5, pending="delete")]
    with pytest.raises(WikiUnavailable):
        await app.page("LIN", 11, generation=2, slug="entity/a")


@pytest.mark.parametrize(
    "target,applied,minimum,empty,ready,allows",
    [
        (5, 5, 5, False, True, True),
        (6, 5, 5, False, True, False),
        (4, 4, 5, False, True, False),
        (0, 0, 0, False, True, False),
        (0, 0, 0, True, True, True),
        (True, True, 0, False, True, False),
        (5, 5, 5, False, False, False),
    ],
)
def test_exact_read_only_proof(target, applied, minimum, empty, ready, allows):
    wire = {
        "success": True,
        "data": {"target_revision": target, "applied_revision": applied, "empty": empty, "ready": ready},
    }
    assert read_proof(wire, minimum) is allows


async def test_writer_cas_release_only_for_pinned_library_and_delete(wiki):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as Binding

    _, _, _, scope = wiki
    token = current_tenant_id.set(scope.tenant_id)
    engine = create_async_engine("sqlite+aiosqlite://")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    control = WikiControl(sessions)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Binding.__table__.create)
        async with sessions.begin() as session:
            session.add(
                Binding(
                    tenant_id=7,
                    space_id=11,
                    provider_key="weknora",
                    active_generation=2,
                    state="ready",
                    revision=4,
                    wiki_target_revision=5,
                    wiki_applied_revision=5,
                )
            )
        async with sessions.begin() as session:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await control.require_provider_safe_deletion(session, 11, "knowledge_space_clear")
            assert await control.begin(session, scope, "delete1")
            assert not await control.begin(session, scope, "delete2")
            pending = replace(scope, pending="delete1", revision=5)
            assert not await control.pin(session, pending, "delete1", 5)
            assert await control.pin(session, pending, "delete1", 8)
            pinned = replace(pending, revision=6, target=8)
            get = AsyncMock(
                return_value={
                    "success": True,
                    "data": {"target_revision": 8, "applied_revision": 8, "empty": False, "ready": True},
                }
            )
            proof = await observe_revision(get, pinned)
            assert not await control.release(
                session, pinned, "delete1", replace(proof, scope=replace(pinned, remote_kb_id="other"))
            )
            assert not await control.release(session, pinned, "other", proof)
            assert await control.release(session, pinned, "delete1", proof)
            released = replace(pinned, revision=7, pending=None, applied=8)
            assert await control.begin(session, released, "delete2")
            assert not await control.release(session, pinned, "delete1", proof)
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()
