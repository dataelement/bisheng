from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import FilelibSyncNotFoundError
from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams, FilelibSyncResponseData
from bisheng.open_endpoints.domain.services.filelib_sync_audit_writer import (
    ACTION_UPLOAD_FAILED,
    ACTION_UPLOAD_SUCCESS,
    FilelibSyncAuditWriter,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
    ResolvedFileSyncTarget,
)


def _rule() -> DeveloperTokenFileSyncRule:
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {"mode": "fixed", "knowledge_id": 8},
            "dynamic_source": None,
        }
    )


def _params() -> FilelibSyncParams:
    return FilelibSyncParams(
        external_file_id="DOC-001",
        file_name="report.pdf",
        responsible_person_id="owner-ext",
    )


def _service(knowledge_space_service=None) -> FilelibSyncService:
    return FilelibSyncService(
        request=SimpleNamespace(headers={"X-Request-ID": "req-123"}),
        login_user=UserPayload(user_id=1, user_name="caller", tenant_id=1),
        token_id=42,
        token_name="SG-HR",
        file_sync_rule=_rule(),
        repository=SimpleNamespace(find_by_id=AsyncMock()),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


def _stub_orchestration(service: FilelibSyncService, knowledge_file: KnowledgeFile):
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_user_external_id="owner-ext",
        responsible_department=SimpleNamespace(id=20),
        main_department=SimpleNamespace(id=10, name="主责单位"),
        business_domain_department=None,
        target_space_department=None,
    )
    target_space = Knowledge(id=8, name="信息库", type=3, tenant_id=5, business_domain_codes=["IT"])
    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(SimpleNamespace(code="POL"), SimpleNamespace(code="MGMT")))
    service._resolve_business_domain = Mock(return_value=SimpleNamespace(code="IT", name="信息", space_ids=[8]))
    service._resolve_target_space = AsyncMock(
        return_value=ResolvedFileSyncTarget(space=target_space, folder_id=100, used_personal_fallback=False),
    )
    service._resolve_target_folder = AsyncMock(return_value=100)
    service._ensure_domain_bound = Mock()
    service._require_upload_permission = AsyncMock()
    service._cleanup_duplicate_files_before_sync = AsyncMock(return_value=None)
    service.repository.find_by_id = AsyncMock(return_value=knowledge_file)
    return identity, target_space


def test_filelib_sync_actions_are_ui_visible():
    for action in (
        "filelib_sync.upload.success",
        "filelib_sync.upload.failed",
        "filelib_sync.inspection_standard.batch.success",
        "filelib_sync.inspection_standard.batch.failed",
    ):
        assert action in _UI_VISIBLE_V2_ACTIONS


@pytest.mark.asyncio
async def test_write_upload_success_calls_ainsert_v2():
    login_user = UserPayload(user_id=1, user_name="caller", tenant_id=1)
    params = _params()
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_external_id="owner-ext",
    )
    target = ResolvedFileSyncTarget(
        space=Knowledge(id=8, name="信息库", type=3, tenant_id=5),
        folder_id=100,
        used_personal_fallback=False,
    )
    created_file = KnowledgeFile(
        id=90583,
        knowledge_id=8,
        file_name="report.pdf",
        file_encoding="PP-2026-001",
        status=5,
        create_time=datetime(2026, 7, 28),
    )
    response = FilelibSyncResponseData(
        external_file_id="DOC-001",
        file_id=90583,
        file_encoding="PP-2026-001",
        knowledge_id=8,
        knowledge_name="信息库",
        status=5,
        version_link_pending=False,
        replaced_file_id=None,
    )

    with (
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_audit_writer.AuditLogDao.ainsert_v2",
            new_callable=AsyncMock,
        ) as ainsert,
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_audit_writer.get_request_ip",
            return_value="127.0.0.1",
        ),
    ):
        await FilelibSyncAuditWriter.write_upload_success(
            request=SimpleNamespace(headers={"X-Request-ID": "req-123"}),
            login_user=login_user,
            token_id=42,
            token_name="SG-HR",
            params=params,
            identity=identity,
            target=target,
            created_file=created_file,
            response=response,
            endpoint_tag="sync",
            trigger_type=None,
            business_domain_code="PP",
            category_code="POLICY",
            subcategory_code="MGMT_POLICY",
            replaced_file_id=None,
            folder_display_name="政策目录",
        )

    ainsert.assert_awaited_once()
    kwargs = ainsert.await_args.kwargs
    assert kwargs["tenant_id"] == 5
    assert kwargs["operator_id"] == 1
    assert kwargs["action"] == ACTION_UPLOAD_SUCCESS
    assert kwargs["target_type"] == "knowledge_file"
    assert kwargs["target_id"] == "90583"
    assert kwargs["metadata"]["external_file_id"] == "DOC-001"
    assert kwargs["metadata"]["token_id"] == 42
    assert kwargs["metadata"]["knowledge_id"] == 8
    assert kwargs["metadata"]["folder_name"] == "政策目录"
    assert kwargs["metadata"]["responsible_user_name"] == "liu-y"
    assert kwargs["metadata"]["request_id"] == "req-123"
    assert kwargs["ip_address"] == "127.0.0.1"
    assert "Token: SG-HR (ID: 42)" in kwargs["note"]
    assert "知识空间: 信息库 (ID: 8)" in kwargs["note"]
    assert "目录: 政策目录" in kwargs["note"]
    assert "外部文件ID: DOC-001" in kwargs["note"]


