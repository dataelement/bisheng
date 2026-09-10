from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_cursor_repository_impl import (
    KnowledgeFulltextCursorRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextSearchHit,
    KnowledgeFulltextSearchSession,
    KnowledgeFulltextUploaderSupport,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalAdvancedUploaderSearchReq,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileCountReq,
    ShougangPortalFileItemResp,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_search_service import KnowledgeFulltextSearchService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _file(file_id: int, *, status: int = 2):
    return SimpleNamespace(
        id=file_id,
        knowledge_id=12,
        file_type=1,
        status=status,
        deleted_at=None,
        update_time=datetime(2026, 8, 14),
    )


def _session() -> KnowledgeFulltextSearchSession:
    return KnowledgeFulltextSearchSession(
        pit_id="pit-1",
        context_signature="a" * 64,
        expected_sort_values=4,
    )


@pytest.mark.asyncio
async def test_advanced_fulltext_bounded_scan_restores_es_order_and_preserves_lookahead():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=12)]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service._portal_file_download_map = {}
    service._portal_discovery_result = None
    session = _session()
    search_service = SimpleNamespace(
        begin=AsyncMock(return_value=session),
        fetch=AsyncMock(
            side_effect=[
                KnowledgeFulltextSearchBatch(
                    pit_id="pit-1",
                    hits=[
                        KnowledgeFulltextSearchHit(
                            file_id=90,
                            score=9,
                            sort_values=[9, "2026-08-14", 90, 901],
                        ),
                        KnowledgeFulltextSearchHit(
                            file_id=20,
                            score=8,
                            sort_values=[8, "2026-08-14", 20, 201],
                        ),
                    ],
                    exhausted=False,
                ),
                KnowledgeFulltextSearchBatch(
                    pit_id="pit-1",
                    hits=[
                        KnowledgeFulltextSearchHit(
                            file_id=30,
                            score=7,
                            sort_values=[7, "2026-08-14", 30, 301],
                        )
                    ],
                    exhausted=True,
                ),
            ]
        ),
        encode_next_cursor=MagicMock(return_value="cursor-after-20"),
        close=AsyncMock(),
    )
    service.knowledge_fulltext_search_service = search_service
    service.knowledge_file_repo = SimpleNamespace(
        find_by_ids=AsyncMock(side_effect=[[_file(20), _file(90, status=3)], [_file(30)]])
    )
    service._filter_shougang_portal_search_files = AsyncMock(side_effect=lambda files, **_: files)
    service._map_shougang_portal_files_to_items = AsyncMock(
        side_effect=lambda *, files, **_: [
            ShougangPortalFileItemResp(id=file.id, space_id=12, title=str(file.id)) for file in files
        ]
    )

    result = await service.advanced_search_shougang_portal_files(
        ShougangPortalAdvancedFileSearchReq(
            discovery_scope="public_and_department",
            space_ids=[12],
            all_keywords="轧机",
            limit=1,
        )
    )

    assert [item["id"] for item in result["data"]] == [20]
    assert result["has_more"] is True
    assert result["next_cursor"] == "cursor-after-20"
    assert service.knowledge_file_repo.find_by_ids.await_count == 2
    assert service._filter_shougang_portal_search_files.await_count == 2
    assert all(
        call.kwargs["defer_department_access"] is True
        for call in service._filter_shougang_portal_search_files.await_args_list
    )
    search_service.encode_next_cursor.assert_called_once_with(
        session,
        sort_values=[8, "2026-08-14", 20, 201],
    )
    search_service.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploader_candidates_require_strictly_visible_supporting_file():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=12)]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service._portal_file_download_map = {}
    service.user_repository = SimpleNamespace(
        list_active_by_name=AsyncMock(
            return_value=[
                SimpleNamespace(user_id=1, user_name="张三"),
                SimpleNamespace(user_id=2, user_name="张安"),
            ]
        )
    )
    service.knowledge_fulltext_search_service = SimpleNamespace(
        find_uploader_supports=AsyncMock(
            return_value=[
                KnowledgeFulltextUploaderSupport(user_id=1, file_ids=[101]),
                KnowledgeFulltextUploaderSupport(user_id=2, file_ids=[102]),
            ]
        )
    )
    service.knowledge_file_repo = SimpleNamespace(find_by_ids=AsyncMock(return_value=[_file(101), _file(102)]))
    service._filter_shougang_portal_search_files = AsyncMock(return_value=[_file(102)])

    result = await service.search_shougang_portal_advanced_uploaders(
        ShougangPortalAdvancedUploaderSearchReq(
            discovery_scope="public_and_department",
            space_ids=[12],
            q=" 张 ",
        )
    )

    assert result == {"data": [{"user_id": 2, "user_name": "张安"}]}
    service._filter_shougang_portal_search_files.assert_awaited_once()
    assert service._filter_shougang_portal_search_files.await_args.kwargs["defer_department_access"] is False


