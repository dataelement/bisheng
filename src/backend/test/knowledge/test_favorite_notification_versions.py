from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED,
    FAVORITE_SOURCE_VERSION_ADDED,
    FAVORITE_SOURCE_VERSION_DELETED,
    FAVORITE_SOURCE_VERSION_LINKED,
    FAVORITE_SOURCE_VERSION_UNLINKED,
)
from bisheng.knowledge.domain.services.knowledge_version_service import (
    KnowledgeVersionService,
)


def _service():
    service = KnowledgeVersionService.__new__(KnowledgeVersionService)
    service.login_user = SimpleNamespace(
        user_id=7,
        user_name="编辑者",
        tenant_id=1,
    )
    return service


@pytest.mark.parametrize(
    "action_code",
    [
        FAVORITE_SOURCE_VERSION_LINKED,
        FAVORITE_SOURCE_VERSION_ADDED,
        FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED,
        FAVORITE_SOURCE_VERSION_DELETED,
    ],
)
async def test_version_change_enqueues_action_specific_events(action_code):
    service = _service()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_version_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await service._notify_favorite_version_changed(
            [(101, "制度.pdf", 10), (101, "重复.pdf", 10)],
            action_code=action_code,
            before_value="V1",
            after_value="V2",
        )

    events = enqueue.call_args.args[0]
    assert len(events) == 1
    assert events[0].action_code == action_code
    assert events[0].before_value == "V1"
    assert events[0].after_value == "V2"
    assert events[0].source_space_id == 10


async def test_version_change_noop_when_values_are_equal():
    service = _service()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_version_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await service._notify_favorite_version_changed(
            [(101, "制度.pdf", 10)],
            action_code=FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED,
            before_value="V2",
            after_value="V2",
        )

    enqueue.assert_not_called()


def test_version_unlinked_is_reserved_constant_only():
    assert FAVORITE_SOURCE_VERSION_UNLINKED == "favorite_source_version_unlinked"
