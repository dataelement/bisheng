from __future__ import annotations

from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import FilelibSyncNotFoundError
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncParams
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


def _service(repository=None, knowledge_space_service=None) -> FilelibSyncService:
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=UserPayload(user_id=1, user_name="caller", tenant_id=1),
        token_id=42,
        token_name="联调Token",
        file_sync_rule=_rule(),
        repository=repository or SimpleNamespace(find_by_id=AsyncMock()),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


def _params() -> FilelibSyncParams:
    return FilelibSyncParams(
        external_file_id="automotive_sheet_intro",
        file_name="汽车板介绍.pdf",
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
    target_space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"])
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
    service._resolve_same_name_version_overwrite = AsyncMock(return_value=(None, None))
    service.repository.find_by_id = AsyncMock(return_value=knowledge_file)
    return identity, target_space


@pytest.mark.asyncio
async def test_sync_delegates_to_sync_from_staged_file():
    service = _service()
    params = _params()
    upload = UploadFile(filename="汽车板介绍.pdf", file=BytesIO(b"pdf"), size=3)
    expected = SimpleNamespace(external_file_id="automotive_sheet_intro", file_id=9)

    service._save_temporary_file = AsyncMock(return_value="/tmp/staged.pdf")
    service.sync_from_staged_file = AsyncMock(return_value=expected)

    result = await service.sync(
        raw_params=params.model_dump_json(),
        upload_file=upload,
    )

    service._save_temporary_file.assert_awaited_once_with(params, upload)
    service.sync_from_staged_file.assert_awaited_once_with(
        params=params,
        local_file_path="/tmp/staged.pdf",
        endpoint_tag="sync",
        allow_personal_fallback=True,
    )
    assert result is expected


@pytest.mark.asyncio
async def test_sync_from_staged_file_writes_endpoint_and_trigger_metadata():
    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="汽车板介绍.pdf",
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

    async def _generate_fixed_encoding(**kwargs):
        kwargs["knowledge_file"].file_encoding = "SGGF-POL-IT-20260700000009"
        return kwargs["knowledge_file"].file_encoding

    with (
        patch.object(
            FileEncodingTransformer,
            "generate_fixed_encoding",
            side_effect=_generate_fixed_encoding,
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ),
    ):
        result = await service.sync_from_staged_file(
            params=_params(),
            local_file_path="/tmp/staged.pdf",
            endpoint_tag="automotive_sheet_intro_sync",
            trigger_type="scheduled",
            allow_personal_fallback=False,
        )

    assert knowledge_file.user_metadata["filelib_sync_endpoint"] == "automotive_sheet_intro_sync"
    assert knowledge_file.user_metadata["filelib_sync_trigger"] == "scheduled"
    assert "filelib_sync_target_fallback" not in (knowledge_file.user_metadata or {})
    assert result.file_id == 9


@pytest.mark.asyncio
async def test_sync_from_staged_file_disables_personal_fallback():
    service = _service()
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_user_external_id="owner-ext",
        main_department=SimpleNamespace(id=10, name="主责单位"),
        business_domain_department=None,
        target_space_department=None,
    )
    service._require_dynamic_source_id = Mock()
    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(SimpleNamespace(), SimpleNamespace()))
    service._resolve_business_domain = Mock(return_value=SimpleNamespace(code="IT"))
    service._resolve_configured_target_space = AsyncMock(
        side_effect=FilelibSyncNotFoundError(msg="configured target knowledge space does not exist"),
    )
    service._resolve_personal_fallback_target = AsyncMock()

    with pytest.raises(FilelibSyncNotFoundError, match="configured target knowledge space does not exist"):
        await service.sync_from_staged_file(
            params=_params(),
            local_file_path="/tmp/staged.pdf",
            allow_personal_fallback=False,
        )

    service._resolve_personal_fallback_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_from_staged_file_skips_permission_personal_fallback_when_disabled():
    service = _service()
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_user_external_id="owner-ext",
        main_department=SimpleNamespace(id=10, name="主责单位"),
        business_domain_department=None,
    )
    target_space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"])
    service._require_dynamic_source_id = Mock()
    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(SimpleNamespace(), SimpleNamespace()))
    service._resolve_business_domain = Mock(return_value=SimpleNamespace(code="IT"))
    service._resolve_target_space = AsyncMock(
        return_value=ResolvedFileSyncTarget(space=target_space, folder_id=None, used_personal_fallback=False),
    )
    service._resolve_target_folder = AsyncMock(return_value=None)
    service._require_upload_permission = AsyncMock(
        side_effect=FilelibSyncNotFoundError(msg="configured file sync target does not exist"),
    )
    service._resolve_personal_fallback_target = AsyncMock()

    with pytest.raises(FilelibSyncNotFoundError, match="configured file sync target does not exist"):
        await service.sync_from_staged_file(
            params=_params(),
            local_file_path="/tmp/staged.pdf",
            allow_personal_fallback=False,
        )

    service._resolve_personal_fallback_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_from_staged_file_re_stages_local_file_with_display_name(tmp_path):
    local_pdf = tmp_path / "tmp5id1omnw.pdf"
    local_pdf.write_bytes(b"%PDF-1.4")

    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="汽车板介绍.pdf",
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

    minio_path = "http://minio/tmp/uuid.pdf"
    service._ensure_upload_path_preserves_display_name = AsyncMock(return_value=minio_path)

    with (
        patch.object(
            FileEncodingTransformer,
            "generate_fixed_encoding",
            AsyncMock(return_value="SGGF-POL-IT-20260700000009"),
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ),
    ):
        await service.sync_from_staged_file(
            params=_params(),
            local_file_path=str(local_pdf),
            endpoint_tag="automotive_sheet_intro_sync",
            trigger_type="manual",
            allow_personal_fallback=False,
        )

    service._ensure_upload_path_preserves_display_name.assert_awaited_once_with(
        local_file_path=str(local_pdf),
        file_name="汽车板介绍.pdf",
    )
    knowledge_space_service.add_file.assert_awaited_once()
    assert knowledge_space_service.add_file.await_args.kwargs["file_path"] == [minio_path]