@pytest.mark.parametrize("limit", [1, 2, 100])
async def test_category_browse_deduplicates_documents_across_batches_and_pages(monkeypatch, limit):
    # 两组跨库入口外加一个先被权限过滤的入口。相同标题不能作为去重依据。
    pairs = [
        (848, None),
        (2719, None),
        (2726, 2506),
        (2725, 2506),
        (2724, 2505),
        (9992042, None),
        (2722, 2506),
        (2721, 2505),
    ]
    files = {file_id: _file(file_id) for file_id, _ in pairs}
    for file_id, document_id in pairs:
        files[file_id].reference_document_id = document_id
        if file_id in {2722, 2721}:
            files[file_id].knowledge_id = 366
    hits = [
        KnowledgeFulltextSearchHit(file_id=file_id, sort_values=[i, file_id, i]) for i, (file_id, _) in enumerate(pairs)
    ]

    async def search(query, *, pit_id, search_after, size):
        start = int(search_after[0]) + 1 if search_after else 0
        return KnowledgeFulltextSearchBatch(
            pit_id=pit_id,
            hits=hits[start : start + size],
            exhausted=start + size >= len(hits),
        )

    states = {}

    async def save(key, value, *, ex):
        assert ex == 120
        states[key] = value
        return True

    redis = SimpleNamespace(
        async_connection=SimpleNamespace(
            set=save,
            get=AsyncMock(side_effect=lambda key: states.get(key)),
        )
    )

    search_service = KnowledgeFulltextSearchService(
        repository=SimpleNamespace(open_pit=AsyncMock(return_value="pit-1"), search=search, close_pit=AsyncMock()),
        readiness_guard=SimpleNamespace(ensure_ready=AsyncMock()),
        cursor_repository=KnowledgeFulltextCursorRepositoryImpl(redis),
    )
    service = object.__new__(KnowledgeSpaceService)
    service.knowledge_fulltext_search_service = search_service
    service.knowledge_file_repo = SimpleNamespace(
        find_by_ids=AsyncMock(side_effect=lambda ids: [files[i] for i in reversed(ids)]),
    )
    service._get_shougang_portal_request_spaces = AsyncMock(
        return_value=[SimpleNamespace(id=12), SimpleNamespace(id=366)],
    )
    service._portal_file_download_map = {}
    service._portal_discovery_result = None
    service._filter_shougang_portal_search_files = AsyncMock(
        side_effect=lambda files, **_: [file for file in files if file.id != 2726],
    )
    service._map_shougang_portal_files_to_items = AsyncMock(
        side_effect=lambda *, files, **_: [
            ShougangPortalFileItemResp(id=file.id, space_id=file.knowledge_id, title="相同标题") for file in files
        ],
    )
    monkeypatch.setattr("bisheng.knowledge.domain.knowledge_fulltext_constants.KNOWLEDGE_FULLTEXT_SEARCH_BATCH_SIZE", 2)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.knowledge_fulltext_constants.KNOWLEDGE_FULLTEXT_SEARCH_MAX_SCAN_HITS", 3
    )
    cursor = None
    listed = []
    for _ in range(12):
        result = await service._list_shougang_portal_files_via_fulltext_document_type(
            ShougangPortalFileBrowseReq(
                document_type="NEW", discovery_scope="portal_enabled", limit=limit, cursor=cursor
            ),
        )
        assert len(result["data"]) <= limit
        listed.extend(item["id"] for item in result["data"])
        if not result["has_more"]:
            break
        assert result["next_cursor"]
        assert len(result["next_cursor"]) == 32
        cursor = result["next_cursor"]
    else:
        pytest.fail("分类分页未结束")
    assert listed == [848, 2719, 2725, 2724, 9992042]

    service.browse_shougang_portal_files = service._list_shougang_portal_files_via_fulltext_document_type
    count = await service.count_shougang_portal_files(
        ShougangPortalFileCountReq(query_type="browse", document_type="NEW", discovery_scope="portal_enabled"),
    )
    assert count["total"] == len(listed)
