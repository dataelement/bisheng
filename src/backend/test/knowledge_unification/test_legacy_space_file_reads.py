"""Flat legacy pages use real SQL primary facts and the original typed F048 checks."""

from datetime import datetime

import pytest

from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.application import legacy_files
from bisheng.knowledge.domain.models import knowledge_file as file_models
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.repositories import knowledge_compatibility_repository as compatibility
from bisheng.knowledge.domain.repositories.legacy_file_read_repository import LegacyFileReadRepository
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from test.knowledge_unification.test_legacy_document_permissions import real_targets as real_targets


@pytest.fixture
async def reads(real_targets, monkeypatch):
    sessions = compatibility.get_async_db_session
    async with sessions() as session:
        for model in (File, Document, Version, Tag, TagLink):
            await session.run_sync(lambda s, model=model: model.__table__.create(s.connection(), checkfirst=True))
        for ident in (81, 82, 83, 84):
            session.add(
                File(
                    id=ident,
                    knowledge_id=13,
                    tenant_id=101,
                    file_name=f"f{ident}.txt",
                    status=2,
                    user_id=7,
                    update_time=datetime(2026, 1, 1),
                    file_level_path="/90" if ident == 83 else "",
                )
            )
            session.add(
                Mode(
                    id=ident,
                    tenant_id=101,
                    resource_type="knowledge_file",
                    resource_id=str(ident),
                    mode="INHERIT",
                    version=1,
                    projection_state="CURRENT",
                )
            )
        session.add(Document(id=91, knowledge_id=13, primary_version_id=121))
        session.add(Version(id=121, document_id=91, knowledge_file_id=81, version_no=2, is_primary=True))
        session.add(Version(id=122, document_id=91, knowledge_file_id=82, version_no=1, is_primary=False))
        # A physical primary flag without the document's primary pointer is not current.
        session.add(Document(id=92, knowledge_id=13, primary_version_id=None))
        session.add(Version(id=124, document_id=92, knowledge_file_id=84, version_no=1, is_primary=True))
        await session.commit()
        root = await session.get(Knowledge, 13)
    monkeypatch.setattr(file_models, "get_async_db_session", sessions)
    monkeypatch.setattr(legacy_files, "LegacyFileReadRepository", lambda: LegacyFileReadRepository(sessions))
    from bisheng.knowledge.domain.services import knowledge_space_service

    async def adapter(kind):
        return real_targets.adapters[kind]

    monkeypatch.setattr(knowledge_space_service, "get_f048_resource_adapter", adapter)
    from bisheng.permission.application import control_state

    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    state = real_targets.adapters["knowledge_file"]._loader._versions._state
    state.permission_snapshots = control_state.SqlPermissionControlState().permission_snapshots

    async def visible(checks, consistency=None):
        real_targets.fga.calls.append(("batch", checks))
        return [row["object"].endswith((":13", ":81")) for row in checks]

    real_targets.fga.batch_check = visible
    return real_targets, sessions, root


async def decorate(_knowledge, rows):
    return [row.model_dump() for row in rows]


async def test_positive_primary_single_compatibility_and_visible_total(reads):
    context, sessions, root = reads
    candidates = await LegacyFileReadRepository(sessions).acandidates(space_id=13)
    assert [row.id for row in candidates] == [83, 81]
    owner = legacy_files.LegacyFilesApplication(request=None, identity=context.user)
    result, _writeable = await owner.alist(knowledge=root, decorate=decorate, page=1, page_size=1)
    page, total = result
    assert total == 1 and [row["id"] for row in page] == [81]
    (empty, total), _ = await owner.alist(knowledge=root, decorate=decorate, page=2, page_size=1)
    assert empty == [] and total == 1
    checks = [row for kind, batch in context.fga.calls if kind == "batch" for row in batch]
    assert any(row["object"].endswith(":83") for row in checks)
    assert all(not row["object"].endswith((":82", ":84")) for row in checks)


async def test_cursor_is_actor_space_filter_bound_and_does_not_repeat(reads):
    context, _sessions, root = reads
    owner = legacy_files.LegacyFilesApplication(request=None, identity=context.user)
    first, _ = await owner.alist(knowledge=root, decorate=decorate, use_cursor=True, page_size=1)
    assert [row["id"] for row in first.data] == [81] and first.has_more
    last, _ = await owner.alist(
        knowledge=root,
        decorate=decorate,
        use_cursor=True,
        page_size=1,
        cursor=first.next_cursor,
    )
    assert last.data == [] and not last.has_more
    from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError

    with pytest.raises(KnowledgeInvalidCursorError):
        await owner.alist(
            knowledge=root, decorate=decorate, use_cursor=True, keyword="changed", cursor=first.next_cursor
        )


async def test_native_cursor_budget_preserves_empty_nonterminal_page(reads):
    context, sessions, root = reads
    async with sessions() as session:
        session.add_all(
            File(id=ident, knowledge_id=13, tenant_id=101, file_name=f"hidden-{ident}", status=2)
            for ident in range(1000, 2001)
        )
        await session.commit()
    owner = legacy_files.LegacyFilesApplication(request=None, identity=context.user)
    first, _ = await owner.alist(knowledge=root, decorate=decorate, use_cursor=True, page_size=1)
    assert first.data == [] and first.has_more and first.next_cursor
    second, _ = await owner.alist(
        knowledge=root, decorate=decorate, use_cursor=True, page_size=1, cursor=first.next_cursor
    )
    assert [row["id"] for row in second.data] == [81]


async def test_native_foreign_row_and_bypass_never_enter_candidates(reads):
    from bisheng.common.errcode.permission import PermissionInvalidResourceError
    from bisheng.core.context.tenant import bypass_tenant_filter

    _context, sessions, _root = reads
    async with sessions() as session:
        session.add(File(id=999, knowledge_id=13, tenant_id=102, file_name="foreign", status=2))
        await session.commit()
    repo = LegacyFileReadRepository(sessions)
    assert [row.id for row in await repo.acandidates(space_id=13)] == [83, 81]
    with bypass_tenant_filter(), pytest.raises(PermissionInvalidResourceError):
        await repo.acandidates(space_id=13)


async def test_original_service_flat_list_decorates_space_tags_without_raw_total(reads, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from bisheng.database.models.group_resource import ResourceTypeEnum
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

    context, _sessions, _root = reads
    monkeypatch.setattr(KnowledgeService, "get_knowledge_files_title", Mock(return_value={}))
    tags = Mock(return_value={})
    monkeypatch.setattr(
        legacy_files.KnowledgeFileDao,
        "acount_file_by_filters",
        AsyncMock(side_effect=AssertionError("raw count would leak hidden files")),
    )
    from bisheng.database.models.tag import TagDao

    monkeypatch.setattr(TagDao, "get_tags_by_resource", tags)
    rows, total, _writeable = await KnowledgeService.aget_knowledge_files(None, context.user, 13)
    assert [row.id for row in rows] == [81] and total == 1
    assert tags.call_args.args[0] == ResourceTypeEnum.SPACE_FILE
