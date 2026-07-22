from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import (
    FilelibSyncNotFoundError,
    FilelibSyncPermissionDeniedError,
)
from bisheng.common.errcode.knowledge_space import (
    SpaceFolderNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
    ResolvedFileSyncTarget,
)


def _rule(*, folder_id: int | None, dynamic: bool = False) -> DeveloperTokenFileSyncRule:
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {
                "mode": "dynamic" if dynamic else "fixed",
                "knowledge_id": None if dynamic else 8,
                "folder_id": None if dynamic else folder_id,
            },
            "dynamic_source": "department_id" if dynamic else None,
        }
    )


def _service(
    rule: DeveloperTokenFileSyncRule,
    *,
    repository=None,
    knowledge_space_service=None,
) -> FilelibSyncService:
    return FilelibSyncService(
        login_user=UserPayload(
            user_id=7,
            user_name="bound",
            user_role=[2],
            tenant_id=5,
        ),
        token_id=42,
        file_sync_rule=rule,
        repository=repository or SimpleNamespace(),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


def _space() -> Knowledge:
    return Knowledge(
        id=8,
        name="信息库",
        type=3,
        business_domain_codes=["IT"],
    )


@pytest.mark.asyncio
async def test_fixed_folder_target_keeps_stable_folder_id() -> None:
    space = _space()
    service = _service(
        _rule(folder_id=4096),
        repository=SimpleNamespace(find_knowledge_by_id=AsyncMock(return_value=space)),
    )

    target = await service._resolve_target_space(SimpleNamespace(selected_department=None))

    assert target == ResolvedFileSyncTarget(space=space, folder_id=4096)


@pytest.mark.asyncio
async def test_dynamic_target_always_resolves_to_space_root() -> None:
    space = _space()
    service = _service(_rule(folder_id=None, dynamic=True))
    service._find_nearest_department_space = AsyncMock(return_value=space)

    target = await service._resolve_target_space(SimpleNamespace(selected_department=SimpleNamespace(id=20)))

    assert target == ResolvedFileSyncTarget(space=space, folder_id=None)


@pytest.mark.asyncio
async def test_deleted_or_mismatched_folder_returns_19903_without_root_fallback() -> None:
    service = _service(_rule(folder_id=4096))
    target = ResolvedFileSyncTarget(space=_space(), folder_id=4096)

    with patch.object(
        KnowledgeSpaceService,
        "validate_file_sync_target",
        new=AsyncMock(side_effect=SpaceFolderNotFoundError()),
    ):
        with pytest.raises(FilelibSyncNotFoundError) as exc_info:
            await service._require_upload_permission(target)

    assert exc_info.value.code == 19903


@pytest.mark.asyncio
async def test_revoked_folder_permission_returns_19902() -> None:
    service = _service(_rule(folder_id=4096))
    target = ResolvedFileSyncTarget(space=_space(), folder_id=4096)

    with patch.object(
        KnowledgeSpaceService,
        "validate_file_sync_target",
        new=AsyncMock(side_effect=SpacePermissionDeniedError()),
    ):
        with pytest.raises(FilelibSyncPermissionDeniedError) as exc_info:
            await service._require_upload_permission(target)

    assert exc_info.value.code == 19902


@pytest.mark.asyncio
async def test_folder_permission_failure_happens_before_temporary_upload() -> None:
    service = _service(_rule(folder_id=4096))
    service._resolve_identity = AsyncMock(return_value=SimpleNamespace(selected_department=None))
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = MagicMock()
    service._resolve_business_domain = MagicMock(return_value=SimpleNamespace())
    service._resolve_target_space = AsyncMock(return_value=ResolvedFileSyncTarget(space=_space(), folder_id=4096))
    service._ensure_domain_bound = MagicMock()
    service._require_upload_permission = AsyncMock(side_effect=FilelibSyncPermissionDeniedError())
    service._save_temporary_file = AsyncMock()

    with pytest.raises(FilelibSyncPermissionDeniedError):
        await service.sync(
            raw_params=json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"}),
            upload_file=UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7),
        )

    service._save_temporary_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_folder_upload_passes_parent_id_and_keeps_response_contract() -> None:
    space = _space()
    created = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="a.pdf",
        status=KnowledgeFileStatus.WAITING.value,
        file_encoding="SGGF-POLICY-IT-20260700000001",
    )
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=created),
        update=AsyncMock(side_effect=lambda value: value),
    )
    knowledge_service = SimpleNamespace(
        get_preview_cache_key=MagicMock(return_value="preview-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=9, status=KnowledgeFileStatus.WAITING.value)]),
        enqueue_file_processing=MagicMock(),
    )
    service = _service(
        _rule(folder_id=4096),
        repository=repository,
        knowledge_space_service=knowledge_service,
    )
    service._resolve_identity = AsyncMock(
        return_value=SimpleNamespace(
            selected_department=None,
            main_department=SimpleNamespace(id=20, name="信息部"),
            responsible_user_id=7,
            responsible_user_name="bound",
        )
    )
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = MagicMock()
    service._resolve_business_domain = MagicMock(return_value=SimpleNamespace(code="IT", name="信息", space_ids=[8]))
    service._resolve_target_space = AsyncMock(return_value=ResolvedFileSyncTarget(space=space, folder_id=4096))
    service._ensure_domain_bound = MagicMock()
    service._require_upload_permission = AsyncMock()
    service._save_temporary_file = AsyncMock(return_value="temporary-url")

    with patch.object(
        FileEncodingTransformer,
        "generate_fixed_encoding",
        new=AsyncMock(return_value=created.file_encoding),
    ):
        result = await service.sync(
            raw_params=json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"}),
            upload_file=UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7),
        )

    assert knowledge_service.add_file.await_args.kwargs["parent_id"] == 4096
    assert result.model_dump().keys() == {
        "external_file_id",
        "file_id",
        "file_encoding",
        "knowledge_id",
        "knowledge_name",
        "status",
    }
