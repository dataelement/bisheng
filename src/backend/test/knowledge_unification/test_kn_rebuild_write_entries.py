"""T669 / AC-51: real write use cases reject before side effects on busy spaces."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError, VersionManagementDisabledError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.models import knowledge_file as knowledge_file_model
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq, FolderUploadItem
from bisheng.knowledge.domain.services import knowledge_space_service as spaces
from bisheng.knowledge.domain.services import knowledge_version_service as versions
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
from test.knowledge_unification import test_legacy_move_composition as move_native

store, tenant, moving, accepted, application = (
    move_native.store,
    move_native.tenant,
    move_native.moving,
    move_native.accepted,
    move_native.application,
)
legacy_move, busy_move = move_native.legacy_move, move_native.busy_move


@pytest.fixture
def concrete_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def writes(concrete_tenant, monkeypatch):
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    )
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [
        Knowledge.__table__,
        KnowledgeFile.__table__,
        KnowledgeDocument.__table__,
        KnowledgeDocumentVersion.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda active: SQLModel.metadata.create_all(active, tables=tables))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                Knowledge(id=19, tenant_id=101, user_id=7, name="busy", type=3, state=3),
                Knowledge(id=20, tenant_id=101, user_id=7, name="idle", type=3, state=1),
            ]
        )
        for space, prefix in [(19, 100), (20, 200)]:
            session.add_all(
                [
                    KnowledgeFile(
                        id=prefix + index,
                        tenant_id=101,
                        knowledge_id=space,
                        user_id=7,
                        file_name=f"{prefix + index}.txt",
                        file_type=1,
                        status=2,
                        md5=str(prefix + index),
                        file_level_path="",
                        level=0,
                    )
                    for index in (1, 2, 3)
                ]
            )
            session.add(
                KnowledgeFile(
                    id=prefix + 50,
                    tenant_id=101,
                    knowledge_id=space,
                    user_id=7,
                    file_name="folder",
                    file_type=0,
                    status=2,
                    file_level_path="",
                    level=0,
                )
            )
            session.add_all(
                [
                    KnowledgeDocument(
                        id=prefix + 400,
                        knowledge_id=space,
                        primary_version_id=prefix + 600,
                        file_level_path="",
                        level=0,
                    ),
                    KnowledgeDocument(
                        id=prefix + 401,
                        knowledge_id=space,
                        primary_version_id=prefix + 601,
                        file_level_path="",
                        level=0,
                    ),
                    KnowledgeDocumentVersion(
                        id=prefix + 600,
                        document_id=prefix + 400,
                        knowledge_file_id=prefix + 1,
                        version_no=1,
                        is_primary=True,
                    ),
                    KnowledgeDocumentVersion(
                        id=prefix + 601,
                        document_id=prefix + 401,
                        knowledge_file_id=prefix + 2,
                        version_no=1,
                        is_primary=True,
                    ),
                    KnowledgeDocumentVersion(
                        id=prefix + 602,
                        document_id=prefix + 400,
                        knowledge_file_id=prefix + 3,
                        version_no=2,
                        is_primary=False,
                    ),
                ]
            )
        await session.commit()

        @asynccontextmanager
        async def sessions():
            yield session

        monkeypatch.setattr(knowledge_model, "get_async_db_session", sessions)
        monkeypatch.setattr(knowledge_file_model, "get_async_db_session", sessions)
        monkeypatch.setattr(spaces, "get_async_db_session", sessions)
        monkeypatch.setattr(spaces.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
        user = UserPayload(user_id=7, tenant_id=101, user_name="owner", user_role=[])
        service = KnowledgeSpaceService(None, user)
        service._require_action = AsyncMock()
        service._require_read_permission = AsyncMock()
        service._initialize_child_resource_permissions = AsyncMock()
        service.upload_application_factory = MagicMock(side_effect=AssertionError("no app work while busy"))

        async def actions(kind, ident, **kwargs):
            return ["move"] if kind == "knowledge_file" else ["upload_file"]

        service._get_effective_actions = AsyncMock(side_effect=actions)
        service._replace_resource_parent_tuple = AsyncMock(side_effect=AssertionError("no move projection while busy"))
        process = MagicMock(side_effect=AssertionError("no object/file work while busy"))
        fetch = AsyncMock(side_effect=AssertionError("no external fetch while busy"))
        quota = AsyncMock(side_effect=AssertionError("no quota/object work while busy"))
        monkeypatch.setattr(spaces.KnowledgeService, "process_one_file", process)
        monkeypatch.setattr(spaces.KnowledgeService, "prepare_one_file", process)
        monkeypatch.setattr(spaces.KnowledgeWebLinkImportService, "fetch", fetch)
        monkeypatch.setattr(spaces.QuotaService, "get_knowledge_space_upload_limit_bytes", quota)
        monkeypatch.setattr(spaces.SpaceFileDao, "count_folder_by_name", AsyncMock(return_value=0))
        settings = SimpleNamespace(version_management=SimpleNamespace(enabled=True))
        monkeypatch.setattr(
            versions, "bisheng_settings", SimpleNamespace(async_get_knowledge=AsyncMock(return_value=settings))
        )
        version_service = KnowledgeVersionService(
            None,
            user,
            KnowledgeDocumentRepositoryImpl(session),
            KnowledgeDocumentVersionRepositoryImpl(session),
            KnowledgeFileRepositoryImpl(session),
        )
        from bisheng.knowledge.application.knowledge_version_mutation import KnowledgeVersionMutationApplication

        @asynccontextmanager
        async def fresh_version_sessions():
            async with AsyncSession(engine, expire_on_commit=False) as owned:
                yield owned

        version_service.version_mutation_application = KnowledgeVersionMutationApplication(
            session_factory=fresh_version_sessions,
            require_version_management_enabled=version_service._require_version_management_enabled,
        )
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service.KnowledgeAuditTelemetryService.audit_link_file_version",
            MagicMock(),
        )
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service.KnowledgeAuditTelemetryService.audit_set_primary_version",
            MagicMock(),
        )
        mutations = []

        def statement_seen(active, state, statement, parameters, context, many):
            if context.isinsert or context.isupdate or context.isdelete:
                mutations.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", statement_seen)
        yield SimpleNamespace(
            session=session,
            service=service,
            version=version_service,
            settings=settings,
            process=process,
            fetch=fetch,
            quota=quota,
            mutations=mutations,
        )
    await engine.dispose()


@pytest.mark.parametrize("entry", ["upload", "web", "folder"])
@pytest.mark.parametrize("transition_only", [False, True])
async def test_upload_entries_check_real_space_after_original_action_before_io(writes, entry, transition_only):
    if transition_only:
        row = await writes.session.get(Knowledge, 19)
        row.state, row.model_transition = 1, {"operation_id": "pending"}
        await writes.session.commit()
        writes.mutations.clear()
    with pytest.raises(KnowledgeProcessingConflictError) as failure:
        if entry == "upload":
            await writes.service.add_file(19, ["not-downloaded"])
        elif entry == "web":
            await writes.service.import_web_link(19, "https://must-not-fetch.invalid")
        else:
            await writes.service.upload_folder_items(
                19, [FolderUploadItem(file_path="not-downloaded", relative_path="new/a.txt", size=1)]
            )
    assert failure.value.Code == 10999
    writes.service._require_action.assert_awaited_once_with("knowledge_space", 19, "upload_file")
    writes.process.assert_not_called()
    writes.fetch.assert_not_awaited()
    writes.quota.assert_not_awaited()
    assert writes.mutations == []


async def test_original_upload_permission_denial_precedes_processing_state(writes):
    writes.service._require_action.side_effect = SpacePermissionDeniedError()
    with pytest.raises(SpacePermissionDeniedError):
        await writes.service.add_file(19, ["not-downloaded"])
    assert not writes.mutations
    writes.quota.assert_not_awaited()


@pytest.mark.parametrize("entry", ["link", "primary", "merge"])
async def test_real_version_chain_remains_unchanged_while_its_space_is_rebuilding(writes, entry):
    before = [
        (row.id, row.document_id, row.is_primary)
        for row in (await writes.session.exec(select(KnowledgeDocumentVersion))).all()
    ]
    with pytest.raises(KnowledgeProcessingConflictError) as failure:
        if entry == "link":
            await writes.version.link_file_to_document(102, 500)
        elif entry == "primary":
            await writes.version.set_primary_version(702)
        else:
            await writes.version.merge_source_document_into_current(101, 501)
    assert failure.value.Code == 10999 and writes.mutations == []
    after = [
        (row.id, row.document_id, row.is_primary)
        for row in (await writes.session.exec(select(KnowledgeDocumentVersion))).all()
    ]
    assert after == before


@pytest.mark.parametrize("entry", ["link", "primary", "merge"])
async def test_version_feature_switch_keeps_its_original_error_before_state_guard(writes, entry):
    writes.settings.version_management.enabled = False
    with pytest.raises(VersionManagementDisabledError):
        if entry == "link":
            await writes.version.link_file_to_document(102, 500)
        elif entry == "primary":
            await writes.version.set_primary_version(702)
        else:
            await writes.version.merge_source_document_into_current(101, 501)
    assert not writes.mutations


@pytest.mark.parametrize("source,target,folder", [(19, 20, None), (20, 19, None), (19, 19, 150)])
async def test_move_checks_real_source_and_destination_after_original_both_sided_actions(
    busy_move, source, target, folder
):
    writes = busy_move
    file_id = 101 if source == 19 else 201
    with pytest.raises(KnowledgeProcessingConflictError) as failure:
        await writes.service.aprecheck_move(
            source,
            FileMoveReq(items=[{"id": file_id, "type": "file"}], target_space_id=target, target_folder_id=folder),
        )
    assert failure.value.Code == 10999 and writes.mutations == []
    assert any(
        call.args[:2] == ("knowledge_file", file_id) for call in writes.service._get_effective_actions.await_args_list
    )
    writes.service._replace_resource_parent_tuple.assert_not_awaited()


async def test_move_without_original_source_action_keeps_original_invalid_item_result(busy_move):
    writes = busy_move
    writes.service._get_effective_actions.side_effect = lambda kind, ident, **kwargs: (
        ["upload_file"] if kind == "knowledge_space" else []
    )
    result = await writes.service.aprecheck_move(
        19, FileMoveReq(items=[{"id": 101, "type": "file"}], target_space_id=20)
    )
    assert not result.can_execute and result.valid_items == [] and result.invalid_items[0].reason == "no_permission"
    assert not writes.mutations


async def test_unrelated_idle_space_reaches_its_original_upload_path(writes):
    with pytest.raises(AssertionError, match="quota/object"):
        await writes.service.add_file(20, ["not-downloaded"])
    writes.quota.assert_awaited_once()


async def test_idle_space_still_preserves_history_when_linking_a_real_version(writes):
    result = await writes.version.link_file_to_document(202, 600)
    assert result.document_id == 600 and result.new_version_no == 3
    chain = await writes.version.version_repo.find_by_document_id(600)
    assert {row.knowledge_file_id for row in chain} == {201, 202, 203}
    assert [row.knowledge_file_id for row in chain if row.is_primary] == [202]


async def test_empty_folder_creation_does_not_gain_a_processing_block(writes):
    folder = await writes.service.add_folder(19, "new-empty-folder")
    assert folder.file_type == 0 and folder.knowledge_id == 19
    assert (await writes.session.get(Knowledge, 19)).state == 3
    writes.service._require_action.assert_awaited_once_with("knowledge_space", 19, "create_folder")


async def test_folder_rename_keeps_its_original_action_on_a_rebuilding_space(writes):
    folder = await writes.service.rename_folder(150, "renamed")
    assert folder.file_name == "renamed"
    writes.service._require_action.assert_awaited_once_with("folder", 150, "rename")


async def test_file_rename_keeps_its_original_action_on_a_rebuilding_space(writes, monkeypatch):
    from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_file_chunk

    dispatch = MagicMock()
    monkeypatch.setattr(rebuild_knowledge_file_chunk, "delay", dispatch)
    monkeypatch.setattr(spaces.SpaceFileDao, "count_file_by_name", AsyncMock(return_value=0))

    async def load_file(ident):
        return await writes.session.get(KnowledgeFile, ident)

    writes.service._get_file_for_action = AsyncMock(side_effect=load_file)
    file = await writes.service.rename_file(101, "renamed.txt")
    assert file.file_name == "renamed.txt"
    writes.service._require_action.assert_awaited_once_with("knowledge_file", 101, "rename")
    dispatch.assert_called_once_with(file_id=101)
