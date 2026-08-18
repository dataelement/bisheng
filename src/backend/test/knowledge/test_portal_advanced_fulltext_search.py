from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextSearchHit,
    KnowledgeFulltextSearchSession,
    KnowledgeFulltextUploaderSupport,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalAdvancedUploaderSearchReq,
    ShougangPortalFileItemResp,
)
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
        find_by_ids=AsyncMock(
            side_effect=[[_file(20), _file(90, status=3)], [_file(30)]]
        )
    )
    service._filter_shougang_portal_search_files = AsyncMock(side_effect=lambda files, **_: files)
    service._map_shougang_portal_files_to_items = AsyncMock(
        side_effect=lambda *, files, **_: [
            ShougangPortalFileItemResp(id=file.id, space_id=12, title=str(file.id))
            for file in files
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
    service.knowledge_file_repo = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[_file(101), _file(102)])
    )
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
    assert (
        service._filter_shougang_portal_search_files.await_args.kwargs[
            "defer_department_access"
        ]
        is False
    )
