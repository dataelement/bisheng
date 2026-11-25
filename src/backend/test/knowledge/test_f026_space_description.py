"""Description-only edits must not change another setting or the release flag."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.api.endpoints.knowledge_space import update_space
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceUpdateReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.parametrize(("patch", "expected"), [({}, True), ({"is_released": False}, False)])
async def test_patch_preserves_published_space_unless_explicit(monkeypatch, patch, expected):
    space = SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, auth_type="public", is_released=True)
    svc = KnowledgeSpaceService(request=None, login_user=SimpleNamespace(user_id=5, tenant_id=1))
    permission = AsyncMock()
    monkeypatch.setattr(svc, "_require_action", permission)
    apply_tags = AsyncMock()
    monkeypatch.setattr(svc, "_apply_auto_tag_binding", apply_tags)
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(KnowledgeDao, "async_update_space", AsyncMock(return_value=space))
    await update_space(2, KnowledgeSpaceUpdateReq(description="new", **patch), svc)
    permission.assert_awaited_once_with("knowledge_space", 2, "edit")
    assert space.description == "new"
    assert space.is_released is expected
    apply_tags.assert_not_awaited()
