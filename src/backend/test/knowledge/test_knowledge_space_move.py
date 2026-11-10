"""F034 — KnowledgeSpaceService.move_items unit tests (same-space + cross-space).

Strategy: DB-backed (async_db_session) for the validation matrix + same-space
cascade + cross-space version-chain effects; the permission boundary
(``_get_effective_actions``), the cross-space migrate dispatch, and tag I/O
are patched. See features/v2.6.0/034-knowledge-space-file-move/design.md.
"""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationConfirmationRequiredError,
    KnowledgeOperationPlanConflictError,
)
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from test.knowledge_unification import test_legacy_move_composition as native

FILE = 1
DIR = 0

_SVC = "bisheng.knowledge.domain.services.knowledge_space_service"


store, tenant, moving, accepted, application = (
    native.store,
    native.tenant,
    native.moving,
    native.accepted,
    native.application,
)
legacy_move = native.legacy_move
actual_processing_task, job_tenant = native.base.actual_processing_task, native.base.job_tenant


@pytest.fixture
async def async_db_session(legacy_move):
    async with legacy_move.app.built.sessions() as session:
        yield session


# ── seeding helpers ────────────────────────────────────────────────────────


async def _seed_spaces(session):
    """Two spaces in tenant 1, one space in tenant 2 (for the tenant-mismatch case)."""
    session.add(
        Knowledge(
            id=1, name="A", type=3, user_id=7, tenant_id=101, model="11", index_name="idx1", collection_name="col1"
        )
    )
    session.add(
        Knowledge(
            id=2, name="B", type=3, user_id=7, tenant_id=101, model="11", index_name="idx2", collection_name="col2"
        )
    )
    session.add(Knowledge(id=9, name="OtherTenant", type=3, user_id=7, tenant_id=2))
    await session.commit()


async def _add(session, legacy_move, *, registered=True, **kw):
    kw.setdefault("status", KnowledgeFileStatus.SUCCESS.value)
    kw.setdefault("user_id", 7)
    kw.setdefault("tenant_id", 101)
    path = tuple(int(value) for value in (kw.get("file_level_path") or "").split("/") if value)
    for depth, ident in enumerate(path):
        if await session.get(KnowledgeFile, ident) is None:
            await _add(
                session,
                legacy_move,
                id=ident,
                knowledge_id=kw["knowledge_id"],
                file_type=DIR,
                file_name=f"ancestor-{ident}",
                level=depth,
                file_level_path="/" + "/".join(map(str, path[:depth])) if depth else "",
            )
    f = KnowledgeFile(**kw)
    session.add(f)
    await session.commit()
    await session.refresh(f)
    await native.add_mode(session, f, legacy_move)
    if registered and f.file_type == FILE:
        session.add(
            KnowledgeDocument(
                id=200000 + f.id,
                knowledge_id=f.knowledge_id,
                primary_version_id=100000 + f.id,
                file_level_path=f.file_level_path,
                level=f.level,
            )
        )
        session.add(
            KnowledgeDocumentVersion(
                id=100000 + f.id,
                document_id=200000 + f.id,
                knowledge_file_id=f.id,
                version_no=1,
                is_primary=True,
            )
        )
        await session.commit()
    return f


def _svc(legacy_move):
    return native.service(legacy_move)


# ── same-space: happy path + cascade ───────────────────────────────────────


