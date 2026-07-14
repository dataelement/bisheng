import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.api.endpoints.knowledge_space import set_space_pin
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_set_pin_endpoint_keeps_legacy_is_pined_contract():
    service = SimpleNamespace(pin_space=AsyncMock(return_value=True))

    response = await set_space_pin(space_id=10, is_pined=True, svc=service)

    service.pin_space.assert_awaited_once_with(10, True)
    assert response.data is True
    assert "is_pined" in inspect.signature(set_space_pin).parameters


def test_endpoint_delegates_to_service_without_repository_or_orm_access():
    source = inspect.getsource(set_space_pin)

    assert "svc.pin_space" in source
    assert "Repository" not in source
    assert "UserLink" not in source


def test_delete_cleanup_runs_only_after_main_knowledge_delete_call():
    source = inspect.getsource(KnowledgeSpaceService.delete_space)

    delete_index = source.index("KnowledgeDao.async_delete_knowledge")
    cleanup_index = source.index("KnowledgeSpacePinService.delete_space_pins")
    assert delete_index < cleanup_index
