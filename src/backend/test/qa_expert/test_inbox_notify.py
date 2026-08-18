# ruff: noqa: RUF002, RUF003
"""T021：邀请/回答/采纳/转公开走 inbox；匿名触发人用别名。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.qa_expert.domain.identity import IdentityService
from bisheng.qa_expert.domain.publish_service import PublishService
from bisheng.qa_expert.domain.services import AnswerService, CommentService, QuestionService


async def test_invite_answer_adopt_publish_send_inbox():
    qsvc = QuestionService()
    qsvc._send_expert_invitation_inbox_notice = AsyncMock()
    asvc = AnswerService()
    asvc._send_answer_notification = AsyncMock()
    qsvc._send_adoption_notification = AsyncMock()
    pub = PublishService()
    pub.notify = AsyncMock()

    await qsvc._send_expert_invitation_inbox_notice(
        SimpleNamespace(id=1, invited_experts="5", title="t", description="d"), 1, "asker"
    )
    await asvc._send_answer_notification(
        SimpleNamespace(id=1, user_id=1, title="t"),
        SimpleNamespace(id=2, expert_name="匿名同事A", expert_id=5, content="a"),
    )
    await qsvc._send_adoption_notification(
        SimpleNamespace(id=1, user_id=1, title="t"), SimpleNamespace(id=2, expert_id=5, content="a")
    )
    await pub._notify("publish_started", SimpleNamespace(id=1, title="t", user_id=1), extra={"request_id": 9})

    qsvc._send_expert_invitation_inbox_notice.assert_awaited()
    asvc._send_answer_notification.assert_awaited()
    qsvc._send_adoption_notification.assert_awaited()
    pub.notify.assert_awaited()


async def test_comment_inbox_notifies_asker_and_answerer(monkeypatch):
    captured: dict = {}

    async def fake_display(*_args, **_kwargs):
        return "评者", False

    async def fake_send(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("bisheng.qa_expert.domain.inbox_notice.display_name_for_trigger", fake_display)
    monkeypatch.setattr("bisheng.qa_expert.domain.inbox_notice.send_qa_inbox", fake_send)
    svc = CommentService()
    svc.question_repo = MagicMock()
    svc.question_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(id=1, user_id=101, title="题", tenant_id=1))
    await svc._send_comment_notification(
        SimpleNamespace(id=2, question_id=1, user_id=201),
        SimpleNamespace(
            id=9,
            user_id=301,
            user_name="评者",
            anonymous=0,
            reveal_on_public=None,
            content="评",
        ),
    )
    assert captured["action_code"] == "qa_answer_commented"
    assert captured["receivers"] == [201, 101]
    assert captured["sender_user_id"] == 301


async def test_anonymous_sender_uses_alias_not_real_name():
    svc = IdentityService()
    svc.alias_repo = MagicMock()
    svc.alias_repo.get_by_question_user = AsyncMock(return_value=None)
    svc.alias_repo.next_alias_ord = AsyncMock(return_value=1)
    svc.alias_repo.create = AsyncMock(side_effect=lambda row: row)
    view = await svc.mask_identity(
        SimpleNamespace(user_id=9, is_admin=lambda: False, role=None),
        question_id=1,
        user_id=50,
        real_name="李专家",
        anonymous=True,
        question_type="directed",
        reveal_on_public=0,
    )
    assert view.display_name == "匿名同事A"
    assert "李专家" not in view.display_name


async def test_publish_approved_inbox_keeps_asker_as_receiver(monkeypatch):
    """转公开通过是系统终态：提问者不能因默认发件人被从收件人剔除。"""
    captured: dict = {}

    async def fake_send(**kwargs):
        captured.update(kwargs)

    pub = PublishService()
    pub.approver_repo = MagicMock()
    pub.approver_repo.list_by_request = AsyncMock(
        return_value=[SimpleNamespace(user_id=101), SimpleNamespace(user_id=201)]
    )
    monkeypatch.setattr("bisheng.qa_expert.domain.inbox_notice.send_qa_inbox", fake_send)
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.ApprovalInstanceRepository.find_latest_by_business_key",
        AsyncMock(return_value=None),
    )
    question = SimpleNamespace(
        id=1,
        title="t",
        user_id=101,
        tenant_id=1,
        asker_anonymous=0,
        asker_reveal_on_public=None,
    )
    await pub._send_inbox("publish_approved", question, {"request_id": 9})
    assert captured["action_code"] == "qa_publish_approved"
    assert captured["sender_user_id"] == 0
    assert 101 in captured["receivers"]
    assert 201 in captured["receivers"]


async def test_publish_started_inbox_still_excludes_initiator(monkeypatch):
    """发起转公开仍排除操作人，避免提问者收到自己刚提交的待办。"""
    captured: dict = {}

    async def fake_display(*_args, **_kwargs):
        return "提问者", False

    async def fake_send(**kwargs):
        captured.update(kwargs)

    pub = PublishService()
    pub.approver_repo = MagicMock()
    pub.approver_repo.list_by_request = AsyncMock(
        return_value=[SimpleNamespace(user_id=101), SimpleNamespace(user_id=201)]
    )
    monkeypatch.setattr("bisheng.qa_expert.domain.inbox_notice.display_name_for_trigger", fake_display)
    monkeypatch.setattr("bisheng.qa_expert.domain.inbox_notice.send_qa_inbox", fake_send)
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.ApprovalInstanceRepository.find_latest_by_business_key",
        AsyncMock(return_value=None),
    )
    question = SimpleNamespace(
        id=1,
        title="t",
        user_id=101,
        tenant_id=1,
        asker_anonymous=0,
        asker_reveal_on_public=None,
    )
    await pub._send_inbox(
        "publish_started",
        question,
        {"request_id": 9, "user": SimpleNamespace(user_id=101, user_name="提问者")},
    )
    assert captured["sender_user_id"] == 101
    # send_qa_inbox 会排除发件人；发起人仍是提问者时，提问者收不到待办。
    filtered = [uid for uid in captured["receivers"] if uid and int(uid) != int(captured["sender_user_id"])]
    assert 101 not in filtered
    assert 201 in filtered


async def test_stale_publish_decision_rejected_after_ended():
    pub = PublishService()
    pub.request_repo = MagicMock()
    pub.approver_repo = MagicMock()
    pub.request_repo.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=3,
            status="ended",
            expire_at=__import__("datetime").datetime(2099, 1, 1),
            question_id=1,
        )
    )
    import pytest

    from bisheng.common.errcode.qa_expert import QaExpertPublishNotAllowedError

    with pytest.raises(QaExpertPublishNotAllowedError):
        await pub.decide_publish(3, SimpleNamespace(user_id=1), "approved")
