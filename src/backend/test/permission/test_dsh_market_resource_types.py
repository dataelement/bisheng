"""F022 registers enterprise market plugins and workbenches as F048 resources.

覆盖 AC: AC-01, AC-02, AC-03, AC-05, AC-19.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.openfga import authorization_model_f048 as model_module
from bisheng.permission.api.endpoints.grant_subjects import GRANT_SUBJECT_RESOURCE_TYPES
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services import catalog_policy
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantService
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.owner_service import (
    SYSTEM_OWNED_RESOURCE_ALLOWLIST,
    F048OwnerProjectionService,
    OwnerProjectionContext,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.resource_lifecycle_policy import (
    TENANT_SHARED_CAPABILITY_TYPES,
    default_permission_mode,
)
from test.permission.test_capability_authorization import capability_context
from test.permission.test_f048_grant_policy import FakeGrantState, FakeProjection
from test.permission.test_f048_owner_projection import _Projection, _State

MARKET_TYPES = ("dsh_market_plugin", "dsh_market_workbench")


@pytest.mark.parametrize("resource_type", MARKET_TYPES)
def test_market_types_are_registered_in_every_twin_list(resource_type):
    assert resource_type in model_module.MIGRATED_RESOURCE_TYPES
    assert resource_type in catalog_policy.MIGRATED_RESOURCE_TYPES
    assert resource_type in GRANT_SUBJECT_RESOURCE_TYPES
    assert default_permission_mode(resource_type, has_parent=False) == "CUSTOM"
    # Only the all-type actions apply; there is no market-specific edit action.
    assert resource_type in catalog_policy.ACTION_RESOURCE_SCOPES["manage_permission"]
    assert resource_type in catalog_policy.ACTION_RESOURCE_SCOPES["delete"]
    assert resource_type not in catalog_policy.ACTION_RESOURCE_SCOPES["edit"]


def test_authorization_model_defines_market_types_and_is_versioned():
    model = model_module.build_authorization_model_f048()
    defined = {definition["type"] for definition in model["type_definitions"]}
    assert set(MARKET_TYPES) <= defined
    assert model_module.MODEL_VERSION.endswith("-f022")


def test_market_types_are_revocable_all_member_system_resources():
    assert TENANT_SHARED_CAPABILITY_TYPES == frozenset({"tool", "linsight_skill", *MARKET_TYPES})
    assert set(MARKET_TYPES) <= SYSTEM_OWNED_RESOURCE_ALLOWLIST


def _visibility_model(resource_type):
    return GrantModelSnapshot(
        model_key="viewer",
        active=True,
        action_codes=(),
        derived_level=1,
        visibility_only_resource_types=(resource_type,),
        visibility_level=1,
        visibility_only=True,
    )


@pytest.mark.parametrize("resource_type", MARKET_TYPES)
async def test_system_owned_creation_projects_an_ordinary_tenant_grant(resource_type):
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type=resource_type,
        resource_id="a" * 32,
        resource_version=0,
        context_version="market-v0",
    )
    sources = GrantSourceService()
    tenant_grant = sources.add_source(
        GrantSnapshot(
            grant_id="market-all-members",
            tenant_id=5,
            resource_type=resource_type,
            resource_id="a" * 32,
            model=_visibility_model(resource_type),
            active=False,
            sources=(),
        ),
        sources.canonicalize_source(source_id=100, subject_type="tenant", subject_id="5", source_type="TENANT"),
    )
    projection = _Projection()
    service = F048OwnerProjectionService(source_service=GrantSourceService(), projection=projection, state=_State())
    result = await service.project_created(
        OwnerProjectionContext(
            target=target,
            owner_grant=None,
            source_id=1,
            owner_user_id=None,
            system_owned=True,
            system_predicate=True,
            store_id="store-live",
            model_id="model-f048",
            operator_id=1,
            idempotency_key=f"create:{resource_type}",
            creation_grants=(tenant_grant.grant,),
            creation_deltas=tenant_grant.deltas,
            system_action_codes=("visible",),
        )
    )
    deltas = projection.plans[0].deltas
    assert result.grant is None
    assert any(d.user == "tenant:5#member" and d.relation == "visible" for d in deltas)
    assert any(d.user == "tenant:5#member" and d.relation == "ordinary_assignee" for d in deltas)
    # `user:*` also carries technical mode markers (`custom_mode`,
    # `permission_enabled`); a public visibility marker could not be revoked
    # through the permission dialog.
    assert not any(d.user == "user:*" and (d.relation == "visible" or d.relation.startswith("system_")) for d in deltas)


@pytest.mark.parametrize("resource_type", MARKET_TYPES)
async def test_runtime_builds_the_all_member_grant_for_market_types(resource_type):
    context = capability_context(resource_type)
    runtime = object.__new__(F048PermissionRuntime)
    runtime._sources = GrantSourceService()
    catalog = SimpleNamespace(models=[SimpleNamespace(snapshot=context.models[0])], action_resource_scopes=())
    grant = runtime.tenant_use_grant(context.target, catalog)
    assert grant.grant.sources[0].projected_subject == "tenant:7#member"
    assert grant.grant.sources[0].protected is False


@pytest.mark.parametrize("resource_type", MARKET_TYPES)
async def test_administrators_can_revoke_and_restore_all_member_access(resource_type):
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
    current = replace(context, target=context.target.model_copy(update={"resource_version": 4}), grants=added.grants)
    removed = await service.mutate(
        current,
        changes=(CanonicalGrantChange(operation="REMOVE", assignee_id=88, expected_assignee_version=1),),
        expected_resource_version=4,
        expected_catalog_release_id=context.current_catalog_release_id,
        idempotency_key="remove-tenant",
    )
    assert all(not s.active for g in removed.grants for s in g.sources)


@pytest.mark.parametrize("resource_type", MARKET_TYPES)
async def test_legacy_public_marker_migration_stays_limited_to_tools_and_skills(resource_type):
    context = capability_context(resource_type)
    runtime = object.__new__(F048PermissionRuntime)
    runtime.build_grant_context = AsyncMock(return_value=context)
    with pytest.raises(PermissionInvalidResourceError):
        await runtime.migrate_capability_default(
            actor=PermissionActor(user_id=1, current_tenant_id=7, super_admin=True),
            target=context.target,
            remove_public_markers=False,
        )
    runtime.build_grant_context.assert_not_awaited()
