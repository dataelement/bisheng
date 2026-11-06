"""Skill visibility and executable availability are independent. AC-79/82/83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.services.skill_permission import SkillPermissionAdapter, ensure_builtin_skill_permission
from bisheng.linsight.domain.services.user_skills import UserSkillsService
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.application.resource_authorization import ResourceAuthorizationRegistry
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification.test_perm_runtime import decision


@pytest.fixture
def skills(monkeypatch):
    rows = [
        LinsightSkill(id=1, tenant_id=101, name="on", enabled=True, owner_user_id=0),
        LinsightSkill(id=2, tenant_id=101, name="off", enabled=False, owner_user_id=0),
        LinsightSkill(id=3, tenant_id=202, name="foreign", enabled=True, owner_user_id=0),
        LinsightSkill(id=4, tenant_id=101, name="other-owner", enabled=True, owner_user_id=8),
    ]
    by_id = {row.id: row for row in rows}
    runtime, fga = decision()
    fga.batch_check.side_effect = lambda checks, **kwargs: [True] * len(checks)
    adapter = SkillPermissionAdapter(
        SimpleNamespace(get_permission_version=AsyncMock(return_value=(1, "skill-current"))),
        SimpleNamespace(get=AsyncMock(side_effect=by_id.get)),
    )
    registry = ResourceAuthorizationRegistry()
    registry.register("linsight_skill", adapter)
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    checks = AsyncMock(wraps=business.batch_check_business_actions)
    monkeypatch.setattr(business, "batch_check_business_actions", checks)
    account = SimpleNamespace(disabled_ids=AsyncMock(return_value=set()), save=AsyncMock())
    actor = PermissionActor(user_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        yield SimpleNamespace(
            rows=rows,
            service=UserSkillsService(7, account),
            actor=actor,
            adapter=adapter,
            checks=checks,
            fga=fga,
            account=account,
        )
    finally:
        reset_current_permission_actor(token)


async def test_runtime_candidates_require_enabled_in_addition_to_visibility(skills):
    result = await skills.service.records(candidates=skills.rows, actor=object())
    assert [(row.id, enabled) for row, enabled in result] == [(1, True)]
    assert skills.checks.await_args.kwargs["actions"] == ("visible",)


async def test_management_visibility_keeps_disabled_and_account_off_rows(skills):
    skills.account.disabled_ids.return_value = {1}
    result = await skills.service.records(False, candidates=skills.rows, actor=object())
    assert [(row.id, enabled) for row, enabled in result] == [(1, False), (2, True)]
    assert await skills.service.records(candidates=skills.rows, actor=object()) == []


@pytest.mark.parametrize("action", ["visible", "edit", "delete"])
async def test_disabled_skill_target_stays_resolvable_for_management(skills, action):
    target = await skills.adapter.resolve_permission_target(resource_id="2", actor=skills.actor, action=action)
    assert target.resource_id == "2"


async def test_original_narrowed_scope_filters_runtime_before_fga(skills, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=101, data_scope="OWNED"))
    try:
        assert await skills.service.records(candidates=skills.rows, actor=object()) == []
    finally:
        reset_current_permission_actor(token)
    skills.fga.batch_check.assert_not_awaited()


async def test_builtin_skill_creation_emits_only_visibility(monkeypatch):
    from bisheng.permission.application import process_runtime, system_resource_reconcile

    runtime = object()
    reconcile = AsyncMock()
    monkeypatch.setattr(
        process_runtime,
        "get_f048_process_runtime",
        AsyncMock(return_value=SimpleNamespace(components=SimpleNamespace(facade=runtime))),
    )
    monkeypatch.setattr(system_resource_reconcile, "reconcile_system_owned_resources", reconcile)
    await ensure_builtin_skill_permission(SimpleNamespace(id=2, tenant_id=101))
    assert reconcile.await_args.args[0] is runtime
    assert reconcile.await_args.args[1][0].action_codes == ("visible",)
