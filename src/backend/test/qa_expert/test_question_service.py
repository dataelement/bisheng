# ruff: noqa: RUF002
"""T006：提问 / 列表 / 类似问题（仓储全 mock）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.qa_expert import (
    QaExpertDisabledError,
    QaExpertQuestionAccessDeniedError,
)
from bisheng.database.models.qa_expert import Question
from bisheng.qa_expert.domain.capability import DISPLAY_PENDING_ADOPT, DISPLAY_SOLVED
from bisheng.qa_expert.domain.question_query import FILTER_INVITED_ME, FILTER_MINE, normalize_list_filter
from bisheng.qa_expert.domain.schemas import QuestionCreateRequest
from bisheng.qa_expert.domain.services import InvalidInvitationError, QuestionService


def _user(*, user_id: int, admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, user_name=f"u{user_id}", is_admin=lambda: admin, role=None)


def _expert(*, expert_id: int = 5, user_id: int = 50, status: int = 1, expert_name: str = "专家") -> SimpleNamespace:
    return SimpleNamespace(id=expert_id, user_id=user_id, status=status, expert_name=expert_name)


def _question_row(**kwargs) -> SimpleNamespace:
    data = {
        "id": 10,
        "user_id": 1,
        "title": "公开题",
        "question_type": "public",
        "adopt_count": 0,
        "answer_count": 0,
        "invited_experts": None,
        "created_by": "gzx01",
        "asker_anonymous": 0,
        "asker_reveal_on_public": None,
        "tenant_id": 1,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _service() -> QuestionService:
    svc = QuestionService()
    svc.repository = MagicMock()
    svc.expert_repo = MagicMock()
    svc.expert_repo.get_by_ids = AsyncMock(return_value=[])
    svc.invite_repo = MagicMock()
    svc.answer_repo = MagicMock()
    svc.invite_repo.create_many = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={})
    svc.invite_repo.list_question_ids_for_user = AsyncMock(return_value=[])
    svc._send_expert_invitation_inbox_notice = AsyncMock()
    svc._resolve_question = AsyncMock(side_effect=lambda q: q)
    svc.answer_repo.get_answer_vote_count = AsyncMock(return_value=0)
    svc.answer_repo.list_latest_by_question_ids = AsyncMock(return_value={})

    async def _fake_mask(_viewer, **kwargs):
        anonymous = bool(int(kwargs.get("anonymous") or 0))
        real_name = str(kwargs.get("real_name") or "")
        display = "匿名同事A" if anonymous else real_name

        def _to_dict(*, can_view_real_identity: bool):
            payload = {"display_name": display, "anonymous": anonymous, "avatar_url": None}
            if can_view_real_identity and anonymous:
                payload["real_name"] = real_name
                payload["real_user_id"] = kwargs.get("user_id")
            return payload

        return SimpleNamespace(to_dict=_to_dict)

    svc.identity_service = MagicMock()
    svc.identity_service.mask_identity = AsyncMock(side_effect=_fake_mask)
    svc.identity_service.preload_for_questions = AsyncMock()
    return svc


def _create_request(**kwargs) -> QuestionCreateRequest:
    payload = {
        "title": "如何炼钢",
        "description": "描述",
        "business_domain": "steel",
    }
    payload.update(kwargs)
    return QuestionCreateRequest(**payload)


async def _create(svc: QuestionService, request: QuestionCreateRequest, user_id: int = 1):
    async def fake_create(question: Question) -> Question:
        question.id = 101
        return question

    svc.repository.create = AsyncMock(side_effect=fake_create)
    with patch("bisheng.qa_expert.domain.services.RealtimeQaQuestionFact.record_success", new_callable=AsyncMock):
        return await svc.create_question(user_id, request, "asker", tenant_id=1)


def test_legacy_status_3_4_are_mine_and_invited_not_pending_adopt():
    assert normalize_list_filter(status=3, list_filter=None) == FILTER_MINE
    assert normalize_list_filter(status=4, list_filter=None) == FILTER_INVITED_ME
    assert normalize_list_filter(status=3, list_filter=FILTER_INVITED_ME) == FILTER_INVITED_ME


def test_stock_question_type_defaults_public():
    assert Question(user_id=1, title="t", description="d", business_domain="b").question_type == "public"


async def test_create_rejects_unauthenticated():
    svc = _service()
    with pytest.raises(QaExpertQuestionAccessDeniedError):
        await svc.create_question(0, _create_request(), "anon")


async def test_create_directed_requires_1_to_3_experts():
    svc = _service()
    with pytest.raises(InvalidInvitationError):
        await _create(svc, _create_request(question_type="directed", invited_expert_ids=[]))
    with pytest.raises(InvalidInvitationError):
        await _create(
            svc,
            _create_request(question_type="directed", invited_expert_ids=[5, 6, 7, 8]),
        )


async def test_create_directed_writes_invites_and_type():
    svc = _service()
    svc.expert_repo.get_by_id = AsyncMock(return_value=_expert())
    question = await _create(
        svc,
        _create_request(
            question_type="directed",
            invited_expert_ids=[5],
            asker_reveal_on_public=True,
        ),
    )
    persisted: Question = svc.repository.create.await_args.args[0]
    assert persisted.question_type == "directed"
    assert persisted.invited_experts == "5"
    assert persisted.experts_names == "专家"
    assert persisted.asker_anonymous == 0
    assert persisted.asker_reveal_on_public is None
    assert question.id == 101
    svc.invite_repo.create_many.assert_awaited()
    invites = svc.invite_repo.create_many.await_args.args[0]
    assert len(invites) == 1
    assert invites[0].expert_id == 5
    assert invites[0].user_id == 50


async def test_create_directed_anonymous_requires_reveal_and_persists():
    """定向也可匿名；勾选后必须预选转公开姓名，并写入 qa_question。"""
    svc = _service()
    svc.expert_repo.get_by_id = AsyncMock(return_value=_expert())
    with pytest.raises(InvalidInvitationError):
        await _create(
            svc,
            _create_request(
                question_type="directed",
                invited_expert_ids=[5],
                asker_anonymous=True,
            ),
        )
    question = await _create(
        svc,
        _create_request(
            question_type="directed",
            invited_expert_ids=[5],
            asker_anonymous=True,
            asker_reveal_on_public=False,
        ),
    )
    persisted: Question = svc.repository.create.await_args.args[0]
    assert persisted.asker_anonymous == 1
    assert persisted.asker_reveal_on_public == 0
    assert persisted.question_type == "directed"
    assert question.id == 101


async def test_hydrate_invite_names_replaces_numeric_id_string():
    svc = _service()
    svc.expert_repo.get_by_ids = AsyncMock(return_value=[_expert(expert_id=5, expert_name="gzx001")])
    question = _question_row(invited_experts="5", experts_names=None)
    await svc._hydrate_invite_names([question])
    assert question.experts_names == "gzx001"
    named = _question_row(invited_experts="5", experts_names="gzx001")
    svc.expert_repo.get_by_ids.reset_mock()
    await svc._hydrate_invite_names([named])
    svc.expert_repo.get_by_ids.assert_not_awaited()


async def test_create_public_allows_0_to_3_and_defaults_type():
    svc = _service()
    question = await _create(svc, _create_request())
    persisted: Question = svc.repository.create.await_args.args[0]
    assert persisted.question_type == "public"
    assert question.question_type == "public"
    svc.invite_repo.create_many.assert_not_awaited()
    svc.expert_repo.get_by_id = AsyncMock(
        side_effect=[
            _expert(expert_id=1, user_id=11),
            _expert(expert_id=2, user_id=12),
            _expert(expert_id=3, user_id=13),
            _expert(expert_id=4, user_id=14),
        ]
    )
    with pytest.raises(InvalidInvitationError):
        await _create(svc, _create_request(question_type="public", invited_expert_ids=[1, 2, 3, 4]))


async def test_create_rejects_self_invite_and_disabled_expert():
    svc = _service()
    svc.expert_repo.get_by_id = AsyncMock(return_value=_expert(expert_id=5, user_id=1, status=1))
    with pytest.raises(InvalidInvitationError):
        await _create(
            svc, _create_request(question_type="directed", invited_expert_ids=[5], asker_reveal_on_public=False)
        )
    svc.expert_repo.get_by_id = AsyncMock(return_value=_expert(status=0))
    with pytest.raises(QaExpertDisabledError):
        await _create(
            svc, _create_request(question_type="directed", invited_expert_ids=[5], asker_reveal_on_public=False)
        )


async def test_list_hides_directed_title_from_stranger():
    svc = _service()
    directed = _question_row(id=1, title="定向机密", question_type="directed", user_id=1)
    public = _question_row(id=2, title="公开可见", question_type="public", user_id=1)
    svc.repository.list_all = AsyncMock(return_value=([public], 1))
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={1: {50}})
    items, total = await svc.list_questions(user=_user(user_id=99))
    titles = [item.title for item in items]
    assert "定向机密" not in titles
    assert "公开可见" in titles
    assert total == 1

    svc.repository.list_all = AsyncMock(return_value=([directed, public], 2))
    leaked_items, leaked_total = await svc.list_questions(user=_user(user_id=99))
    assert "定向机密" not in [item.title for item in leaked_items]
    assert leaked_total == 2


async def test_list_total_uses_repository_count_not_page_length():
    """列表 total 必须是匹配总数，不能收成当前页 len(visible)。"""
    svc = _service()
    page = [_question_row(id=index, title=f"公开{index}", question_type="public") for index in range(10)]
    svc.repository.list_all = AsyncMock(return_value=(page, 27))
    items, total = await svc.list_questions(user=_user(user_id=1))
    assert len(items) == 10
    assert total == 27


async def test_list_masks_anonymous_asker_name():
    """匿名公开题列表给非管理员看别名，不得带 created_by 真名展示字段。"""
    svc = _service()
    anon = _question_row(
        id=1,
        title="匿名题",
        question_type="public",
        created_by="gzx01",
        asker_anonymous=1,
    )
    named = _question_row(id=2, title="实名题", question_type="public", created_by="gzx01", asker_anonymous=0)
    svc.repository.list_all = AsyncMock(return_value=([anon, named], 2))
    items, _total = await svc.list_questions(user=_user(user_id=99))
    assert items[0].asker["display_name"] == "匿名同事A"
    assert items[0].asker["anonymous"] is True
    assert "real_name" not in items[0].asker
    assert items[0].created_by == "gzx01"
    assert items[1].asker["display_name"] == "gzx01"
    assert items[1].asker["anonymous"] is False


async def test_list_attaches_latest_answer_preview():
    """有回答的列表项必须带最新一条摘要，不能只给 answer_count。"""
    svc = _service()
    row = _question_row(id=1, title="有回答", answer_count=2)
    empty = _question_row(id=2, title="无回答", answer_count=0)
    svc.repository.list_all = AsyncMock(return_value=([row, empty], 2))
    svc.answer_repo.list_latest_by_question_ids = AsyncMock(
        return_value={
            1: SimpleNamespace(
                id=9,
                question_id=1,
                content="<p>最新答</p>",
                adopted=True,
                expert_name="gzx001",
                user_id=50,
                anonymous=0,
                reveal_on_public=None,
            )
        }
    )
    items, _total = await svc.list_questions(user=_user(user_id=99))
    preview = items[0].latest_answer
    assert preview["id"] == 9
    assert preview["excerpt"] == "最新答"
    assert preview["expert_name"] == "gzx001"
    assert preview["adopted"] is True
    assert preview["anonymous"] is False
    assert getattr(items[1], "latest_answer", None) is None
    svc.answer_repo.list_latest_by_question_ids.assert_awaited()


async def test_list_status_3_is_mine_not_pending_adopt():
    svc = _service()
    mine_solved = _question_row(id=3, title="我的已解决", user_id=1, adopt_count=1, answer_count=1)
    svc.repository.list_all = AsyncMock(return_value=([mine_solved], 1))
    items, _total = await svc.list_questions(user=_user(user_id=1), status=3)
    assert items[0].title == "我的已解决"
    assert items[0].display_status == DISPLAY_SOLVED
    kwargs = svc.repository.list_all.await_args.kwargs
    assert kwargs.get("list_filter") == FILTER_MINE
    assert kwargs.get("display_status") is None


async def test_list_unresolved_excludes_solved():
    svc = _service()
    unanswered = _question_row(id=1, title="未回答", answer_count=0, adopt_count=0)
    pending = _question_row(id=2, title="待采纳", answer_count=2, adopt_count=0)
    solved = _question_row(id=3, title="已解决", answer_count=2, adopt_count=1)
    svc.repository.list_all = AsyncMock(return_value=([unanswered, pending, solved], 3))
    items, _total = await svc.list_questions(user=_user(user_id=1), display_status="unresolved")
    titles = [item.title for item in items]
    assert titles == ["未回答", "待采纳"]
    assert items[1].display_status == DISPLAY_PENDING_ADOPT


async def test_list_skips_minio_resolve_and_per_row_vote_query():
    """列表不得逐条打 MinIO / SUM 回答赞，否则 171 上 10 条就会拖过前端超时。"""
    svc = _service()
    page = [_question_row(id=index, title=f"公开{index}") for index in range(10)]
    svc.repository.list_all = AsyncMock(return_value=(page, 10))
    await svc.list_questions(user=_user(user_id=1))
    svc._resolve_question.assert_not_awaited()
    svc.answer_repo.get_answer_vote_count.assert_not_awaited()
    svc.identity_service.preload_for_questions.assert_awaited()


async def test_detail_denies_stranger_without_leaking_title():
    svc = _service()
    directed = _question_row(id=9, title="定向机密", question_type="directed", user_id=1)
    svc.repository.get_by_id = AsyncMock(return_value=directed)
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={9: {50}})
    with pytest.raises(QaExpertQuestionAccessDeniedError) as exc:
        await svc.get_question_detail(9, user=_user(user_id=99))
    assert "定向机密" not in str(exc.value)
    svc.repository.update.assert_not_called()


async def test_similar_does_not_merge_and_hides_invisible():
    svc = _service()
    directed = _question_row(id=1, title="定向机密炼钢", question_type="directed")
    public = _question_row(id=2, title="公开炼钢", question_type="public")
    svc.repository.search_by_title_like = AsyncMock(return_value=[directed, public])
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={1: {50}})
    hits = await svc.find_similar_questions(user=_user(user_id=99), text="炼钢")
    assert [item.title for item in hits] == ["公开炼钢"]
    await _create(svc, _create_request(title="炼钢新题"))
    svc.repository.create.assert_awaited()
