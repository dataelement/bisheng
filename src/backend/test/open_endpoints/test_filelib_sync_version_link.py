from __future__ import annotations

from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
    ResolvedFileSyncTarget,
)
from bisheng.open_endpoints.domain.services.filelib_sync_version_link_service import (
    FILELIB_SYNC_PENDING_VERSION_LINK_KEY,
    complete_pending_filelib_sync_version_link,
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


def _service(knowledge_space_service=None, repository=None) -> FilelibSyncService:
    if repository is None:
        repository = SimpleNamespace(
            find_by_id=AsyncMock(),
            update=AsyncMock(side_effect=lambda value: value),
            find_files_by_external_file_id=AsyncMock(return_value=[]),
        )
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=UserPayload(user_id=1, user_name="caller", tenant_id=1),
        token_id=42,
        file_sync_rule=_rule(),
        repository=repository,
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_sync_same_name_upload_cleans_duplicates_before_add_file():
    repository = SimpleNamespace(
        find_by_id=AsyncMock(),
        update=AsyncMock(side_effect=lambda value: value),
        find_files_by_external_file_id=AsyncMock(return_value=[]),
    )
    knowledge_space_service = SimpleNamespace(
        get_preview_cache_key=Mock(return_value="cache-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=99, status=KnowledgeFileStatus.WAITING.value)]),
        enqueue_file_title_extraction=AsyncMock(),
    )
    service = _service(knowledge_space_service=knowledge_space_service, repository=repository)
    service._resolve_identity = AsyncMock(
        return_value=SimpleNamespace(
            responsible_user_id=2,
            responsible_user_name="owner",
            responsible_user_external_id="owner-ext",
            responsible_department=SimpleNamespace(id=20),
            main_department=SimpleNamespace(id=10, name="主责单位"),
            business_domain_department=None,
            target_space_department=None,
        )
    )
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(SimpleNamespace(code="POL"), SimpleNamespace(code="MGMT")))
    service._resolve_business_domain = Mock(return_value=SimpleNamespace(code="IT", name="信息", space_ids=[8]))
    service._resolve_target_space = AsyncMock(
        return_value=ResolvedFileSyncTarget(
            space=Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"]),
            folder_id=None,
        )
    )
    service._ensure_domain_bound = Mock()
    service._require_upload_permission = AsyncMock()
    service._save_temporary_file = AsyncMock(return_value="temporary-url")
    service._cleanup_duplicate_files_before_sync = AsyncMock(return_value=55)

    knowledge_file = KnowledgeFile(
        id=99,
        knowledge_id=8,
        file_name="report.pdf",
        status=KnowledgeFileStatus.WAITING.value,
    )
    repository.find_by_id = AsyncMock(return_value=knowledge_file)

    async def _generate_fixed_encoding(**kwargs):
        kwargs["knowledge_file"].file_encoding = "SGGF-POL-IT-20260700000099"
        return kwargs["knowledge_file"].file_encoding

    upload = UploadFile(filename="report.pdf", file=BytesIO(b"new-content"), size=11)
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
        result = await service.sync(
            raw_params='{"external_file_id":"ext-9","file_name":"report.pdf"}',
            upload_file=upload,
        )

    service._cleanup_duplicate_files_before_sync.assert_awaited_once()
    assert knowledge_space_service.add_file.await_args.kwargs["allow_duplicate_name"] is True
    assert knowledge_space_service.add_file.await_args.kwargs["allow_duplicate_content"] is True
    assert result.version_link_pending is False
    assert result.replaced_file_id == 55


@pytest.mark.asyncio
async def test_cleanup_duplicate_files_before_sync_deletes_all_success_matches():
    knowledge_space_service = SimpleNamespace(delete_file=AsyncMock())
    repository = SimpleNamespace(find_files_by_external_file_id=AsyncMock(return_value=[]))
    service = _service(knowledge_space_service=knowledge_space_service, repository=repository)
    existing = [
        KnowledgeFile(
            id=55,
            knowledge_id=8,
            file_name="report.pdf",
            status=KnowledgeFileStatus.SUCCESS.value,
            create_time=datetime(2026, 7, 1),
        ),
        KnowledgeFile(
            id=57,
            knowledge_id=8,
            file_name="report.pdf",
            status=KnowledgeFileStatus.SUCCESS.value,
            create_time=datetime(2026, 7, 2),
        ),
    ]
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.asyncio.to_thread",
        new=AsyncMock(
            side_effect=[
                SimpleNamespace(file_level_path="", knowledge_id=8),
                existing,
            ]
        ),
    ):
        replaced_file_id = await service._cleanup_duplicate_files_before_sync(
            knowledge_id=8,
            folder_id=9001,
            file_name="report.pdf",
            external_file_id="ext-9",
        )

    assert replaced_file_id == 57
    assert knowledge_space_service.delete_file.await_count == 2
    knowledge_space_service.delete_file.assert_any_await(55)
    knowledge_space_service.delete_file.assert_any_await(57)


