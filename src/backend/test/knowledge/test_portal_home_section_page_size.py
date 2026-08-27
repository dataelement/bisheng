"""门户首页 latest_selected: page_size 必须在循环内读取, 不能 NameError."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalHomeReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _login_user():
    return SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True)


def _file_items(count: int) -> list:
    items = []
    for index in range(count):
        item = MagicMock()
        item.model_dump.return_value = {"id": index}
        items.append(item)
    return items


@pytest.mark.asyncio
async def test_home_latest_selected_uses_section_page_size() -> None:
    svc = KnowledgeSpaceService(request=None, login_user=_login_user())
    req = ShougangPortalHomeReq(
        space_ids=[12],
        sections=[{"tag": "最新精选", "recommendation": "latest_selected", "page_size": 4}],
    )
    space = SimpleNamespace(id=12, name="轧线")

    with (
        patch.object(
            svc,
            "_get_shougang_portal_request_spaces",
            new_callable=AsyncMock,
            return_value=[space],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService.collect_space_portal_tag_map",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch.object(
            svc,
            "_get_shougang_portal_hot_read_file_items",
            new_callable=AsyncMock,
            return_value=_file_items(4),
        ) as mock_hot,
    ):
        result = await svc._get_shougang_portal_home_sections(req)

    mock_hot.assert_awaited_once()
    assert mock_hot.await_args.kwargs["limit"] == 4
    assert len(result["sections"]["最新精选"]) == 4
