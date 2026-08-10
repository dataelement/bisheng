"""补扣队列：稳定幂等键与失败入队语义。"""

from __future__ import annotations

import pytest

from bisheng.points.domain.services.points_pending_deduct_service import (
    DeductAttemptResult,
    PointsPendingDeductService,
    stable_deduct_idempotency_key,
)


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
