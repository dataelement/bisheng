from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import GroupedKnowledgeSpacesResp
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _AsyncSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestKnowledgeSpaceLevelEnum:
    def test_is_team_level_true_for_team_and_team_ks(self) -> None:
        assert KnowledgeSpaceLevelEnum.is_team_level(KnowledgeSpaceLevelEnum.TEAM) is True
        assert KnowledgeSpaceLevelEnum.is_team_level(KnowledgeSpaceLevelEnum.TEAM_KS) is True
        assert KnowledgeSpaceLevelEnum.is_team_level("team") is True
        assert KnowledgeSpaceLevelEnum.is_team_level("team_ks") is True

    def test_is_team_level_false_for_other_levels(self) -> None:
        assert KnowledgeSpaceLevelEnum.is_team_level(KnowledgeSpaceLevelEnum.PUBLIC) is False
        assert KnowledgeSpaceLevelEnum.is_team_level(KnowledgeSpaceLevelEnum.DEPARTMENT) is False
        assert KnowledgeSpaceLevelEnum.is_team_level(KnowledgeSpaceLevelEnum.PERSONAL) is False
        assert KnowledgeSpaceLevelEnum.is_team_level("personal") is False
        assert KnowledgeSpaceLevelEnum.is_team_level(None) is False


class TestKnowledgeSpaceScopeDao:
    @pytest.mark.asyncio
    async def test_aget_space_ids_by_levels_queries_multiple_levels(self) -> None:
        session = SimpleNamespace(
            exec=AsyncMock(return_value=SimpleNamespace(all=Mock(return_value=[1, 2, 3]))),
            add=Mock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )

        with patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.get_async_db_session",
            return_value=_AsyncSessionContext(session),
        ):
            result = await KnowledgeSpaceScopeDao.aget_space_ids_by_levels(
                [KnowledgeSpaceLevelEnum.TEAM, KnowledgeSpaceLevelEnum.TEAM_KS]
            )

        assert result == [1, 2, 3]
        session.exec.assert_awaited_once()


class TestKnowledgeSpaceServiceGrouping:
    def _make_service(self, *, is_admin: bool = False, user_id: int = 7) -> KnowledgeSpaceService:
        login_user = SimpleNamespace(
            user_id=user_id,
            tenant_id=1,
            is_admin=Mock(return_value=is_admin),
        )
        service = KnowledgeSpaceService(request=Mock(), login_user=login_user)
        return service

    @pytest.mark.asyncio
    async def test_get_grouped_spaces_merges_team_and_team_ks(self) -> None:
        service = self._make_service(user_id=7)
        service._ensure_personal_spaces = AsyncMock()
        service._list_accessible_spaces = AsyncMock(
            return_value=[
                SimpleNamespace(space_level=KnowledgeSpaceLevelEnum.TEAM, user_id=7),
                SimpleNamespace(space_level=KnowledgeSpaceLevelEnum.TEAM_KS, user_id=7),
                SimpleNamespace(space_level=KnowledgeSpaceLevelEnum.PUBLIC, user_id=7),
            ]
        )

        result = await service.get_grouped_spaces()

        assert isinstance(result, GroupedKnowledgeSpacesResp)
        assert len(result.team_spaces) == 2
        assert len(result.public_spaces) == 1
        assert len(result.department_spaces) == 0
        assert len(result.personal_spaces) == 0

    @pytest.mark.asyncio
    async def test_get_spaces_by_level_team_returns_team_and_team_ks(self) -> None:
        service = self._make_service(user_id=7)
        service._normalize_space_level = Mock(return_value=KnowledgeSpaceLevelEnum.TEAM)

        team_space = SimpleNamespace(id=1, space_level=KnowledgeSpaceLevelEnum.TEAM)
        clinic_space = SimpleNamespace(id=2, space_level=KnowledgeSpaceLevelEnum.TEAM_KS)

        with (
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_levels",
                new=AsyncMock(return_value=[1, 2]),
            ),
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService._format_accessible_spaces",
                new=AsyncMock(return_value=[team_space, clinic_space]),
            ),
        ):
            result = await service.get_spaces_by_level(KnowledgeSpaceLevelEnum.TEAM)

        assert len(result) == 2
        assert any(space.space_level == KnowledgeSpaceLevelEnum.TEAM for space in result)
        assert any(space.space_level == KnowledgeSpaceLevelEnum.TEAM_KS for space in result)
