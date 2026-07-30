from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_BUSINESS_DOMAIN_UPDATED,
    FAVORITE_SOURCE_MOVED,
    FAVORITE_SOURCE_RENAMED,
    FAVORITE_SOURCE_SUBCATEGORY_UPDATED,
    FAVORITE_SOURCE_TAGS_UPDATED,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _service():
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(
        user_id=7,
        user_name="编辑者",
        tenant_id=1,
    )
    return service


@pytest.mark.parametrize(
    ("action_code", "before_value", "after_value"),
    [
        (FAVORITE_SOURCE_RENAMED, "旧制度.pdf", "新制度.pdf"),
        (FAVORITE_SOURCE_MOVED, "制度库/旧目录", "制度库/新目录"),
        (FAVORITE_SOURCE_TAGS_UPDATED, ["安全", "生产"], ["安全", "质量"]),
        (FAVORITE_SOURCE_BUSINESS_DOMAIN_UPDATED, "财务", "人力资源"),
        (FAVORITE_SOURCE_SUBCATEGORY_UPDATED, "制度", "标准"),
    ],
)
async def test_document_change_enqueues_one_field_event(
    action_code,
    before_value,
    after_value,
):
    service = _service()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await KnowledgeSpaceService._notify_favorite_source_changed(
            service,
            source_space_id=10,
            source_file_id=20,
            file_name="新制度.pdf",
            action_code=action_code,
            before_value=before_value,
            after_value=after_value,
        )

    event = enqueue.call_args.args[0][0]
    assert event.tenant_id == 1
    assert event.source_space_id == 10
    assert event.source_file_id == 20
    assert event.action_code == action_code
    assert event.before_value == before_value
    assert event.after_value == after_value


async def test_document_change_does_not_enqueue_equal_values():
    service = _service()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "enqueue_favorite_change_events"
    ) as enqueue:
        await KnowledgeSpaceService._notify_favorite_source_changed(
            service,
            source_space_id=10,
            source_file_id=20,
            file_name="制度.pdf",
            action_code=FAVORITE_SOURCE_TAGS_UPDATED,
            before_value=["安全", "生产"],
            after_value=["生产", "安全", "安全"],
        )

    enqueue.assert_not_called()


async def test_document_change_broker_failure_does_not_escape():
    service = _service()

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "enqueue_favorite_change_events",
        side_effect=RuntimeError("broker unavailable"),
    ):
        await KnowledgeSpaceService._notify_favorite_source_changed(
            service,
            source_space_id=10,
            source_file_id=20,
            file_name="新制度.pdf",
            action_code=FAVORITE_SOURCE_RENAMED,
            before_value="旧制度.pdf",
            after_value="新制度.pdf",
        )
