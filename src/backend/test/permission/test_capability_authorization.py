"""Ordinary grants govern public capability access and revocation."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import GrantLevelForbiddenError, PermissionInvalidResourceError
from bisheng.linsight.domain.services.skill_permission import SkillPermissionAdapter
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantService
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from test.permission.test_f048_grant_policy import FakeGrantState, FakeProjection, _context


def capability_context(resource_type="tool"):
    context = _context(capabilities=(), system_authorized=True)
    model = GrantModelSnapshot(model_key="viewer", active=True, action_codes=("use",), derived_level=1)
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7, resource_type=resource_type, resource_id="42", resource_version=3, context_version="v3"
    )
    grant = F048PermissionRuntime._empty_grant(target=target, model=model)
    return replace(context, target=target, models=(model,), grants=(grant,))


@pytest.mark.parametrize("resource_type", ["tool", "linsight_skill"])
async def test_tenant_grant_revoke_removes_use_and_visibility(resource_type):
    context = capability_context(resource_type)
    projection = FakeProjection()
    sources = GrantSourceService()
    service = GrantService(source_service=sources, projection=projection, state=FakeGrantState())
    source = sources.canonicalize_source(source_id=88, subject_type="tenant", subject_id="7", source_type="TENANT")
    added = await service.mutate(
        context,
        changes=(CanonicalGrantChange(operation="ADD", model_key="viewer", source=source),),
        expected_resource_version=3,
        expected_catalog_release_id=context.current_catalog_release_id,
        idempotency_key="add-tenant",
    )
    assert any(
        d.user == "tenant:7#member" and d.relation == "ordinary_assignee" and d.action == "WRITE"
        for d in projection.plans[-1].deltas
    )
    assert all(d.relation != "system_use_marker" for d in projection.plans[-1].deltas)
    visible = (
        VisibilityProjectionCompiler().compile(tenant_id=7, grants=added.grants, existing_sources=()).active_sources
    )
    current = replace(
        context,
        target=context.target.model_copy(update={"resource_version": 4}),
        grants=added.grants,
        existing_visible_sources=visible,
    )
    removed = await service.mutate(
        current,
        changes=(CanonicalGrantChange(operation="REMOVE", assignee_id=88, expected_assignee_version=1),),
        expected_resource_version=4,
        expected_catalog_release_id=context.current_catalog_release_id,
        idempotency_key="remove-tenant",
    )
    assert all(not s.active for g in removed.grants for s in g.sources)
    for relation in ["visible", "ordinary_assignee"]:
        assert any(
            d.user == "tenant:7#member" and d.relation == relation and d.action == "DELETE"
            for d in projection.plans[-1].deltas
        )


@pytest.mark.parametrize("tenant_id,actions", [("8", ("use",)), ("7", ("use", "manage_permission"))])
async def test_tenant_grant_rejects_cross_tenant_and_management(tenant_id, actions):
    context = capability_context()
    model = replace(context.models[0], action_codes=actions)
    context = replace(context, models=(model,), grants=(replace(context.grants[0], model=model),))
    projection = FakeProjection()
    sources = GrantSourceService()
    service = GrantService(source_service=sources, projection=projection, state=FakeGrantState())
    source = sources.canonicalize_source(
        source_id=88, subject_type="tenant", subject_id=tenant_id, source_type="TENANT"
    )
    with pytest.raises(GrantLevelForbiddenError):
        await service.mutate(
            context,
            changes=(CanonicalGrantChange(operation="ADD", model_key="viewer", source=source),),
            expected_resource_version=3,
            expected_catalog_release_id=context.current_catalog_release_id,
            idempotency_key="invalid",
        )
    assert projection.prepared == []


@pytest.mark.parametrize(
    "tenant,source,owner,enabled,allowed",
    [
        (7, "builtin", None, True, True),
        (8, "builtin", None, True, False),
        (7, "personal", 9, True, False),
        (7, "personal", 2, True, True),
        (7, "builtin", None, False, False),
    ],
)
async def test_skill_target_checks_tenant_owner_status(tenant, source, owner, enabled, allowed):
    row = SimpleNamespace(id=42, tenant_id=tenant, source=source, created_by=owner, enabled=enabled, update_time=None)
    runtime = SimpleNamespace(get_permission_version=AsyncMock(return_value=(3, "current")))
    adapter = SkillPermissionAdapter(runtime, SimpleNamespace(get=AsyncMock(return_value=row)))
    actor = PermissionActor(user_id=2, current_tenant_id=7)
    if allowed:
        target = await adapter.resolve_permission_target(resource_id="42", actor=actor, action="use")
        assert (target.resource_type, target.tenant_id) == ("linsight_skill", 7)
    else:
        with pytest.raises(PermissionInvalidResourceError):
            await adapter.resolve_permission_target(resource_id="42", actor=actor, action="use")
        runtime.get_permission_version.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,operation,source,expected",
    [
        (None, None, False, "create"),
        (SimpleNamespace(projection_state="CURRENT"), None, False, "migrate"),
        (SimpleNamespace(projection_state="CURRENT"), None, True, "preserved"),
        (SimpleNamespace(projection_state="CURRENT"), SimpleNamespace(status="FINALIZED"), False, "preserved"),
    ],
)
def test_migration_keeps_existing_and_revoked_grants(mode, operation, source, expected):
    from scripts.migrate_capability_authorization import migration_state

    assert migration_state(mode, operation, source) == expected


def test_migration_stops_for_unfinished_operation():
    from scripts.migrate_capability_authorization import migration_state

    with pytest.raises(RuntimeError):
        migration_state(SimpleNamespace(projection_state="CURRENT"), SimpleNamespace(status="COMMIT_UNKNOWN"), False)


async def test_default_grant_uses_tenant_members_and_migration_deletes_public_markers():
    context = capability_context()
    runtime = object.__new__(F048PermissionRuntime)
    runtime._sources = GrantSourceService()
    catalog = SimpleNamespace(models=[SimpleNamespace(snapshot=context.models[0])])
    runtime.current_catalog = AsyncMock(return_value=catalog)
    runtime.build_grant_context = AsyncMock(return_value=context)
    runtime._grants = SimpleNamespace(mutate=AsyncMock())
    grant = runtime.tenant_use_grant(context.target, catalog)
    assert grant.grant.sources[0].projected_subject == "tenant:7#member"
    assert grant.grant.sources[0].protected is False
    await runtime.migrate_capability_default(
        actor=PermissionActor(user_id=1, current_tenant_id=7, super_admin=True),
        target=context.target,
        remove_public_markers=True,
    )
    kwargs = runtime._grants.mutate.call_args.kwargs
    assert {(delta.user, delta.relation, delta.action) for delta in kwargs["migration_deltas"]} == {
        ("user:*", "visible", "DELETE"),
        ("user:*", "system_use_marker", "DELETE"),
    }
    assert kwargs["changes"][0].source.projected_subject == "tenant:7#member"
