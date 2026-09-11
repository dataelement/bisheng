"""People named while a resource is being created must confirm, like anyone else.

Adding somebody to a knowledge space or a channel raises an invitation they
have to accept. That was enforced only on the permission endpoint used after
the resource exists; the creation form wrote its grants through a second path
that never consulted the gate. So a space created with three people in the form
had all three in it immediately, and putting the same people in a minute later
correctly asked each of them first. Live evidence, three spaces in a row: the
grant landed active with source ``direct:user:<id>`` and no invitation row.

The worker that writes a grant *after* its invitation was approved uses the
same application object, and must keep writing directly -- it is handed no gate.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.permission.application.initial_grant import (
    InitialGrantAddition,
    InitialGrantApplication,
    InitialGrantRequest,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.personal_grant_invite_gate import (
    PendingInvite,
    PersonalGrantInviteGate,
)

PERSON = InitialGrantAddition(model_key="editor", subject_type="user", subject_id="150025")
DEPARTMENT = InitialGrantAddition(
    model_key="viewer",
    subject_type="department",
    subject_id="5",
    userset_relation="subtree_member",
    include_children=True,
)


class _Runtime:
    def __init__(self) -> None:
        self.mutations: list[dict] = []

    async def allocate_source_ids(self, count: int):
        return tuple(range(91, 91 + count))

    async def build_grant_context(self, **_kwargs):
        # A resource that was just created holds only its owner.
        return SimpleNamespace(grants=(), models=())

    async def mutate_grants(self, **kwargs):
        self.mutations.append(kwargs)
        return SimpleNamespace(resource_version=2, grants=kwargs["changes"])


class _Subjects:
    def __init__(self) -> None:
        self.sources = GrantSourceService()

    async def canonical_source(self, **kwargs):
        source_types = {"user": "DIRECT", "department": "DEPARTMENT", "user_group": "USER_GROUP"}
        return self.sources.canonicalize_source(
            source_id=kwargs["source_id"],
            subject_type=kwargs["subject_type"],
            subject_id=kwargs["subject_id"],
            userset_relation=kwargs["userset_relation"],
            include_children=kwargs["include_children"],
            source_type=source_types[kwargs["subject_type"]],
        )


class _Gate:
    """Stands in for the shared gate: people are diverted, everything else is not."""

    def __init__(self, *, scenario_disabled: bool = False) -> None:
        self.scenario_disabled = scenario_disabled
        self.invited: list = []

    def select(self, *, target, actor, changes, grants):
        direct = [change for change in changes if change.subject.type != "user"]
        gated = [change for change in changes if change.subject.type == "user"]
        return direct, gated

    @asynccontextmanager
    async def scenario_guard(self, *, tenant_id: int):
        if self.scenario_disabled:
            raise ApprovalScenarioDisabledError()
        yield

    async def raise_invites(self, *, target, actor, changes, models):
        self.invited.extend(changes)
        return [
            PendingInvite(
                subject_id=change.subject.id,
                model_key=change.model_key,
                outcome="invite_created",
                request_id=index + 1,
                approval_instance_id=500 + index,
            )
            for index, change in enumerate(changes)
        ]


def _target() -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="101",
        resource_version=1,
        context_version="knowledge-space:101:v1",
    )


def _actor() -> PermissionActor:
    return PermissionActor(user_id=11, current_tenant_id=7)


def _request(*additions: InitialGrantAddition) -> InitialGrantRequest:
    return InitialGrantRequest(
        command_key="create-request-1",
        expected_catalog_release_id=42,
        additions=additions,
    )


async def _apply(runtime, gate, *additions):
    service = InitialGrantApplication(runtime=runtime, subjects=_Subjects(), invite_gate=gate)
    return await service.apply(actor=_actor(), target=_target(), request=_request(*additions))


async def test_a_person_named_at_creation_is_invited_not_granted() -> None:
    runtime, gate = _Runtime(), _Gate()

    outcome = await _apply(runtime, gate, PERSON)

    assert [invite.subject_id for invite in outcome.pending] == ["150025"]
    # Nothing to write, so the resource is left at the version it was created at
    # rather than burning one on an empty mutation.
    assert outcome.mutation is None
    assert runtime.mutations == []


async def test_only_the_ungated_additions_reach_the_mutation() -> None:
    """A department is not a person and still applies straight away."""

    runtime, gate = _Runtime(), _Gate()

    outcome = await _apply(runtime, gate, PERSON, DEPARTMENT)

    assert [invite.subject_id for invite in outcome.pending] == ["150025"]
    assert len(runtime.mutations) == 1
    written = runtime.mutations[0]["changes"]
    assert [change.model_key for change in written] == ["viewer"]
    assert [change.source.source_type for change in written] == ["DEPARTMENT"]


async def test_confirmation_switched_off_keeps_the_old_direct_behaviour() -> None:
    """Failing instead would leave the creator unable to staff the resource."""

    runtime, gate = _Runtime(), _Gate(scenario_disabled=True)

    outcome = await _apply(runtime, gate, PERSON)

    assert outcome.pending == ()
    assert gate.invited == []
    written = runtime.mutations[0]["changes"]
    assert [change.model_key for change in written] == ["editor"]


async def test_without_a_gate_every_addition_is_written_directly() -> None:
    """The post-approval worker path: re-gating an approved invite would loop."""

    runtime = _Runtime()
    service = InitialGrantApplication(runtime=runtime, subjects=_Subjects())

    outcome = await service.apply(actor=_actor(), target=_target(), request=_request(PERSON))

    assert outcome.pending == ()
    assert [change.model_key for change in runtime.mutations[0]["changes"]] == ["editor"]


def test_the_real_gate_diverts_a_newcomer_and_leaves_a_department_alone() -> None:
    """The decision itself, not the wiring: a fresh resource has granted nobody."""

    service = InitialGrantApplication(runtime=_Runtime(), subjects=_Subjects())
    changes = [service._as_change(addition) for addition in (PERSON, DEPARTMENT)]

    direct, gated = PersonalGrantInviteGate().select(
        target=_target(),
        actor=_actor(),
        changes=changes,
        grants=(),
    )

    assert [change.subject.type for change in gated] == ["user"]
    assert [change.subject.type for change in direct] == ["department"]
