from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.knowledge_parse_priority import (
    KnowledgeParsePriority,
)
from bisheng.role.domain.services.knowledge_parse_priority_service import (
    KnowledgeParsePriorityService,
)


class FakeRolePriorityRepository:
    def __init__(
        self,
        *,
        user_exists: bool = True,
        configs: list[dict | None] | None = None,
    ) -> None:
        self._user_exists = user_exists
        self._configs = configs or []

    async def user_exists(self, user_id: int) -> bool:
        return self._user_exists

    async def list_role_quota_configs(self, user_id: int) -> list[dict | None]:
        return self._configs


def test_priority_transport_mapping_is_stable() -> None:
    assert KnowledgeParsePriority.HIGH.celery_priority == 0
    assert KnowledgeParsePriority.MEDIUM.celery_priority == 3
    assert KnowledgeParsePriority.LOW.celery_priority == 9
    assert KnowledgeParsePriority.HIGH.rank > KnowledgeParsePriority.MEDIUM.rank
    assert KnowledgeParsePriority.MEDIUM.rank > KnowledgeParsePriority.LOW.rank


@pytest.mark.parametrize(
    ("configs", "expected"),
    [
        ([{"knowledge_file_parse_priority": "low"}], KnowledgeParsePriority.LOW),
        ([None], KnowledgeParsePriority.MEDIUM),
        ([], KnowledgeParsePriority.MEDIUM),
        (
            [
                {"knowledge_file_parse_priority": "low"},
                {"knowledge_file_parse_priority": "high"},
            ],
            KnowledgeParsePriority.HIGH,
        ),
    ],
    ids=["low", "missing-key", "no-role", "multi-role-highest"],
)
async def test_resolve_uses_highest_tenant_role(
    configs: list[dict | None],
    expected: KnowledgeParsePriority,
) -> None:
    service = KnowledgeParsePriorityService(FakeRolePriorityRepository(configs=configs))

    assert await service.resolve(user_id=9, is_global_super=False) is expected


async def test_resolve_global_super_is_high_without_repository_reads() -> None:
    repository = FakeRolePriorityRepository(user_exists=False)
    repository.user_exists = AsyncMock(side_effect=AssertionError("must not read"))
    service = KnowledgeParsePriorityService(repository)

    assert await service.resolve(user_id=1, is_global_super=True) is KnowledgeParsePriority.HIGH


@pytest.mark.parametrize(
    ("user_id", "user_exists"),
    [(None, False), (7, False)],
    ids=["no-user", "missing-user"],
)
async def test_resolve_missing_identity_is_low(
    user_id: int | None,
    user_exists: bool,
) -> None:
    service = KnowledgeParsePriorityService(FakeRolePriorityRepository(user_exists=user_exists))

    assert await service.resolve(user_id=user_id, is_global_super=False) is KnowledgeParsePriority.LOW


async def test_resolve_dependency_failure_degrades_to_low(caplog) -> None:
    repository = FakeRolePriorityRepository()
    repository.user_exists = AsyncMock(side_effect=RuntimeError("db unavailable"))
    service = KnowledgeParsePriorityService(repository)

    result = await service.resolve(user_id=8, is_global_super=False)

    assert result is KnowledgeParsePriority.LOW
    assert "knowledge parse priority resolution failed" in caplog.text
