"""Point rule edits commit the rule row and one audit_log row together."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.points import (
    PointsPermissionDeniedError,
    PointsRuleAuditError,
    PointsRuleConflictError,
    PointsRuleNotFoundError,
)
from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS
from bisheng.points.domain.schemas.points_schema import PointCopiesUpdateRequest, PointCopyItem, PointRuleRequest
from bisheng.points.domain.services.points_rule_service import PointsRuleService

_AUDIT_MESSAGE = "保存失败，积分规则未更改，请重试"  # noqa: RUF001


def _operator(user_id: int = 17, *, allowed: bool = True):
    if allowed:
        return SimpleNamespace(is_admin=lambda: True, is_global_super=True, user_id=user_id, user_name="平台管理员甲")
    return SimpleNamespace(
        is_admin=lambda: False, is_global_super=False, user_id=user_id, user_name="普通用户", role_names=[]
    )


def _rule(**overrides):
    data = {
        "id": 41,
        "tenant_id": 1,
        "rule_code": "M1",
        "rule_type": "admin_reward",
        "name": "公共库所有者月奖",
        "display_name": "公共库所有者月奖",
        "score_expr": {"mode": "fixed", "score": 200},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "enabled",
        "remark": None,
        "sort_order": 31,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _service(rule):
    repo = SimpleNamespace(
        get_rule_by_id=AsyncMock(return_value=rule),
        save_rule=AsyncMock(side_effect=lambda item: item),
        upsert_copies=AsyncMock(return_value=[]),
    )
    session = SimpleNamespace(commit=AsyncMock(), add=MagicMock(), rollback=AsyncMock())
    return PointsRuleService(session=session, repository=repo), session, repo


def _audits(session):
    found = []
    for call in session.add.call_args_list:
        obj = call.args[0]
        if getattr(obj, "action", None) == "points.rule.update":
            found.append(obj)
    return found


def test_rule_update_action_is_visible_on_system_audit_page():
    assert "points.rule.update" in _UI_VISIBLE_V2_ACTIONS


@pytest.mark.asyncio
async def test_admin_reward_score_change_writes_one_audit(caplog):
    rule = _rule()
    service, session, repo = _service(rule)
    caplog.set_level(logging.INFO)

    out = await service.update_rule(
        1,
        _operator(),
        41,
        PointRuleRequest(score_expr={"mode": "fixed", "score": 180}),
    )

    assert out.score_expr["score"] == 180
    assert session.commit.await_count == 1
    assert repo.save_rule.await_count == 1
    audits = _audits(session)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.operator_id == 17
    assert audit.operator_name == "平台管理员甲"
    assert audit.tenant_id == 1
    assert audit.operator_tenant_id == 1
    assert audit.target_type == "point_rule"
    assert audit.target_id == "41"
    assert audit.object_name == "M1"
    assert audit.audit_metadata["rule_type"] == "admin_reward"
    assert audit.audit_metadata["changes"] == [{"field": "score", "before": 200, "after": 180}]
    assert "points.rule.updated" in caplog.text
    assert "user_point_log" not in caplog.text


@pytest.mark.asyncio
async def test_one_save_with_several_fields_writes_one_audit():
    rule = _rule()
    service, session, _repo = _service(rule)

    await service.update_rule(
        1,
        _operator(),
        41,
        PointRuleRequest(
            display_name="公共库所有者",
            remark="月奖调整",
            status="disabled",
            score_expr={"mode": "fixed", "score": 180},
        ),
    )

    audits = _audits(session)
    assert len(audits) == 1
    fields = {item["field"] for item in audits[0].audit_metadata["changes"]}
    assert fields == {"score", "display_name", "remark", "status"}
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_unchanged_admin_reward_does_not_commit(caplog):
    rule = _rule()
    service, session, repo = _service(rule)
    caplog.set_level(logging.INFO)

    out = await service.update_rule(
        1,
        _operator(),
        41,
        PointRuleRequest(display_name=" 公共库所有者月奖 ", remark="   ", score_expr={"mode": "fixed", "score": 200}),
    )

    assert out.display_name == "公共库所有者月奖"
    assert out.status == "enabled"
    assert rule.score_expr["score"] == 200
    assert session.commit.await_count == 0
    assert repo.save_rule.await_count == 0
    assert _audits(session) == []
    assert "points.rule.updated" not in caplog.text
    assert "points.rule.update_failed" not in caplog.text


@pytest.mark.asyncio
async def test_user_without_platform_role_cannot_save():
    rule = _rule()
    service, session, repo = _service(rule)

    with pytest.raises(PointsPermissionDeniedError) as caught:
        await service.update_rule(
            1, _operator(99, allowed=False), 41, PointRuleRequest(score_expr={"score": 180, "mode": "fixed"})
        )

    assert caught.value.message == "无积分管理权限"
    assert rule.score_expr["score"] == 200
    assert session.commit.await_count == 0
    assert repo.get_rule_by_id.await_count == 0
    assert _audits(session) == []


@pytest.mark.asyncio
async def test_commit_failure_keeps_previous_score_and_returns_fixed_message(caplog):
    rule = _rule()
    service, session, _repo = _service(rule)
    session.commit = AsyncMock(side_effect=RuntimeError("db down"))
    caplog.set_level(logging.ERROR)

    with pytest.raises(PointsRuleAuditError) as caught:
        await service.update_rule(1, _operator(), 41, PointRuleRequest(score_expr={"mode": "fixed", "score": 180}))

    assert caught.value.code == 18209
    assert caught.value.message == _AUDIT_MESSAGE
    assert session.rollback.await_count == 1
    assert rule.score_expr["score"] == 200
    assert "points.rule.update_failed" in caplog.text
    assert "points.rule.updated" not in caplog.text


@pytest.mark.asyncio
async def test_earn_and_deduct_changes_each_write_one_audit():
    earn = _rule(
        id=11,
        rule_code="G1",
        rule_type="earn",
        name="公共库上传",
        display_name="公共库上传",
        score_expr={"mode": "fixed", "score": 3},
        daily_cap=15,
        beneficiary="uploader",
        sort_order=1,
    )
    earn_service, earn_session, _earn_repo = _service(earn)
    await earn_service.update_rule(1, _operator(), 11, PointRuleRequest(display_name="上传文档"))
    earn_audits = _audits(earn_session)
    assert len(earn_audits) == 1
    assert earn_audits[0].audit_metadata["rule_type"] == "earn"
    assert earn_audits[0].audit_metadata["rule_code"] == "G1"
    assert earn.display_name == "上传文档"

    deduct = _rule(
        id=21,
        rule_code="R1",
        rule_type="deduct",
        name="删除文档",
        display_name="删除文档",
        score_expr={"mode": "fixed", "score": 100},
        beneficiary=None,
        sort_order=2,
    )
    deduct_service, deduct_session, _deduct_repo = _service(deduct)
    await deduct_service.update_rule(1, _operator(), 21, PointRuleRequest(score_expr={"mode": "fixed", "score": 80}))
    deduct_audits = _audits(deduct_session)
    assert len(deduct_audits) == 1
    assert deduct_audits[0].audit_metadata["rule_type"] == "deduct"
    assert deduct_audits[0].audit_metadata["changes"] == [{"field": "score", "before": 100, "after": 80}]


@pytest.mark.asyncio
async def test_disable_then_enable_each_write_status_change():
    enabled = _rule()
    disable_service, disable_session, _disable_repo = _service(enabled)
    await disable_service.update_rule(1, _operator(), 41, PointRuleRequest(status="disabled"))
    disabled_audit = _audits(disable_session)[0]
    assert disabled_audit.audit_metadata["changes"] == [{"field": "status", "before": "enabled", "after": "disabled"}]

    disabled = _rule(status="disabled")
    enable_service, enable_session, _enable_repo = _service(disabled)
    await enable_service.update_rule(1, _operator(), 41, PointRuleRequest(status="enabled"))
    enabled_audit = _audits(enable_session)[0]
    assert enabled_audit.audit_metadata["changes"] == [{"field": "status", "before": "disabled", "after": "enabled"}]


@pytest.mark.asyncio
async def test_saving_the_same_score_again_does_not_add_another_audit():
    rule = _rule(score_expr={"mode": "fixed", "score": 180})
    service, session, _repo = _service(rule)

    await service.update_rule(1, _operator(), 41, PointRuleRequest(score_expr={"mode": "fixed", "score": 180}))

    assert session.commit.await_count == 0
    assert _audits(session) == []
    assert rule.score_expr["score"] == 180


@pytest.mark.asyncio
async def test_invalid_status_does_not_write_audit():
    rule = _rule()
    service, session, repo = _service(rule)

    with pytest.raises(PointsRuleConflictError) as caught:
        await service.update_rule(1, _operator(), 41, PointRuleRequest(status="paused"))

    assert caught.value.code == 18203
    assert caught.value.message != _AUDIT_MESSAGE
    assert rule.status == "enabled"
    assert session.commit.await_count == 0
    assert repo.save_rule.await_count == 0
    assert _audits(session) == []


@pytest.mark.asyncio
async def test_missing_rule_does_not_write_audit():
    service, session, repo = _service(None)
    repo.get_rule_by_id = AsyncMock(return_value=None)

    with pytest.raises(PointsRuleNotFoundError):
        await service.update_rule(1, _operator(), 999, PointRuleRequest(score_expr={"mode": "fixed", "score": 180}))

    assert session.commit.await_count == 0
    assert _audits(session) == []


@pytest.mark.asyncio
async def test_padded_display_name_is_not_a_change():
    rule = _rule()
    service, session, repo = _service(rule)

    await service.update_rule(1, _operator(), 41, PointRuleRequest(display_name=" 公共库所有者月奖 "))

    assert rule.display_name == "公共库所有者月奖"
    assert session.commit.await_count == 0
    assert repo.save_rule.await_count == 0


@pytest.mark.asyncio
async def test_fixed_score_key_order_is_not_a_change():
    rule = _rule()
    service, session, _repo = _service(rule)

    await service.update_rule(1, _operator(), 41, PointRuleRequest(score_expr={"score": 200, "mode": "fixed"}))

    assert session.commit.await_count == 0
    assert _audits(session) == []
    assert rule.score_expr == {"mode": "fixed", "score": 200}


@pytest.mark.asyncio
async def test_copy_save_does_not_write_rule_audit():
    service, session, repo = _service(_rule())

    await service.update_copies(
        1,
        _operator(),
        PointCopiesUpdateRequest(items=[PointCopyItem(copy_key="guide", content="说明", sort_order=1)]),
    )

    assert repo.upsert_copies.await_count == 1
    assert _audits(session) == []
