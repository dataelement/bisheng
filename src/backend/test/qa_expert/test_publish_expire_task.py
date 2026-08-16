# ruff: noqa: RUF002
"""T031：转公开到期任务。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.qa_expert.domain.publish_service import PUBLISH_EXPIRED, PublishService


async def test_expire_pending_marks_expired_and_notifies():
    svc = PublishService()
    svc.request_repo = MagicMock()
    svc.question_repo = MagicMock()
    svc.notify = AsyncMock()
    now = datetime(2026, 8, 20, 12, 0, 0)
    row = SimpleNamespace(
        id=4,
        question_id=20,
        status="pending",
        expire_at=datetime(2026, 8, 18, 12, 0, 0),
        tenant_id=1,
    )
    svc.request_repo.list_expired_pending = AsyncMock(return_value=[row])
    svc.question_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=20, title="定向", user_id=1, active_publish_request_id=4)
    )
    svc.request_repo.update = AsyncMock()
    svc.question_repo.update = AsyncMock()
    count = await svc.expire_pending(now=now, tenant_id=1)
    assert count == 1
    assert svc.request_repo.update.await_args.kwargs["status"] == PUBLISH_EXPIRED
    svc.notify.assert_awaited()
