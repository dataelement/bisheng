"""Application boundary between business-verified resources and permission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.permission.domain.services.permission_explain_service import (
    PermissionExplainContext,
    PermissionExplanation,
)


class PermissionDecisionFacadePort(Protocol):
    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...

    async def check_visible(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> bool: ...

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]: ...


class PermissionExplainFacadePort(Protocol):
    async def explain(
        self,
        context: PermissionExplainContext,
    ) -> PermissionExplanation: ...


class PermissionDisplayPort(Protocol):
    async def bulk_subject_names(
        self,
        subjects: tuple[tuple[str, str], ...],
    ) -> dict[tuple[str, str], str]: ...


@dataclass(frozen=True, slots=True)
class DisplayedPermissionExplanation:
    """Permission fields remain authoritative; names are optional decoration."""

    permission: PermissionExplanation
    subject_names: dict[tuple[str, str], str]


class ResourcePermissionCoordinator:
    """Reject raw HTTP dicts and coordinate only internal verified DTOs."""

    def __init__(
        self,
        *,
        decision_service: PermissionDecisionFacadePort,
        explain_service: PermissionExplainFacadePort,
        display_port: PermissionDisplayPort | None,
    ) -> None:
        self._decision = decision_service
        self._explain = explain_service
        self._display = display_port

    @staticmethod
    def require_verified_target(value: object) -> VerifiedPermissionTarget:
        if not isinstance(value, VerifiedPermissionTarget):
            raise TypeError("Resource permission operations require VerifiedPermissionTarget")
        return value

    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool:
        return await self._decision.check_action(
            actor,
            self.require_verified_target(target),
            action,
        )

    async def check_visible(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> bool:
        return await self._decision.check_visible(
            actor,
            self.require_verified_target(target),
        )

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]:
        verified = tuple(self.require_verified_target(target) for target in targets)
        return await self._decision.batch_check_actions(
            actor,
            verified,
            action,
        )

    async def explain(
        self,
        target: VerifiedPermissionTarget,
        context: PermissionExplainContext,
    ) -> DisplayedPermissionExplanation:
        target = self.require_verified_target(target)
        if (
            context.tenant_id != target.tenant_id
            or context.resource_type != target.resource_type
            or context.resource_id != target.resource_id
            or context.resource_version != target.resource_version
        ):
            raise ValueError("Permission explanation context does not match target")
        permission = await self._explain.explain(context)
        names: dict[tuple[str, str], str] = {}
        if self._display is not None:
            subjects = tuple(dict.fromkeys((source.subject_type, source.subject_id) for source in permission.sources))
            try:
                names = await self._display.bulk_subject_names(subjects)
            except Exception:
                logger.exception(
                    "Failed to enrich F048 permission subject display names",
                )
                names = {}
        return DisplayedPermissionExplanation(
            permission=permission,
            subject_names=names,
        )