@pytest.mark.asyncio
async def test_same_space_move_file_updates_path_and_parent_tuple(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=20,
        knowledge_id=1,
        file_name="a.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    res = await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=1, target_folder_id=10)

    assert [m["id"] for m in res["moved"]] == [20]
    assert res["moved"][0]["cross_space"] is False
    fresh = await async_db_session.get(KnowledgeFile, 20)
    assert fresh.file_level_path == "/10"
    assert fresh.level == 1
    assert fresh.knowledge_id == 1  # same space
    assert legacy_move.app.built.bridge.components.projection._fga.calls
    svc._dispatch_knowledge_chat_rehome.assert_not_called()


@pytest.mark.asyncio
async def test_same_space_move_folder_cascades_subtree(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    # dst (id=10) at root; src folder (id=30) at root with child file (id=31) and sub-folder (id=32)
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=30,
        knowledge_id=1,
        file_name="src",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=31,
        knowledge_id=1,
        file_name="c.pdf",
        file_type=FILE,
        level=1,
        file_level_path="/30",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=32,
        knowledge_id=1,
        file_name="sub",
        file_type=DIR,
        level=1,
        file_level_path="/30",
    )

    svc = _svc(legacy_move)
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
async def test_invalid_reasons_into_self_subtree_current_parent(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    # src folder 30 at root; sub-folder 32 under 30
    await _add(
        async_db_session,
        legacy_move,
        id=30,
        knowledge_id=1,
        file_name="src",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=32,
        knowledge_id=1,
        file_name="sub",
        file_type=DIR,
        level=1,
        file_level_path="/30",
    )

    svc = _svc(legacy_move)
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
async def test_invalid_depth_exceeded_empty_folder(async_db_session, legacy_move):
    """Depth counts FOLDER layers (UI 第1层 = level 0 ⇒ deepest folder level 9):
    even an EMPTY folder moved into a deepest-level folder must be rejected.
    """
    await _seed_spaces(async_db_session)
    # target folder at level 9 = 第10层 (deepest allowed); a folder moved under it → level 10
    await _add(
        async_db_session,
        legacy_move,
        id=40,
        knowledge_id=1,
        file_name="deep",
        file_type=DIR,
        level=9,
        file_level_path="/1/2/3/4/5/6/7/8/9",
    )
    await _add(
        async_db_session, legacy_move, id=41, knowledge_id=1, file_name="mv", file_type=DIR, level=0, file_level_path=""
    )

    svc = _svc(legacy_move)
    res = await svc.move_items(1, [{"id": 41, "type": "folder"}], target_space_id=1, target_folder_id=40)
    assert res["invalid"][0]["reason"] == "depth_exceeded"


@pytest.mark.asyncio
async def test_file_into_deepest_folder_allowed(async_db_session, legacy_move):
    """Files don't count as a layer: moving a FILE into a 第10层 (level 9)
    folder is allowed even though the file lands at level 10.
    """
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=40,
        knowledge_id=1,
        file_name="deep",
        file_type=DIR,
        level=9,
        file_level_path="/1/2/3/4/5/6/7/8/9",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=42,
        knowledge_id=1,
        file_name="f.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    res = await svc.move_items(1, [{"id": 42, "type": "file"}], target_space_id=1, target_folder_id=40)
    assert res["invalid"] == []
    assert res["moved"][0]["id"] == 42


@pytest.mark.asyncio
async def test_depth_ignores_files_in_subtree(async_db_session, legacy_move):
    """A folder whose deepest node is a FILE is limited by its folders only:
    moving it so its deepest folder lands exactly at level 9 is allowed,
    even though the file inside lands at level 10.
    """
    await _seed_spaces(async_db_session)
    # target at level 8 = 第9层
    await _add(
        async_db_session,
        legacy_move,
        id=40,
        knowledge_id=1,
        file_name="deep",
        file_type=DIR,
        level=8,
        file_level_path="/1/2/3/4/5/6/7/8",
    )
    await _add(
        async_db_session, legacy_move, id=41, knowledge_id=1, file_name="mv", file_type=DIR, level=0, file_level_path=""
    )
    await _add(
        async_db_session,
        legacy_move,
        id=43,
        knowledge_id=1,
        file_name="in.pdf",
        file_type=FILE,
        level=1,
        file_level_path="/41",
    )

    svc = _svc(legacy_move)
    res = await svc.move_items(1, [{"id": 41, "type": "folder"}], target_space_id=1, target_folder_id=40)
    assert res["invalid"] == []
    assert {m["id"] for m in res["moved"]} == {41}


@pytest.mark.asyncio
async def test_invalid_name_conflict_folder_same_dir(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    # dst folder 10 already contains a folder named "dup"; moving another "dup" into it → conflict
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=11,
        knowledge_id=1,
        file_name="dup",
        file_type=DIR,
        level=1,
        file_level_path="/10",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=12,
        knowledge_id=1,
        file_name="dup",
        file_type=DIR,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    res = await svc.move_items(1, [{"id": 12, "type": "folder"}], target_space_id=1, target_folder_id=10)
    assert res["invalid"][0]["reason"] == "name_conflict"


@pytest.mark.asyncio
async def test_cross_space_folder_name_conflict_rejected(async_db_session, legacy_move):
    """AC-12 (2026-06-11): cross-space FOLDER move also checks same-level folder
    name conflict in the TARGET space."""
    await _seed_spaces(async_db_session)
    # target space 2: folder "dst"(200) already contains folder "dup"(201)
    await _add(
        async_db_session,
        legacy_move,
        id=200,
        knowledge_id=2,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=201,
        knowledge_id=2,
        file_name="dup",
        file_type=DIR,
        level=1,
        file_level_path="/200",
    )
    # source space 1: folder "dup"(202) being moved into space-2 folder 200
    await _add(
        async_db_session,
        legacy_move,
        id=202,
        knowledge_id=1,
        file_name="dup",
        file_type=DIR,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    res = await svc.aprecheck_move(
        1, FileMoveReq(items=[{"id": 202, "type": "folder"}], target_space_id=2, target_folder_id=200)
    )
    assert res.invalid_items[0].reason == "name_conflict"
    assert not res.can_execute and res.valid_items == []


@pytest.mark.asyncio
async def test_cross_space_file_name_conflict_allowed(
    async_db_session, legacy_move, monkeypatch, actual_processing_task
):
    """AC-12 (2026-06-11): FILES are never name-checked on move — a same-named
    file in the target space does NOT block a cross-space file move."""
    await _seed_spaces(async_db_session)
    # target space 2 root already has a file "f.pdf"(300)
    await _add(
        async_db_session,
        legacy_move,
        id=300,
        knowledge_id=2,
        file_name="f.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )
    # source space 1 has same-named file "f.pdf"(301)
    await _add(
        async_db_session,
        legacy_move,
        registered=False,
        id=301,
        knowledge_id=1,
        file_name="f.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )
    doc = KnowledgeDocument(knowledge_id=1, file_level_path="")
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)
    async_db_session.add(
        KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=301, version_no=1, is_primary=True)
    )
    await async_db_session.flush()
    doc.primary_version_id = (
        await async_db_session.exec(
            native.sa.select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.document_id == doc.id, KnowledgeDocumentVersion.is_primary.is_(True)
            )
        )
    ).one()[0]
    await async_db_session.commit()

    svc = _svc(legacy_move)
    with pytest.raises(KnowledgeOperationConfirmationRequiredError):
        await svc.move_items(1, [{"id": 301, "type": "file"}], target_space_id=2)
    plan = await svc.aprecheck_move(1, FileMoveReq(items=[{"id": 301, "type": "file"}], target_space_id=2))
    assert plan.invalid_items == [] and plan.can_execute
    result = await svc.aconfirm_move(1, native.confirmation(plan))
    assert result.state == "accepted"  # accepting the operation has not moved a File
    async_db_session.expire_all()
    assert (await async_db_session.get(KnowledgeFile, 301)).knowledge_id == 1
    await async_db_session.rollback()
    await native.run_accepted(legacy_move, result, monkeypatch)
    assert (await async_db_session.get(KnowledgeFile, 301)).knowledge_id == 2
    svc._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=1,
        source_flow_ids=["space_1_file_301"],
        reason="cross_space_move",
    )


@pytest.mark.asyncio
async def test_no_permission_blocks_item(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=20,
        knowledge_id=1,
        file_name="a.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    # upload_file present so the target check (#5) passes; no move_file on the
    # item → it's rejected with no_permission by the per-item gate.
    svc._get_effective_actions = AsyncMock(return_value={"upload_file"})
    res = await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=1, target_folder_id=10)
    assert res["moved"] == []
    assert res["invalid"][0]["reason"] == "no_permission"


@pytest.mark.asyncio
async def test_skip_invalid_two_step(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=20,
        knowledge_id=1,
        file_name="a.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )
    # 30 = folder moved into itself → invalid
    await _add(
        async_db_session,
        legacy_move,
        id=30,
        knowledge_id=1,
        file_name="src",
        file_type=DIR,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
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
    await async_db_session.rollback()
    svc2 = _svc(legacy_move)
    r2 = await svc2.move_items(
        1,
        [{"id": 20, "type": "file"}, {"id": 30, "type": "folder"}],
        target_space_id=10 and 1,  # space 1
        target_folder_id=30,
        skip_invalid=True,
    )
    assert r2["moved"] == []  # bare skip=True is not an immutable confirmation
    confirmation = native.confirmation(r2)
    await async_db_session.rollback()
    r2 = await svc2.aconfirm_move(1, confirmation)
    assert any(m["id"] == 20 for m in r2["moved"])
    assert any(iv["id"] == 30 for iv in r2["invalid"])


# ── cross-space ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_space_moves_version_chain_clears_tags_sets_rebuilding(
    async_db_session, legacy_move, monkeypatch, actual_processing_task
):
    await _seed_spaces(async_db_session)
    # version chain in space 1: primary file 100 + history file 101 under one document
    await _add(
        async_db_session,
        legacy_move,
        registered=False,
        id=100,
        knowledge_id=1,
        file_name="v2.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        registered=False,
        id=101,
        knowledge_id=1,
        file_name="v1.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
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
    await async_db_session.flush()
    doc.primary_version_id = (
        await async_db_session.exec(
            native.sa.select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.document_id == doc.id, KnowledgeDocumentVersion.is_primary.is_(True)
            )
        )
    ).one()[0]
    await async_db_session.commit()

    async_db_session.add_all(
        [
            TagLink(
                id=100, tenant_id=101, tag_id=1, resource_id="100", resource_type=ResourceTypeEnum.SPACE_FILE.value
            ),
            TagLink(
                id=101, tenant_id=101, tag_id=1, resource_id="101", resource_type=ResourceTypeEnum.SPACE_FILE.value
            ),
        ]
    )
    await async_db_session.commit()
    svc = _svc(legacy_move)
    plan = await svc.aprecheck_move(1, FileMoveReq(items=[{"id": 100, "type": "file"}], target_space_id=2))
    result = await svc.aconfirm_move(1, native.confirmation(plan))
    assert result.state == "accepted"
    async with legacy_move.app.built.sessions() as session:
        revision = (await session.get(native.base.Job, result.job_id)).revision
    lease = await legacy_move.app.owner.astart_attempt(result.job_id, expected_dispatch_revision=revision)
    assert lease is not None
    assert (await legacy_move.app.owner.aensure_logical(lease)).state == "running"
    doc_id = doc.id
    async_db_session.expire_all()
    f100, f101 = await async_db_session.get(KnowledgeFile, 100), await async_db_session.get(KnowledgeFile, 101)
    assert f100.knowledge_id == f101.knowledge_id == 2
    assert f100.status == f101.status == KnowledgeFileStatus.REBUILDING.value
    assert (await async_db_session.get(KnowledgeDocument, doc_id)).knowledge_id == 2
    assert not (await async_db_session.execute(native.sa.select(TagLink))).scalars().all()
    items = (await async_db_session.execute(native.sa.select(KnowledgeProcessingItem))).scalars().all()
    assert {row.file_id for row in items} == {100, 101}
    await async_db_session.rollback()
    # Expire the first lease so the original task resumes that real logical move.
    async with legacy_move.app.built.sessions() as session, session.begin():
        job = await session.get(native.base.Job, result.job_id)
        job.lease_until = legacy_move.app.built.clock[0]
    await native.run_accepted(legacy_move, result, monkeypatch)
    async_db_session.expire_all()
    assert (await async_db_session.get(KnowledgeFile, 100)).status == KnowledgeFileStatus.SUCCESS.value
    assert (await async_db_session.get(KnowledgeFile, 101)).status == KnowledgeFileStatus.SUCCESS.value
    items = (await async_db_session.execute(native.sa.select(KnowledgeProcessingItem))).scalars().all()
    assert all(row.state == "succeeded" and row.source_cleaned for row in items)
    svc._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=1,
        source_flow_ids=["space_1_file_100", "space_1_file_101"],
        reason="cross_space_move",
    )


@pytest.mark.asyncio
async def test_cross_space_cross_tenant_rejected(async_db_session, legacy_move):
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=20,
        knowledge_id=1,
        file_name="a.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )
    svc = _svc(legacy_move)
    with pytest.raises(KnowledgeOperationPlanConflictError) as denied:
        await svc.aprecheck_move(1, FileMoveReq(items=[{"id": 20, "type": "file"}], target_space_id=9))
    assert denied.value.kwargs["reason"] == "move_batch_space_missing"


@pytest.mark.asyncio
async def test_cross_space_folder_name_conflict_at_target_root_null_path(async_db_session, legacy_move):
    """#2 fix: a same-name folder at the TARGET space root must be detected even
    when its file_level_path is NULL (historical rows), not "". Without root-path
    normalisation NULL == "" is false in SQL and the dup check silently passes."""
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=210,
        knowledge_id=2,
        file_name="dup",
        file_type=DIR,
        level=0,
        file_level_path=None,
    )
    await _add(
        async_db_session,
        legacy_move,
        id=211,
        knowledge_id=1,
        file_name="dup",
        file_type=DIR,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    res = await svc.aprecheck_move(1, FileMoveReq(items=[{"id": 211, "type": "folder"}], target_space_id=2))
    assert res.invalid_items[0].reason == "name_conflict"
    assert not res.can_execute and res.valid_items == []


@pytest.mark.asyncio
async def test_move_rejected_without_upload_file_on_target(async_db_session, legacy_move):
    """#5 (decision-8 reversal): moving into a target the user has no upload_file
    on is rejected server-side. The target check runs before per-item checks, so
    a missing upload_file raises outright."""
    await _seed_spaces(async_db_session)
    await _add(
        async_db_session,
        legacy_move,
        id=10,
        knowledge_id=1,
        file_name="dst",
        file_type=DIR,
        level=0,
        file_level_path="",
    )
    await _add(
        async_db_session,
        legacy_move,
        id=20,
        knowledge_id=1,
        file_name="a.pdf",
        file_type=FILE,
        level=0,
        file_level_path="",
    )

    svc = _svc(legacy_move)
    svc._get_effective_actions = AsyncMock(return_value={"move"})
    with pytest.raises(SpacePermissionDeniedError):
        await svc.move_items(1, [{"id": 20, "type": "file"}], target_space_id=1, target_folder_id=10)
