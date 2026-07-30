"""Knowledge-space business regressions that remain valid after F048.

F048 action, lifecycle, preview, and download contracts live in the focused
``test_f048_*`` suites. This module deliberately keeps only business behavior
that is independent of the retired permission-id/relation-model runtime.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _load_service_class():
    """Compatibility helper used by focused knowledge-space test modules."""

    return KnowledgeSpaceService


def _make_login_user(
    user_id: int = 7,
    user_name: str = "tester",
) -> SimpleNamespace:
    async def _get_user_group_ids(_user_id: int) -> list[int]:
        return []

    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        tenant_id=1,
        is_admin=lambda: False,
        get_user_group_ids=_get_user_group_ids,
    )


def _make_space(
    *,
    space_id: int = 1,
    user_id: int = 1,
    auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
    state: int = KnowledgeState.PUBLISHED.value,
    is_released: bool = False,
) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=user_id,
        name="Knowledge Space",
        type=KnowledgeTypeEnum.SPACE.value,
        description="desc",
        model="model-1",
        state=state,
        is_released=is_released,
        auth_type=auth_type,
    )


def _make_file(
    *,
    file_id: int = 11,
    knowledge_id: int = 1,
    file_type: int = FileType.FILE.value,
    file_name: str = "doc.txt",
    file_level_path: str = "",
    level: int = 0,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=knowledge_id,
        file_name=file_name,
        file_type=file_type,
        file_level_path=file_level_path,
        level=level,
        object_name="minio/object",
    )


def _make_member(
    *,
    user_id: int,
    user_role: UserRoleEnum,
    space_id: int,
) -> SpaceChannelMember:
    return SpaceChannelMember(
        id=user_id,
        business_id=str(space_id),
        business_type=BusinessTypeEnum.SPACE,
        user_id=user_id,
        user_role=user_role,
        status=MembershipStatusEnum.ACTIVE,
    )


@pytest.fixture
def service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(MagicMock(), _make_login_user())


async def test_get_space_info_raises_when_space_is_missing(
    service: KnowledgeSpaceService,
) -> None:
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(SpaceNotFoundError):
            await service.get_space_info(1)


async def test_create_limit_count_excludes_department_spaces(
    service: KnowledgeSpaceService,
) -> None:
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_count_spaces_by_user",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_count,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "LLMService.get_workbench_llm",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with pytest.raises(WorkbenchEmbeddingError):
            await service.create_knowledge_space(name="Space")

    mock_count.assert_awaited_once_with(
        service.login_user.user_id,
        exclude_department_spaces=True,
    )


async def test_created_spaces_exclude_department_bound_spaces(
    service: KnowledgeSpaceService,
) -> None:
    department_member = _make_member(
        user_id=service.login_user.user_id,
        user_role=UserRoleEnum.CREATOR,
        space_id=101,
    )
    normal_member = _make_member(
        user_id=service.login_user.user_id,
        user_role=UserRoleEnum.CREATOR,
        space_id=102,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_get_user_created_members",
            new_callable=AsyncMock,
            return_value=[department_member, normal_member],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_department_ids_by_space_ids",
            new_callable=AsyncMock,
            return_value={101: 10},
        ),
        patch.object(
            service,
            "_format_member_spaces",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_format,
    ):
        await service.get_my_created_spaces()

    mock_format.assert_awaited_once_with([normal_member], "update_time")


async def test_unsubscribe_space_blocks_creator(
    service: KnowledgeSpaceService,
) -> None:
    owned_space = _make_space(user_id=service.login_user.user_id)
    creator_member = _make_member(
        user_id=service.login_user.user_id,
        user_role=UserRoleEnum.CREATOR,
        space_id=1,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=owned_space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_find_member",
            new_callable=AsyncMock,
            return_value=creator_member,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.delete_space_member",
            new_callable=AsyncMock,
        ) as mock_delete_member,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.unsubscribe_space(1)

    mock_delete_member.assert_not_awaited()