@pytest.mark.asyncio
async def test_cleanup_duplicate_files_before_sync_deletes_non_success_existing():
    knowledge_space_service = SimpleNamespace(delete_file=AsyncMock())
    repository = SimpleNamespace(find_files_by_external_file_id=AsyncMock(return_value=[]))
    service = _service(knowledge_space_service=knowledge_space_service, repository=repository)
    existing = [
        KnowledgeFile(id=56, knowledge_id=8, file_name="report.pdf", status=KnowledgeFileStatus.WAITING.value),
    ]
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.asyncio.to_thread",
        new=AsyncMock(
            side_effect=[
                SimpleNamespace(file_level_path="", knowledge_id=8),
                existing,
            ]
        ),
    ):
        replaced_file_id = await service._cleanup_duplicate_files_before_sync(
            knowledge_id=8,
            folder_id=9001,
            file_name="report.pdf",
            external_file_id="ext-9",
        )

    assert replaced_file_id == 56
    knowledge_space_service.delete_file.assert_awaited_once_with(56)


@pytest.mark.asyncio
async def test_cleanup_duplicate_files_before_sync_includes_external_file_id_matches():
    knowledge_space_service = SimpleNamespace(delete_file=AsyncMock())
    external_match = KnowledgeFile(
        id=60,
        knowledge_id=8,
        file_name="legacy-name.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        create_time=datetime(2026, 7, 3),
        user_metadata={"external_file_id": "ext-9"},
    )
    repository = SimpleNamespace(find_files_by_external_file_id=AsyncMock(return_value=[external_match]))
    service = _service(knowledge_space_service=knowledge_space_service, repository=repository)
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.asyncio.to_thread",
        new=AsyncMock(
            side_effect=[
                SimpleNamespace(file_level_path="", knowledge_id=8),
                [],
            ]
        ),
    ):
        replaced_file_id = await service._cleanup_duplicate_files_before_sync(
            knowledge_id=8,
            folder_id=9001,
            file_name="report.pdf",
            external_file_id="ext-9",
        )

    assert replaced_file_id == 60
    knowledge_space_service.delete_file.assert_awaited_once_with(60)
    repository.find_files_by_external_file_id.assert_awaited_once_with(
        8,
        "ext-9",
        file_level_path="9001",
    )


@pytest.mark.asyncio
async def test_complete_pending_filelib_sync_version_link_calls_link_service():
    db_file = KnowledgeFile(
        id=99,
        knowledge_id=8,
        user_id=1,
        user_name="caller",
        tenant_id=1,
        status=KnowledgeFileStatus.SUCCESS.value,
        user_metadata={
            FILELIB_SYNC_PENDING_VERSION_LINK_KEY: {
                "target_document_id": 7001,
                "replaced_file_id": 55,
            }
        },
    )
    link_service = SimpleNamespace(
        link_file_to_document=AsyncMock(),
        doc_repo=SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(id=7001)), update=AsyncMock()),
        message_service=None,
    )

    mock_session = SimpleNamespace(sync_session=MagicMock())
    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.query_by_id_sync",
            return_value=db_file,
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.update",
        ) as mock_update,
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_version_link_service.get_async_db_session",
        ) as mock_session_factory,
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_version_link_service.get_message_service",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_version_link_service.KnowledgeVersionService",
            return_value=link_service,
        ),
    ):
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        linked = await complete_pending_filelib_sync_version_link(99)

    assert linked is True
    link_service.link_file_to_document.assert_awaited_once_with(99, 7001)
    mock_update.assert_called_once()
    assert FILELIB_SYNC_PENDING_VERSION_LINK_KEY not in (db_file.user_metadata or {})
    assert db_file.user_metadata["filelib_sync_version_linked"]["target_document_id"] == 7001
