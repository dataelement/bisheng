"""Business-service entry points for concrete F048 actions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
    PermissionPublishNotReadyError,
)
from bisheng.permission.application.access import (
    get_f048_resource_registry,
    get_f048_runtime,
)
from bisheng.permission.application.identity import (
    LoginPermissionIdentity,
    resolve_permission_actor,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget

_MAX_BATCH_CHECKS = 100


async def check_business_action(
    login_user: LoginPermissionIdentity,
    *,
    resource_type: str,
    resource_id: str | int,
    action: str,
) -> bool:
    """Check one business-verified resource through the sole F048 facade."""

    actor = await resolve_permission_actor(login_user)
    if actor.super_admin:
        # The decision layer allows a super admin unconditionally, but only after
        # the target is resolved. Resolution runs business data-validity guards
        # (e.g. owner/tenant/status checks in the F048 resource adapter) that do
        # not exempt super admins, so a legitimate-but-imperfect record would
        # raise before the decision is ever reached. The batch path already
        # short-circuits super admins for the same reason; mirror it here so the
        # single-resource path (detail, delete, etc.) stays consistent.
        return True
    registry = await get_f048_resource_registry()
    target = await registry.resolve(
        resource_type=resource_type,
        resource_id=str(resource_id),
        actor=actor,
        action=action,
    )
    runtime = await get_f048_runtime()
    return await runtime.check_action(actor, target, action)


async def require_business_action(
    login_user: LoginPermissionIdentity,
    *,
    resource_type: str,
    resource_id: str | int,
    action: str,
) -> None:
    if not await check_business_action(
        login_user,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
    ):
        raise UnAuthorizedError()


async def batch_check_business_actions(
    login_user: LoginPermissionIdentity,
    *,
    resource_type: str,
    resource_ids: Iterable[str | int],
    actions: Iterable[str],
) -> dict[str, frozenset[str]]:
    """Resolve a bounded candidate batch, then BatchCheck exact actions."""

    normalized_ids = tuple(dict.fromkeys(str(value) for value in resource_ids))
    normalized_actions = tuple(dict.fromkeys(action.strip() for action in actions))
    if not normalized_ids or not normalized_actions:
        return {}

    actor = await resolve_permission_actor(login_user)
    if actor.super_admin:
        # The decision layer already allows a super admin unconditionally, but it
        # only says so after every candidate has been resolved — several queries
        # each, per action. Listing a page of 100 candidates against 5 actions
        # therefore paid 500 resolutions to reach a foregone conclusion.
        return {resource_id: frozenset(normalized_actions) for resource_id in normalized_ids}

    registry = await get_f048_resource_registry()
    result: dict[str, set[str]] = {resource_id: set() for resource_id in normalized_ids}
    runtime = await get_f048_runtime()
    for action in normalized_actions:
        resolved = await asyncio.gather(
            *(
                registry.resolve(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    actor=actor,
                    action=action,
                )
                for resource_id in normalized_ids
            ),
            return_exceptions=True,
        )
        targets: list[VerifiedPermissionTarget] = []
        target_ids: list[str] = []
        for resource_id, resolution in zip(
            normalized_ids,
            resolved,
            strict=True,
        ):
            if isinstance(
                resolution,
                (
                    InvalidCatalogActionError,
                    PermissionInvalidResourceError,
                    PermissionPublishNotReadyError,
                ),
            ):
                continue
            if isinstance(resolution, BaseException):
                raise resolution
            targets.append(resolution)
            target_ids.append(resource_id)
        for offset in range(0, len(targets), _MAX_BATCH_CHECKS):
            batch_targets = tuple(targets[offset : offset + _MAX_BATCH_CHECKS])
            batch_ids = target_ids[offset : offset + _MAX_BATCH_CHECKS]
            allowed = await runtime.batch_check_actions(
                actor,
                batch_targets,
                action,
            )
            for resource_id, is_allowed in zip(
                batch_ids,
                allowed,
                strict=True,
            ):
                if is_allowed:
                    result[resource_id].add(action)
    return {resource_id: frozenset(action_codes) for resource_id, action_codes in result.items()}


async def batch_check_business_visible(
    login_user: LoginPermissionIdentity,
    *,
    resource_type: str,
    resource_ids: Iterable[str | int],
) -> dict[str, bool]:
    """Resolve bounded business candidates and check final visible without admin expansion."""

    normalized_ids = tuple(dict.fromkeys(str(value) for value in resource_ids))
    if not normalized_ids:
        return {}

    actor = await resolve_permission_actor(login_user)
    registry = await get_f048_resource_registry()
    resolved = await asyncio.gather(
        *(
            registry.resolve(
                resource_type=resource_type,
                resource_id=resource_id,
                actor=actor,
                action="visible",
            )
            for resource_id in normalized_ids
        ),
        return_exceptions=True,
    )
    result = dict.fromkeys(normalized_ids, False)
    targets: list[VerifiedPermissionTarget] = []
    target_ids: list[str] = []
    for resource_id, resolution in zip(normalized_ids, resolved, strict=True):
        if isinstance(
            resolution,
            (
                InvalidCatalogActionError,
                PermissionInvalidResourceError,
                PermissionPublishNotReadyError,
            ),
        ):
            continue
        if isinstance(resolution, BaseException):
            raise resolution
        targets.append(resolution)
        target_ids.append(resource_id)

    runtime = await get_f048_runtime()
    for offset in range(0, len(targets), _MAX_BATCH_CHECKS):
        batch_targets = tuple(targets[offset : offset + _MAX_BATCH_CHECKS])
        batch_ids = target_ids[offset : offset + _MAX_BATCH_CHECKS]
        allowed = await runtime.batch_check_actions(
            actor,
            batch_targets,
            "visible",
        )
        for resource_id, is_allowed in zip(batch_ids, allowed, strict=True):
            result[resource_id] = bool(is_allowed)
    return result
