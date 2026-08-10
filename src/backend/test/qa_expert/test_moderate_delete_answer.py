"""平台超管违规删除回答：作者解析、软删、级联评论、采纳指针与可选扣分。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.points import PointsPermissionDeniedError
from bisheng.qa_expert.domain.moderate_delete_service import ModerateDeleteService
from bisheng.qa_expert.domain.schemas import ModerateDeleteRequest
from bisheng.qa_expert.domain.services import AnswerNotFoundError, ExpertNotFoundError


def _admin_user(user_id: int = 1):
    return SimpleNamespace(user_id=user_id, is_global_super=True, is_admin=lambda: True)


def _normal_user(user_id: int = 2):
    return SimpleNamespace(user_id=user_id, is_global_super=False, is_admin=lambda: False)


def _service_with_mocks() -> tuple[ModerateDeleteService, MagicMock]:
    """构造 service 并替换仓储/扣分依赖为 AsyncMock。"""
    svc = ModerateDeleteService()
    svc.question_repo = MagicMock()
    svc.answer_repo = MagicMock()
    svc.comment_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.pending_deduct = MagicMock()
    return svc, svc.pending_deduct


def test_schema_accepts_answer_target_type():
    req = ModerateDeleteRequest(target_type="answer", target_id=9)
    assert req.target_type == "answer"


def test_schema_rejects_unknown_target_type():
    with pytest.raises(ValidationError):
        ModerateDeleteRequest(target_type="vote", target_id=1)


@pytest.mark.asyncio
async def test_non_admin_rejected():
    svc, _ = _service_with_mocks()
    with pytest.raises(PointsPermissionDeniedError):
        await svc.moderate_delete(
            operator=_normal_user(),
            target_type="answer",
            target_id=1,
        )


@pytest.mark.asyncio
async def test_delete_answer_no_rule_cascades_and_clears_adopted():
    svc, pending = _service_with_mocks()
    svc.answer_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=10,
            question_id=100,
            expert_id=5,
            status=2,
        )
    )
    svc.expert_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=5, user_id=55)
    )
    svc.answer_repo.delete = AsyncMock(return_value=True)
    svc.comment_repo.delete_by_answer_id = AsyncMock(return_value=3)
    svc.question_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=100,
            answer_count=2,
            adopted_answer_id=10,
            status=1,
        )
    )
    svc.question_repo.update = AsyncMock(return_value=True)

    result = await svc.moderate_delete(
        operator=_admin_user(),
        target_type="answer",
        target_id=10,
        rule_code=None,
    )

    assert result.deleted is True
    assert result.target_type == "answer"
    assert result.target_user_id == 55
    assert result.deducted is False
    assert result.reason == "no_rule"
    svc.answer_repo.delete.assert_awaited_once_with(10)
    svc.comment_repo.delete_by_answer_id.assert_awaited_once_with(10)
    svc.question_repo.update.assert_awaited_once_with(
        100,
        answer_count=1,
        adopted_answer_id=None,
        status=0,
    )
    pending.deduct_or_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_delete_answer_with_rule_uses_qa_answer_biz_type():
    svc, pending = _service_with_mocks()
    svc.answer_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=11,
            question_id=101,
            expert_id=6,
            status=1,
        )
    )
    svc.expert_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=6, user_id=66)
    )
    svc.answer_repo.delete = AsyncMock(return_value=True)
    svc.comment_repo.delete_by_answer_id = AsyncMock(return_value=0)
    svc.question_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=101,
            answer_count=1,
            adopted_answer_id=None,
            status=0,
        )
    )
    svc.question_repo.update = AsyncMock(return_value=True)
    pending.deduct_or_enqueue = AsyncMock(
        return_value=SimpleNamespace(applied=True, pending=False, reason=None)
    )

    result = await svc.moderate_delete(
        operator=_admin_user(user_id=9),
        target_type="answer",
        target_id=11,
        rule_code="r1",
        remark="违规",
    )

    assert result.deducted is True
    assert result.pending_deduct is False
    pending.deduct_or_enqueue.assert_awaited_once()
    kwargs = pending.deduct_or_enqueue.await_args.kwargs
    assert kwargs["user_id"] == 66
    assert kwargs["rule_code"] == "R1"
    assert kwargs["biz_type"] == "qa_answer"
    assert kwargs["biz_id"] == "11"
    assert kwargs["operator_id"] == 9
    assert kwargs["remark"] == "违规"
    svc.question_repo.update.assert_awaited_once_with(101, answer_count=0)


@pytest.mark.asyncio
async def test_delete_missing_answer_raises():
    svc, _ = _service_with_mocks()
    svc.answer_repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(AnswerNotFoundError):
        await svc.moderate_delete(
            operator=_admin_user(),
            target_type="answer",
            target_id=999,
        )


@pytest.mark.asyncio
async def test_delete_answer_without_expert_raises():
    svc, _ = _service_with_mocks()
    svc.answer_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=12,
            question_id=102,
            expert_id=None,
            status=1,
        )
    )
    with pytest.raises(ExpertNotFoundError):
        await svc.moderate_delete(
            operator=_admin_user(),
            target_type="answer",
            target_id=12,
        )
