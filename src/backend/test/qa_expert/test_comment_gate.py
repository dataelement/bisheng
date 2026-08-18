# ruff: noqa: RUF002
"""T010：定向评论资格与追问豁免（仓储全 mock）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.qa_expert import QaExpertAnonymousRevealRequiredError, QaExpertCommentNotAllowedError
from bisheng.database.models.qa_expert import Comment, Question
from bisheng.qa_expert.domain.schemas import CommentCreateRequest
from bisheng.qa_expert.domain.services import CommentService


def _question(**kwargs) -> Question:
    data = {
        "id": 9,
        "user_id": 1,
        "title": "炼钢",
        "description": "描述",
        "business_domain": "steel",
        "question_type": "directed",
        "answer_count": 0,
        "adopt_count": 0,
        "comment_count": 0,
    }
    data.update(kwargs)
    return Question(**data)


def _service() -> CommentService:
    svc = CommentService()
    svc.repository = MagicMock()
    svc.answer_repo = MagicMock()
    svc.question_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={9: {50}})
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=SimpleNamespace(id=3, user_id=50, status=1))
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=False)
    svc.answer_repo.update = AsyncMock()
    svc.question_repo.update = AsyncMock()
    svc._send_comment_notification = AsyncMock()

    async def fake_create(comment: Comment) -> Comment:
        comment.id = 21
        return comment

    svc.repository.create = AsyncMock(side_effect=fake_create)
    return svc


async def test_directed_invited_cannot_comment_before_answer():
    svc = _service()
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    with pytest.raises(QaExpertCommentNotAllowedError):
        await svc.create_comment(50, "专家", CommentCreateRequest(answer_id=11, content="先评一句"))
    svc.repository.create.assert_not_awaited()


async def test_directed_invited_can_comment_after_answer():
    svc = _service()
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=True)
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(answer_count=1))
    comment = await svc.create_comment(
        50,
        "专家",
        CommentCreateRequest(answer_id=11, content="补充", anonymous=True, reveal_on_public=False),
    )
    assert comment.id == 21
    persisted: Comment = svc.repository.create.await_args.args[0]
    assert persisted.anonymous == 1
    assert persisted.reveal_on_public == 0


async def test_public_logged_in_can_comment():
    svc = _service()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(question_type="public"))
    comment = await svc.create_comment(99, "同事", CommentCreateRequest(answer_id=11, content="公开可评"))
    assert comment.content == "公开可评"


async def test_follow_up_skips_expert_answer_gate():
    svc = _service()
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    comment = await svc.create_comment(
        50,
        "专家",
        CommentCreateRequest(answer_id=0, question_id=9, content="追问", is_follow_up=True),
    )
    assert comment.is_follow_up is True
    svc.repository.create.assert_awaited()


async def test_asker_follow_up_inherits_question_anonymous_ignoring_client():
    """提问者追问继承问题匿名；请求体匿名=false 也不能改成实名。"""
    svc = _service()
    svc.question_repo.get_by_id = AsyncMock(
        return_value=_question(user_id=1, asker_anonymous=1, asker_reveal_on_public=0)
    )
    comment = await svc.create_comment(
        1,
        "提问者",
        CommentCreateRequest(
            answer_id=0,
            question_id=9,
            content="追问一句",
            is_follow_up=True,
            anonymous=False,
            reveal_on_public=True,
        ),
    )
    assert comment.is_follow_up is True
    persisted: Comment = svc.repository.create.await_args.args[0]
    assert persisted.anonymous == 1
    assert persisted.reveal_on_public == 0


async def test_self_comment_inherits_answer_anonymous():
    """专家评论自己的回答时继承该回答匿名，忽略请求体。"""
    svc = _service()
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=True)
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0, user_id=50, anonymous=1, reveal_on_public=0)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(question_type="public", answer_count=1))
    await svc.create_comment(
        50,
        "专家",
        CommentCreateRequest(answer_id=11, content="自评补充", anonymous=False, reveal_on_public=True),
    )
    persisted: Comment = svc.repository.create.await_args.args[0]
    assert persisted.anonymous == 1
    assert persisted.reveal_on_public == 0


async def test_other_comment_uses_request_anonymous():
    """评论他人回答时用请求体独立选择匿名。"""
    svc = _service()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0, user_id=50, anonymous=0, reveal_on_public=None)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(question_type="public"))
    await svc.create_comment(
        99,
        "同事",
        CommentCreateRequest(answer_id=11, content="路人评", anonymous=True),
    )
    persisted: Comment = svc.repository.create.await_args.args[0]
    assert persisted.anonymous == 1
    assert persisted.reveal_on_public is None


async def test_directed_anonymous_comment_requires_reveal():
    """定向题评他人且匿名时必须预选转公开姓名，拒绝后不写库。"""
    svc = _service()
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=True)
    answer = SimpleNamespace(id=11, question_id=9, comment_count=0, user_id=88)
    svc.answer_repo.get_by_id = AsyncMock(return_value=answer)
    svc.question_repo.get_by_id = AsyncMock(return_value=_question(answer_count=1))
    with pytest.raises(QaExpertAnonymousRevealRequiredError):
        await svc.create_comment(
            50,
            "专家",
            CommentCreateRequest(answer_id=11, content="定向匿名评", anonymous=True),
        )
    svc.repository.create.assert_not_awaited()
