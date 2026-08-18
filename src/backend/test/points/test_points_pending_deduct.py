# ruff: noqa: RUF002
"""补扣队列：稳定幂等键、失败入队与扣分站内信。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.points.domain.services.points_pending_deduct_service import (
    DeductAttemptResult,
    PointsPendingDeductService,
    stable_deduct_idempotency_key,
)


def _patch_successful_ledger(monkeypatch, *, score: int = 100, log_id: int = 42, replayed: bool = False):
    """伪造账本会话：规则启用且扣分成功。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    rule = SimpleNamespace(
        rule_code="R1",
        rule_type="deduct",
        status="enabled",
        name="色情低俗/暴力违法",
        score_expr={"score": score},
    )
    repo = SimpleNamespace(get_rule=AsyncMock(return_value=rule))
    ledger_result = SimpleNamespace(replayed=replayed, log_id=log_id)

    class _Ledger:
        async def deduct(self, **_kwargs):
            return ledger_result

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.PointsRepository",
        lambda _session: repo,
    )
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.PointsLedgerService",
        lambda _repo: _Ledger(),
    )
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
        lambda: session,
    )
    return session


def test_stable_deduct_idempotency_key_normalizes_rule():
    """同一内容+规则生成稳定键，规则编码大写。"""
    key = stable_deduct_idempotency_key("r1", "qa_question", "12")
    assert key == "deduct:R1:qa_question:12"
    assert key == stable_deduct_idempotency_key("R1", "qa_question", "12")


@pytest.mark.asyncio
async def test_deduct_or_enqueue_enqueues_when_ledger_raises(monkeypatch):
    """立即扣分抛错时必须入补扣队列且不向外抛。"""
    calls: list[dict] = []

    async def fake_enqueue(**kwargs):
        calls.append(kwargs)

    service = PointsPendingDeductService()
    monkeypatch.setattr(service, "_enqueue", fake_enqueue)

    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    # 强制进入异常分支：伪造 get_async_db_session 上下文失败
    class _BoomCM:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
        lambda: _BoomCM(),
    )

    result = await service.deduct_or_enqueue(
        tenant_id=1,
        user_id=9,
        rule_code="R1",
        biz_type="qa_comment",
        biz_id="77",
        operator_id=1,
        remark="违规",
    )
    assert isinstance(result, DeductAttemptResult)
    assert result.applied is False
    assert result.pending is True
    assert calls and calls[0]["idempotency_key"] == "deduct:R1:qa_comment:77"


@pytest.mark.asyncio
async def test_deduct_or_enqueue_notifies_injected_service(monkeypatch):
    """立即扣分成功后必须发 deduct_admin 站内信；备注优先作为原因。"""
    _patch_successful_ledger(monkeypatch)
    notify = AsyncMock()
    service = PointsPendingDeductService(notify=notify)
    result = await service.deduct_or_enqueue(
        tenant_id=1,
        user_id=66,
        rule_code="r1",
        biz_type="qa_answer",
        biz_id="11",
        operator_id=9,
        remark="违规删除未采纳回答",
    )
    assert result.applied is True
    assert result.pending is False
    notify.notify.assert_awaited_once_with(
        user_id=66,
        template_code="deduct_admin",
        delta=100,
        reason="违规删除未采纳回答",
    )


@pytest.mark.asyncio
async def test_deduct_or_enqueue_builds_message_service_when_bare(monkeypatch):
    """裸 PointsNotifyService 必须走工厂注入 MessageService，不能静默跳过。"""
    ledger_session = _patch_successful_ledger(monkeypatch)
    notify = AsyncMock()
    built = AsyncMock(return_value=notify)
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_pending_deduct_service.build_points_notify_service",
        built,
    )
    service = PointsPendingDeductService()
    assert service.notify.message_service is None

    result = await service.deduct_or_enqueue(
        tenant_id=1,
        user_id=66,
        rule_code="R1",
        biz_type="qa_answer",
        biz_id="11",
        operator_id=9,
        remark="",
    )
    assert result.applied is True
    built.assert_awaited_once()
    notify.notify.assert_awaited_once_with(
        user_id=66,
        template_code="deduct_admin",
        delta=100,
        reason="色情低俗/暴力违法",
    )
    assert ledger_session.commit.await_count >= 2


@pytest.mark.asyncio
async def test_deduct_or_enqueue_skips_notify_on_replay(monkeypatch):
    """幂等重放已入账时不再发站内信。"""
    _patch_successful_ledger(monkeypatch, replayed=True)
    notify = AsyncMock()
    service = PointsPendingDeductService(notify=notify)
    result = await service.deduct_or_enqueue(
        tenant_id=1,
        user_id=66,
        rule_code="R1",
        biz_type="qa_answer",
        biz_id="11",
        operator_id=9,
    )
    assert result.replayed is True
    notify.notify.assert_not_awaited()