@pytest.mark.asyncio
async def test_ensure_upload_path_preserves_display_name_for_local_file(tmp_path):
    local_pdf = tmp_path / "tmp5id1omnw.pdf"
    local_pdf.write_bytes(b"%PDF-1.4")

    minio_client = SimpleNamespace(
        tmp_bucket="tmp-bucket",
        put_object_tmp=AsyncMock(),
        get_share_link=AsyncMock(return_value="http://minio/tmp/uuid.pdf"),
    )

    with (
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeService.save_upload_file_original_name",
            AsyncMock(return_value="uuid.pdf"),
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.get_minio_storage",
            AsyncMock(return_value=minio_client),
        ),
    ):
        staged_path = await FilelibSyncService._ensure_upload_path_preserves_display_name(
            local_file_path=str(local_pdf),
            file_name="汽车板介绍.pdf",
        )

    assert staged_path == "http://minio/tmp/uuid.pdf"
    minio_client.put_object_tmp.assert_awaited_once_with(
        object_name="uuid.pdf",
        file=str(local_pdf),
        content_type="application/pdf",
    )


@pytest.mark.asyncio
async def test_ensure_upload_path_preserves_display_name_skips_minio_url():
    minio_url = "http://minio/tmp/already-staged.pdf?X-Amz-Signature=abc"

    with patch("bisheng.open_endpoints.domain.services.filelib_sync_service.os.path.isfile", return_value=False):
        staged_path = await FilelibSyncService._ensure_upload_path_preserves_display_name(
            local_file_path=minio_url,
            file_name="汽车板介绍.pdf",
        )

    assert staged_path == minio_url
