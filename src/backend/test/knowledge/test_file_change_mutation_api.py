from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
    FileChangeMutationResult,
    FileChangeRequestCommand,
)


@pytest_asyncio.fixture
async def footprint_engine():
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=[
                    KnowledgeFile.__table__,
                    KnowledgeDocument.__table__,
                    KnowledgeDocumentVersion.__table__,
                ],
            )
        )
    yield engine
    await engine.dispose()


def _mount_app(*, mutation_service, stage_service=None, owner_service=None) -> FastAPI:
    from bisheng.knowledge.api.dependencies import (
        get_knowledge_space_file_change_service,
        get_knowledge_space_service,
        get_knowledge_space_upload_stage_service,
    )
    from bisheng.knowledge.api.endpoints import knowledge, knowledge_space

    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(knowledge.router)
    api.include_router(knowledge_space.router)
    app.include_router(api)
    app.dependency_overrides[get_knowledge_space_file_change_service] = lambda: mutation_service
    if stage_service is not None:
        app.dependency_overrides[get_knowledge_space_upload_stage_service] = lambda: stage_service
    if owner_service is not None:
        app.dependency_overrides[get_knowledge_space_service] = lambda: owner_service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=7,
        user_name="applicant",
        tenant_id=42,
    )
    return app


def _mutation_service(*results: FileChangeMutationResult):
    service = SimpleNamespace()
    service.request_changes = AsyncMock(return_value=list(results))
    service.request_change = AsyncMock(side_effect=list(results))
    return service


