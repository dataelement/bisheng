# ruff: noqa: RUF002
"""T008：首答锁（仓储全 mock）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.qa_expert import QaExpertAnonymousRevealRequiredError, QaExpertContentLockedError
from bisheng.database.models.qa_expert import Answer, Expert, Question
from bisheng.qa_expert.domain.schemas import AnswerCreateRequest, QuestionUpdateRequest
from bisheng.qa_expert.domain.services import AnswerService, QuestionService


def _question(**kwargs) -> Question:
    data = {
        "id": 9,
        "user_id": 1,
        "title": "炼钢",
        "description": "描述",
        "business_domain": "steel",
        "question_type": "public",
        "content_locked": 0,
        "answer_count": 0,
        "adopt_count": 0,
    }
    data.update(kwargs)
    return Question(**data)


def _expert(*, expert_id: int = 3, user_id: int = 8, status: int = 1) -> Expert:
    return Expert(id=expert_id, user_id=user_id, expert_name=f"专家{expert_id}", status=status)


def _answer_service() -> AnswerService:
    svc = AnswerService()
    svc.repository = MagicMock()
    svc.question_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.question_repo.try_lock_content = AsyncMock(return_value=True)
    svc.question_repo.update = AsyncMock()
    svc.question_repo.increment_answer_count = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.expert_repo.increment_answer_count = AsyncMock()
    svc.expert_repo.get_by_id = AsyncMock(return_value=_expert())
    svc._send_answer_notification = AsyncMock()
    svc._resolve_answer = AsyncMock(side_effect=lambda answer: answer)
    return svc


async def _submit(svc: AnswerService, *, user_id: int = 8, question_id: int = 9) -> Answer:
    next_id = {"n": 10}

    async def fake_create(answer: Answer) -> Answer:
        next_id["n"] += 1
        answer.id = next_id["n"]
        return answer

    svc.repository.create = AsyncMock(side_effect=fake_create)
    return await svc.create_answer(
        user_id,
        AnswerCreateRequest(question_id=question_id, content="有效回答"),
        tenant_id=1,
    )


async def test_first_valid_answer_locks_content():
    svc = _answer_service()
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=_expert())
    answer = await _submit(svc)
    assert answer.id is not None
    persisted: Answer = svc.repository.create.await_args.args[0]
    assert persisted.user_id == 8
    svc.question_repo.try_lock_content.assert_awaited_once_with(9)
    svc.question_repo.increment_answer_count.assert_awaited_once_with(9)


async def test_concurrent_first_answers_both_succeed_lock_once():
    svc = _answer_service()
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    experts = {
        8: _expert(expert_id=3, user_id=8),
        9: _expert(expert_id=4, user_id=9),
    }
    svc.expert_repo.get_by_user_id = AsyncMock(side_effect=lambda uid: experts[uid])
    locked = {"v": 0}

    async def fake_lock(_question_id: int) -> bool:
        if locked["v"] == 0:
            locked["v"] = 1
            return True
        return False

    svc.question_repo.try_lock_content = AsyncMock(side_effect=fake_lock)
    next_id = {"n": 10}

    async def fake_create(answer: Answer) -> Answer:
        next_id["n"] += 1
        answer.id = next_id["n"]
        return answer

    svc.repository.create = AsyncMock(side_effect=fake_create)
    request = AnswerCreateRequest(question_id=9, content="有效回答")
    first = await svc.create_answer(8, request, tenant_id=1)
    second = await svc.create_answer(9, request, tenant_id=1)
    assert first.id != second.id
    assert svc.question_repo.try_lock_content.await_count == 2
    assert locked["v"] == 1


async def test_delete_all_unadopted_does_not_unlock():
    svc = _answer_service()
    question = SimpleNamespace(id=9, user_id=1, content_locked=1, answer_count=1)
    answer = SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1)
    svc.repository.get_by_id = AsyncMock(return_value=answer)
    svc.repository.delete = AsyncMock(return_value=True)
    svc.question_repo.get_by_id = AsyncMock(return_value=question)
    assert await svc.delete_answer(11, 8) is True
    svc.question_repo.update.assert_awaited()
    kwargs = svc.question_repo.update.await_args.kwargs
    assert kwargs.get("answer_count") == 0
    assert "content_locked" not in kwargs


async def test_update_question_rejected_when_locked():
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.repository.get_by_id = AsyncMock(return_value=_question(content_locked=1))
    with pytest.raises(QaExpertContentLockedError):
        await svc.update_question(9, QuestionUpdateRequest(title="改标题"))
    svc.repository.update.assert_not_called()


async def test_submit_answer_persists_anonymous_choice():
    """专家回答可选择匿名；未匿名不落 reveal。"""
    svc = _answer_service()
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=_expert())

    async def fake_create(answer: Answer) -> Answer:
        answer.id = 11
        return answer

    svc.repository.create = AsyncMock(side_effect=fake_create)
    await svc.create_answer(
        8,
        AnswerCreateRequest(question_id=9, content="匿名答", anonymous=True),
        tenant_id=1,
    )
    persisted: Answer = svc.repository.create.await_args.args[0]
    assert persisted.anonymous == 1
    assert persisted.reveal_on_public is None


async def test_directed_anonymous_answer_requires_reveal():
    """定向匿名回答未选转公开姓名则拒绝，不写 qa_answer。"""
    svc = _answer_service()
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(question_type="directed"))
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=_expert())
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={9: {8}})
    svc.repository.create = AsyncMock()
    with pytest.raises(QaExpertAnonymousRevealRequiredError):
        await svc.create_answer(
            8,
            AnswerCreateRequest(question_id=9, content="定向匿名答", anonymous=True),
            tenant_id=1,
        )
    svc.repository.create.assert_not_awaited()
