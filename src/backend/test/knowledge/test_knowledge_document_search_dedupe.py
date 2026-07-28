"""Portal semantic search must rank canonical chunks, not entry copies."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
    PortalFileCandidate,
    PortalSearchChunk,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFileSearchReq,
)


def _entry(
    *,
    file_id: int,
    space_id: int,
    entry_type: KnowledgeFileEntryType,
    desired_content_generation: int = 4,
    applied_content_generation: int = 4,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=7,
        knowledge_id=space_id,
        file_name="canonical.pdf",
        file_type=1,
        status=KnowledgeFileStatus.SUCCESS.value,
        reference_document_id=91,
        entry_type=entry_type.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        projection_status=KnowledgeFileProjectionStatus.READY.value,
        desired_content_generation=desired_content_generation,
        applied_content_generation=applied_content_generation,
        desired_entry_generation=1,
        applied_entry_generation=1,
    )


def _chunk(
    *,
    file_id: int,
    space_id: int,
    retriever: str,
    rank: int,
    content_generation: int = 4,
) -> PortalSearchChunk:
    return PortalSearchChunk(
        file_id=file_id,
        knowledge_id=space_id,
        canonical_document_id=91,
        canonical_version_id=501,
        chunk_index=0,
        content_generation=content_generation,
        entry_generation=1,
        content="same canonical chunk",
        source="test",
        retriever=retriever,
        rank=rank,
        score=1.0 / rank,
        metadata={
            "document_id": file_id,
            "knowledge_id": space_id,
            "canonical_document_id": 91,
            "canonical_version_id": 501,
            "chunk_index": 0,
            "content_generation": content_generation,
            "entry_generation": 1,
        },
    )


async def test_search_filters_stale_projection_and_dedupes_before_scoring() -> None:
    publish = _entry(
        file_id=101,
        space_id=10,
        entry_type=KnowledgeFileEntryType.PUBLISH,
    )
    manager = _entry(
        file_id=100,
        space_id=20,
        entry_type=KnowledgeFileEntryType.MANAGER,
    )
    stale_share = _entry(
        file_id=102,
        space_id=30,
        entry_type=KnowledgeFileEntryType.SHARE,
        desired_content_generation=4,
        applied_content_generation=4,
    )
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    service._filter_shougang_portal_visible_files = AsyncMock(
        return_value=[publish, manager, stale_share]
    )
    service.doc_repo = SimpleNamespace(
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=91, primary_version_id=501)
            ]
        )
    )
    service.version_repo = SimpleNamespace()
    chunks = [
        _chunk(file_id=100, space_id=20, retriever="es", rank=2),
        _chunk(file_id=101, space_id=10, retriever="es", rank=1),
        _chunk(file_id=100, space_id=20, retriever="vector", rank=1),
        _chunk(
            file_id=102,
            space_id=30,
            retriever="es",
            rank=1,
            content_generation=3,
        ),
    ]

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeFileDao.aget_file_by_ids",
        new=AsyncMock(return_value=[publish, manager, stale_share]),
    ):
        result = await service._filter_and_dedupe_portal_search_chunks(
            chunks=chunks,
            spaces=[
                SimpleNamespace(id=10),
                SimpleNamespace(id=20),
                SimpleNamespace(id=30),
            ],
        )

    assert len(result) == 2
    assert {chunk.retriever for chunk in result} == {"es", "vector"}
    assert {chunk.file_id for chunk in result} == {101}
    assert {chunk.knowledge_id for chunk in result} == {10}
    assert {chunk.canonical_document_id for chunk in result} == {91}
    grouped = service._group_shougang_portal_chunks_by_file(result)
    assert list(grouped) == [101]


def test_semantic_search_cursor_pages_canonical_sequence_without_duplicates():
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    now = datetime(2026, 7, 27, 12, 0, 0)
    candidates = [
        PortalFileCandidate(
            file_id=index,
            knowledge_id=10,
            canonical_document_id=100 + index,
            final_score=10.0 - index,
        )
        for index in range(1, 5)
    ]
    file_map = {
        index: KnowledgeFile(
            id=index,
            tenant_id=7,
            knowledge_id=10,
            file_name=f"{index}.pdf",
            file_type=1,
            status=KnowledgeFileStatus.SUCCESS.value,
            update_time=now - timedelta(minutes=index),
        )
        for index in range(1, 5)
    }
    first_req = ShougangPortalFileSearchReq(
        q="检修",
        space_ids=[10],
        limit=2,
    )

    first, first_has_more, cursor = (
        service._paginate_shougang_portal_semantic_candidates(
            candidates=candidates,
            file_map=file_map,
            req=first_req,
            space_ids=[10],
        )
    )
    second_req = first_req.model_copy(update={"cursor": cursor})
    second, second_has_more, second_cursor = (
        service._paginate_shougang_portal_semantic_candidates(
            candidates=candidates,
            file_map=file_map,
            req=second_req,
            space_ids=[10],
        )
    )

    assert [item.canonical_document_id for item in first] == [101, 102]
    assert [item.canonical_document_id for item in second] == [103, 104]
    assert first_has_more is True
    assert cursor is not None
    assert second_has_more is False
    assert second_cursor is None


def test_portal_item_contract_exposes_server_distribution_capabilities():
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    service._portal_file_download_map = {101: True}
    service._portal_file_access_decision_map = {}

    item = service._map_shougang_portal_file_item(
        10,
        {
            "id": 101,
            "file_name": "检修方案.pdf",
            "entry_type": "share",
            "entry_status": "active",
            "canonical_document_id": 91,
            "canonical_version_id": 501,
            "manager_file_id": 100,
            "manager_space_id": 20,
            "desired_content_generation": 4,
            "applied_content_generation": 3,
            "desired_entry_generation": 2,
            "applied_entry_generation": 2,
            "projection_status": "pending",
            "projection_ready": False,
            "capabilities": {
                "can_view": True,
                "can_preview": True,
                "can_download": False,
            },
        },
    )

    assert item.entry_type == "share"
    assert item.canonical_document_id == 91
    assert item.manager_file_id is None
    assert item.manager_space_id == 20
    assert item.projection_ready is False
    assert item.capabilities.can_download is False
    assert item.can_download is False


async def test_portal_preview_reads_canonical_manager_content():
    share = _entry(
        file_id=101,
        space_id=10,
        entry_type=KnowledgeFileEntryType.SHARE,
    )
    manager = _entry(
        file_id=100,
        space_id=20,
        entry_type=KnowledgeFileEntryType.MANAGER,
    )
    capabilities = KnowledgeDocumentEntryCapabilities(
        can_view=True,
        can_preview=True,
        can_download=False,
    )
    resolved = ResolvedKnowledgeDocumentEntry(
        tenant_id=7,
        requested_space_id=10,
        entry_file_id=101,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        canonical_document_id=91,
        canonical_version_id=501,
        content_file_id=100,
        manager_file_id=100,
        manager_space_id=20,
        projection_status=KnowledgeFileProjectionStatus.READY.value,
        projection_ready=True,
        capabilities=capabilities,
    )
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    service._get_authorized_shougang_portal_file = AsyncMock(
        return_value=(share, [SimpleNamespace(id=10)])
    )
    service._resolve_document_entry = AsyncMock(return_value=resolved)
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
            return_value={"content_file_id": 100},
        ),
    ):
        detail = await service.get_shougang_portal_file_preview(
            space_id=10,
            file_id=101,
        )

    assert detail["content_file_id"] == 100
    assert detail["entry_file_id"] == 101
    assert detail["manager_file_id"] is None
    assert detail["manager_space_id"] == 20
    assert detail["can_download"] is False


async def test_portal_deep_link_resolves_old_physical_id_to_local_entry():
    share = _entry(
        file_id=101,
        space_id=10,
        entry_type=KnowledgeFileEntryType.SHARE,
    )
    resolved = ResolvedKnowledgeDocumentEntry(
        tenant_id=7,
        requested_space_id=10,
        entry_file_id=101,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        content_file_id=100,
        manager_file_id=100,
        manager_space_id=20,
        capabilities=KnowledgeDocumentEntryCapabilities(),
    )
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=UserPayload(
            user_id=11,
            user_name="tester",
            tenant_id=7,
        ),
    )
    service.document_durable_reference_resolver = SimpleNamespace(
        resolve=AsyncMock(return_value=resolved)
    )
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=SimpleNamespace(status="allowed")
        )
    )
    service._get_shougang_portal_request_spaces = AsyncMock(
        return_value=[SimpleNamespace(id=10)]
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeFileDao.query_by_id",
        new=AsyncMock(return_value=share),
    ) as query:
        file, spaces = await service._get_authorized_shougang_portal_file(
            space_id=10,
            file_id=999,
        )

    query.assert_awaited_once_with(101)
    assert file.id == 101
    assert [space.id for space in spaces] == [10]
