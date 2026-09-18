"""分类浏览使用业务库存。投影和全文服务不决定文件是否可见。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalCategoryFileCountItem,
    ShougangPortalDomainFileCountItem,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileCountReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.parametrize("navigation_kind", ["category", "domain"])
@pytest.mark.parametrize("page_size,sort", [(1, "updated_at_desc"), (2, "updated_at_asc"), (100, "updated_at_desc")])
async def test_category_inventory_is_independent_of_projection_and_fulltext(
    async_db_session, monkeypatch, page_size, sort, navigation_kind
):
    inventory_filter = {"document_type": "NEW"} if navigation_kind == "category" else {"business_domain_code": "PP"}

    async def navigation_counts(service, *, scope="portal_enabled", space_ids=None):
        if navigation_kind == "category":
            return (
                await service.count_shougang_portal_category_files(
                    [ShougangPortalCategoryFileCountItem(code="NEW", space_ids=space_ids or [])], discovery_scope=scope
                )
            )["NEW"]
        return (
            await service.count_shougang_portal_domain_files(
                [ShougangPortalDomainFileCountItem(code="PP", space_ids=space_ids or [])], discovery_scope=scope
            )
        )["PP"]

    async def insert(file_id, *, space_id=10, document_id=None, **overrides):
        payload = {
            "id": file_id,
            "knowledge_id": space_id,
            "user_id": 1,
            "user_name": "tester",
            "file_name": f"{file_id}.pdf",
            "file_encoding": f"SGGF-NEW-PP-202609-{file_id:06d}",
            "file_subcategory_code": "NEW-A",
            "file_type": 1,
            "status": 2,
            "reference_document_id": document_id or file_id + 1000,
            "entry_type": "manager",
            "entry_status": "active",
            "update_time": datetime(2026, 1, 1) + timedelta(seconds=file_id),
        }
        payload.update(overrides)
        async_db_session.add(KnowledgeFile(**payload))

    # 不创建任何全文索引。失败、等待、处理中和正常入口都属于业务库存。
    for file_id, state in enumerate(["failed", "pending", "processing", "ready"], 1):
        await insert(file_id, projection_status=state)
    # 同文档的发布入口跨越分页边界。仍只能算一篇。
    await insert(5, space_id=20, document_id=1001, entry_type="publish", projection_status="ready")
    await insert(6, deleted_at=datetime(2026, 1, 2))
    await insert(7, entry_status="invalid")
    await insert(8, status=3)
    await insert(9, file_type=0)
    await insert(10, file_encoding="SGGF-POL-PM-000010")
    await insert(11, space_id=30)
    # 高优先级入口只是 LIKE 命中；精确分类不符时应选择另一个合格入口。
    await insert(
        12,
        document_id=1005,
        file_encoding="SG-NEW-POL-PP-000012" if navigation_kind == "category" else "SG-PP-NEW-PM-000012",
    )
    await insert(13, space_id=20, document_id=1005, entry_type="share")
    # 可见性过滤也必须先于去重，否则被拒绝的管理入口会遮住可见发布入口。
    await insert(14, document_id=1006)
    await insert(15, space_id=20, document_id=1006, entry_type="publish")
    await insert(16, space_id=20)
    # 同一逻辑文档的入口跨越数据库扫描批次，不能重复计数或改变代表入口。
    for file_id in range(100, 605):
        await insert(file_id, space_id=20, document_id=1001, entry_type="share")
    await async_db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield async_db_session

    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session", session_factory)
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=Mock(user_id=1, tenant_id=1))
    spaces = [SimpleNamespace(id=i, name=str(i), space_level="public") for i in [10, 20]]
    discovery = SimpleNamespace(
        discoverable_space_ids=[10, 20],
        explicitly_visible_space_ids=[],
        explicitly_visible_file_ids=[],
        explicit_file_space_by_id={},
        grant_parent_space_ids=[],
        snapshot="inventory-scope",
    )
    service._portal_discovery_result = discovery
    service.resolve_portal_discovery = AsyncMock(return_value=discovery)
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service._get_shougang_portal_tag_file_ids = AsyncMock(return_value=None)
    service._get_valid_department_space_ids = AsyncMock(return_value=set())
    service._get_effective_permission_ids = AsyncMock(return_value={"view_file"})
    service._public_space_viewer_permission_ids = AsyncMock(return_value={"view_file"})
    service._load_file_tags_batch = AsyncMock(return_value={})
    service._find_pending_publish_approval_file_ids = AsyncMock(return_value=set())
    service._resolve_shougang_portal_source_paths = AsyncMock(return_value=({}, {}))
    service.get_logo_share_link = Mock(return_value="")
    service.advanced_search_shougang_portal_files = AsyncMock(side_effect=AssertionError("不能查询全文索引"))
    original_filter = service._filter_shougang_portal_search_files

    async def filter_visible(files, **kwargs):
        return await original_filter([file for file in files if file.id != 14], **kwargs)

    service._filter_shougang_portal_search_files = filter_visible

    listed = []
    cursor = None
    for _ in range(10):
        page = await service.browse_shougang_portal_files(
            ShougangPortalFileBrowseReq(
                **inventory_filter, discovery_scope="portal_enabled", limit=page_size, cursor=cursor, sort=sort
            )
        )
        assert len(page["data"]) <= page_size
        assert page["total"] == 7
        listed.extend(page["data"])
        if not page["has_more"]:
            break
        assert page["next_cursor"]
        cursor = page["next_cursor"]
    else:
        pytest.fail("数据库分类分页未结束")

    expected_ids = [1, 2, 3, 4, 13, 15, 16] if sort.endswith("asc") else [16, 15, 13, 4, 3, 2, 1]
    assert [item["id"] for item in listed] == expected_ids
    by_id = {item["id"]: item for item in listed}
    assert by_id[1]["projection_status"] == "failed"
    assert by_id[1]["projection_ready"] is False
    assert by_id[4]["projection_ready"] is True

    navigation = await navigation_counts(service)
    total = await service.count_shougang_portal_files(
        ShougangPortalFileCountReq(query_type="browse", **inventory_filter, discovery_scope="portal_enabled")
    )
    assert navigation == total["total"] == len(listed) == 7
    service.advanced_search_shougang_portal_files.assert_not_awaited()

    # 双标签在选代表入口前取交集，列表与专用计数也使用这组条件。
    async def tag_ids(_space_ids, tag):
        return {"标签一": [1, 12, 13], "标签二": [5, 13]}.get(tag)

    service._get_shougang_portal_tag_file_ids = tag_ids
    filtered_req = dict(**inventory_filter, discovery_scope="portal_enabled", tag="标签一", filter_tag="标签二")
    filtered_page = await service.browse_shougang_portal_files(ShougangPortalFileBrowseReq(**filtered_req))
    filtered_count = await service.count_shougang_portal_files(ShougangPortalFileCountReq(**filtered_req))
    assert [item["id"] for item in filtered_page["data"]] == [13]
    assert filtered_page["total"] == filtered_count["total"] == 1

    # 单文件授权不能扩展为整个父库：20 库只授予 13、15，16 必须排除。
    discovery.discoverable_space_ids = [10]
    discovery.explicitly_visible_file_ids = [13, 15]
    discovery.explicit_file_space_by_id = {13: 20, 15: 20}
    discovery.grant_parent_space_ids = [20]
    original_visible = service._filter_shougang_portal_visible_files

    async def configured_visible(files, **kwargs):
        return await original_visible([file for file in files if file.id != 14], **kwargs)

    service._filter_shougang_portal_visible_files = configured_visible
    configured_page = await service.browse_shougang_portal_files(
        ShougangPortalFileBrowseReq(**inventory_filter, discovery_scope="portal_configured", limit=100)
    )
    configured_counts = await navigation_counts(service, scope="portal_configured", space_ids=[10, 20])
    assert {item["id"] for item in configured_page["data"]} == {1, 2, 3, 4, 13, 15}
    assert configured_page["total"] == configured_counts == 6
