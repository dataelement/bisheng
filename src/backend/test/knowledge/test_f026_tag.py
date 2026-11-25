"""T025: local DB + controlled port contracts, not WeKnora service integration."""

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary as Library
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding, KnowledgeProviderTagRef


@pytest_asyncio.fixture
async def store(tmp_path):
    from bisheng.knowledge.domain.models.provider_tag_import import ProviderTagImport
    from bisheng.knowledge.domain.repositories.provider_tag_repository import ProviderTagRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/tags.db")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for cls in (KnowledgeProviderBinding, KnowledgeProviderTagRef, ProviderTagImport, Library):
            await conn.run_sync(cls.__table__.create)
    async with sessions.begin() as session:
        session.add_all(
            [
                KnowledgeProviderBinding(
                    tenant_id=7, space_id=n, provider_key="weknora", active_generation=1, state="ready"
                )
                for n in (8, 9)
            ]
        )
    try:
        yield ProviderTagRepository(sessions), sessions
    finally:
        await engine.dispose()


def svc(store, port):
    from bisheng.knowledge.application.provider_tags import ProviderTags

    return ProviderTags(store[0], port, authorize=AsyncMock(return_value=True))


async def test_page_501_rename_tombstone_generation(store):
    from bisheng.knowledge.application.provider_tags import TagConflict, TagScope

    scope = TagScope(7, 8, 1)
    port = AsyncMock()
    app = svc(store, port)
    port.page.return_value = ([("r501", "word 501")], 501)
    last = await app.page(scope, page=6, page_size=100)
    ref = last["data"][0]["tag_ref_id"]
    assert 0 < ref < 2**53 and last["total"] == 501
    port.page.assert_awaited_with(scope, 6, 100)
    port.page.return_value = ([("r1", "first")], 501)
    first = await app.page(scope, page=1, page_size=100)
    assert await app.resolve(scope, [ref, first["data"][0]["tag_ref_id"]]) == ("r501", "r1")
    port.page.return_value = ([("r501", "renamed")], 501)
    assert (await app.page(scope, page=6, page_size=100))["data"] == [{"name": "renamed", "tag_ref_id": ref}]
    with pytest.raises(TagConflict):
        await app.resolve(TagScope(7, 8, 2), [ref])
    await app.delete(scope, ref)
    port.delete_relations_only.assert_awaited_once_with(scope, "r501")
    with pytest.raises(TagConflict):
        await app.resolve(scope, [ref])


async def test_manual_edit_commands_and_revision(store):
    from bisheng.knowledge.application.provider_tags import TagConflict, TagScope

    scope = TagScope(7, 8, 1)
    port = AsyncMock()
    app = svc(store, port)
    port.page.return_value = ([("uuid", "word")], 1)
    ref = (await app.page(scope, page=1, page_size=50))["data"][0]["tag_ref_id"]
    await app.edit(scope, 22, "append", [])
    port.edit_manual.assert_not_awaited()
    await app.edit(scope, 22, "append", [ref])
    port.edit_manual.assert_awaited_with(scope, 22, "append", ("uuid",), None)
    for mode, refs in [("replace", [ref]), ("clear", [])]:
        with pytest.raises(TagConflict):
            await app.edit(scope, 22, mode, refs)
        port.edit_manual.side_effect = TagConflict("stale remote revision")
        with pytest.raises(TagConflict):
            await app.edit(scope, 22, mode, refs, expected_revision=1)
        port.edit_manual.assert_awaited_with(scope, 22, mode, ("uuid",) if refs else (), 1)
    app.authorize.return_value = False
    with pytest.raises(PermissionError):
        await app.edit(scope, 22, "append", [ref])


async def test_unpublished_vocabulary_never_classifies(store):
    from bisheng.knowledge.application.provider_tags import TagScope

    port = AsyncMock()
    app = svc(store, port)
    scope = TagScope(7, 8, 1)
    port.published_revision.return_value = None
    assert await app.classify(scope, 22) is None
    port.classify_version.assert_not_awaited()
    port.published_revision.return_value = 4
    await app.classify(scope, 22)
    port.classify_version.assert_awaited_once_with(scope, 22, 4)


async def test_freeze_each_department_and_recover_lost_ack(store):
    from bisheng.knowledge.application.provider_tags import TagScope

    port = AsyncMock()
    app = svc(store, port)
    a, b = TagScope(7, 8, 1), TagScope(7, 9, 1)
    async with store[1].begin() as db:
        db.add_all(
            [
                Library(id=i, tenant_id=t, owner_knowledge_id=o, tags=["X", "Y"], name="template")
                for i, t, o in [(1, 7, None), (2, 7, 9), (3, 99, None)]
            ]
        )
    plans = await asyncio.gather(*(app.freeze_template(scope, 1, request_key="k", actor_id=3) for scope in (a, a, b)))
    assert plans[0] == plans[1] and plans[0] != plans[2]
    async with store[1].begin() as db:
        (await db.get(Library, 1)).tags = ["changed"]
    receipts = {}

    async def apply(scope, key, words):
        assert words == ("X", "Y")
        receipts[(scope, key)] = 7
        if scope == b:
            raise TimeoutError()
        return 7

    async def lookup(scope, key):
        return receipts.get((scope, key))

    port.import_if_absent.side_effect = apply
    port.import_receipt.side_effect = lookup
    assert await app.resume_import(a, plans[0], actor_id=3) == 7
    with pytest.raises(TimeoutError):
        await app.resume_import(b, plans[2], actor_id=3)
    assert await app.resume_import(b, plans[2], actor_id=3) == 7
    assert await app.resume_import(a, plans[0], actor_id=3) == 7
    assert port.import_if_absent.await_count == 2
    for library in (2, 3):
        with pytest.raises(PermissionError):
            await app.freeze_template(b, library, request_key="bad", actor_id=3)


async def test_external_batch_precheck_has_no_vocabulary_or_relation_effect(store):
    from bisheng.knowledge.application.provider_tags import TagScope

    scope = TagScope(7, 8, 1)
    port = AsyncMock()
    app = svc(store, port)
    app.authorize.side_effect = lambda s, action, file: file != 23
    assert await app.precheck_append(scope, [22, 23, 22], [], new_names=["new"]) == ((22,), (23,))
    assert not port.mock_calls