def test_space_multipart_upload_keeps_legacy_contract_and_registers_temporary_stage(monkeypatch):
    from bisheng.knowledge.api.endpoints import knowledge as knowledge_endpoint
    from bisheng.role.domain.services.quota_service import QuotaService

    monkeypatch.setattr(QuotaService, "check_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(knowledge_endpoint, "validate_knowledge_upload_file_size", lambda *_args: None)
    stage = SimpleNamespace(
        upload_id="77d59a61-861b-46fc-8477-c15cb2d01f3d",
        space_id=101,
        file_name="report.pdf",
        file_size=3,
        content_hash="abc",
        state="uploaded",
        expire_at=datetime(2026, 9, 1, tzinfo=UTC),
        create_time=datetime(2026, 8, 11, tzinfo=UTC),
        object_name="knowledge-space-upload-stage/42/secret",
        tenant_id=42,
    )
    stage_service = SimpleNamespace(create_stage=AsyncMock(return_value=stage))
    owner = SimpleNamespace(authorize_upload_stage=AsyncMock())
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeService,
        "save_upload_file_original_name",
        AsyncMock(return_value="opaque-report.pdf"),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "save_uploaded_file",
        AsyncMock(return_value="https://minio/tmp/opaque-report.pdf"),
    )
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=3)),
    )
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeFileDao,
        "get_repeat_file",
        AsyncMock(return_value=None),
    )
    app = _mount_app(
        mutation_service=_mutation_service(),
        stage_service=stage_service,
        owner_service=owner,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/upload/101",
            files={"file": ("report.pdf", b"pdf", "application/pdf")},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["upload_id"] == stage.upload_id
    assert data["file_path"] == "https://minio/tmp/opaque-report.pdf"
    assert data["file_name"] == "report.pdf"
    assert "object_name" not in data
    assert "tenant_id" not in data
    assert data["content_hash"]
    owner.authorize_upload_stage.assert_awaited_once_with(101)
    stage_service.create_stage.assert_awaited_once_with(
        space_id=101,
        uploader_user_id=7,
        file_name="report.pdf",
        file_size=3,
        content_hash=data["content_hash"],
        temporary_object_name="opaque-report.pdf",
    )


def test_shared_upload_static_route_stays_legacy_and_precedes_space_dynamic_route(monkeypatch):
    """Non-space callers keep /upload while /upload/{space_id} owns opaque staging."""
    from bisheng.knowledge.api.endpoints import knowledge as knowledge_endpoint

    save_name = AsyncMock(return_value="opaque.txt")
    save_file = AsyncMock(return_value="https://minio/tmp/opaque.txt")
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeService,
        "save_upload_file_original_name",
        save_name,
    )
    monkeypatch.setattr(knowledge_endpoint, "save_uploaded_file", save_file)
    monkeypatch.setattr(knowledge_endpoint, "validate_knowledge_upload_file_size", lambda *_args: None)
    app = _mount_app(mutation_service=_mutation_service())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("shared.txt", b"shared", "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["data"]["file_path"] == "https://minio/tmp/opaque.txt"
    save_name.assert_awaited_once_with("shared.txt")
    save_file.assert_awaited_once()


def test_dynamic_upload_route_keeps_legacy_non_space_contract(monkeypatch):
    from bisheng.knowledge.api.endpoints import knowledge as knowledge_endpoint
    from bisheng.role.domain.services.quota_service import QuotaService

    monkeypatch.setattr(QuotaService, "check_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(knowledge_endpoint, "validate_knowledge_upload_file_size", lambda *_args: None)
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeService,
        "save_upload_file_original_name",
        AsyncMock(return_value="opaque.pdf"),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "save_uploaded_file",
        AsyncMock(return_value="https://minio/tmp/opaque.pdf"),
    )
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=0)),
    )
    monkeypatch.setattr(
        knowledge_endpoint.KnowledgeFileDao,
        "get_repeat_file",
        AsyncMock(return_value=None),
    )
    stage_service = SimpleNamespace(create_stage=AsyncMock())
    owner = SimpleNamespace(authorize_upload_stage=AsyncMock())
    app = _mount_app(
        mutation_service=_mutation_service(),
        stage_service=stage_service,
        owner_service=owner,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/upload/88",
            files={"file": ("legacy.pdf", b"pdf", "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json()["data"]["file_path"] == "https://minio/tmp/opaque.pdf"
    assert response.json()["data"]["upload_id"] is None
    stage_service.create_stage.assert_not_awaited()
    owner.authorize_upload_stage.assert_not_awaited()


def test_file_upload_registration_accepts_only_upload_ids_and_maps_each_result():
    service = _mutation_service(
        FileChangeMutationResult(decision="direct", resource={"id": 11, "file_name": "a.pdf"}),
        FileChangeMutationResult(decision="pending", approval_instance_id=31, change_request_id=41),
        FileChangeMutationResult(decision="invalid", error_code=18072, error_message="conflict"),
    )
    owner = SimpleNamespace(build_file_change_commands=AsyncMock(side_effect=lambda **kwargs: kwargs["items"]))
    app = _mount_app(mutation_service=service, owner_service=owner)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/space/101/files",
            json={"upload_ids": ["u-1", "u-2", "u-3"], "parent_id": 9},
        )
        leaked = client.post(
            "/api/v1/knowledge/space/101/files",
            json={"upload_ids": ["u-1"], "object_name": "secret", "tenant_id": 9},
        )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "input_id": "u-1",
            "resource_type": "file",
            "decision": "direct",
            "resource": {"id": 11, "file_name": "a.pdf"},
            "approval_instance_id": None,
            "change_request_id": None,
            "error_code": None,
            "error_message": None,
        },
        {
            "input_id": "u-2",
            "resource_type": "file",
            "decision": "pending",
            "resource": None,
            "approval_instance_id": 31,
            "change_request_id": 41,
            "error_code": None,
            "error_message": None,
        },
        {
            "input_id": "u-3",
            "resource_type": "file",
            "decision": "invalid",
            "resource": None,
            "approval_instance_id": None,
            "change_request_id": None,
            "error_code": 18072,
            "error_message": "conflict",
        },
    ]
    assert leaked.status_code == 422
    assert service.request_changes.await_count == 1


def test_folder_upload_maps_relative_paths_but_never_accepts_client_file_metadata():
    service = _mutation_service(
        FileChangeMutationResult(decision="pending", approval_instance_id=51, change_request_id=61),
        FileChangeMutationResult(decision="invalid", error_message="bad path"),
    )
    owner = SimpleNamespace(build_file_change_commands=AsyncMock(side_effect=lambda **kwargs: kwargs["items"]))
    app = _mount_app(mutation_service=service, owner_service=owner)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/space/101/folders/upload",
            json={
                "parent_id": None,
                "items": [
                    {"upload_id": "u-1", "relative_path": "Top/a.pdf"},
                    {"upload_id": "u-2", "relative_path": "Top/b.pdf"},
                ],
            },
        )
        leaked = client.post(
            "/api/v1/knowledge/space/101/folders/upload",
            json={"items": [{"upload_id": "u-1", "relative_path": "a.pdf", "size": 3}]},
        )

    assert response.status_code == 200
    assert [item["decision"] for item in response.json()["data"]] == ["pending", "invalid"]
    assert leaked.status_code == 422


