"""ADD-only ordinary Grant orchestration after F048 owner creation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from bisheng.permission.application.ports import (
    InitialGrantRuntimePort,
    InitialGrantSubjectDirectoryPort,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange, GrantMutationResult
from bisheng.permission.domain.services.permission_action_service import PermissionActor


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


class InitialGrantApplication:
    """Canonicalize subjects and delegate all authorization to F048 mutation."""

    def __init__(
        self,
        *,
        runtime: InitialGrantRuntimePort,
        subjects: InitialGrantSubjectDirectoryPort,
    ) -> None:
        self._runtime = runtime
        self._subjects = subjects

    async def apply(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        request: InitialGrantRequest,
    ) -> GrantMutationResult:
        self._validate(target, request)
        source_ids = iter(await self._runtime.allocate_source_ids(len(request.additions)))
        changes: list[CanonicalGrantChange] = []
        for addition in request.additions:
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
