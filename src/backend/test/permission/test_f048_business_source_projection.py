"""Business-owned membership source reconciliation contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import (
    GrantMutationContext,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _GrantMutation:
    def __init__(self) -> None:
        self.calls = []

    async def mutate(self, context, **kwargs):
        self.calls.append((context, kwargs))
        return kwargs


def _target(version: int = 3) -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="channel",
        resource_id="channel-1",
        resource_version=version,
        context_version=f"ctx-{version}",
    )


def _model(key: str, level: int) -> GrantModelSnapshot:
    return GrantModelSnapshot(
        model_key=key,
        active=True,
        action_codes=("visible", "manage_permission"),
        derived_level=level,
    )


def _grant(
    model: GrantModelSnapshot,
    *,
    sources=(),
) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=f"grant-{model.model_key}",
        tenant_id=5,
        resource_type="channel",
        resource_id="channel-1",
        model=model,
        active=bool(sources),
        sources=tuple(sources),
    )


def _runtime(context: GrantMutationContext):
    runtime = object.__new__(F048PermissionRuntime)
    mutation = _GrantMutation()
    runtime._grants = mutation

    async def build_grant_context(*, actor, target):
        del actor, target
        return context

    runtime.build_grant_context = build_grant_context
    return runtime, mutation


def _context(*, grants) -> GrantMutationContext:
    target = _target()
    return GrantMutationContext(
        target=target,
        current_catalog_release_id=8,
        store_id="store",
        model_id="model",
        operator_id=7,
        mode="CUSTOM",
        system_authorized=False,
        capabilities=(),
        models=tuple(grant.model for grant in grants),
        grants=tuple(grants),
    )


def _source(source_id: int = 1):
    return GrantSourceService().canonicalize_source(
        source_id=source_id,
        subject_type="user",
        subject_id="8",
        source_type="CHANNEL_MEMBERSHIP",
        source_ref="channel-1:user:8",
    )


@pytest.mark.asyncio
async def test_business_membership_add_uses_system_authorized_mutation() -> None:
    viewer = _grant(_model("viewer", 1))
    manager = _grant(_model("manager", 3))
    runtime, mutation = _runtime(_context(grants=(viewer, manager)))

    await runtime.sync_business_source_model(
        actor=PermissionActor(user_id=7, current_tenant_id=5),
        target=_target(),
        source=_source(),
        model_key="viewer",
        idempotency_key="membership-add",
    )

    context, request = mutation.calls[0]
    assert context.system_authorized is True
    assert request["changes"][0].operation == "ADD"
    assert request["changes"][0].model_key == "viewer"
    assert request["changes"][0].source.source_id != 1


@pytest.mark.asyncio
async def test_business_membership_move_and_remove_are_exact() -> None:
    existing = replace(_source(42), version=4)
    viewer = _grant(_model("viewer", 1), sources=(existing,))
    manager = _grant(_model("manager", 3))
    runtime, mutation = _runtime(_context(grants=(viewer, manager)))

    await runtime.sync_business_source_model(
        actor=PermissionActor(user_id=7, current_tenant_id=5),
        target=_target(),
        source=_source(),
        model_key="manager",
        idempotency_key="membership-move",
    )
    move = mutation.calls[0][1]["changes"][0]
    assert move.operation == "MOVE"
    assert move.assignee_id == 42
    assert move.expected_assignee_version == 4
    assert move.target_model_key == "manager"

    mutation.calls.clear()
    await runtime.sync_business_source_model(
        actor=PermissionActor(user_id=7, current_tenant_id=5),
        target=_target(),
        source=_source(),
        model_key=None,
        idempotency_key="membership-remove",
    )
    remove = mutation.calls[0][1]["changes"][0]
    assert remove.operation == "REMOVE"
    assert remove.assignee_id == 42


@pytest.mark.asyncio
async def test_business_membership_same_model_is_idempotent() -> None:
    viewer = _grant(_model("viewer", 1), sources=(_source(42),))
    runtime, mutation = _runtime(_context(grants=(viewer,)))

    result = await runtime.sync_business_source_model(
        actor=PermissionActor(user_id=7, current_tenant_id=5),
        target=_target(),
        source=_source(),
        model_key="viewer",
        idempotency_key="membership-noop",
    )

    assert result is None
    assert mutation.calls == []


@pytest.mark.asyncio
async def test_private_switch_removes_only_ordinary_sources() -> None:
    ordinary = _source(42)
    protected = replace(_source(43), protected=True)
    viewer = _grant(_model("viewer", 1), sources=(ordinary,))
    owner = _grant(_model("owner", 4), sources=(protected,))
    runtime, mutation = _runtime(_context(grants=(viewer, owner)))

    await runtime.remove_ordinary_sources(
        actor=PermissionActor(user_id=7, current_tenant_id=5),
        target=_target(),
        idempotency_key="private",
    )

    changes = mutation.calls[0][1]["changes"]
    assert [(row.operation, row.assignee_id) for row in changes] == [("REMOVE", 42)]