def test_single_rename_and_delete_return_decision_envelopes_without_mutating_pending_resource():
    service = _mutation_service(
        FileChangeMutationResult(decision="pending", approval_instance_id=71, change_request_id=81),
        FileChangeMutationResult(decision="direct", resource={"id": 12, "file_name": "renamed"}),
        FileChangeMutationResult(decision="pending", approval_instance_id=72, change_request_id=82),
        FileChangeMutationResult(decision="direct", resource=None),
    )
    owner = SimpleNamespace(build_file_change_command=AsyncMock(side_effect=lambda **kwargs: kwargs))
    app = _mount_app(mutation_service=service, owner_service=owner)

    with TestClient(app) as client:
        file_rename = client.put("/api/v1/knowledge/space/101/files/11", json={"name": "new.pdf"})
        folder_rename = client.put("/api/v1/knowledge/space/101/folders/12", json={"name": "renamed"})
        file_delete = client.delete("/api/v1/knowledge/space/101/files/13")
        folder_delete = client.delete("/api/v1/knowledge/space/101/folders/14")

    assert file_rename.json()["data"] == {
        "decision": "pending",
        "approval_instance_id": 71,
        "change_request_id": 81,
        "resource": None,
    }
    assert folder_rename.json()["data"]["decision"] == "direct"
    assert file_delete.json()["data"]["decision"] == "pending"
    assert folder_delete.json()["data"]["decision"] == "direct"
    assert service.request_change.await_count == 4


def test_move_batch_delete_and_batch_rename_keep_item_commits_independent():
    service = _mutation_service(
        FileChangeMutationResult(decision="direct", resource={"id": 1}),
        FileChangeMutationResult(decision="pending", approval_instance_id=201, change_request_id=301),
        FileChangeMutationResult(decision="invalid", error_code=18072, error_message="locked"),
    )
    owner = SimpleNamespace(build_file_change_commands=AsyncMock(side_effect=lambda **kwargs: kwargs["items"]))
    app = _mount_app(mutation_service=service, owner_service=owner)

    payload = {
        "items": [{"id": 1, "type": "file"}, {"id": 2, "type": "folder"}, {"id": 3, "type": "file"}],
        "target_space_id": 102,
        "target_folder_id": 8,
        "skip_invalid": True,
    }
    with TestClient(app) as client:
        move = client.post("/api/v1/knowledge/space/101/files/move", json=payload)

    assert move.status_code == 200
    assert [item["id"] for item in move.json()["data"]["moved"]] == [1]
    assert [item["id"] for item in move.json()["data"]["pending"]] == [2]
    assert [item["id"] for item in move.json()["data"]["invalid"]] == [3]
    service.request_changes.assert_awaited_once()

    service.request_changes.reset_mock()
    service.request_changes.return_value = [
        FileChangeMutationResult(decision="direct"),
        FileChangeMutationResult(decision="pending", approval_instance_id=202, change_request_id=302),
        FileChangeMutationResult(decision="invalid", error_message="gone"),
    ]
    with TestClient(app) as client:
        deleted = client.post(
            "/api/v1/knowledge/space/101/files/batch-delete",
            json={"file_ids": [1, 3], "folder_ids": [2]},
        )
        renamed = client.post(
            "/api/v1/knowledge/space/101/files/batch-rename",
            json={
                "items": [
                    {"id": 1, "type": "file", "name": "a.pdf"},
                    {"id": 2, "type": "folder", "name": "folder"},
                    {"id": 3, "type": "file", "name": "c.pdf"},
                ]
            },
        )

    assert [item["id"] for item in deleted.json()["data"]["deleted"]] == [1]
    assert [item["id"] for item in deleted.json()["data"]["pending"]] == [3]
    assert [item["id"] for item in deleted.json()["data"]["invalid"]] == [2]
    assert [item["id"] for item in renamed.json()["data"]["renamed"]] == [1]
    assert [item["id"] for item in renamed.json()["data"]["pending"]] == [2]
    assert [item["id"] for item in renamed.json()["data"]["invalid"]] == [3]
    assert service.request_changes.await_count == 2


