"""Listing must not pay for actions it only needs on the page it returns.

`batch_check_business_actions` loops actions on the outside and resolves every
candidate inside, so its cost is actions x candidates. The knowledge list asked
for all five list actions on each of its 100-row scan batches while filtering on
one of them, and the four extras were then used only for the <=20 rows that
survived — 500 resolutions per batch to decorate at most twenty. One observed
request spent 70s this way.

A super admin is worse still: the decision layer allows them unconditionally,
but only after each candidate has already been resolved.
"""

from __future__ import annotations

import pytest

from bisheng.permission.application import business_authorization
from bisheng.permission.domain.services.permission_action_service import PermissionActor


class _CountingRegistry:
    def __init__(self) -> None:
        self.resolutions = 0

    async def resolve(self, *, resource_type, resource_id, actor, action):
        del resource_type, actor, action
        self.resolutions += 1
        return object()


class _AllowAllRuntime:
    async def batch_check_actions(self, actor, targets, action):
        del actor, action
        return [True] * len(targets)

    async def check_action(self, actor, target, action):
        del actor, target, action
        return True


@pytest.fixture
def counted(monkeypatch):
    registry = _CountingRegistry()

    async def get_registry():
        return registry

    async def get_runtime():
        return _AllowAllRuntime()

    monkeypatch.setattr(business_authorization, "get_f048_resource_registry", get_registry)
    monkeypatch.setattr(business_authorization, "get_f048_runtime", get_runtime)
    return registry


def _actor_resolver(monkeypatch, actor: PermissionActor) -> None:
    async def resolve(login_user):
        del login_user
        return actor

    monkeypatch.setattr(business_authorization, "resolve_permission_actor", resolve)


async def test_cost_is_actions_times_candidates(monkeypatch, counted) -> None:
    """The multiplier is real, which is why the caller must not over-ask."""

    _actor_resolver(monkeypatch, PermissionActor(user_id=7, current_tenant_id=1))

    await business_authorization.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=[str(index) for index in range(100)],
        actions=("visible", "use", "edit", "delete", "manage_permission"),
    )

    assert counted.resolutions == 500


async def test_filtering_on_one_action_costs_one_pass(monkeypatch, counted) -> None:
    _actor_resolver(monkeypatch, PermissionActor(user_id=7, current_tenant_id=1))

    await business_authorization.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=[str(index) for index in range(100)],
        actions=("visible",),
    )

    assert counted.resolutions == 100


async def test_a_super_admin_resolves_nothing(monkeypatch, counted) -> None:
    _actor_resolver(
        monkeypatch,
        PermissionActor(user_id=1, current_tenant_id=1, super_admin=True),
    )

    granted = await business_authorization.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=["1", "2", "3"],
        actions=("visible", "use", "edit"),
    )

    assert counted.resolutions == 0
    assert granted == {
        "1": frozenset({"visible", "use", "edit"}),
        "2": frozenset({"visible", "use", "edit"}),
        "3": frozenset({"visible", "use", "edit"}),
    }


async def test_an_ordinary_user_still_goes_through_resolution(monkeypatch, counted) -> None:
    """The shortcut must key off the identity, never off the batch shape."""

    _actor_resolver(monkeypatch, PermissionActor(user_id=7, current_tenant_id=1))

    await business_authorization.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=["1", "2", "3"],
        actions=("visible",),
    )

    assert counted.resolutions == 3


async def test_super_admin_single_check_resolves_nothing(monkeypatch, counted) -> None:
    """Single-resource checks (detail, delete, ...) must short-circuit too.

    Resolution runs business data-validity guards that do not exempt super
    admins, so resolving a legitimate-but-imperfect record (e.g. a system-owned
    custom dashboard with a null owner) would raise before the decision layer
    ever allowed the super admin. Mirror the batch path and resolve nothing.
    """

    _actor_resolver(
        monkeypatch,
        PermissionActor(user_id=1, current_tenant_id=1, super_admin=True),
    )

    allowed = await business_authorization.check_business_action(
        object(),
        resource_type="dashboard",
        resource_id="156",
        action="visible",
    )

    assert allowed is True
    assert counted.resolutions == 0


async def test_ordinary_user_single_check_still_resolves(monkeypatch, counted) -> None:
    """The shortcut keys off the identity, never off the call shape."""

    _actor_resolver(monkeypatch, PermissionActor(user_id=7, current_tenant_id=1))

    allowed = await business_authorization.check_business_action(
        object(),
        resource_type="dashboard",
        resource_id="156",
        action="visible",
    )

    assert allowed is True
    assert counted.resolutions == 1


async def test_single_check_accepts_pre_resolved_actor(monkeypatch, counted) -> None:
    async def unexpected_resolve(_login_user):
        raise AssertionError("provided actor must bypass identity resolution")

    monkeypatch.setattr(business_authorization, "resolve_permission_actor", unexpected_resolve)
    actor = PermissionActor(user_id=7, current_tenant_id=1)

    allowed = await business_authorization.check_business_action(
        object(),
        resource_type="dashboard",
        resource_id="156",
        action="visible",
        actor=actor,
    )

    assert allowed is True
    assert counted.resolutions == 1


@pytest.mark.parametrize(
    "actor",
    [
        PermissionActor(user_id=1, current_tenant_id=1, super_admin=True),
        PermissionActor(user_id=2, current_tenant_id=7, tenant_admin_tenant_ids=frozenset({7})),
    ],
)
async def test_visible_batch_never_expands_admin_identity(
    monkeypatch,
    counted,
    actor: PermissionActor,
) -> None:
    _actor_resolver(monkeypatch, actor)

    granted = await business_authorization.batch_check_business_visible(
        object(),
        resource_type="knowledge_file",
        resource_ids=["1", "2", "3"],
    )

    assert counted.resolutions == 3
    assert granted == {"1": True, "2": True, "3": True}


async def test_visible_batch_accepts_pre_resolved_actor(monkeypatch, counted) -> None:
    async def unexpected_resolve(_login_user):
        raise AssertionError("provided actor must bypass identity resolution")

    monkeypatch.setattr(business_authorization, "resolve_permission_actor", unexpected_resolve)
    actor = PermissionActor(user_id=7, current_tenant_id=1)

    granted = await business_authorization.batch_check_business_visible(
        object(),
        resource_type="knowledge_file",
        resource_ids=["1", "2", "3"],
        actor=actor,
    )

    assert counted.resolutions == 3
    assert granted == {"1": True, "2": True, "3": True}
