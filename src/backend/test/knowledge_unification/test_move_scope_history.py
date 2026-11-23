"""T951: real historical-file paths choose one complete-document destination."""

from collections import Counter
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.move_scope_repository import MoveRoot, MoveScopeRepository
from bisheng.permission.domain.models.grant import ResourcePermissionMode
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionRepository
from test.knowledge_unification import test_kn_space_web_link_wiring as web_fixtures
from test.knowledge_unification import test_move_scope_repository as fixtures

store, tenant, moving = fixtures.store, fixtures.tenant, fixtures.moving
business, admission = web_fixtures.business, web_fixtures.admission
processing, application, files = web_fixtures.processing, web_fixtures.application, web_fixtures.files
legacy, upload, web = web_fixtures.legacy, web_fixtures.upload, web_fixtures.web


def parent_mode(key, path, *, kind="knowledge_file", space=10):
    parent = path.rsplit("/", 1)[-1] if path else str(space)
    return ResourcePermissionMode(
        id=key,
        tenant_id=101,
        resource_type=kind,
        resource_id=str(key),
        mode="INHERIT",
        parent_type="folder" if path else "knowledge_space",
        parent_id=parent,
        version=4,
        projection_state="CURRENT",
    )


def history_shape(moving, paths, *, primary=""):
    with Session(moving.sync) as session:
        for key, path in ((52, "/50"), (53, "/50"), (60, "")):
            session.add(
                KnowledgeFile(
                    id=key,
                    tenant_id=101,
                    knowledge_id=10,
                    file_type=0,
                    file_name=str(key),
                    file_level_path=path,
                    level=bool(path),
                )
            )
            session.add(parent_mode(key, path, kind="folder"))
        document = session.get(KnowledgeDocument, 80)
        document.file_level_path, document.level = primary, primary.count("/")
        for key, path in {81: primary, **paths}.items():
            row = session.get(KnowledgeFile, key)
            if row is None:
                row = KnowledgeFile(id=key, tenant_id=101, knowledge_id=10, file_name=f"history-{key}", status=3)
                session.add(row)
                session.add(
                    KnowledgeDocumentVersion(id=100 + key, document_id=80, knowledge_file_id=key, version_no=key - 80)
                )
                session.add(parent_mode(key, path))
            else:
                mode = session.get(ResourcePermissionMode, key)
                mode.parent_type = "folder" if path else "knowledge_space"
                mode.parent_id = path.rsplit("/", 1)[-1] if path else "10"
            row.file_level_path, row.level = path, path.count("/")
        session.commit()