@pytest.mark.asyncio
async def test_write_upload_failed_records_error_code():
    login_user = UserPayload(user_id=1, user_name="caller", tenant_id=1)
    params = _params()
    error = FilelibSyncNotFoundError(msg="configured target knowledge space does not exist")

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_audit_writer.AuditLogDao.ainsert_v2",
        new_callable=AsyncMock,
    ) as ainsert:
        await FilelibSyncAuditWriter.write_upload_failed(
            request=None,
            login_user=login_user,
            token_id=42,
            token_name="SG-HR",
            params=params,
            endpoint_tag="sync",
            trigger_type=None,
            identity=None,
            target=None,
            business_domain_code=None,
            category_code="POLICY",
            subcategory_code="MGMT_POLICY",
            replaced_file_id=None,
            extra_user_metadata=None,
            error=error,
        )

    kwargs = ainsert.await_args.kwargs
    assert kwargs["action"] == ACTION_UPLOAD_FAILED
    assert kwargs["target_type"] == "external_file"
    assert kwargs["target_id"] == "DOC-001"
    assert kwargs["metadata"]["error_code"] == 19903
    assert "configured target knowledge space does not exist" in kwargs["metadata"]["error_message"]
    assert "Token: SG-HR (ID: 42)" in kwargs["note"]
    assert "错误码: 19903" in kwargs["note"]


def test_build_upload_note_uses_root_folder_label_when_folder_missing():
    note = FilelibSyncAuditWriter._build_upload_note(
        token_id=42,
        token_name="SG-HR",
        params=_params(),
        folder_display_name="根目录",
        identity=SimpleNamespace(
            responsible_user_id=2,
            responsible_user_external_id="owner-ext",
            responsible_user_name="liu-y",
        ),
        target=ResolvedFileSyncTarget(
            space=Knowledge(id=8, name="信息库", type=3, tenant_id=5),
            folder_id=None,
            used_personal_fallback=False,
        ),
        business_domain_code="PP",
        category_code="POLICY",
        subcategory_code="MGMT_POLICY",
        created_file=None,
        error_code=None,
        error_message=None,
    )
    assert "目录: 根目录" in note


@pytest.mark.asyncio
async def test_sync_from_staged_file_success_writes_audit():
    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="report.pdf",
        status=5,
        create_time=datetime(2026, 7, 28),
    )
    knowledge_space_service = SimpleNamespace(
        get_preview_cache_key=Mock(return_value="cache-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=9, status=5)]),
        enqueue_file_title_extraction=AsyncMock(),
    )
    service = _service(knowledge_space_service=knowledge_space_service)
    _stub_orchestration(service, knowledge_file)

    with (
        patch.object(
            FileEncodingTransformer,
            "generate_fixed_encoding",
            AsyncMock(return_value="PP-2026-001"),
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.FilelibSyncAuditWriter.write_upload_success",
            new_callable=AsyncMock,
        ) as write_success,
    ):
        result = await service.sync_from_staged_file(
            params=_params(),
            local_file_path="/tmp/staged.pdf",
            endpoint_tag="sync",
            allow_personal_fallback=False,
        )

    assert result.file_id == 9
    write_success.assert_awaited_once()
    assert write_success.await_args.kwargs["token_name"] == "SG-HR"
    assert write_success.await_args.kwargs["endpoint_tag"] == "sync"


@pytest.mark.asyncio
async def test_sync_from_staged_file_business_error_writes_failed_audit():
    service = _service()
    service._require_dynamic_source_id = Mock()
    service._resolve_identity = AsyncMock(
        side_effect=FilelibSyncNotFoundError(msg="configured target knowledge space does not exist"),
    )
    service._cleanup_failed_sync = AsyncMock()

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.FilelibSyncAuditWriter.write_upload_failed",
        new_callable=AsyncMock,
    ) as write_failed:
        with pytest.raises(FilelibSyncNotFoundError):
            await service.sync_from_staged_file(
                params=_params(),
                local_file_path="/tmp/staged.pdf",
                allow_personal_fallback=False,
            )

    write_failed.assert_awaited_once()
    assert write_failed.await_args.kwargs["error"].code == 19903


@pytest.mark.asyncio
async def test_sync_from_staged_file_audit_failure_does_not_break_success():
    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="report.pdf",
        status=5,
        create_time=datetime(2026, 7, 28),
    )
    knowledge_space_service = SimpleNamespace(
        get_preview_cache_key=Mock(return_value="cache-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=9, status=5)]),
        enqueue_file_title_extraction=AsyncMock(),
    )
    service = _service(knowledge_space_service=knowledge_space_service)
    _stub_orchestration(service, knowledge_file)

    with (
        patch.object(
            FileEncodingTransformer,
            "generate_fixed_encoding",
            AsyncMock(return_value="PP-2026-001"),
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_audit_writer.AuditLogDao.ainsert_v2",
            new_callable=AsyncMock,
            side_effect=RuntimeError("audit db down"),
        ),
    ):
        result = await service.sync_from_staged_file(
            params=_params(),
            local_file_path="/tmp/staged.pdf",
            endpoint_tag="sync",
            allow_personal_fallback=False,
        )

    assert result.file_id == 9
    assert result.external_file_id == "DOC-001"
