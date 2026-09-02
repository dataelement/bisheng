# ruff: noqa: RUF002
"""作者删答：未采纳可删并级联评论；已采纳/转公开 pending 拒绝。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.qa_expert import QaExpertAnswerDeleteNotAllowedError, QaExpertQuestionAccessDeniedError
from bisheng.qa_expert.domain.services import AnswerService, CommentService, PermissionDeniedError


def _answer_service() -> AnswerService:
    svc = AnswerService()
    svc.repository = MagicMock()
    svc.question_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.comment_repo = MagicMock()
    svc.publish_request_repo = MagicMock()
    svc.comment_repo.delete_by_answer_id = AsyncMock(return_value=2)
    svc.publish_request_repo.get_pending_by_question = AsyncMock(return_value=None)
    svc.publish_refresher = AsyncMock()
    svc.question_repo.update = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.expert_repo.increment_answer_count = AsyncMock()
    return svc


async def test_author_deletes_unadopted_and_cascades_comments():
    svc = _answer_service()
    question = SimpleNamespace(id=9, user_id=1, content_locked=1, answer_count=1)
    answer = SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=False)
    svc.repository.get_by_id = AsyncMock(return_value=answer)
    svc.repository.delete = AsyncMock(return_value=True)
    svc.question_repo.get_by_id = AsyncMock(return_value=question)
    assert await svc.delete_answer(11, 8) is True
    svc.comment_repo.delete_by_answer_id.assert_awaited_once_with(11)
    kwargs = svc.question_repo.update.await_args.kwargs
    assert kwargs.get("answer_count") == 0
    assert "content_locked" not in kwargs
    svc.expert_repo.increment_answer_count.assert_awaited_once_with(3, count=-1)


async def test_non_author_cannot_delete():
    svc = _answer_service()
    svc.repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=False)
    )
    svc.repository.delete = AsyncMock()
    with pytest.raises(PermissionDeniedError):
        await svc.delete_answer(11, 99)
    svc.repository.delete.assert_not_awaited()
    svc.expert_repo.increment_answer_count.assert_not_awaited()


async def test_adopted_answer_cannot_delete():
    svc = _answer_service()
    svc.repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=True)
    )
    svc.repository.delete = AsyncMock()
    with pytest.raises(QaExpertAnswerDeleteNotAllowedError):
        await svc.delete_answer(11, 8)
    svc.repository.delete.assert_not_awaited()
    svc.comment_repo.delete_by_answer_id.assert_not_awaited()
    svc.expert_repo.increment_answer_count.assert_not_awaited()


async def test_delete_runs_lazy_expire_before_pending_check():
    svc = _answer_service()
    question = SimpleNamespace(id=9, user_id=1, answer_count=1)
    svc.repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=False)
    )
    svc.repository.delete = AsyncMock(return_value=True)
    svc.question_repo.get_by_id = AsyncMock(return_value=question)
    assert await svc.delete_answer(11, 8) is True
    svc.publish_refresher.assert_awaited_once_with(9)
    svc.publish_request_repo.get_pending_by_question.assert_awaited_once_with(9)
    svc.expert_repo.increment_answer_count.assert_awaited_once_with(3, count=-1)


async def test_pending_publish_blocks_unadopted_delete():
    svc = _answer_service()
    svc.repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=False)
    )
    svc.publish_request_repo.get_pending_by_question = AsyncMock(return_value=SimpleNamespace(id=4, status="pending"))
    svc.repository.delete = AsyncMock()
    with pytest.raises(QaExpertAnswerDeleteNotAllowedError):
        await svc.delete_answer(11, 8)
    svc.repository.delete.assert_not_awaited()
    svc.expert_repo.increment_answer_count.assert_not_awaited()


async def test_finished_publish_allows_unadopted_delete():
    svc = _answer_service()
    question = SimpleNamespace(id=9, user_id=1, answer_count=2)
    svc.repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=11, question_id=9, user_id=8, expert_id=3, status=1, adopted=False)
    )
    svc.repository.delete = AsyncMock(return_value=True)
    svc.question_repo.get_by_id = AsyncMock(return_value=question)
    svc.publish_request_repo.get_pending_by_question = AsyncMock(return_value=None)
    assert await svc.delete_answer(11, 8) is True
    svc.repository.delete.assert_awaited_once_with(11)
    svc.expert_repo.increment_answer_count.assert_awaited_once_with(3, count=-1)


async def test_directed_stranger_cannot_list_comments():
    svc = CommentService()
    svc.answer_repo = MagicMock()
    svc.question_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.repository = MagicMock()
    svc.answer_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=11, question_id=9))
    svc.question_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(id=9, user_id=1, question_type="directed", adopt_count=0, answer_count=1)
    )
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={9: {8}})
    svc.repository.get_by_answer_id = AsyncMock()
    with pytest.raises(QaExpertQuestionAccessDeniedError):
        await svc.get_comments(
            answer_id=11,
            question_id=9,
            user=SimpleNamespace(user_id=301, is_admin=lambda: False, role=None),
        )
    svc.repository.get_by_answer_id.assert_not_awaited()
