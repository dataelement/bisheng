"""F118 system-owner projection contracts. AC-78, AC-79, AC-81, AC-83."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
    model_snapshot_for_target,
)
from bisheng.permission.domain.services.owner_service import F048OwnerProjectionService, OwnerProjectionContext
from bisheng.permission.domain.services.projection_plan import ProjectionOutcome


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("This owner projection test must not open a network connection")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.socket.connect_ex", reject)
    monkeypatch.setattr("socket.create_connection", reject)


def system_context(resource_type="workflow", action_codes=("visible",)):
    return OwnerProjectionContext(
        target=VerifiedPermissionTarget.from_business_service(
            tenant_id=5,
            resource_type=resource_type,
            resource_id="builtin-1",
            resource_version=0,
            context_version="builtin-v0",
        ),
        owner_grant=None,
        source_id=1,
        owner_user_id=None,
        system_owned=True,
        system_predicate=True,
        store_id="store",
        model_id="model",
        operator_id=7,
        idempotency_key=f"create:{resource_type}:builtin-1",
        system_action_codes=action_codes,
        permission_mode="CUSTOM",
    )


def tenant_context(resource_type="tool", action_codes=("visible",)):
    context = system_context(resource_type, action_codes)
    model = model_snapshot_for_target(
        GrantModelSnapshot(
            "original-viewer",
            True,
            ("download",),
            derived_level=1,
            visibility_only_resource_types=("tool", "linsight_skill"),
            visibility_level=3,
        ),
        resource_type=resource_type,
        applicable_action_codes=(),
    )
    sources = GrantSourceService()
    mutation = sources.add_source(
        GrantSnapshot("builtin-viewer", 5, resource_type, "builtin-1", model, False, ()),
        sources.canonicalize_source(source_id=9, subject_type="tenant", subject_id="5", source_type="TENANT"),
    )
    return replace(context, creation_grants=(mutation.grant,), creation_deltas=mutation.deltas)


def harness(*, error=None):
    events = []

    def prepare(plan):
        events.append("prepare-plan")
        return SimpleNamespace(id=77, status="PREPARED")

    def execute(plan):
        events.append("execute-projection")
        if error:
            raise error
        return ProjectionOutcome(77, 1, "FINALIZED", "c" * 64)

    projection = SimpleNamespace(
        prepare=AsyncMock(side_effect=prepare), execute=AsyncMock(side_effect=execute), abandon_prepared=AsyncMock()
    )
    state = SimpleNamespace(
        prepare=AsyncMock(side_effect=lambda *args, **kwargs: events.append("prepare-state")),
        finalize=AsyncMock(side_effect=lambda *args, **kwargs: events.append("finalize-state")),
        mark_compensation_required=AsyncMock(),
    )
    return (
        F048OwnerProjectionService(source_service=GrantSourceService(), projection=projection, state=state),
        projection,
        state,
        events,
    )


@pytest.mark.parametrize("resource_type", ("workflow", "assistant", "tool", "linsight_skill"))
@pytest.mark.parametrize("action_codes", (("use",), ("visible", "use")))
async def test_retired_system_use_is_rejected_before_preparing_any_projection(resource_type, action_codes):
    context = (
        tenant_context(resource_type, action_codes)
        if resource_type in {"tool", "linsight_skill"}
        else system_context(resource_type, action_codes)
    )
    service, projection, state, events = harness()
    with pytest.raises(PermissionInvalidResourceError):
        await service.project_created(context)
    projection.prepare.assert_not_awaited()
    state.prepare.assert_not_awaited()
    assert events == []


@pytest.mark.parametrize("resource_type", ("workflow", "assistant"))
async def test_system_application_visible_projection_keeps_original_subject_and_commit_order(resource_type):
    context = system_context(resource_type)
    service, projection, state, events = harness()
    result = await service.project_created(context)
    plan = projection.prepare.call_args.args[0]
    assert events == ["prepare-plan", "prepare-state", "execute-projection", "finalize-state"]
    assert result.grant is result.source is None
    assert {(row.user, row.relation) for row in plan.deltas if row.relation == "visible"} == {("user:*", "visible")}
    assert not any(row.relation.startswith("system_") or "use" in row.relation for row in plan.deltas)
    assert state.prepare.call_args.args[0] is context
    assert state.finalize.call_args.args[0] is context


@pytest.mark.parametrize("resource_type", ("tool", "linsight_skill"))
async def test_builtin_tenant_projection_accepts_pure_viewer_without_changing_source_or_tier(resource_type):
    context = tenant_context(resource_type)
    original = context.creation_grants[0]
    service, projection, state, events = harness()
    await service.project_created(context)
    plan = projection.prepare.call_args.args[0]
    visibility = state.prepare.call_args.args[3]
    assert events == ["prepare-plan", "prepare-state", "execute-projection", "finalize-state"]
    assert original.model.visibility_only and original.model.action_codes == ()
    assert original.model.derived_level == original.model.visibility_level == 3
    assert state.finalize.call_args.args[0].creation_grants[0] is original
    assert visibility.active_sources[0].source_fingerprint == original.sources[0].source_fingerprint
    assert visibility.active_sources[0].model_key == "original-viewer"
    assert {(row.user, row.relation) for row in plan.deltas if row.relation == "visible"} == {
        ("tenant:5#member", "visible")
    }
    assert not any("use" in row.relation or row.relation.startswith("system_") for row in plan.deltas)


@pytest.mark.parametrize("action_codes", ((), ("edit",), ("rename",), ("share",), ("publish",), ("manage_permission",)))
async def test_system_action_empty_and_other_actions_remain_invalid(action_codes):
    service, projection, _, _ = harness()
    with pytest.raises(PermissionInvalidResourceError):
        await service.project_created(system_context(action_codes=action_codes))
    projection.prepare.assert_not_awaited()


async def test_existing_download_system_marker_is_preserved():
    service, projection, _, _ = harness()
    await service.project_created(system_context(action_codes=("visible", "download")))
    relations = {row.relation for row in projection.prepare.call_args.args[0].deltas}
    assert "system_download_marker" in relations
    assert "visible" in relations and "system_use_marker" not in relations


@pytest.mark.parametrize("change", ({"system_predicate": False}, {"owner_user_id": 7}))
async def test_system_owned_creation_still_requires_the_original_business_predicate(change):
    service, projection, _, _ = harness()
    with pytest.raises(PermissionInvalidResourceError):
        await service.project_created(replace(system_context(), **change))
    projection.prepare.assert_not_awaited()


async def test_arbitrary_unmarked_empty_model_cannot_gain_tenant_visibility():
    context = tenant_context()
    grant = replace(context.creation_grants[0], model=GrantModelSnapshot("empty", True, (), derived_level=3))
    service, projection, _, _ = harness()
    with pytest.raises(ValueError, match="valid permission model"):
        await service.project_created(replace(context, creation_grants=(grant,)))
    projection.prepare.assert_not_awaited()


async def test_projection_failure_never_finalizes_sql_state():
    error = RuntimeError("injected projection failure")
    service, _, state, events = harness(error=error)
    context = tenant_context()
    with pytest.raises(RuntimeError, match="injected projection failure"):
        await service.project_created(context)
    assert events == ["prepare-plan", "prepare-state", "execute-projection"]
    state.finalize.assert_not_awaited()
    state.mark_compensation_required.assert_awaited_once_with(context, error)
