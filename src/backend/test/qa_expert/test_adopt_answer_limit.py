# ruff: noqa: RUF002
"""同题最多 3 个最佳答案：上限拦截、已采纳幂等、软删不计上限。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.qa_expert.domain.services import (
    MAX_ADOPTED_ANSWERS_PER_QUESTION,
    AdoptLimitExceededError,
    QuestionService,
)


def _question(*, question_id: int = 100, user_id: int = 1, adopt_count: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=question_id,
        user_id=user_id,
        adopted_answer_id=None,
        status=0,
        adopt_count=adopt_count,
        answer_count=1,
        question_type="public",
        resolved_at=None,
        tenant_id=1,
        display_status=None,
    )


def _answer(
    *,
    answer_id: int,
    question_id: int = 100,
    expert_id: int = 5,
    adopted: bool = False,
    status: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=answer_id,
        question_id=question_id,
        expert_id=expert_id,
        user_id=55,
        adopted=adopted,
        status=status,
    )


def _service() -> QuestionService:
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.answer_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.adopt_repo = MagicMock()
    svc.eligibility_repo = MagicMock()
    svc.adopt_repo.create = AsyncMock()
    svc.eligibility_repo.create_many = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.answer_repo.list_all_by_question_id = AsyncMock(return_value=[])
    svc.answer_repo.update = AsyncMock()
    svc._send_adoption_notification = AsyncMock()

    async def fake_apply(question_id: int, **kwargs):
        q = await svc.repository.get_by_id_for_update(question_id)
        current = int(getattr(q, "adopt_count", 0) or 0)
        is_first = current == 0
        q.adopt_count = current + 1
        q.status = 1
        q.adopted_answer_id = kwargs["answer_id"]
        if is_first:
            q.resolved_at = datetime.utcnow()
        await svc.repository.update(
            question_id,
            adopted_answer_id=q.adopted_answer_id,
            status=1,
            adopt_count=q.adopt_count,
            resolved_at=q.resolved_at,
        )
        await svc.answer_repo.update(kwargs["answer_id"], status=1, adopted=True)
        return SimpleNamespace(question=q, status="ok", is_first=is_first)

    svc.repository.apply_adopt_count_locked = AsyncMock(side_effect=fake_apply)
    return svc


@pytest.mark.asyncio
async def test_adopt_first_three_succeeds():
    svc = _service()
    q = _question()
    svc.repository.get_by_id_for_update = AsyncMock(return_value=q)
    svc.repository.update = AsyncMock(return_value=q)
    svc.answer_repo.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()
    svc.expert_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=55))

    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ) as notify:
        for answer_id in (11, 12, 13):
            svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=answer_id, adopted=False))
            result = await svc.adopt_answer(100, answer_id, operator_id=1)
            assert result is q

    assert svc.expert_repo.increment_adoption_count.await_count == 3
    assert notify.await_count == 3


@pytest.mark.asyncio
async def test_adopt_fourth_raises_limit():
    svc = _service()
    svc.repository.get_by_id_for_update = AsyncMock(
        return_value=_question(adopt_count=MAX_ADOPTED_ANSWERS_PER_QUESTION)
    )
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=14, adopted=False))
    svc.repository.update = AsyncMock()
    svc.answer_repo.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()

    with pytest.raises(AdoptLimitExceededError):
        await svc.adopt_answer(100, 14, operator_id=1)

    svc.repository.update.assert_not_awaited()
    svc.expert_repo.increment_adoption_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_adopted_is_idempotent():
    svc = _service()
    q = _question(question_id=100)
    svc.repository.get_by_id_for_update = AsyncMock(return_value=q)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=11, adopted=True, status=1))
    svc.answer_repo.count_adopted_by_question_id = AsyncMock()
    svc.repository.update = AsyncMock()
    svc.answer_repo.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()

    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ) as notify:
        result = await svc.adopt_answer(100, 11, operator_id=1)

    assert result is q
    svc.answer_repo.count_adopted_by_question_id.assert_not_awaited()
    svc.expert_repo.increment_adoption_count.assert_not_awaited()
    svc._send_adoption_notification.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_deleted_adopted_not_counted_in_limit_path():
    """软删回答不计上限：count 由仓储过滤；此处验证 count=2 时仍可采纳第 3 条。"""
    svc = _service()
    q = _question(adopt_count=2)
    svc.repository.get_by_id_for_update = AsyncMock(return_value=q)
    svc.repository.update = AsyncMock(return_value=q)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=20, adopted=False))
    svc.answer_repo.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()
    svc.expert_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=55))

    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ):
        await svc.adopt_answer(100, 20, operator_id=1)

    svc.repository.update.assert_awaited_once()
    svc.expert_repo.increment_adoption_count.assert_awaited_once()
