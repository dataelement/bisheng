"""Accepting an invitation must not be a one-way door.

Joining by subscribing writes a membership row; accepting an invitation writes
a personal Grant source and no row at all. Leaving was implemented as
"cancel your subscription", so it looked for that row, found none, and refused
— telling the invitee their access came from somebody else's grant and only an
administrator could take it back. It was their own grant, accepted by them.

What must still be refused is leaving access that arrived through a department
or a user group: an individual cannot resign from their department's grant.
That is the case the refusal was written for, and the only one it should
appear in now.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantMutationContext
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor

INVITEE = "150025"
COLLEAGUE = "150041"


def _source(
    *,
    source_id: int,
    subject_type: str = "user",
    subject_id: str = INVITEE,
    source_type: str = "DIRECT",
    protected: bool = False,
    active: bool = True,
) -> GrantSourceRecord:
    return GrantSourceRecord(
        source_id=source_id,
        subject_type=subject_type,
        subject_id=subject_id,
        userset_relation=None,
        include_children=False,
        source_type=source_type,
        source_ref=f"ref-{source_id}",
        source_locator=f"{source_type.lower()}:{subject_type}:{subject_id}",
        source_fingerprint=f"fp-{source_id}",
        projected_subject=f"{subject_type}:{subject_id}",
        protected=protected,
        active=active,
        version=1,
    )


def _grant(*sources: GrantSourceRecord) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id="g-1",
        tenant_id=1,
        resource_type="knowledge_space",
        resource_id="177",
        model=GrantModelSnapshot(model_key="viewer", active=True, action_codes=("download",)),
        active=True,
        sources=tuple(sources),
        version=1,
    )


def _target() -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=1,
        resource_type="knowledge_space",
        resource_id="177",
        resource_version=3,
        context_version="knowledge-space:177:v3",
    )


def _actor() -> PermissionActor:
    return PermissionActor(user_id=int(INVITEE), current_tenant_id=1)


def _runtime(*sources: GrantSourceRecord):
    """A runtime whose grant context holds exactly these sources."""

    runtime = F048PermissionRuntime.__new__(F048PermissionRuntime)
    context = GrantMutationContext(
        target=_target(),
        current_catalog_release_id=9,
        store_id="store-1",
        model_id="model-1",
        operator_id=int(INVITEE),
        mode="CUSTOM",
        # Deliberately the state a plain member is in: no management capability.
        system_authorized=False,
        capabilities=("manage_permission",),
        models=(),
        grants=(_grant(*sources),),
    )
    runtime.build_grant_context = AsyncMock(return_value=context)
    runtime._grants = SimpleNamespace(mutate=AsyncMock(return_value="mutated"))
    return runtime


async def _remove(runtime, subject_id: str = INVITEE):
    return await runtime.remove_subject_sources(
        actor=_actor(),
        target=_target(),
        subject_type="user",
        subject_id=subject_id,
        idempotency_key="space-leave:177:150025:3",
    )


async def test_the_invitees_own_source_is_removed() -> None:
    runtime = _runtime(_source(source_id=41))

    assert await _remove(runtime) == "mutated"

    changes = runtime._grants.mutate.await_args.kwargs["changes"]
    assert [change.operation for change in changes] == ["REMOVE"]
    assert changes[0].assignee_id == 41


async def test_leaving_does_not_need_permission_management() -> None:
    """They are removing their own row, not administering anyone else's."""

    runtime = _runtime(_source(source_id=41))

    await _remove(runtime)

    context = runtime._grants.mutate.await_args.args[0]
    assert context.system_authorized is True
    assert context.capabilities == ()


@pytest.mark.parametrize("subject_type", ["department", "user_group"])
async def test_an_organization_grant_is_left_alone(subject_type) -> None:
    """Nobody resigns from their department on their own behalf."""

    runtime = _runtime(_source(source_id=41, subject_type=subject_type, subject_id="7"))

    assert await _remove(runtime) is None
    runtime._grants.mutate.assert_not_awaited()


async def test_another_persons_source_is_never_touched() -> None:
    runtime = _runtime(
        _source(source_id=41, subject_id=COLLEAGUE),
        _source(source_id=42, subject_id=INVITEE),
    )

    await _remove(runtime)

    changes = runtime._grants.mutate.await_args.kwargs["changes"]
    assert [change.assignee_id for change in changes] == [42]


async def test_a_protected_source_survives() -> None:
    """The creator's own grant is protected and is not a way out of a space."""

    runtime = _runtime(_source(source_id=41, protected=True))

    assert await _remove(runtime) is None
    runtime._grants.mutate.assert_not_awaited()


async def test_an_inactive_source_is_not_removed_again() -> None:
    runtime = _runtime(_source(source_id=41, active=False))

    assert await _remove(runtime) is None
    runtime._grants.mutate.assert_not_awaited()


async def test_membership_and_invitation_sources_both_go() -> None:
    """Someone who both subscribed and was invited leaves once, completely."""

    runtime = _runtime(
        _source(source_id=41, source_type="DIRECT"),
        _source(source_id=42, source_type="SPACE_MEMBERSHIP"),
    )

    await _remove(runtime)

    changes = runtime._grants.mutate.await_args.kwargs["changes"]
    assert sorted(change.assignee_id for change in changes) == [41, 42]


async def test_one_call_stays_within_the_fifty_change_contract() -> None:
    runtime = _runtime(*[_source(source_id=index) for index in range(1, 61)])

    await _remove(runtime)

    assert len(runtime._grants.mutate.await_args.kwargs["changes"]) == 50
