from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeDepartmentFileUnavailableError,
    KnowledgeDepartmentFileViewApprovalRequiredError,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessSource,
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(
            user_id=9,
            user_name="申请人",
            tenant_id=1,
            is_admin=lambda: False,
        ),
    )


def _file() -> SimpleNamespace:
    return SimpleNamespace(
        id=21,
        knowledge_id=2,
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        file_name="设备点检标准.pdf",
        parse_type="pdf",
        reference_document_id=None,
    )


@pytest.mark.asyncio
async def test_department_file_detail_fails_before_mapping_when_approval_required():
    service = _service()
    file = _file()
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
                department_id=30,
            )
        )
    )
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
        new=AsyncMock(return_value=file),
    ):
        with pytest.raises(KnowledgeDepartmentFileViewApprovalRequiredError):
            await service.get_shougang_portal_file(
                space_id=2,
                file_id=21,
            )


@pytest.mark.asyncio
async def test_invalid_department_binding_fails_closed_for_content():
    service = _service()
    file = _file()
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.UNAVAILABLE,
                invalid_reason="invalid_binding",
            )
        )
    )
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
        new=AsyncMock(return_value=file),
    ):
        with pytest.raises(KnowledgeDepartmentFileUnavailableError):
            await service.get_shougang_portal_file_preview(
                space_id=2,
                file_id=21,
            )


@pytest.mark.asyncio
async def test_approval_grant_can_preview_but_does_not_add_download_permission():
    service = _service()
    file = _file()
    space = SimpleNamespace(id=2, index_name="space-2")
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.ALLOWED,
                source="approval_grant",
                can_download=False,
                department_id=30,
            )
        )
    )
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[space])
    service._get_effective_permission_ids = AsyncMock(return_value=set())
    service._log_file_preview_success = AsyncMock()
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_detail",
            return_value={"preview_url": "/preview/21.pdf"},
        ),
    ):
        result = await service.get_shougang_portal_file_preview(
            space_id=2,
            file_id=21,
        )

    assert result == {
        "preview_url": "/preview/21.pdf",
        "can_download": False,
    }


@pytest.mark.asyncio
async def test_approval_grant_detail_projection_keeps_department_download_decision():
    service = _service()
    file = _file()
    space = SimpleNamespace(id=2)
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.ALLOWED,
                source=DepartmentFileAccessSource.APPROVAL_GRANT,
                can_download=False,
                department_id=30,
            )
        )
    )
    service._get_shougang_portal_request_spaces = AsyncMock(
        return_value=[space]
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeFileDao.query_by_id",
        new=AsyncMock(return_value=file),
    ):
        authorized, _ = await service._get_authorized_shougang_portal_file(
            space_id=2,
            file_id=21,
        )

    assert authorized is file
    item = service._map_shougang_portal_file_item(
        2,
        {
            "id": 21,
            "file_name": "设备点检标准.pdf",
        },
    )
    assert item.is_department_file is True
    assert item.access_source == DepartmentFileAccessSource.APPROVAL_GRANT
    assert item.can_download is False


@pytest.mark.asyncio
async def test_approval_grant_keeps_clinic_file_when_legacy_discovery_omits_space():
    service = _service()
    file = _file()
    space = SimpleNamespace(id=2, type=3, tenant_id=1)
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.ALLOWED,
                source=DepartmentFileAccessSource.APPROVAL_GRANT,
                can_download=False,
                department_id=30,
            )
        )
    )
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[])

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
    ):
        authorized, spaces = await service._get_authorized_shougang_portal_file(
            space_id=2,
            file_id=21,
        )

    assert authorized is file
    assert spaces == [space]
    assert service._portal_file_download_map[21] is False


@pytest.mark.asyncio
async def test_approval_grant_can_preview_distributed_share_entry():
    service = _service()
    share = _file()
    share.tenant_id = 1
    share.entry_type = "share"
    share.entry_status = "active"
    share.reference_document_id = 90
    manager = SimpleNamespace(id=22)
    resolved = ResolvedKnowledgeDocumentEntry(
        tenant_id=1,
        requested_space_id=2,
        entry_file_id=21,
        entry_type="share",
        entry_status="active",
        canonical_document_id=90,
        canonical_version_id=91,
        content_file_id=22,
        manager_file_id=22,
        manager_space_id=3,
        capabilities=KnowledgeDocumentEntryCapabilities(),
    )
    service._get_authorized_shougang_portal_file = AsyncMock(
        return_value=(share, [SimpleNamespace(id=2)])
    )
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(return_value=resolved)
    )
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.ALLOWED,
                source=DepartmentFileAccessSource.APPROVAL_GRANT,
                can_download=False,
                department_id=30,
            )
        )
    )
    service._log_file_preview_success = AsyncMock()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=manager),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeService.get_file_share_detail",
            return_value={"preview_url": "/preview/22.pdf"},
        ),
    ):
        result = await service.get_shougang_portal_file_preview(
            space_id=2,
            file_id=21,
        )

    assert result["preview_url"] == "/preview/22.pdf"
    assert result["capabilities"]["can_view"] is True
    assert result["capabilities"]["can_preview"] is True
    assert result["can_download"] is False


@pytest.mark.asyncio
async def test_portal_chunks_filter_out_any_unrequested_document_hit():
    service = _service()
    file = _file()
    space = SimpleNamespace(id=2, index_name="space-2")
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=DepartmentFileAccessDecision(
                file_id=21,
                space_id=2,
                status=DepartmentFileAccessStatus.ALLOWED,
                source="approval_grant",
                department_id=30,
            )
        )
    )
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[space])
    search = Mock(
        return_value={
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_source": {
                            "text": "授权正文",
                            "metadata": {
                                "document_id": 21,
                                "chunk_index": 1,
                            },
                        }
                    },
                    {
                        "_source": {
                            "text": "越权正文",
                            "metadata": {
                                "document_id": 999,
                                "chunk_index": 1,
                            },
                        }
                    },
                ],
            }
        }
    )
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeRag.init_knowledge_es_vectorstore",
            new=AsyncMock(return_value=SimpleNamespace(client=SimpleNamespace(search=search))),
        ),
    ):
        result = await service.get_shougang_portal_file_chunks(
            space_id=2,
            file_id=21,
            page=1,
            limit=100,
        )

    assert [item["text"] for item in result["data"]] == ["授权正文"]
    assert result["data"][0]["metadata"]["document_id"] == 21
    assert search.call_args.kwargs["body"]["post_filter"] == {"terms": {"metadata.document_id": [21]}}
