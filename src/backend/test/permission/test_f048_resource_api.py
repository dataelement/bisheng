"""F048 resource API business-boundary contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.permission.application.resource_api import (
    F048ResourcePermissionApi,
)
from bisheng.permission.domain.schemas import (
    GrantMutationRequest,
    VerifiedPermissionTarget,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.permission.domain.services.permission_explain_service import (
    PermissionSourceExplanation,
)


class _Resources:
    async def resolve(self, **kwargs):
        del kwargs
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=9,
            resource_type="workflow",
            resource_id="wf-1",
            resource_version=3,
            context_version="workflow:wf-1:v3",
        )


class _ToolPort:
    async def resolve_permission_target(self, *, resource_id, actor, action):
        del actor, action
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=9,
            resource_type="tool",
            resource_id=resource_id,
            resource_version=3,
            context_version=f"tool:{resource_id}:v3",
        )

    async def load_permission_record(self, *, resource_id):
        return SimpleNamespace(
            resource_id=resource_id,
            preset=True,
            system_allowlisted=True,
        )


class _ToolResources:
    def __init__(self) -> None:
        self.port = _ToolPort()

    async def resolve(self, **kwargs):
        return await self.port.resolve_permission_target(
            resource_id=kwargs["resource_id"],
            actor=kwargs["actor"],
            action=kwargs["action"],
        )

    def port_for(self, resource_type):
        return self.port if resource_type == "tool" else None


class _Runtime:
    def __init__(self) -> None:
        self.changes = ()
        self.page_calls = []

    async def allocate_source_ids(self, count):
        assert count == 1
        return (91,)

    async def mutate_grants(self, **kwargs):
        self.changes = kwargs["changes"]
        model = SimpleNamespace(
            model_key="viewer",
            derived_level=1,
            active=True,
        )
        source = SimpleNamespace(
            source_id=91,
            version=2,
            subject_type="user",
            subject_id="8",
            source_type="DIRECT",
            include_children=False,
            protected=False,
            active=True,
        )
        return SimpleNamespace(
            resource_version=4,
            grants=(
                SimpleNamespace(
                    model=model,
                    active=True,
                    sources=(source,),
                ),
            ),
        )

    async def require_manage_permission(self, actor, target):
        del actor, target

    async def current_catalog(self):
        model = SimpleNamespace(
            snapshot=SimpleNamespace(model_key="viewer"),
            name="Viewer",
        )
        return SimpleNamespace(release_id=12, models=(model,))

    async def list_permission_sources_page(self, **kwargs):
        self.page_calls.append(kwargs)
        return (
            (
                PermissionSourceExplanation(
                    source_id=91,
                    source_version=2,
                    subject_type="user",
                    subject_id="8",
                    userset_relation=None,
                    include_children=False,
                    source_type="DIRECT",
                    model_key="viewer",
                    model_level=1,
                    scope="LOCAL",
                    inherited_from=None,
                    protected=False,
                    editable=True,
                ),
            ),
            True,
        )


class _Subjects:
    def __init__(self) -> None:
        self.tenant_ids = []
        self.sources = GrantSourceService()

    async def canonical_source(self, *, tenant_id, source_id, **kwargs):
        self.tenant_ids.append(tenant_id)
        return self.sources.canonicalize_source(
            source_id=source_id,
            subject_type=kwargs["subject_type"],
            subject_id=kwargs["subject_id"],
            source_type="DIRECT",
        )

    async def display_names(self, subjects):
        return {("user", "8"): "Member 8"}

    async def actor_projected_subjects(self, actor):
        return frozenset({f"user:{actor.user_id}"})


@pytest.mark.asyncio
async def test_super_admin_subject_validation_uses_target_tenant() -> None:
    runtime = _Runtime()
    subjects = _Subjects()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=subjects,
    )
    actor = PermissionActor(
        user_id=7,
        current_tenant_id=5,
        super_admin=True,
    )

    result = await api.mutate_grants(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
        request=GrantMutationRequest.model_validate(
            {
                "idempotency_key": "grant-target-tenant",
                "expected_resource_version": 3,
                "expected_catalog_release_id": 12,
                "changes": [
                    {
                        "op": "ADD",
                        "model_key": "viewer",
                        "subject": {
                            "type": "user",
                            "id": "8",
                        },
                    }
                ],
            }
        ),
    )

    assert result["resource_version"] == 4
    assert result["items"][0]["subject"] == {
        "type": "user",
        "id": "8",
        "name": None,
    }
    assert subjects.tenant_ids == [9]
    assert runtime.changes[0].source.projected_subject == "user:8"
    assert runtime.page_calls == []


class _ContextRuntime(_Runtime):
    """A runtime whose FGA visible check always denies.

    check_visible never waves admins through, so an admin's context request must
    not depend on it — the API's own identity shortcut is what must let them in.
    """

    def __init__(self) -> None:
        super().__init__()
        self.visible_checks = 0

    async def check_action(self, actor, target, action):
        if action == "visible":
            self.visible_checks += 1
            return False
        return True

    async def current_mode(self, target):
        del target
        return SimpleNamespace(mode="CUSTOM", projection_state="READY")

    async def mode_for_target(self, target):
        del target
        return SimpleNamespace(
            mode="CUSTOM",
            projection_state="CURRENT",
            version=3,
        )

    async def effective_actions(self, resource_type):
        del resource_type
        # 'visible' is a base relation, not a registered action, so it never
        # appears in the effective action set.
        return ("use", "edit", "delete", "manage_permission")


class _ExplainRuntime(_ContextRuntime):
    """Visible via FGA, but the grant-derived explanation is empty.

    Models an ordinary user who can see the resource yet holds no grant rows —
    the path that must stay grant-derived (and NOT be handed the full set).
    """

    async def check_action(self, actor, target, action):
        if action == "visible":
            self.visible_checks += 1
            return True
        return True

    async def explain_permissions(self, **kwargs):
        del kwargs
        return SimpleNamespace(mode="CUSTOM", action_codes=(), sources=())


@pytest.mark.asyncio
async def test_super_admin_reads_context_without_a_visible_tuple() -> None:
    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=5, super_admin=True)

    result = await api.get_context(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
    )

    # The visibility gate must be skipped for the super admin, never consulted.
    assert runtime.visible_checks == 0
    assert result["mode"] == "CUSTOM"
    assert result["can_manage_permission"] is True


@pytest.mark.asyncio
async def test_tenant_admin_reads_context_for_own_tenant_without_visible_tuple() -> None:
    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    # _Resources resolves the target into tenant 9.
    actor = PermissionActor(
        user_id=7,
        current_tenant_id=9,
        tenant_admin_tenant_ids=frozenset({9}),
    )

    result = await api.get_context(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
    )

    assert runtime.visible_checks == 0
    assert result["can_manage_permission"] is True


@pytest.mark.asyncio
async def test_ordinary_user_context_still_requires_a_visible_tuple() -> None:
    from bisheng.common.errcode.permission import PermissionDeniedError

    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=9)

    with pytest.raises(PermissionDeniedError):
        await api.get_context(
            resource_type="workflow",
            resource_id="wf-1",
            actor=actor,
        )
    assert runtime.visible_checks == 1


@pytest.mark.asyncio
async def test_super_admin_my_permissions_returns_full_effective_actions() -> None:
    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=5, super_admin=True)

    result = await api.get_my_permissions(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
    )

    # No grant rows exist for a super admin, so the grant-derived explanation
    # would be empty; the full effective action set is reported instead.
    assert result["actions"] == ["use", "edit", "delete", "manage_permission"]
    assert result["sources"] == []
    assert result["projection_degraded"] is False
    assert runtime.visible_checks == 0


@pytest.mark.asyncio
async def test_ordinary_user_my_permissions_for_preset_tool_returns_empty_actions() -> None:
    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_ToolResources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=9)

    result = await api.get_my_permissions(
        resource_type="tool",
        resource_id="20",
        actor=actor,
    )

    assert result["actions"] == []
    assert result["sources"] == []
    assert result["projection_degraded"] is False
    assert runtime.visible_checks == 0


@pytest.mark.asyncio
async def test_super_admin_my_permissions_for_preset_tool_returns_full_actions() -> None:
    runtime = _ContextRuntime()
    api = F048ResourcePermissionApi(
        resources=_ToolResources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=5, super_admin=True)

    result = await api.get_my_permissions(
        resource_type="tool",
        resource_id="20",
        actor=actor,
    )

    assert result["actions"] == ["use", "edit", "delete", "manage_permission"]
    assert result["sources"] == []
    assert runtime.visible_checks == 0


@pytest.mark.asyncio
async def test_ordinary_user_my_permissions_stays_grant_derived() -> None:
    runtime = _ExplainRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    # Same tenant as the resolved target (9) but no admin rights.
    actor = PermissionActor(user_id=7, current_tenant_id=9)

    result = await api.get_my_permissions(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
    )

    # Ordinary user: went through the real visibility check and stayed on the
    # grant-derived path (empty here), never handed the full effective set.
    assert runtime.visible_checks == 1
    assert result["actions"] == []


class _DegradedPermissionRuntime(_ExplainRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.explain_calls = 0

    async def mode_for_target(self, target):
        del target
        return SimpleNamespace(
            mode="CUSTOM",
            projection_state="FAILED_CLOSED",
            version=3,
        )

    async def check_action(self, actor, target, action):
        del actor, target
        if action == "visible":
            self.visible_checks += 1
            return True
        return action in {"use", "edit"}

    async def explain_permissions(self, **kwargs):
        del kwargs
        self.explain_calls += 1
        raise AssertionError("degraded projection must not read staged grant explanations")


@pytest.mark.asyncio
async def test_degraded_my_permissions_uses_openfga_actions_without_staged_sources() -> None:
    runtime = _DegradedPermissionRuntime()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=_Subjects(),
    )
    actor = PermissionActor(user_id=7, current_tenant_id=9)

    result = await api.get_my_permissions(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
    )

    assert result == {
        "mode": "CUSTOM",
        "actions": ["use", "edit"],
        "sources": [],
        "roster_complete": False,
        "projection_state": "FAILED_CLOSED",
        "projection_degraded": True,
    }
    assert runtime.visible_checks == 1
    assert runtime.explain_calls == 0


@pytest.mark.asyncio
async def test_roster_uses_bounded_sql_page_instead_of_full_explanation() -> None:
    runtime = _Runtime()
    subjects = _Subjects()
    api = F048ResourcePermissionApi(
        resources=_Resources(),
        runtime=runtime,
        subjects=subjects,
    )
    actor = PermissionActor(
        user_id=7,
        current_tenant_id=9,
        tenant_admin_tenant_ids=frozenset({9}),
    )

    result = await api.list_grants(
        resource_type="workflow",
        resource_id="wf-1",
        actor=actor,
        cursor=None,
        page_size=25,
    )

    assert result["data"][0]["subject"]["name"] == "Member 8"
    assert result["has_more"] is True
    assert result["next_cursor"]
    assert runtime.page_calls == [
        {
            "actor": actor,
            "target": await _Resources().resolve(),
            "after_id": 0,
            "limit": 25,
        }
    ]
