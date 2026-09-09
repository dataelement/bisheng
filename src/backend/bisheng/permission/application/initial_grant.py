"""ADD-only ordinary Grant orchestration after F048 owner creation."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from hashlib import sha256

from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.permission.application.ports import (
    InitialGrantRuntimePort,
    InitialGrantSubjectDirectoryPort,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.schemas.f048 import (
    GrantMutationChange,
    GrantMutationOperation,
    GrantSubjectInput,
)
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantMutationResult
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.personal_grant_invite_gate import PendingInvite


@dataclass(frozen=True, slots=True)
class InitialGrantAddition:
    """One client-independent ordinary Grant requested at creation time."""

    model_key: str
    subject_type: str
    subject_id: str
    userset_relation: str | None = None
    include_children: bool = False


@dataclass(frozen=True, slots=True)
class InitialGrantRequest:
    """Internal command; mutation operations and source metadata are not exposed."""

    command_key: str
    expected_catalog_release_id: int
    additions: tuple[InitialGrantAddition, ...]


@dataclass(frozen=True, slots=True)
class InitialGrantOutcome:
    """What creation actually did: what it wrote, and who it invited instead.

    ``mutation`` is None when every addition became an invitation, because
    there is then nothing to write and an empty mutation would burn a resource
    version for no change.
    """

    mutation: GrantMutationResult | None
    pending: tuple[PendingInvite, ...] = ()


class InitialGrantApplication:
    """Canonicalize subjects and delegate all authorization to F048 mutation.

    Personal grants are gated the same way here as on the ordinary permission
    endpoint: somebody added while the resource is being created has agreed to
    nothing yet, so they get an invitation to confirm rather than access. The
    gate is injected because one caller must not have it — the worker that
    writes a grant *after* its invitation was approved would otherwise send the
    approved invitation back for approval.
    """

    def __init__(
        self,
        *,
        runtime: InitialGrantRuntimePort,
        subjects: InitialGrantSubjectDirectoryPort,
        invite_gate=None,
    ) -> None:
        self._runtime = runtime
        self._subjects = subjects
        self._invite_gate = invite_gate

    async def apply(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        request: InitialGrantRequest,
    ) -> InitialGrantOutcome:
        self._validate(target, request)
        applied = request.additions
        pending: tuple[PendingInvite, ...] = ()

        async with AsyncExitStack() as stack:
            if self._invite_gate is not None:
                applied, pending = await self._gate(
                    stack=stack,
                    actor=actor,
                    target=target,
                    additions=request.additions,
                )
            if not applied:
                return InitialGrantOutcome(mutation=None, pending=pending)
            mutation = await self._mutate(
                actor=actor,
                target=target,
                request=request,
                additions=applied,
            )
        return InitialGrantOutcome(mutation=mutation, pending=pending)

    async def _gate(
        self,
        *,
        stack: AsyncExitStack,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        additions: tuple[InitialGrantAddition, ...],
    ) -> tuple[tuple[InitialGrantAddition, ...], tuple[PendingInvite, ...]]:
        context = await self._runtime.build_grant_context(actor=actor, target=target)
        direct, gated = self._invite_gate.select(
            target=target,
            actor=actor,
            changes=[self._as_change(addition) for addition in additions],
            grants=context.grants,
        )
        if gated:
            try:
                # Held until the mutation is done, so the scenario cannot be
                # switched off between raising the invitations and writing the
                # grants that were not gated.
                await stack.enter_async_context(
                    self._invite_gate.scenario_guard(tenant_id=int(target.tenant_id)),
                )
            except ApprovalScenarioDisabledError:
                # Confirmation is off tenant-wide, so a personal grant keeps the
                # direct semantics it had before the gate existed. Failing here
                # would leave the creator unable to staff the new resource.
                direct = [*direct, *gated]
                gated = []
        pending = await self._invite_gate.raise_invites(
            target=target,
            actor=actor,
            changes=gated,
            models=context.models,
        )
        return tuple(self._as_addition(change) for change in direct), tuple(pending)

    async def _mutate(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        request: InitialGrantRequest,
        additions: tuple[InitialGrantAddition, ...],
    ) -> GrantMutationResult:
        source_ids = iter(await self._runtime.allocate_source_ids(len(additions)))
        changes: list[CanonicalGrantChange] = []
        for addition in additions:
            source = await self._subjects.canonical_source(
                tenant_id=target.tenant_id,
                source_id=next(source_ids),
                subject_type=addition.subject_type,
                subject_id=addition.subject_id,
                userset_relation=addition.userset_relation,
                include_children=addition.include_children,
            )
            if source.protected or source.source_type not in {
                "DIRECT",
                "DEPARTMENT",
                "USER_GROUP",
            }:
                raise ValueError("initial Grants require a canonical ordinary source")
            changes.append(
                CanonicalGrantChange(
                    operation="ADD",
                    model_key=addition.model_key,
                    source=source,
                )
            )
        return await self._runtime.mutate_grants(
            actor=actor,
            target=target,
            changes=tuple(changes),
            expected_resource_version=target.resource_version,
            expected_catalog_release_id=request.expected_catalog_release_id,
            idempotency_key=self._idempotency_key(target, request.command_key),
        )

    @staticmethod
    def _as_change(addition: InitialGrantAddition) -> GrantMutationChange:
        """Present an addition in the shape the shared gate decides on."""

        return GrantMutationChange(
            op=GrantMutationOperation.ADD,
            model_key=addition.model_key,
            subject=GrantSubjectInput(
                type=addition.subject_type,
                id=addition.subject_id,
                userset_relation=addition.userset_relation,
                include_children=addition.include_children,
            ),
        )

    @staticmethod
    def _as_addition(change: GrantMutationChange) -> InitialGrantAddition:
        subject = change.subject
        return InitialGrantAddition(
            model_key=str(change.model_key),
            subject_type=subject.type,
            subject_id=subject.id,
            userset_relation=subject.userset_relation,
            include_children=subject.include_children,
        )

    @staticmethod
    def _validate(target: object, request: InitialGrantRequest) -> None:
        if not isinstance(target, VerifiedPermissionTarget):
            raise TypeError("Initial Grants require VerifiedPermissionTarget")
        if not request.command_key.strip():
            raise ValueError("Initial Grant command_key must not be empty")
        if request.expected_catalog_release_id <= 0:
            raise ValueError("Initial Grant Catalog release must be positive")
        if not 1 <= len(request.additions) <= 50:
            raise ValueError("Initial Grants require between 1 and 50 additions")
        if not all(isinstance(addition, InitialGrantAddition) for addition in request.additions):
            raise TypeError("Initial Grants accept ADD-only InitialGrantAddition values")
        if any(not addition.model_key.strip() for addition in request.additions):
            raise ValueError("Initial Grant model_key must not be empty")

    @staticmethod
    def _idempotency_key(target: VerifiedPermissionTarget, command_key: str) -> str:
        canonical = "|".join(
            (
                str(target.tenant_id),
                target.resource_type,
                target.resource_id,
                command_key.strip(),
            )
        )
        digest = sha256(canonical.encode()).hexdigest()[:43]
        return f"f050:initial-grants:{digest}"