async def test_owner_repository_expands_version_siblings_folder_subtree_and_move_ancestors(footprint_engine):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
        KnowledgeSpaceFileChangeLockScope,
    )
    from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
        KnowledgeSpaceMutationRepository,
    )

    factory = async_sessionmaker(footprint_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                KnowledgeFile(id=1, tenant_id=42, knowledge_id=101, file_name="v1.pdf", file_type=1),
                KnowledgeFile(id=2, tenant_id=42, knowledge_id=101, file_name="v2.pdf", file_type=1),
                KnowledgeFile(
                    id=10,
                    tenant_id=42,
                    knowledge_id=101,
                    file_name="tree",
                    file_type=FileType.DIR.value,
                    file_level_path="",
                ),
                KnowledgeFile(
                    id=20,
                    tenant_id=42,
                    knowledge_id=102,
                    file_name="ancestor",
                    file_type=FileType.DIR.value,
                    file_level_path="",
                ),
                KnowledgeFile(
                    id=21,
                    tenant_id=42,
                    knowledge_id=102,
                    file_name="target",
                    file_type=FileType.DIR.value,
                    file_level_path="/20",
                ),
            ]
        )
        document = KnowledgeDocument(id=100, knowledge_id=101, primary_version_id=1001)
        session.add(document)
        session.add_all(
            [
                KnowledgeDocumentVersion(
                    id=1001,
                    document_id=100,
                    knowledge_file_id=1,
                    version_no=1,
                    is_primary=True,
                ),
                KnowledgeDocumentVersion(
                    id=1002,
                    document_id=100,
                    knowledge_file_id=2,
                    version_no=2,
                    is_primary=False,
                ),
            ]
        )
        await session.commit()

        repository = KnowledgeSpaceMutationRepository(session)
        rename = SimpleNamespace(action="rename", space_id=101, resource_id=1)
        folder = SimpleNamespace(action="delete", space_id=101, resource_id=10)
        move = SimpleNamespace(
            action="move",
            space_id=101,
            resource_id=1,
            target_space_id=102,
            target_parent_id=21,
        )
        rename_entries = await repository.resolve_file_change_footprints(tenant_id=42, command=rename)
        folder_entries = await repository.resolve_file_change_footprints(tenant_id=42, command=folder)
        move_entries = await repository.resolve_file_change_footprints(tenant_id=42, command=move)

    assert {entry.resource_id for entry in rename_entries if entry.resource_type == "knowledge_file_version"} == {
        1001,
        1002,
    }
    assert folder_entries[0].resource_id == 10
    assert folder_entries[0].lock_scope == KnowledgeSpaceFileChangeLockScope.SUBTREE
    assert folder_entries[0].path_root == "/10/"
    assert {(entry.resource_id, entry.lock_scope) for entry in move_entries if entry.space_id == 102} == {
        (20, KnowledgeSpaceFileChangeLockScope.EXACT),
        (21, KnowledgeSpaceFileChangeLockScope.DESTINATION),
    }


async def test_direct_stage_upload_bridges_original_name_before_using_legacy_owner(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStage
    from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
        KnowledgeSpaceUploadStageRepository,
    )
    from bisheng.knowledge.domain.services import knowledge_space_service as owner_module
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    stage = KnowledgeSpaceUploadStage(
        id=9,
        tenant_id=42,
        upload_id="77d59a61-861b-46fc-8477-c15cb2d01f3d",
        space_id=101,
        uploader_user_id=7,
        object_name="temporary-upload.pdf",
        file_name="quarterly report.pdf",
        file_size=3,
        content_hash="abc",
        state="uploaded",
        expire_at="2026-09-01T00:00:00Z",
    )

    @asynccontextmanager
    async def fake_session_factory():
        yield MagicMock()

    monkeypatch.setattr(owner_module, "get_async_db_session", fake_session_factory)
    monkeypatch.setattr(KnowledgeSpaceUploadStageRepository, "get_by_upload_id", AsyncMock(return_value=stage))
    save_name = AsyncMock(return_value="uuid-name.pdf")
    monkeypatch.setattr(owner_module.KnowledgeService, "save_upload_file_original_name", save_name)
    storage = SimpleNamespace(
        bucket="formal",
        tmp_bucket="tmp",
        copy_object=AsyncMock(),
        get_share_link=AsyncMock(return_value="https://minio/tmp/uuid-name.pdf"),
        remove_object=AsyncMock(),
    )
    attached_stage = stage.model_copy(
        update={
            "object_name": "knowledge-space-upload-stage/42/opaque",
            "state": "attached",
        }
    )
    stage_service = SimpleNamespace(
        storage=storage,
        attach=AsyncMock(return_value=attached_stage),
        consume=AsyncMock(),
    )
    owner = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, user_name="applicant", tenant_id=42),
    )
    owner.add_file = AsyncMock(return_value=[SimpleNamespace(id=99, file_name="quarterly report.pdf")])
    command = FileChangeRequestCommand(
        action="upload",
        space_id=101,
        applicant_user_id=7,
        applicant_user_name="applicant",
        resource_type="staged_upload",
        resource_name="quarterly report.pdf",
        upload_id=stage.upload_id,
    )
    monkeypatch.setattr(owner_module, "get_current_tenant_id", lambda: 42)

    result = await owner.execute_direct_file_change(command, stage_service=stage_service)

    assert result.file_name == "quarterly report.pdf"
    save_name.assert_awaited_once_with("quarterly report.pdf")
    storage.copy_object.assert_awaited_once_with(
        source_bucket="formal",
        source_object=attached_stage.object_name,
        dest_bucket="tmp",
        dest_object="uuid-name.pdf",
    )
    stage_service.attach.assert_awaited_once_with(stage.upload_id)
    owner.add_file.assert_awaited_once_with(
        101,
        ["https://minio/tmp/uuid-name.pdf"],
        parent_id=None,
    )
    stage_service.consume.assert_awaited_once_with(stage.upload_id)


