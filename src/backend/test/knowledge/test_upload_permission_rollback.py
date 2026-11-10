"""Root uploads and partial-batch compensation without external middleware."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, select

from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.knowledge_permission_service import F048KnowledgeFilePermissionAdapter
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.test_knowledge_space_service import _make_file, _make_login_user, _make_space
from test.knowledge_unification import test_kn_upload as native
from test.knowledge_unification.test_kn_model_bindings import state as model_state


@pytest.fixture
def upload(monkeypatch):
    service = module.KnowledgeSpaceService(None, _make_login_user())
    space = _make_space(space_id=348)
    space.tenant_id = 1
    files = [_make_file(file_id=i, knowledge_id=348) for i in (347, 348, 349)]
    for row in files:
        row.tenant_id = 1
        row.user_id = 7
        row.file_size = 1
        row.split_rule = module.FileProcessBase(knowledge_id=348).model_dump_json()
        row.object_name = f"original/{row.id}.txt"
    business = {row.id: row for row in files}
    permissions = {}
    events = []

    async def create(**kwargs):
        target = kwargs["target"]
        permissions[int(target.resource_id)] = target

    async def rollback(**kwargs):
        file_id = int(kwargs["target"].resource_id)
        events.append(("permission", file_id))
        permissions.pop(file_id, None)

    permission = SimpleNamespace(
        authorize_created=AsyncMock(side_effect=create), rollback_created=AsyncMock(side_effect=rollback)
    )
    adapter = F048KnowledgeFilePermissionAdapter(loader=None, permission=permission)
    monkeypatch.setattr(service, "_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(
        service, "_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=1))
    )
    monkeypatch.setattr(service, "_require_action", AsyncMock())
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    monkeypatch.setattr(module.SpaceFileDao, "get_user_total_file_size", AsyncMock(return_value=0))
    monkeypatch.setattr(module.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.QuotaService, "get_tenant_storage_remaining_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(module.KnowledgeService, "process_one_file", MagicMock(side_effect=files))
    monkeypatch.setattr(module.KnowledgeFileDao, "update", lambda row: row)
    monkeypatch.setattr(module.KnowledgeFileDao, "query_by_id", AsyncMock(side_effect=business.get))

    async def delete(ids):
        for file_id in ids:
            events.append(("business", file_id))
            business.pop(file_id, None)

    monkeypatch.setattr(module.KnowledgeFileDao, "adelete_batch", AsyncMock(side_effect=delete))
    storage = MagicMock()
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    from bisheng.worker.knowledge import scheduler

    dispatch = MagicMock()
    monkeypatch.setattr(scheduler, "enqueue_or_dispatch", dispatch)
    return SimpleNamespace(
        service=service,
        files=files,
        business=business,
        permissions=permissions,
        permission=permission,
        events=events,
        storage=storage,
        dispatch=dispatch,
    )


def _use_session(monkeypatch, session):
    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(module, "get_async_db_session", factory)


async def test_root_upload_with_matching_space_file_id(native_root_upload):
    case = native_root_upload
    result = await case.service.add_file(348, ["a", "b", "c"], parent_id=None)
    assert [row.id for row in result] == [347, 348, 349]
    assert all(row.tenant_id == 101 and row.knowledge_id == 348 for row in result)
    assert case.permissions[348].parent_type == "knowledge_space" and case.permissions[348].parent_id == "348"
    case.service._require_action.assert_awaited()
    assert all(
        call.args == ("knowledge_space", 348, "upload_file") for call in case.service._require_action.await_args_list
    )
    assert case.publish.call_count == 3 and case.prepared.call_count == 3
    case.permission.rollback_created.assert_not_awaited()
    async with case.context.sessions() as session:
        for row in result:
            version = (
                await session.exec(
                    select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == row.id)
                )
            ).one()
            document = await session.get(KnowledgeDocument, version.document_id)
            assert version.version_no == 1 and version.is_primary and document.primary_version_id == version.id
    assert len(case.objects) == 3


async def test_mid_batch_failure_cleans_initialized_and_uninitialized_files(native_root_upload):
    case = native_root_upload
    before, bindings_before = await case.rows(), model_state(case.context)
    create = case.permission.authorize_created.side_effect

    async def fail_second(**kwargs):
        await create(**kwargs)
        if kwargs["target"].resource_id == "348":
            raise RuntimeError("injected upload failure")

    case.permission.authorize_created.side_effect = fail_second
    with pytest.raises(RuntimeError, match="injected upload failure"):
        await case.service.add_file(348, ["a", "b", "c"])
    # Only the real two-item prefix was issued; the third item never existed.
    assert await case.rows() == before and model_state(case.context) == bindings_before
    assert not case.permissions and not case.objects
    assert case.prepared.call_count == case.permission.authorize_created.await_count == 2
    assert case.legacy.storage.put_object_sync.call_count == case.legacy.storage.remove_object_sync.call_count == 2
    assert case.permission.rollback_created.await_count == 2
    assert not any(ident == 349 for _, ident in case.events)
    case.publish.assert_not_called()
    for ident in (347, 348):
        assert (
            case.events.index(("permission", ident))
            < case.events.index(("sql-absent", ident))
            < case.events.index(("blob-remove", ident))
        )


async def test_cleanup_failure_retains_affected_business_row_and_continues(upload):
    rollback = upload.permission.rollback_created.side_effect

    async def fail_second(**kwargs):
        if kwargs["target"].resource_id == "348":
            raise RuntimeError("permission service unavailable")
        await rollback(**kwargs)

    upload.permission.rollback_created.side_effect = fail_second
    with pytest.raises(ExceptionGroup):
        await upload.service._rollback_uploaded_files(upload.files, parent_type="knowledge_space", parent_id=348)
    assert list(upload.business) == [348]
    assert upload.storage.remove_object_sync.call_count == 2


# Only the two actual add_file cases use this native Owner assembly. The old
# helper-compensation control above/below retains its existing isolated fixture.

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy = native.processing, native.application, native.files, native.legacy
native_upload = native.upload


@pytest.fixture
async def native_root_upload(native_upload, monkeypatch, tmp_path):
    case = native_upload
    context = case.context
    async with context.sessions() as session:
        await KnowledgeModelReferenceApplication.acreate(
            session,
            Knowledge(
                id=348,
                tenant_id=101,
                user_id=7,
                name="native upload",
                type=3,
                state=4,
                model="11",
                index_generation="g348",
            ),
            login_user=context.user,
            project_created=AsyncMock(),
        )
        # A real legal DIR establishes the native PK sequence. Root and File
        # namespaces may share 348; no client-supplied or mocked File ID is used.
        session.add(
            KnowledgeFile(
                id=346,
                tenant_id=101,
                knowledge_id=348,
                file_name="existing folder",
                file_type=0,
                status=2,
                level=0,
                file_level_path="",
            )
        )
        await session.commit()
    downloads = {}
    for name in ["a", "b", "c"]:
        path = tmp_path / (name + ".txt")
        path.write_text("actual unique " + name + " contents")
        downloads[name] = (str(path), name + ".txt")
    monkeypatch.setitem(
        case.legacy.cls.prepare_one_file.__func__.__globals__, "file_download", lambda path: downloads[path]
    )
    prepared = MagicMock(wraps=case.legacy.cls.prepare_one_file)
    monkeypatch.setattr(case.legacy.cls, "prepare_one_file", prepared)
    case.prepared = prepared
    case.permissions, case.objects, case.events = {}, set(), []
    case.permission = case.projection._permission

    async def create(**kwargs):
        target = kwargs["target"]
        ident = int(target.resource_id)
        assert target.tenant_id == 101 and target.resource_type == "knowledge_file"
        assert target.parent_type == "knowledge_space" and target.parent_id == "348"
        case.permissions[ident] = target
        case.events.append(("permission-create", ident))

    async def rollback(**kwargs):
        ident = int(kwargs["target"].resource_id)
        # Original SQL chain must still exist until the FGA rollback ACK.
        async with context.sessions() as session:
            assert await session.get(KnowledgeFile, ident) is not None
            assert (
                await session.exec(
                    select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == ident)
                )
            ).one()
        case.events.append(("permission", ident))
        case.permissions.pop(ident, None)

    case.permission.authorize_created.side_effect = create
    case.permission.rollback_created.side_effect = rollback

    def put(*, bucket_name, object_name, file):
        ident = int(object_name.rsplit("/", 1)[1].split(".", 1)[0])
        with Session(context.sync) as session:
            assert session.get(KnowledgeFile, ident) is not None
            version = session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == ident)
            ).one()
            assert session.get(KnowledgeDocument, version.document_id).primary_version_id == version.id
        case.objects.add(object_name)
        case.events.append(("blob-create", ident))

    def remove(*, bucket_name, object_name):
        ident = int(object_name.rsplit("/", 1)[1].split(".", 1)[0])
        assert ident not in case.permissions
        with Session(context.sync) as session:
            assert session.get(KnowledgeFile, ident) is None
            assert not session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == ident)
            ).all()
        case.events.append(("sql-absent", ident))
        case.objects.discard(object_name)
        case.events.append(("blob-remove", ident))

    case.legacy.storage.put_object_sync.side_effect = put
    case.legacy.storage.remove_object_sync.side_effect = remove

    async def rows():
        async with context.sessions() as session:
            result = []
            for model in (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
                result.append(tuple((await session.execute(select(model.__table__).order_by(model.id))).mappings()))
            return tuple(result)

    case.rows = rows
    return case
