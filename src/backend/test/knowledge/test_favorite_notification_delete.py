from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.knowledge.domain.services.favorite_notify import (
    collect_favorite_recipient_snapshots,
)


def _reference(user_id: int, favorite_space_id: int, source_file_id: int):
    return SimpleNamespace(
        user_id=user_id,
        knowledge_id=favorite_space_id,
        tenant_id=1,
        user_metadata={
            "favorite_reference": {
                "source_space_id": 10,
                "source_file_id": source_file_id,
            }
        },
    )


async def test_delete_snapshot_filters_permission_actor_and_duplicates_before_mutation():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(
            return_value=[
                _reference(11, 101, 20),
                _reference(11, 101, 20),
                _reference(12, 102, 20),
                _reference(7, 107, 20),
            ]
        )
    )
    can_view_file = AsyncMock(side_effect=lambda user_id, _file: user_id == 11)
    source = SimpleNamespace(id=20, knowledge_id=10, tenant_id=1)

    snapshots = await collect_favorite_recipient_snapshots(
        file_repository=repository,
        source_files=[source],
        actor_user_id=7,
        can_view_file=can_view_file,
    )

    assert [item.model_dump() for item in snapshots[20]] == [
        {"user_id": 11, "favorite_space_id": 101}
    ]
    repository.find_favorite_referrers_by_source_file_ids.assert_awaited_once_with(
        [20]
    )


async def test_delete_snapshot_fails_closed_on_permission_error():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(
            return_value=[_reference(11, 101, 20)]
        )
    )

    snapshots = await collect_favorite_recipient_snapshots(
        file_repository=repository,
        source_files=[SimpleNamespace(id=20, knowledge_id=10, tenant_id=1)],
        actor_user_id=7,
        can_view_file=AsyncMock(side_effect=RuntimeError("permission unavailable")),
    )

    assert snapshots[20] == []