async def test_folder_file_change_authorization_uses_folder_lookup_and_permission():
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    owner = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, user_name="applicant", tenant_id=42),
    )
    folder = SimpleNamespace(id=5117, file_type=0, knowledge_id=81)
    owner._get_folder_for_action = AsyncMock(return_value=folder)
    owner._get_file_for_action = AsyncMock(side_effect=AssertionError("folder must not use file lookup"))
    owner._require_permission_id = AsyncMock()
    command = FileChangeRequestCommand(
        action="rename",
        space_id=81,
        applicant_user_id=7,
        applicant_user_name="applicant",
        resource_type="folder",
        resource_name="1234",
        resource_id=5117,
        action_snapshot={"new_name": "renamed"},
    )

    await owner.authorize_file_change(command)

    owner._get_folder_for_action.assert_awaited_once_with(81, 5117)
    owner._get_file_for_action.assert_not_awaited()
    owner._require_permission_id.assert_awaited_once_with(
        "folder",
        5117,
        "rename_folder",
        space_id=81,
    )


async def test_failed_upload_cleanup_is_request_bound_permissionless_and_retry_idempotent(monkeypatch):
    from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
        KnowledgeSpaceFileChangeRequestRepository,
    )
    from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
        KnowledgeSpaceMutationRepository,
    )
    from bisheng.knowledge.domain.services import knowledge_space_service as owner_module
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

    session = MagicMock()

    @asynccontextmanager
    async def begin():
        yield

    @asynccontextmanager
    async def session_factory():
        yield session

    session.begin = begin
    request = SimpleNamespace(action="upload", space_id=101, executed_resource_id=501)
    file_record = SimpleNamespace(
        id=501,
        file_name="failed.pdf",
        file_level_path="",
        level=0,
        status=3,
    )
    monkeypatch.setattr(owner_module, "get_async_db_session", session_factory)
    monkeypatch.setattr(owner_module, "get_current_tenant_id", lambda: 42)
    monkeypatch.setattr(
        KnowledgeSpaceFileChangeRequestRepository,
        "get_by_id",
        AsyncMock(return_value=request),
    )
    monkeypatch.setattr(
        KnowledgeSpaceMutationRepository,
        "get_formal_file",
        AsyncMock(side_effect=[file_record, None]),
    )
    build_manifest = AsyncMock(return_value={"file_ids": [501]})
    apply_cutover = AsyncMock()
    monkeypatch.setattr(KnowledgeSpaceMutationRepository, "build_delete_manifest", build_manifest)
    monkeypatch.setattr(KnowledgeSpaceMutationRepository, "apply_delete_cutover", apply_cutover)
    dispatch = MagicMock()
    monkeypatch.setattr(delete_knowledge_file_celery, "apply_async", dispatch)

    owner = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, user_name="applicant", tenant_id=42),
    )
    owner._cleanup_resource_tuples = AsyncMock()

    for _ in range(2):
        await owner.cleanup_failed_file_change_upload(
            tenant_id=42,
            space_id=101,
            request_id=41,
            executed_resource_id=501,
        )

    build_manifest.assert_awaited_once()
    apply_cutover.assert_awaited_once()
    assert dispatch.call_count == 2
    dispatch.assert_called_with(
        kwargs={"file_ids": [501], "knowledge_id": 101, "clear_minio": True},
        headers={"tenant_id": 42},
    )
    assert owner._cleanup_resource_tuples.await_count == 2