@pytest.mark.parametrize("nested", [False, True])
async def test_folder_covered_history_carries_all_versions_to_its_unique_relative_destination(moving, nested):
    old_path = "/50/52" if nested else "/50"
    history_shape(moving, {82: old_path})
    writes = []

    def observe(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(moving.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with AsyncSession(moving.engine) as session:
            scope = await fixtures.load(moving, session)
    finally:
        event.remove(moving.engine.sync_engine, "before_cursor_execute", observe)
    expected = "/51" + old_path
    assert scope.documents[0].after["file_level_path"] == expected
    rows = {row.file_id: row for row in scope.files}
    assert rows[81].after["file_level_path"] == rows[82].after["file_level_path"] == expected
    assert [row["id"] for row in scope.versions] == [181, 182]
    assert rows[82].after["status"] == 7 and rows[82].before["object_name"] == rows[82].after["object_name"]
    assert not writes


async def test_same_history_candidate_is_deduplicated_and_external_history_is_not_another_candidate(moving):
    history_shape(moving, {82: "/50/52", 83: "/50/52", 84: "/60"})
    async with AsyncSession(moving.engine) as session:
        scope = await fixtures.load(moving, session)
    assert len(scope.leaves) == 4
    assert scope.documents[0].after["file_level_path"] == "/51/50/52"
    assert {row.after["file_level_path"] for row in scope.files if row.before["file_type"] == 1} == {"/51/50/52"}


async def test_different_history_destinations_are_a_conflict(moving):
    history_shape(moving, {82: "/50/52", 83: "/50/53"})
    async with AsyncSession(moving.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await fixtures.load(moving, session)


@pytest.mark.parametrize("priority", ["explicit_file", "logical_document"])
async def test_existing_explicit_file_and_logical_document_priorities_are_unchanged(moving, priority):
    primary = "/50/53" if priority == "logical_document" else ""
    history_shape(moving, {82: "/50/52", 83: "/50"}, primary=primary)
    roots = (MoveRoot("folder", 50), MoveRoot("file", 81))
    async with AsyncSession(moving.engine) as session:
        scope = await fixtures.load(moving, session, roots)
    expected = "/51/50/53" if priority == "logical_document" else "/51"
    assert scope.documents[0].after["file_level_path"] == expected
    assert {row.after["file_level_path"] for row in scope.files if row.before["file_type"] == 1} == {expected}


async def test_history_candidates_are_built_once_from_native_versions_not_once_per_document(moving, monkeypatch):
    with Session(moving.sync) as session:
        for n in range(201):
            doc, first, second = 1000 + n, 2000 + 2 * n, 2001 + 2 * n
            session.add(
                KnowledgeDocument(id=doc, knowledge_id=10, primary_version_id=5000 + 2 * n, file_level_path="", level=0)
            )
            for offset, file_id, path in ((0, first, ""), (1, second, "/50")):
                session.add(
                    KnowledgeFile(
                        id=file_id,
                        tenant_id=101,
                        knowledge_id=10,
                        file_name=str(file_id),
                        status=3,
                        file_level_path=path,
                        level=bool(path),
                    )
                )
                session.add(
                    KnowledgeDocumentVersion(
                        id=5000 + 2 * n + offset,
                        document_id=doc,
                        knowledge_file_id=file_id,
                        version_no=offset + 1,
                        is_primary=not offset,
                    )
                )
                session.add(parent_mode(file_id, path))
        session.commit()
    accesses = Counter()
    original = moving.repo._by_ids

    class CountedVersion(dict):
        def __getitem__(self, name):
            accesses[name] += 1
            return super().__getitem__(name)

    async def counted(*args, **kwargs):
        rows = await original(*args, **kwargs)
        return [CountedVersion(row) for row in rows] if args[1] is KnowledgeDocumentVersion else rows

    monkeypatch.setattr(moving.repo, "_by_ids", counted)
    async with AsyncSession(moving.engine) as session:
        scope = await fixtures.load(moving, session)
    assert len(scope.documents) == 202 and len(scope.versions) == 404
    assert accesses["document_id"] < 20 * len(scope.versions)


async def test_real_web_overwrite_history_is_movable_as_a_folder_after_processing_settles(web, monkeypatch):
    context = web.upload.context
    with context.sync.begin() as connection:
        TagLink.__table__.create(connection, checkfirst=True)
        ResourcePermissionMode.__table__.create(connection, checkfirst=True)
    async with context.sessions() as session:
        session.add(
            KnowledgeFile(
                id=55,
                tenant_id=101,
                knowledge_id=40,
                file_type=0,
                file_name="Web folder",
                file_level_path="",
                level=0,
                status=2,
                user_id=7,
            )
        )
        (await session.get(KnowledgeFile, 82)).md5 = web.result.content_hash
        await session.commit()
    # Only the parent projection transport is isolated; dedup, loader and SQL
    # overwrite remain the actual producer. Scope consumes its persisted paths.
    monkeypatch.setattr(web.upload.service, "_replace_resource_parent_tuple", AsyncMock())
    result = await web.upload.service.import_web_link(40, "https://example.test/start", parent_id=55, overwrite=True)
    assert result.id == 82 and result.file_level_path == "/55"
    repo = MoveScopeRepository(parent_states=MoveProjectionRepository(environment="test"))

    async def scope(session):
        return await repo.aload_scope(
            session,
            source_space_id=40,
            destination_space_id=11,
            roots=(MoveRoot("folder", 55),),
            destination_folder_id=None,
        )

    async with context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).file_level_path in (None, "")
        assert (await session.get(KnowledgeDocument, 80)).file_level_path in (None, "")
        assert (await session.get(KnowledgeFile, 82)).status == KnowledgeFileStatus.WAITING.value
        with pytest.raises(KnowledgeProcessingConflictError):
            await scope(session)
        # Parser completion is the explicit boundary here. No parser/provider IO
        # runs in this native scope test; the existing failed state participates
        # in logical movement and retains its original non-success status.
        (await session.get(KnowledgeFile, 82)).status = 3
        for key, path, kind in ((55, "", "folder"), (81, "", "knowledge_file"), (82, "/55", "knowledge_file")):
            session.add(parent_mode(key, path, kind=kind, space=40))
        await session.commit()
    async with context.sessions() as session:
        actual = await scope(session)
        assert {leaf.target.file_id for leaf in actual.leaves} == {81, 82}
        assert actual.documents[0].after["file_level_path"] == "/55"
        assert actual.documents[0].after["primary_version_id"] == 181
        assert next(row for row in actual.files if row.file_id == 82).after["status"] == 3
