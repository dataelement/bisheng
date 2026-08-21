"""F048 business-agnostic concrete-action authorization facade."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionEnumerationIncompleteError,
    PermissionFGAUnavailableError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
)
from bisheng.common.services.metric_log import emit_metric
from bisheng.permission.domain.schemas import (
    VerifiedPermissionTarget,
    VisibilityEnumerationStatus,
    VisibleObjectEnumerationRequest,
    VisibleObjectEnumerationResult,
)
from bisheng.permission.domain.services.catalog_policy import (
    REGISTERED_ACTION_CODES,
)

HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"
MAX_BATCH_CHECKS = 100


@dataclass(frozen=True, slots=True)
class PermissionActor:
    user_id: int
    current_tenant_id: int
    super_admin: bool = False
    tenant_admin_tenant_ids: frozenset[int] = frozenset()


class PermissionCatalogDecisionPort(Protocol):
    async def ensure_runtime_ready(self) -> None: ...

    async def is_action_effective(
        self,
        resource_type: str,
        action: str,
    ) -> bool: ...

    async def effective_actions(
        self,
        resource_type: str,
    ) -> tuple[str, ...]: ...


class PermissionScopeFencePort(Protocol):
    async def ensure_readable(
        self,
        target: VerifiedPermissionTarget,
    ) -> bool: ...


class PermissionConsistencyMarkerPort(Protocol):
    async def consistency_for(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | None,
    ) -> str | None: ...


class PermissionFGADecisionPort(Protocol):
    async def check(
        self,
        *,
        user: str,
        relation: str,
        object: str,
        consistency: str | None = None,
    ) -> bool: ...

    async def batch_check(
        self,
        checks: list[dict],
        consistency: str | None = None,
    ) -> list[bool]: ...

    async def list_objects(
        self,
        *,
        user: str,
        relation: str,
        type: str,
        consistency: str | None = None,
    ) -> list[str]: ...

    async def stream_list_objects(
        self,
        *,
        user: str,
        relation: str,
        type: str,
        consistency: str | None = None,
    ) -> tuple[str, ...]: ...


class PermissionListPolicyPort(Protocol):
    async def allows(
        self,
        resource_type: str,
        action: str,
        max_results: int,
    ) -> bool: ...


class PermissionDecisionEventPort(Protocol):
    async def emit(self, name: str, fields: dict) -> None: ...


class _NullEvents:
    async def emit(self, name: str, fields: dict) -> None:
        return None


class F048PermissionService:
    """Check only verified targets and never query business resource state."""

    def __init__(
        self,
        *,
        catalog: PermissionCatalogDecisionPort,
        scope_fence: PermissionScopeFencePort,
        marker: PermissionConsistencyMarkerPort,
        fga: PermissionFGADecisionPort,
        list_policy: PermissionListPolicyPort,
        events: PermissionDecisionEventPort | None = None,
    ) -> None:
        self._catalog = catalog
        self._scope_fence = scope_fence
        self._marker = marker
        self._fga = fga
        self._list_policy = list_policy
        self._events = events or _NullEvents()

    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool:
        started = perf_counter()
        action = self._normalize_action(action)
        shortcut = await self._identity_shortcut(actor, target, action=action)
        if shortcut is not None:
            allowed, reason = shortcut
            await self._emit_decision(
                actor,
                target,
                action,
                allowed,
                reason,
                None,
                started,
            )
            return allowed

        force_higher_consistency = await self._prepare_action_target(target, action)
        consistency = await self._consistency(
            target,
            force_higher_consistency=force_higher_consistency,
        )
        try:
            allowed = await self._fga.check(
                user=f"user:{actor.user_id}",
                relation=f"can_{action}",
                object=f"{target.resource_type}:{target.resource_id}",
                consistency=consistency,
            )
        except Exception as exc:
            await self._emit_error(actor, target, action, consistency, started)
            raise PermissionFGAUnavailableError(exception=exc) from exc
        await self._emit_decision(
            actor,
            target,
            action,
            allowed,
            "OPENFGA",
            consistency,
            started,
        )
        return allowed

    async def check_visible(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
    ) -> bool:
        started = perf_counter()
        if target.tenant_id != actor.current_tenant_id:
            await self._emit_decision(
                actor,
                target,
                "visible",
                False,
                "TENANT_MISMATCH",
                None,
                started,
            )
            return False
        await self._catalog.ensure_runtime_ready()
        force_higher_consistency = bool(await self._scope_fence.ensure_readable(target))
        consistency = await self._consistency(
            target,
            force_higher_consistency=force_higher_consistency,
        )
        try:
            allowed = await self._fga.check(
                user=f"user:{actor.user_id}",
                relation="visible",
                object=f"{target.resource_type}:{target.resource_id}",
                consistency=consistency,
            )
        except Exception as exc:
            await self._emit_error(
                actor,
                target,
                "visible",
                consistency,
                started,
            )
            raise PermissionFGAUnavailableError(exception=exc) from exc
        await self._emit_decision(
            actor,
            target,
            "visible",
            allowed,
            "OPENFGA",
            consistency,
            started,
        )
        return allowed

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]:
        action = self._normalize_action(action)
        if len(targets) > MAX_BATCH_CHECKS:
            raise ValueError(f"BatchCheck accepts at most {MAX_BATCH_CHECKS} targets")
        results: list[bool | None] = [None] * len(targets)
        unresolved: list[tuple[int, VerifiedPermissionTarget]] = []
        consistency = None
        for index, target in enumerate(targets):
            shortcut = await self._identity_shortcut(
                actor,
                target,
                action=action,
            )
            if shortcut is not None:
                results[index] = shortcut[0]
                continue
            try:
                force_higher_consistency = await self._prepare_action_target(target, action)
            except PermissionPublishNotReadyError as exc:
                results[index] = False
                self._handle_stale_projection(target, exc)
                continue
            target_consistency = await self._consistency(
                target,
                force_higher_consistency=force_higher_consistency,
            )
            if target_consistency == HIGHER_CONSISTENCY:
                consistency = HIGHER_CONSISTENCY
            unresolved.append((index, target))

        if unresolved:
            checks = [
                {
                    "user": f"user:{actor.user_id}",
                    "relation": f"can_{action}",
                    "object": f"{target.resource_type}:{target.resource_id}",
                }
                for _, target in unresolved
            ]
            try:
                resolved = await self._fga.batch_check(
                    checks,
                    consistency=consistency,
                )
            except Exception as exc:
                raise PermissionFGAUnavailableError(exception=exc) from exc
            if len(resolved) != len(unresolved):
                raise PermissionProjectionFailedError(msg="OpenFGA BatchCheck returned an incomplete result")
            for (index, _), allowed in zip(unresolved, resolved, strict=True):
                results[index] = bool(allowed)
        return tuple(bool(value) for value in results)

    async def batch_check_visible(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
    ) -> tuple[bool, ...]:
        if len(targets) > MAX_BATCH_CHECKS:
            raise ValueError(f"BatchCheck accepts at most {MAX_BATCH_CHECKS} targets")
        results: list[bool | None] = [None] * len(targets)
        unresolved: list[tuple[int, VerifiedPermissionTarget]] = []
        consistency = None
        for index, target in enumerate(targets):
            if target.tenant_id != actor.current_tenant_id:
                results[index] = False
                continue
            await self._catalog.ensure_runtime_ready()
            try:
                force_higher_consistency = bool(await self._scope_fence.ensure_readable(target))
            except PermissionPublishNotReadyError as exc:
                results[index] = False
                self._handle_stale_projection(target, exc)
                continue
            target_consistency = await self._consistency(
                target,
                force_higher_consistency=force_higher_consistency,
            )
            if target_consistency == HIGHER_CONSISTENCY:
                consistency = HIGHER_CONSISTENCY
            unresolved.append((index, target))

        if unresolved:
            checks = [
                {
                    "user": f"user:{actor.user_id}",
                    "relation": "visible",
                    "object": (f"{target.resource_type}:{target.resource_id}"),
                }
                for _, target in unresolved
            ]
            try:
                resolved = await self._fga.batch_check(
                    checks,
                    consistency=consistency,
                )
            except Exception as exc:
                raise PermissionFGAUnavailableError(exception=exc) from exc
            if len(resolved) != len(unresolved):
                raise PermissionProjectionFailedError(msg="OpenFGA BatchCheck returned an incomplete result")
            for (index, _), allowed in zip(
                unresolved,
                resolved,
                strict=True,
            ):
                results[index] = bool(allowed)
        return tuple(bool(value) for value in results)

    async def list_visible_objects(
        self,
        actor: PermissionActor,
        *,
        resource_type: str,
        max_results: int,
    ) -> VisibleObjectEnumerationResult:
        """Return a complete immutable visible ID set after normal stream EOF."""

        if actor.current_tenant_id <= 0:
            raise PermissionEnumerationIncompleteError(msg="Visible enumeration has no valid tenant fence")
        request = VisibleObjectEnumerationRequest(
            tenant_id=actor.current_tenant_id,
            resource_type=resource_type,
            fga_user=f"user:{actor.user_id}",
            max_results=max_results,
        )
        started = perf_counter()
        await self._catalog.ensure_runtime_ready()
        consistency = await self._scope_consistency(
            request.tenant_id,
            request.resource_type,
            None,
        )
        try:
            fga_started = perf_counter()
            objects = await self._fga.stream_list_objects(
                user=request.fga_user,
                relation="visible",
                type=request.resource_type,
                consistency=consistency,
            )
        except Exception as exc:
            emit_metric(
                "permission_visible_list",
                tenant=request.tenant_id,
                resource_type=request.resource_type,
                strategy="visible_ids_first",
                candidate_count=0,
                visible_count=0,
                scanned_count=0,
                scan_amplification=0,
                stream_completed=False,
                capacity=request.max_results,
                db_elapsed_ms=0,
                fga_elapsed_ms=(perf_counter() - fga_started) * 1000,
                total_elapsed_ms=(perf_counter() - started) * 1000,
                alert="stream_incomplete",
            )
            raise PermissionEnumerationIncompleteError(exception=exc) from exc

        prefix = f"{request.resource_type}:"
        if any(not value.startswith(prefix) for value in objects):
            raise PermissionEnumerationIncompleteError(
                msg="OpenFGA visible enumeration returned an unexpected object type",
            )
        object_ids = tuple(sorted({value[len(prefix) :] for value in objects}))
        if len(object_ids) > request.max_results:
            self._emit_visible_list_metric(
                request=request,
                visible_count=len(object_ids),
                fga_started=fga_started,
                started=started,
                alert="capacity_exceeded",
            )
            raise PermissionEnumerationIncompleteError(
                msg="Visible enumeration exceeded its reviewed capacity",
            )
        capacity_ratio = len(object_ids) / request.max_results
        self._emit_visible_list_metric(
            request=request,
            visible_count=len(object_ids),
            fga_started=fga_started,
            started=started,
            alert="capacity_80_percent" if capacity_ratio >= 0.8 else None,
        )
        return VisibleObjectEnumerationResult(
            resource_type=request.resource_type,
            object_ids=object_ids,
            max_results=request.max_results,
            status=VisibilityEnumerationStatus.NORMAL,
        )

    @staticmethod
    def _emit_visible_list_metric(
        *,
        request: VisibleObjectEnumerationRequest,
        visible_count: int,
        fga_started: float,
        started: float,
        alert: str | None,
    ) -> None:
        emit_metric(
            "permission_visible_list",
            tenant=request.tenant_id,
            resource_type=request.resource_type,
            strategy="visible_ids_first",
            candidate_count=0,
            visible_count=visible_count,
            scanned_count=visible_count,
            scan_amplification=1 if visible_count else 0,
            stream_completed=True,
            capacity=request.max_results,
            db_elapsed_ms=0,
            fga_elapsed_ms=(perf_counter() - fga_started) * 1000,
            total_elapsed_ms=(perf_counter() - started) * 1000,
            alert=alert,
        )

    async def list_action_objects(
        self,
        actor: PermissionActor,
        *,
        resource_type: str,
        action: str,
        max_results: int,
    ) -> tuple[str, ...] | None:
        action = self._normalize_action(action)
        if actor.super_admin or actor.current_tenant_id in (actor.tenant_admin_tenant_ids):
            return None
        await self._catalog.ensure_runtime_ready()
        if not await self._catalog.is_action_effective(resource_type, action):
            raise InvalidCatalogActionError(msg=f"Action {action} is unavailable for {resource_type}")
        if not await self._list_policy.allows(
            resource_type,
            action,
            max_results,
        ):
            raise PermissionPublishNotReadyError(msg="ListObjects is not enabled for this bounded action path")
        consistency = await self._scope_consistency(
            actor.current_tenant_id,
            resource_type,
            None,
        )
        try:
            objects = await self._fga.list_objects(
                user=f"user:{actor.user_id}",
                relation=f"can_{action}",
                type=resource_type,
                consistency=consistency,
            )
        except Exception as exc:
            raise PermissionFGAUnavailableError(exception=exc) from exc
        if len(objects) > max_results:
            raise PermissionProjectionFailedError(msg="Bounded ListObjects result exceeded its reviewed limit")
        prefix = f"{resource_type}:"
        if any(not value.startswith(prefix) for value in objects):
            raise PermissionProjectionFailedError(msg="OpenFGA ListObjects returned an unexpected object type")
        return tuple(dict.fromkeys(value[len(prefix) :] for value in objects))

    async def effective_actions(self, resource_type: str) -> tuple[str, ...]:
        """All action codes effective for a resource type in the CURRENT catalog.

        Used to report the full capability of a privileged actor, who is
        authorized on identity and therefore holds no grant rows to explain.
        """

        await self._catalog.ensure_runtime_ready()
        return await self._catalog.effective_actions(resource_type)

    @staticmethod
    def _handle_stale_projection(
        target: VerifiedPermissionTarget,
        exc: PermissionPublishNotReadyError,
    ) -> None:
        """Log and metric a stale projection; caller sets results[index] = False."""
        logger.warning(
            "stale_projection: resource={}:{} stored_parent={}:{} expected_parent={}:{}",
            target.resource_type,
            target.resource_id,
            exc.kwargs.get("stored_parent_type", "?"),
            exc.kwargs.get("stored_parent_id", "?"),
            target.parent_type,
            target.parent_id,
        )
        emit_metric(
            "permission",
            event="stale_projection",
            resource_type=target.resource_type,
            resource_id=target.resource_id,
            tenant_id=str(target.tenant_id),
            mismatch_kind="stale_parent_or_version",
        )

    @staticmethod
    def _normalize_action(action: str) -> str:
        normalized = action.strip()
        if normalized != action or normalized == "visible" or normalized not in REGISTERED_ACTION_CODES:
            raise InvalidCatalogActionError(msg=f"Unknown permission action: {action}")
        return normalized

    async def _identity_shortcut(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        *,
        action: str,
    ) -> tuple[bool, str] | None:
        if actor.super_admin:
            return True, "SUPER_ADMIN"
        if target.tenant_id != actor.current_tenant_id:
            return False, "TENANT_MISMATCH"
        if target.tenant_id in actor.tenant_admin_tenant_ids:
            return True, "TENANT_ADMIN"
        return None

    async def _prepare_action_target(
        self,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool:
        await self._catalog.ensure_runtime_ready()
        force_higher_consistency = bool(await self._scope_fence.ensure_readable(target))
        if not await self._catalog.is_action_effective(
            target.resource_type,
            action,
        ):
            raise InvalidCatalogActionError(msg=f"Action {action} is unavailable for {target.resource_type}")
        return force_higher_consistency

    async def _consistency(
        self,
        target: VerifiedPermissionTarget,
        *,
        force_higher_consistency: bool = False,
    ) -> str | None:
        if force_higher_consistency:
            emit_metric(
                "permission",
                event="degraded_projection_decision",
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                tenant_id=str(target.tenant_id),
            )
            return HIGHER_CONSISTENCY
        return await self._scope_consistency(
            target.tenant_id,
            target.resource_type,
            target.resource_id,
        )

    async def _scope_consistency(
        self,
        tenant_id: int,
        resource_type: str,
        resource_id: str | None,
    ) -> str | None:
        try:
            return await self._marker.consistency_for(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        except Exception:
            logger.exception(
                "Failed to read the F048 action marker; using higher consistency",
            )
            return HIGHER_CONSISTENCY

    async def _emit_error(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
        consistency: str | None,
        started: float,
    ) -> None:
        await self._emit_decision(
            actor,
            target,
            action,
            False,
            "OPENFGA_ERROR",
            consistency,
            started,
            outcome="ERROR",
        )

    async def _emit_decision(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
        allowed: bool,
        reason: str,
        consistency: str | None,
        started: float,
        *,
        outcome: str | None = None,
    ) -> None:
        try:
            await self._events.emit(
                "permission_decision",
                {
                    "action": action,
                    "consistency": consistency or "DEFAULT",
                    "elapsed_ms": round((perf_counter() - started) * 1000, 3),
                    "outcome": outcome or ("ALLOW" if allowed else "DENY"),
                    "reason": reason,
                    "resource_type": target.resource_type,
                    "tenant_id": target.tenant_id,
                    "user_id": actor.user_id,
                },
            )
        except Exception:
            logger.exception("Failed to emit the F048 permission decision event")
            return
