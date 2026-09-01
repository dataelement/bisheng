from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _User:
    user_id = 841
    tenant_id = 1

    def is_admin(self):
        return False


async def test_visible_square_space_is_included_in_permission_scan():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    released_approval_space = SimpleNamespace(
        id=4064,
        is_released=True,
        auth_type="approval",
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_all_knowledge",
            new=AsyncMock(return_value=[released_approval_space]),
        ),
        patch.object(
            service,
            "_batch_actions",
            new=AsyncMock(return_value={"4064": frozenset({"visible"})}),
        ),
    ):
        result = await service._scan_space_action_ids("visible")

    assert result == [4064]
