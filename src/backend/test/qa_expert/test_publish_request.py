# ruff: noqa: RUF002
"""T016：转公开有效期、同题 pending、不可改口、默认同意、过期、延期、通过后资格快照。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.qa_expert import (
    QaExpertPublishConflictError,
    QaExpertPublishDurationInvalidError,
    QaExpertPublishNotAllowedError,
)
from bisheng.qa_expert.domain.publish_service import (
    DECISION_APPROVED,
    DECISION_DEFAULT_APPROVED,
    DECISION_PENDING,
    PUBLISH_APPROVED,
    PUBLISH_ENDED,
    PUBLISH_EXPIRED,
    PUBLISH_PENDING,
    PUBLISH_REJECTED,
    PublishService,
    serialize_publish_request,
)


def _user(*, user_id: int, admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, user_name=f"u{user_id}", is_admin=lambda: admin, role=None)


def _question(**kwargs) -> SimpleNamespace:
    data = {
        "id": 20,
        "user_id": 1,
        "title": "定向题",
        "question_type": "directed",
        "adopt_count": 1,
        "answer_count": 1,
        "status": 1,
        "tenant_id": 1,
        "active_publish_request_id": None,
        "content_locked": 1,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _request(**kwargs) -> SimpleNamespace:
    data = {
        "id": 7,
        "question_id": 20,
        "initiator_user_id": 1,
        "status": PUBLISH_PENDING,
        "duration_days": 3,
        "expire_at": datetime(2026, 8, 18, 12, 0, 0),
        "extension_days": 0,
        "version": 0,
        "tenant_id": 1,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _approver(**kwargs) -> SimpleNamespace:
    data = {
        "id": 1,
        "request_id": 7,
        "user_id": 1,
        "role_in_request": "asker",
        "decision": DECISION_PENDING,
        "decided_at": None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _service() -> PublishService:
    svc = PublishService()
    svc.question_repo = MagicMock()
    svc.answer_repo = MagicMock()
    svc.invite_repo = MagicMock()
    svc.expert_repo = MagicMock()
    svc.request_repo = MagicMock()
    svc.approver_repo = MagicMock()
    svc.eligibility_repo = MagicMock()
    svc.notify = AsyncMock()
    svc.question_repo.get_by_id_for_update = AsyncMock(return_value=_question())
    svc.question_repo.get_by_id = AsyncMock(return_value=_question())
    svc.question_repo.update = AsyncMock()
    svc.invite_repo.list_user_ids_by_question_ids = AsyncMock(return_value={20: {50}})
    svc.expert_repo.get_by_user_id = AsyncMock(return_value=SimpleNamespace(id=5, user_id=1, status=1))
    svc.answer_repo.has_effective_answer = AsyncMock(return_value=False)
    svc.answer_repo.list_all_by_question_id = AsyncMock(return_value=[SimpleNamespace(id=11, user_id=50, status=1)])
    svc.request_repo.get_pending_by_question = AsyncMock(return_value=None)
    svc.request_repo.create = AsyncMock(side_effect=lambda row: _request())
    svc.request_repo.get_by_id = AsyncMock(return_value=_request())
    svc.request_repo.update = AsyncMock(side_effect=lambda rid, **kw: _request(**kw, id=rid))
    svc.request_repo.list_expired_pending = AsyncMock(return_value=[])
    svc.approver_repo.create_many = AsyncMock()
    svc.approver_repo.list_by_request = AsyncMock(
        return_value=[
            _approver(id=1, user_id=1, decision=DECISION_APPROVED),
            _approver(id=2, user_id=50, role_in_request="answerer", decision=DECISION_PENDING),
        ]
    )
    svc.approver_repo.get_for_user = AsyncMock(return_value=_approver(id=2, user_id=50, role_in_request="answerer"))
    svc.approver_repo.update = AsyncMock()
    svc.approver_repo.list_pending_for_user = AsyncMock(return_value=[])
    svc.eligibility_repo.list_user_ids = AsyncMock(return_value=set())
    svc.eligibility_repo.create_many = AsyncMock()
    return svc


async def test_invalid_duration_raises_18310():
    svc = _service()
    with pytest.raises(QaExpertPublishDurationInvalidError) as exc:
        await svc.create_publish_request(20, _user(user_id=1), duration_days=2)
    assert exc.value.Code == 18310
    svc.request_repo.create.assert_not_awaited()


async def test_duplicate_pending_raises_18306():
    svc = _service()
    svc.request_repo.get_pending_by_question = AsyncMock(return_value=_request())
    with pytest.raises(QaExpertPublishConflictError) as exc:
        await svc.create_publish_request(20, _user(user_id=1), duration_days=3)
    assert exc.value.Code == 18306


async def test_decision_cannot_be_changed():
    svc = _service()
    svc.request_repo.get_by_id = AsyncMock(return_value=_request())
    svc.approver_repo.get_for_user = AsyncMock(return_value=_approver(id=2, user_id=50, decision=DECISION_APPROVED))
    with pytest.raises(QaExpertPublishNotAllowedError):
        await svc.decide_publish(7, _user(user_id=50), "rejected")
    svc.approver_repo.update.assert_not_awaited()


async def test_reject_keeps_directed_and_allows_retry():
    svc = _service()
    now = datetime(2026, 8, 15, 12, 0, 0)
    result = await svc.decide_publish(7, _user(user_id=50), "rejected", now=now)
    assert result.status == PUBLISH_REJECTED
    svc.request_repo.update.assert_awaited()
    svc.question_repo.update.assert_not_called()  # active_publish_request_id 为空时只关申请头
    assert svc.eligibility_repo.create_many.await_count == 0


async def test_all_approved_sets_public_and_writes_eligibility():
    svc = _service()
    now = datetime(2026, 8, 15, 12, 0, 0)

    async def _update(row_id, **kwargs):
        return _approver(id=row_id, user_id=50, decision=kwargs.get("decision"), decided_at=now)

    svc.approver_repo.update = AsyncMock(side_effect=_update)

    async def _list(_rid):
        return [
            _approver(id=1, user_id=1, decision=DECISION_APPROVED),
            _approver(id=2, user_id=50, role_in_request="answerer", decision=DECISION_APPROVED),
        ]

    svc.approver_repo.list_by_request = AsyncMock(side_effect=_list)
    result = await svc.decide_publish(7, _user(user_id=50), "approved", now=now)
    assert result.status == PUBLISH_APPROVED
    kwargs = svc.question_repo.update.await_args.kwargs
    assert kwargs.get("question_type") == "public"
    rows = svc.eligibility_repo.create_many.await_args.args[0]
    user_ids = {int(r.user_id) for r in rows}
    assert 50 in user_ids
    assert 99 not in user_ids


async def test_disabled_expert_default_approved_can_pass_silently():
    svc = _service()
    now = datetime(2026, 8, 15, 12, 0, 0)
    pending_row = _approver(id=2, user_id=50, role_in_request="answerer", decision=DECISION_PENDING)
    svc.approver_repo.list_pending_for_user = AsyncMock(return_value=[pending_row])
    svc.request_repo.get_by_id = AsyncMock(return_value=_request())
    svc.approver_repo.list_by_request = AsyncMock(
        return_value=[
            _approver(id=1, user_id=1, decision=DECISION_APPROVED),
            _approver(id=2, user_id=50, decision=DECISION_DEFAULT_APPROVED),
        ]
    )
    passed = await svc.on_expert_disabled(50, now=now)
    assert passed == [7]
    update_kw = svc.approver_repo.update.await_args.kwargs
    assert update_kw["decision"] == DECISION_DEFAULT_APPROVED


async def test_expire_pending_marks_expired():
    svc = _service()
    now = datetime(2026, 8, 20, 12, 0, 0)
    svc.request_repo.list_expired_pending = AsyncMock(
        return_value=[_request(expire_at=datetime(2026, 8, 18, 12, 0, 0))]
    )
    count = await svc.expire_pending(now=now, tenant_id=1)
    assert count == 1
    assert svc.request_repo.update.await_args.kwargs["status"] == PUBLISH_EXPIRED
    svc.notify.assert_awaited()


async def test_asker_disabled_ends_request():
    svc = _service()
    svc.request_repo.get_pending_by_question = AsyncMock(return_value=_request())
    result = await svc.on_asker_disabled(20)
    assert result.status == PUBLISH_ENDED


async def test_asker_initiator_is_auto_approved():
    """提问者发起转公开：本人审批行直接 approved，回答专家仍 pending。"""
    svc = _service()
    now = datetime(2026, 8, 16, 12, 0, 0)
    rows = await svc._build_approvers(_question(), _request(), _user(user_id=1), now)
    by_user = {int(row.user_id): row for row in rows}
    assert by_user[1].decision == DECISION_APPROVED
    assert by_user[1].decided_at == now
    assert by_user[50].decision == DECISION_PENDING
    assert by_user[50].decided_at is None


def test_serialize_exposes_viewer_decision():
    payload = serialize_publish_request(_request(), viewer_decision="approved")
    assert payload["viewer_decision"] == "approved"
    assert payload["status"] == PUBLISH_PENDING


async def test_answerer_initiator_is_auto_approved():
    """回答专家发起转公开：该专家默认同意，提问者仍需审批。"""
    svc = _service()
    now = datetime(2026, 8, 16, 12, 0, 0)
    rows = await svc._build_approvers(
        _question(),
        _request(initiator_user_id=50),
        _user(user_id=50),
        now,
    )
    by_user = {int(row.user_id): row for row in rows}
    assert by_user[1].decision == DECISION_PENDING
    assert by_user[50].decision == DECISION_APPROVED
    assert by_user[50].decided_at == now


async def test_extend_one_day_capped_at_three():
    svc = _service()
    now = datetime(2026, 8, 15, 12, 0, 0)
    svc.request_repo.get_by_id = AsyncMock(return_value=_request(extension_days=2, expire_at=now + timedelta(days=1)))
    updated = await svc.extend_one_day(7, _user(user_id=1), now=now)
    assert updated.extension_days == 3
    svc.request_repo.get_by_id = AsyncMock(return_value=_request(extension_days=3))
    with pytest.raises(QaExpertPublishDurationInvalidError):
        await svc.extend_one_day(7, _user(user_id=1), now=now)
