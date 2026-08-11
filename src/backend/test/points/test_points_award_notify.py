"""自动发分站内信：outcome 判定与 commit 后 flush。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services.points_award_facade import AwardOutcome
from bisheng.points.domain.services.points_award_hooks import _flush_award_notifies
from bisheng.points.domain.services.points_ledger_service import LedgerResult


def test_award_outcome_should_notify_only_on_fresh_earn():
    """仅新入账成功才发信；skip / 重放 / 日 cap 不发。"""
    ok = AwardOutcome.success(
        result=LedgerResult(applied_delta=2, balance=2, log_id=1),
        user_id=4,
        rule_code="G2",
        rule_name="上传部门库文档",
    )
    assert ok.should_notify is True

    replayed = AwardOutcome.success(
        result=LedgerResult(applied_delta=2, balance=2, log_id=1, replayed=True),
        user_id=4,
        rule_code="G2",
        rule_name="上传部门库文档",
    )
    assert replayed.should_notify is False

    capped = AwardOutcome(skipped=True, reason="daily_cap", result=LedgerResult(0, 0, skipped_cap=True))
    assert capped.should_notify is False

    skipped = AwardOutcome(skipped=True, reason="rule_disabled")
    assert skipped.should_notify is False


@pytest.mark.asyncio
async def test_flush_award_notifies_sends_mapped_template():
    """commit 后按规则模板调用 notify，并提交消息会话。"""
    outcome = AwardOutcome.success(
        result=LedgerResult(applied_delta=2, balance=2, log_id=9),
        user_id=4,
        rule_code="G2",
        rule_name="上传部门库文档",
    )
    notify = AsyncMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    with (
        patch(
            "bisheng.points.domain.services.points_award_hooks.get_async_db_session",
            return_value=session,
        ),
        patch(
            "bisheng.points.domain.services.points_award_hooks.build_points_notify_service",
            AsyncMock(return_value=notify),
        ),
    ):
        await _flush_award_notifies([outcome, AwardOutcome(skipped=True, reason="x")])

    notify.notify.assert_awaited_once_with(
        user_id=4,
        template_code="earn_publish",
        rule_name="上传部门库文档",
        delta=2,
    )
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_flush_award_notifies_noop_when_empty():
    """无可通知 outcome 时不打开消息会话。"""
    with patch("bisheng.points.domain.services.points_award_hooks.get_async_db_session") as session_factory:
        await _flush_award_notifies([AwardOutcome(skipped=True, reason="points_disabled")])
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_points_notify_respects_notify_enabled_false():
    """notify_enabled=false 时不调用 MessageService。"""
    from bisheng.points.domain.services.points_notify_service import PointsNotifyService

    message = SimpleNamespace(send_generic_notify=AsyncMock())
    svc = PointsNotifyService(message_service=message)
    with patch(
        "bisheng.points.domain.services.points_notify_service._notify_enabled",
        return_value=False,
    ):
        await svc.notify(user_id=1, template_code="earn_favorite", delta=5)
    message.send_generic_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_points_notify_payload_uses_action_code_in_system_text():
    """system_text 为 action_code，完整文案放 metadata，供前端正确渲染。"""
    from bisheng.points.domain.services.points_notify_service import PointsNotifyService

    message = SimpleNamespace(send_generic_notify=AsyncMock())
    svc = PointsNotifyService(message_service=message)
    with patch(
        "bisheng.points.domain.services.points_notify_service._notify_enabled",
        return_value=True,
    ):
        await svc.notify(
            user_id=4,
            template_code="earn_publish",
            rule_name="上传部门库文档",
            delta=2,
        )
    kwargs = message.send_generic_notify.await_args.kwargs
    assert kwargs["action_code"] == "points_changed"
    item = kwargs["content_item_list"][0]
    assert item["content"] == "points_changed"
    assert item["metadata"]["points_message"] == "你因「上传部门库文档」获得 2 积分。"
