# ruff: noqa: RUF002
"""T012：采纳槽位、首次已解决、公开题资格快照（仓储全 mock）。"""

import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.qa_expert import QaExpertAdoptLimitError, QaExpertAnswerNotAllowedError
from bisheng.database.models.qa_expert import Answer, AnswerAdopt, AnswerEligibility, Question
from bisheng.qa_expert.domain.capability import DISPLAY_SOLVED
from bisheng.qa_expert.domain.schemas import AnswerCreateRequest
from bisheng.qa_expert.domain.services import (
    MAX_ADOPTED_ANSWERS_PER_QUESTION,
    AnswerService,
    QuestionService,
)


def _question(**kwargs) -> SimpleNamespace:
    data = {
        "id": 100,
        "user_id": 1,
        "title": "炼钢",
        "question_type": "public",
        "adopt_count": 0,
        "answer_count": 2,
        "status": 0,
        "resolved_at": None,
        "adopted_answer_id": None,
        "tenant_id": 1,
        "display_status": None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _answer(**kwargs) -> SimpleNamespace:
    data = {
        "id": 11,
        "question_id": 100,
        "expert_id": 5,
        "user_id": 55,
        "adopted": False,
        "status": 1,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


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
    svc.repository.update = AsyncMock()
    svc.expert_repo.increment_adoption_count = AsyncMock()
    svc.expert_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=55))
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
        await svc.adopt_repo.create(
            AnswerAdopt(
                tenant_id=kwargs.get("tenant_id") or 1,
                question_id=question_id,
                answer_id=kwargs["answer_id"],
                expert_user_id=kwargs["expert_user_id"],
                adopted_by=kwargs["adopted_by"],
            )
        )
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


async def test_first_adopt_marks_resolved_and_writes_slot():
    svc = _service()
    question = _question()
    svc.repository.get_by_id_for_update = AsyncMock(return_value=question)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer())
    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ) as notify:
        result = await svc.adopt_answer(100, 11, operator_id=1)
    assert result.adopt_count == 1
    assert result.status == 1
    assert result.resolved_at is not None
    assert result.display_status == DISPLAY_SOLVED
    slot: AnswerAdopt = svc.adopt_repo.create.await_args.args[0]
    assert slot.answer_id == 11
    assert slot.question_id == 100
    assert slot.expert_user_id == 55
    assert slot.adopted_by == 1
    notify.assert_awaited_once()
    source = inspect.getsource(QuestionService.adopt_answer)
    assert "user_point_log" not in source
    assert "notify_answer_adopted" in source


async def test_fourth_adopt_raises_18304():
    svc = _service()
    svc.repository.get_by_id_for_update = AsyncMock(
        return_value=_question(adopt_count=MAX_ADOPTED_ANSWERS_PER_QUESTION)
    )
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(id=14))
    with pytest.raises(QaExpertAdoptLimitError) as exc:
        await svc.adopt_answer(100, 14, operator_id=1)
    assert exc.value.Code == 18304
    svc.adopt_repo.create.assert_not_awaited()
    svc.repository.update.assert_not_awaited()


async def test_same_expert_multiple_answers_fill_multiple_slots():
    svc = _service()
    question = _question(adopt_count=0)
    svc.repository.get_by_id_for_update = AsyncMock(return_value=question)
    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ) as notify:
        svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(id=11, expert_id=5, user_id=55))
        await svc.adopt_answer(100, 11, operator_id=1)
        svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(id=12, expert_id=5, user_id=55))
        await svc.adopt_answer(100, 12, operator_id=1)
    answer_ids = [call.args[0].answer_id for call in svc.adopt_repo.create.await_args_list]
    assert answer_ids == [11, 12]
    assert [call.args[0].expert_user_id for call in svc.adopt_repo.create.await_args_list] == [55, 55]
    assert notify.await_count == 2
    assert question.adopt_count == 2


async def test_public_first_adopt_writes_eligibility_including_deleted_author():
    svc = _service()
    question = _question(question_type="public", adopt_count=0)
    svc.repository.get_by_id_for_update = AsyncMock(return_value=question)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer(id=11, user_id=55))
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={100: {70}})
    svc.answer_repo.list_all_by_question_id = AsyncMock(
        return_value=[
            _answer(id=11, user_id=55, status=1),
            _answer(id=99, user_id=80, expert_id=9, status=3, adopted=False),
        ]
    )
    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ):
        await svc.adopt_answer(100, 11, operator_id=1)
    rows: list[AnswerEligibility] = svc.eligibility_repo.create_many.await_args.args[0]
    by_user = {int(row.user_id): row.source for row in rows}
    assert by_user[70] == "invited"
    assert by_user[55] == "pre_adopt_answer"
    assert by_user[80] == "pre_adopt_answer"


async def test_directed_first_adopt_skips_eligibility():
    svc = _service()
    question = _question(question_type="directed", adopt_count=0)
    svc.repository.get_by_id_for_update = AsyncMock(return_value=question)
    svc.answer_repo.get_by_id = AsyncMock(return_value=_answer())
    with patch(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        new_callable=AsyncMock,
    ):
        await svc.adopt_answer(100, 11, operator_id=1)
    svc.eligibility_repo.create_many.assert_not_awaited()


async def test_public_after_adopt_only_snapshot_experts_can_answer():
    svc = AnswerService()
    svc.repository = MagicMock()
    svc.question_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.eligibility_repo = MagicMock()
    svc.question_repo.try_lock_content = AsyncMock(return_value=False)
    svc.question_repo.update = AsyncMock()
    svc.question_repo.increment_answer_count = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.eligibility_repo.list_user_ids = AsyncMock(return_value={55})
    svc.expert_repo.increment_answer_count = AsyncMock()
    svc._send_answer_notification = AsyncMock()
    svc._resolve_answer = AsyncMock(side_effect=lambda answer: answer)
    question = Question(
        id=100,
        user_id=1,
        title="t",
        description="d",
        business_domain="steel",
        question_type="public",
        adopt_count=1,
        answer_count=1,
    )
    svc.question_repo.get_by_id = AsyncMock(return_value=question)
    outsider = SimpleNamespace(id=9, user_id=99, status=1, expert_name="外人")
    insider = SimpleNamespace(id=5, user_id=55, status=1, expert_name="快照内")
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=outsider)
    with pytest.raises(QaExpertAnswerNotAllowedError):
        await svc.create_answer(99, AnswerCreateRequest(question_id=100, content="不可答"), tenant_id=1)
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=insider)

    async def fake_create(answer: Answer) -> Answer:
        answer.id = 30
        return answer

    svc.repository.create = AsyncMock(side_effect=fake_create)
    allowed = await svc.create_answer(55, AnswerCreateRequest(question_id=100, content="可答"), tenant_id=1)
    assert allowed.id == 30
