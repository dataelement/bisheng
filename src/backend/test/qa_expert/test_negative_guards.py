# ruff: noqa: RUF002
"""T022：无 closed 状态写入；专家库管理员不是超管；moderate-delete 拒绝门户管理员。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.points import PointsPermissionDeniedError
from bisheng.points.domain.services.points_auth import is_platform_super_admin
from bisheng.qa_expert.domain.capability import is_expert_library_admin
from bisheng.qa_expert.domain.moderate_delete_service import ModerateDeleteService
from bisheng.qa_expert.domain.question_query import question_display_status
from bisheng.qa_expert.domain.schemas import QuestionCreateRequest
from bisheng.qa_expert.domain.services import QuestionService


def test_display_status_never_closed():
    q = SimpleNamespace(adopt_count=0, answer_count=0)
    assert question_display_status(q) == "unanswered"
    q.answer_count = 2
    assert question_display_status(q) == "pending_adopt"
    q.adopt_count = 1
    assert question_display_status(q) == "solved"
    assert question_display_status(q) != "closed"


def test_portal_admin_role_is_not_global_super():
    user = SimpleNamespace(
        user_id=3,
        user_name="portal-admin",
        role="管理员",
        is_admin=lambda: False,
        is_global_super=False,
    )
    assert is_expert_library_admin(user) is True
    assert is_platform_super_admin(user) is False


@pytest.mark.asyncio
async def test_expert_library_admin_cannot_moderate_delete():
    svc = ModerateDeleteService()
    svc.question_repo = MagicMock()
    operator = SimpleNamespace(
        user_id=3,
        role="管理员",
        is_admin=lambda: False,
        is_global_super=False,
    )
    with pytest.raises(PointsPermissionDeniedError):
        await svc.moderate_delete(operator=operator, target_type="question", target_id=1)


async def test_create_question_does_not_write_closed_status():
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.invite_repo.create_many = AsyncMock()
    svc._send_expert_invitation_inbox_notice = AsyncMock()
    svc._resolve_question = AsyncMock(side_effect=lambda q: q)

    captured = {}

    async def fake_create(question):
        captured["status"] = getattr(question, "status", None)
        question.id = 1
        return question

    svc.repository.create = AsyncMock(side_effect=fake_create)
    from unittest.mock import patch

    req = QuestionCreateRequest(title="t", description="d", business_domain="steel")
    with patch("bisheng.qa_expert.domain.services.RealtimeQaQuestionFact.record_success", new_callable=AsyncMock):
        await svc.create_question(1, req, "asker", tenant_id=1)
    assert captured.get("status") in (None, 0)
    assert captured.get("status") != 2
