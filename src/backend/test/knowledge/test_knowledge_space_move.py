"""F034 — KnowledgeSpaceService.move_items unit tests (same-space + cross-space).

Strategy: DB-backed (async_db_session) for the validation matrix + same-space
cascade + cross-space version-chain effects; the permission boundary
(_get_effective_permission_ids), the cross-space migrate dispatch, and tag I/O
are patched. See features/v2.6.0/034-knowledge-space-file-move/design.md.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceTenantMismatchError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

FILE = 1
DIR = 0

_SVC = "bisheng.knowledge.domain.services.knowledge_space_service"


@pytest.fixture(autouse=True)
def _wire_service_db(async_db_session):
    """Route the service's `async with get_async_db_session()` block to the test
    in-memory session, and stub the post-commit KnowledgeDao update (it opens its
    own session). See test_add_file_creates_document_v1 for the pattern.
    """

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    with (
        patch(f"{_SVC}.get_async_db_session", new=_ctx),
        patch(f"{_SVC}.KnowledgeDao.async_update_knowledge_update_time_by_id", new_callable=AsyncMock),
    ):
        yield


# ── seeding helpers ────────────────────────────────────────────────────────


async def _seed_spaces(session):
    """Two spaces in tenant 1, one space in tenant 2 (for the tenant-mismatch case)."""
    session.add(Knowledge(id=1, name="A", type=3, user_id=1, tenant_id=1))
    session.add(Knowledge(id=2, name="B", type=3, user_id=1, tenant_id=1, model="m2"))
    session.add(Knowledge(id=9, name="OtherTenant", type=3, user_id=1, tenant_id=2))
    await session.commit()


async def _add(session, **kw):
    kw.setdefault("status", KnowledgeFileStatus.SUCCESS.value)
    kw.setdefault("user_id", 1)
    f = KnowledgeFile(**kw)
    session.add(f)
    await session.commit()
    await session.refresh(f)
    return f


def _svc():
    svc = KnowledgeSpaceService(request=MagicMock(), login_user=MagicMock(user_id=1, user_name="u1", tenant_id=1))
    # Grant everything by default; individual tests override.
    svc._get_effective_permission_ids = AsyncMock(
        return_value={"view_space", "move_file", "move_folder", "upload_file"}
    )
    svc._require_read_permission = AsyncMock(return_value=MagicMock(id=1, tenant_id=1))
    svc._replace_resource_parent_tuple = AsyncMock(return_value=None)
    svc._ensure_space_async_task_tenant_consistency = MagicMock(return_value=None)
    return svc


# ── same-space: happy path + cascade ───────────────────────────────────────


@pytest.mark.asyncio
async def test_same_space_move_file_updates_path_and_parent_tuple(async_db_session):
    await _seed_spaces(async_db_session)
    await _add(async_db_session, id=10, knowledge_id=1, file_name="dst", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=20, knowledge_id=1, file_name="a.pdf", file_type=FILE, level=0, file_level_path="")

    svc = _svc()
    res = await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=1, target_folder_id=10)

    assert [m["id"] for m in res["moved"]] == [20]
    assert res["moved"][0]["cross_space"] is False
    fresh = await async_db_session.get(KnowledgeFile, 20)
    assert fresh.file_level_path == "/10"
    assert fresh.level == 1
    assert fresh.knowledge_id == 1  # same space
    svc._replace_resource_parent_tuple.assert_awaited()


@pytest.mark.asyncio
async def test_same_space_move_folder_cascades_subtree(async_db_session):
    await _seed_spaces(async_db_session)
    # dst (id=10) at root; src folder (id=30) at root with child file (id=31) and sub-folder (id=32)
    await _add(async_db_session, id=10, knowledge_id=1, file_name="dst", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=30, knowledge_id=1, file_name="src", file_type=DIR, level=0, file_level_path="")
    await _add(
        async_db_session, id=31, knowledge_id=1, file_name="c.pdf", file_type=FILE, level=1, file_level_path="/30"
    )
    await _add(async_db_session, id=32, knowledge_id=1, file_name="sub", file_type=DIR, level=1, file_level_path="/30")

    svc = _svc()
    res = await svc.move_items(1, [{"id": 30, "type": "folder"}], target_space_id=1, target_folder_id=10)

    assert [m["id"] for m in res["moved"]] == [30]
    src = await async_db_session.get(KnowledgeFile, 30)
    child = await async_db_session.get(KnowledgeFile, 31)
    sub = await async_db_session.get(KnowledgeFile, 32)
    assert src.file_level_path == "/10" and src.level == 1
    assert child.file_level_path == "/10/30" and child.level == 2
    assert sub.file_level_path == "/10/30" and sub.level == 2


# ── validation matrix ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_reasons_into_self_subtree_current_parent(async_db_session):
    await _seed_spaces(async_db_session)
    # src folder 30 at root; sub-folder 32 under 30
    await _add(async_db_session, id=30, knowledge_id=1, file_name="src", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=32, knowledge_id=1, file_name="sub", file_type=DIR, level=1, file_level_path="/30")

    svc = _svc()
    # into_self: move 30 into 30
    r1 = await svc.move_items(1, [{"id": 30, "type": "folder"}], target_space_id=1, target_folder_id=30)
    assert r1["invalid"][0]["reason"] == "into_self"
    # into_subtree: move 30 into its child 32
    r2 = await svc.move_items(1, [{"id": 30, "type": "folder"}], target_space_id=1, target_folder_id=32)
    assert r2["invalid"][0]["reason"] == "into_subtree"
    # into_current_parent: move 30 (already at root) to root
    r3 = await svc.move_items(1, [{"id": 30, "type": "folder"}], target_space_id=1, target_folder_id=None)
    assert r3["invalid"][0]["reason"] == "into_current_parent"


@pytest.mark.asyncio
async def test_invalid_depth_exceeded(async_db_session):
    await _seed_spaces(async_db_session)
    # target folder at level 10 (deepest allowed); moving any folder under it → level 11
    await _add(
        async_db_session,
        id=40,
        knowledge_id=1,
        file_name="deep",
        file_type=DIR,
        level=10,
        file_level_path="/1/2/3/4/5/6/7/8/9",
    )
    await _add(async_db_session, id=41, knowledge_id=1, file_name="mv", file_type=DIR, level=0, file_level_path="")

    svc = _svc()
    res = await svc.move_items(1, [{"id": 41, "type": "folder"}], target_space_id=1, target_folder_id=40)
    assert res["invalid"][0]["reason"] == "depth_exceeded"


@pytest.mark.asyncio
async def test_invalid_name_conflict_folder_same_dir(async_db_session):
    await _seed_spaces(async_db_session)
    # dst folder 10 already contains a folder named "dup"; moving another "dup" into it → conflict
    await _add(async_db_session, id=10, knowledge_id=1, file_name="dst", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=11, knowledge_id=1, file_name="dup", file_type=DIR, level=1, file_level_path="/10")
    await _add(async_db_session, id=12, knowledge_id=1, file_name="dup", file_type=DIR, level=0, file_level_path="")

    svc = _svc()
    res = await svc.move_items(1, [{"id": 12, "type": "folder"}], target_space_id=1, target_folder_id=10)
    assert res["invalid"][0]["reason"] == "name_conflict"


@pytest.mark.asyncio
async def test_no_permission_blocks_item(async_db_session):
    await _seed_spaces(async_db_session)
    await _add(async_db_session, id=10, knowledge_id=1, file_name="dst", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=20, knowledge_id=1, file_name="a.pdf", file_type=FILE, level=0, file_level_path="")

    svc = _svc()
    svc._get_effective_permission_ids = AsyncMock(return_value={"view_space", "view_file"})  # no move_file
    res = await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=1, target_folder_id=10)
    assert res["moved"] == []
    assert res["invalid"][0]["reason"] == "no_permission"


@pytest.mark.asyncio
async def test_skip_invalid_two_step(async_db_session):
    await _seed_spaces(async_db_session)
    await _add(async_db_session, id=10, knowledge_id=1, file_name="dst", file_type=DIR, level=0, file_level_path="")
    await _add(async_db_session, id=20, knowledge_id=1, file_name="a.pdf", file_type=FILE, level=0, file_level_path="")
    # 30 = folder moved into itself → invalid
    await _add(async_db_session, id=30, knowledge_id=1, file_name="src", file_type=DIR, level=0, file_level_path="")

    svc = _svc()
    # skip_invalid=False + has invalid (30 into itself) → nothing committed
    r1 = await svc.move_items(
        1,
        [{"id": 20, "type": "file"}, {"id": 30, "type": "folder"}],
        target_space_id=1,
        target_folder_id=30,
        skip_invalid=False,
    )
    assert r1["moved"] == [] and r1["invalid"]
    f20 = await async_db_session.get(KnowledgeFile, 20)
    assert f20.file_level_path == ""  # untouched

    # skip_invalid=True → move the valid ones (20 into 10), report invalid (30)
    svc2 = _svc()
    r2 = await svc2.move_items(
        1,
        [{"id": 20, "type": "file"}, {"id": 30, "type": "folder"}],
        target_space_id=10 and 1,  # space 1
        target_folder_id=30,
        skip_invalid=True,
    )
    assert any(m["id"] == 20 for m in r2["moved"])
    assert any(iv["id"] == 30 for iv in r2["invalid"])


# ── cross-space ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_space_moves_version_chain_clears_tags_sets_rebuilding(async_db_session, monkeypatch):
    await _seed_spaces(async_db_session)
    # version chain in space 1: primary file 100 + history file 101 under one document
    await _add(
        async_db_session, id=100, knowledge_id=1, file_name="v2.pdf", file_type=FILE, level=0, file_level_path=""
    )
    await _add(
        async_db_session, id=101, knowledge_id=1, file_name="v1.pdf", file_type=FILE, level=0, file_level_path=""
    )
    doc = KnowledgeDocument(knowledge_id=1, file_level_path="")
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)
    async_db_session.add_all(
        [
            KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=2, is_primary=True),
            KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=1, is_primary=False),
        ]
    )
    await async_db_session.commit()

    cleared_tags, dispatched = [], []
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
        AsyncMock(side_effect=lambda *a, **k: cleared_tags.append(a)),
    )

    svc = _svc()
    # move_items reads the version chain directly via the (patched) session.
    svc._dispatch_cross_space_migration = AsyncMock(side_effect=lambda fid: dispatched.append(fid))

    res = await svc.move_items(1, [{"id": 100, "type": "file"}], target_space_id=2, target_folder_id=None)

    assert res["moved"][0]["cross_space"] is True
    # both primary + history moved to space 2
    f100 = await async_db_session.get(KnowledgeFile, 100)
    f101 = await async_db_session.get(KnowledgeFile, 101)
    assert f100.knowledge_id == 2 and f101.knowledge_id == 2
    assert f100.status == KnowledgeFileStatus.REBUILDING.value
    # document anchor moved too
    fresh_doc = await async_db_session.get(KnowledgeDocument, doc.id)
    assert fresh_doc.knowledge_id == 2
    # tags cleared + migration dispatched for both files
    assert {a[1] for a in cleared_tags} == {"100", "101"}
    assert set(dispatched) == {100, 101}


@pytest.mark.asyncio
async def test_cross_space_cross_tenant_rejected(async_db_session):
    await _seed_spaces(async_db_session)
    await _add(async_db_session, id=20, knowledge_id=1, file_name="a.pdf", file_type=FILE, level=0, file_level_path="")
    svc = _svc()
    with pytest.raises(SpaceTenantMismatchError):
        await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=9, target_folder_id=None)
