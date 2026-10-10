"""Dispatch HTTP resource identities to their owning business Services."""

from __future__ import annotations

from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class ResourceAuthorizationPort(Protocol):
    """Business-owned loader that validates one resource before permission."""

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget: ...


class PermissionActionCoordinatorPort(Protocol):
    """Narrow decision surface used after business verification."""

    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...


class ResourceAuthorizationRegistry:
    """Explicit resource-type registry without permission→business imports."""

    def __init__(self) -> None:
        self._ports: dict[str, ResourceAuthorizationPort] = {}

    def register(
        self,
        resource_type: str,
        port: ResourceAuthorizationPort,
    ) -> None:
        normalized = resource_type.strip().lower()
        if not normalized:
            raise ValueError("resource_type must not be empty")
        if normalized in self._ports:
            raise ValueError(f"resource authorization port already registered: {normalized}")
        self._ports[normalized] = port

    def port_for(self, resource_type: str) -> ResourceAuthorizationPort | None:
        return self._ports.get(resource_type.strip().lower())

    async def resolve(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        normalized_type = resource_type.strip().lower()
        normalized_id = resource_id.strip()
        port = self._ports.get(normalized_type)
        if port is None or not normalized_id:
            raise PermissionInvalidResourceError()
        target = await port.resolve_permission_target(
            resource_id=normalized_id,
            actor=actor,
            action=action,
        )
        if (
            not isinstance(target, VerifiedPermissionTarget)
            or target.resource_type != normalized_type
            or target.resource_id != normalized_id
        ):
            raise PermissionInvalidResourceError()
        return target

    async def confirm_absent(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Return True only when the owning business Service has no record.

        ``resolve`` raises the same 19003 for a missing resource, a cross-tenant
        resource and a resource in a state that cannot be authorized. Cleanup
        paths need to tell "the resource is gone" apart from the other cases,
        so this asks the business loader directly. An unregistered type or a
        port without a loader cannot confirm anything and returns False. A
        loader error propagates, so the caller stays fail-closed.
        """

        normalized_id = resource_id.strip()
        port = self.port_for(resource_type)
        load_permission_record = getattr(port, "load_permission_record", None) if port else None
        if load_permission_record is None or not normalized_id:
            return False
        return await load_permission_record(resource_id=normalized_id) is None


class BoundResourceAuthorizationPort:
    """Bind a multi-resource business adapter to one registry key."""

    def __init__(self, *, resource_type: str, adapter) -> None:
        self._resource_type = resource_type
        self._adapter = adapter

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        return await self._adapter.resolve_permission_target(
            resource_type=self._resource_type,
            resource_id=resource_id,
            actor=actor,
            action=action,
        )

    async def load_permission_record(self, *, resource_id: str):
        """Load the business record so the registry can confirm absence."""

        return await self._adapter.load_permission_record(
            resource_type=self._resource_type,
            resource_id=resource_id,
        )


class PermissionDecisionApplication:
    """Resolve a business target, then ask the sole permission facade."""

    def __init__(
        self,
        *,
        resources: ResourceAuthorizationRegistry,
        permission: PermissionActionCoordinatorPort,
    ) -> None:
        self._resources = resources
        self._permission = permission

    async def check(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
        actor: PermissionActor,
    ) -> bool:
        target = await self._resources.resolve(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            action=action,
        )
        return await self._permission.check_action(
            actor,
            target,
            action,
        )
