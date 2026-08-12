"""同题最多 3 个最佳答案：上限拦截、已采纳幂等、软删不计上限。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.qa_expert.domain.services import (
    AdoptLimitExceededError,
    MAX_ADOPTED_ANSWERS_PER_QUESTION,
    QuestionService,
)


def _question(*, question_id: int = 100, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=question_id,
        user_id=user_id,
        adopted_answer_id=None,
        status=0,
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
        adopted=adopted,
        status=status,
    )


def _service() -> QuestionService:
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.answer_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc._send_adoption_notification = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_adopt_first_three_succeeds():
    svc = _service()
    q = _question()
    svc.repository.get_by_id = AsyncMock(return_value=q)
    svc.repository.update = AsyncMock(return_value=q)
    svc.answer_repo.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()
    svc.expert_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=55))

    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ) as notify:
        for idx, answer_id in enumerate((11, 12, 13), start=0):
            svc.answer_repo.get_by_id = AsyncMock(
                return_value=_answer(answer_id=answer_id, adopted=False)
            )
            svc.answer_repo.count_adopted_by_question_id = AsyncMock(return_value=idx)
            result = await svc.adopt_answer(100, answer_id, operator_id=1)
            assert result is q

    assert svc.expert_repo.increment_adoption_count.await_count == 3
    assert notify.await_count == 3


@pytest.mark.asyncio
async def test_adopt_fourth_raises_limit():
    svc = _service()
    svc.repository.get_by_id = AsyncMock(return_value=_question())
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=14, adopted=False))
    svc.answer_repo.count_adopted_by_question_id = AsyncMock(
        return_value=MAX_ADOPTED_ANSWERS_PER_QUESTION
    )
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
    svc.repository.get_by_id = AsyncMock(return_value=q)
    svc.answer_repo.get_by_id = AsyncMock(
        return_value=_answer(answer_id=11, adopted=True, status=1)
    )
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
    q = _question()
    svc.repository.get_by_id = AsyncMock(return_value=q)
    svc.repository.update = AsyncMock(return_value=q)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(answer_id=20, adopted=False))
    # 仓储已排除 status=3，故返回 2（含 1 条软删场景下真实未删除已采纳数）
    svc.answer_repo.count_adopted_by_question_id = AsyncMock(return_value=2)
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
