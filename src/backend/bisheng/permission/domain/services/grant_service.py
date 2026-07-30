"""F048 Grant authorization and mutation orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    GrantLevelForbiddenError,
    InvalidPermissionModeError,
    PermissionModelStateConflictError,
    PermissionMutationTooLargeError,
    PermissionVersionConflictError,
    ProtectedAssignmentMutationError,
)
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    ProjectionOperationStatus,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.projection_service import (
    ProjectionOutcome,
    ProjectionPlan,
    ProjectionTupleDelta,
)


@dataclass(frozen=True, slots=True)
class GrantCapability:
    """One independent model source through which the actor is authorized."""

    model: GrantModelSnapshot
    source_key: str


@dataclass(frozen=True, slots=True)
class CanonicalGrantChange:
    """Server-built mutation; provenance and protection never come from HTTP."""

    operation: str
    model_key: str | None = None
    source: GrantSourceRecord | None = None
    assignee_id: int | None = None
    expected_assignee_version: int | None = None
    target_model_key: str | None = None


@dataclass(frozen=True, slots=True)
class GrantMutationContext:
    """Current permission-only state for one verified business target."""

    target: VerifiedPermissionTarget
    current_catalog_release_id: int
    store_id: str
    model_id: str
    operator_id: int
    mode: str
    system_authorized: bool
    capabilities: tuple[GrantCapability, ...]
    models: tuple[GrantModelSnapshot, ...]
    grants: tuple[GrantSnapshot, ...]


@dataclass(frozen=True, slots=True)
class GrantMutationResult:
    grants: tuple[GrantSnapshot, ...]
    resource_version: int
    projection: ProjectionOutcome


class GrantProjectionPort(Protocol):
    async def prepare(
        self,
        plan: ProjectionPlan,
    ) -> PermissionProjectionOperation: ...

    async def abandon_prepared(
        self,
        plan: ProjectionPlan,
        error: Exception,
    ) -> None: ...

    async def execute(self, plan: ProjectionPlan) -> ProjectionOutcome: ...


class GrantMutationStatePort(Protocol):
    async def prepare(
        self,
        context: GrantMutationContext,
        grants: tuple[GrantSnapshot, ...],
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None: ...

    async def finalize(
        self,
        context: GrantMutationContext,
        grants: tuple[GrantSnapshot, ...],
        outcome: ProjectionOutcome,
    ) -> None: ...


class GrantEventPort(Protocol):
    async def emit(self, name: str, fields: dict) -> None: ...


class _NullEvents:
    async def emit(self, name: str, fields: dict) -> None:
        return None


class GrantService:
    """Authorize each source model independently and project exact deltas."""

    def __init__(
        self,
        *,
        source_service: GrantSourceService,
        projection: GrantProjectionPort,
        state: GrantMutationStatePort,
        events: GrantEventPort | None = None,
    ) -> None:
        self._sources = source_service
        self._projection = projection
        self._state = state
        self._events = events or _NullEvents()

    def grantable_models(
        self,
        context: GrantMutationContext,
    ) -> tuple[GrantModelSnapshot, ...]:
        """Return target models authorized by at least one complete source."""

        available = tuple(
            model for model in context.models if model.active and model.derived_level is not None and model.action_codes
        )
        if context.system_authorized:
            return tuple(
                sorted(
                    available,
                    key=lambda model: (
                        int(model.derived_level),
                        model.model_key,
                    ),
                )
            )
        return tuple(
            sorted(
                (
                    model
                    for model in available
                    if any(self._capability_allows(capability, model) for capability in context.capabilities)
                ),
                key=lambda model: (
                    int(model.derived_level),
                    model.model_key,
                ),
            )
        )

    def require_grantable_model(
        self,
        context: GrantMutationContext,
        model_key: str,
    ) -> GrantModelSnapshot:
        model = next(
            (row for row in context.models if row.model_key == model_key),
            None,
        )
        if model is None or not model.active or model.derived_level is None or not model.action_codes:
            raise PermissionModelStateConflictError(msg=f"Permission model is unavailable: {model_key}")
        if not context.system_authorized and not any(
            self._capability_allows(capability, model) for capability in context.capabilities
        ):
            raise GrantLevelForbiddenError(msg=f"Actor cannot grant permission model: {model_key}")
        return model

    def assert_roster_access(self, context: GrantMutationContext) -> None:
        if context.system_authorized:
            return
        if not any(
            capability.model.active
            and capability.model.derived_level is not None
            and "manage_permission" in capability.model.action_codes
            for capability in context.capabilities
        ):
            raise GrantLevelForbiddenError(msg="Actor has no effective manage_permission model source")

    async def mutate(
        self,
        context: GrantMutationContext,
        *,
        changes: tuple[CanonicalGrantChange, ...],
        expected_resource_version: int,
        expected_catalog_release_id: int,
        idempotency_key: str,
    ) -> GrantMutationResult:
        self._validate_request_versions(
            context,
            expected_resource_version=expected_resource_version,
            expected_catalog_release_id=expected_catalog_release_id,
        )
        if context.mode != "CUSTOM":
            raise InvalidPermissionModeError(msg="Local ordinary Grant mutations require CUSTOM mode")
        if not 1 <= len(changes) <= 50:
            raise PermissionMutationTooLargeError(msg="Grant mutation accepts between 1 and 50 changes")
        self.assert_roster_access(context)

        model_by_key = {model.model_key: model for model in context.models}
        grant_order = [grant.model.model_key for grant in context.grants]
        grants = {
            grant.model.model_key: replace(
                grant,
                model=model_by_key.get(grant.model.model_key, grant.model),
            )
            for grant in context.grants
        }
        compiled: list[ProjectionTupleDelta] = []
        for change in changes:
            deltas = self._apply_change(context, grants, change)
            compiled.extend(deltas)

        final_grants = tuple(grants[model_key] for model_key in grant_order)
        net_deltas = self._net_deltas(tuple(compiled))
        plan = ProjectionPlan(
            tenant_id=context.target.tenant_id,
            idempotency_key=idempotency_key,
            operation_type="GRANT_MUTATION",
            scope_type="resource",
            scope_key=(f"{context.target.resource_type}:{context.target.resource_id}"),
            expected_version=context.target.resource_version,
            target_version=context.target.resource_version + 1,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            change_item_count=len(changes),
            deltas=net_deltas,
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.prepare(
                    context,
                    final_grants,
                    idempotency_key=idempotency_key,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        outcome = await self._projection.execute(plan)
        await self._state.finalize(context, final_grants, outcome)
        await self._emit(context, outcome, len(changes), len(net_deltas))
        return GrantMutationResult(
            grants=final_grants,
            resource_version=outcome.target_version,
            projection=outcome,
        )

    @staticmethod
    def _capability_allows(
        capability: GrantCapability,
        target: GrantModelSnapshot,
    ) -> bool:
        source = capability.model
        if (
            not source.active
            or source.derived_level is None
            or target.derived_level is None
            or "manage_permission" not in source.action_codes
        ):
            return False
        if source.allow_same_level:
            return target.derived_level <= source.derived_level
        return target.derived_level < source.derived_level

    @staticmethod
    def _validate_request_versions(
        context: GrantMutationContext,
        *,
        expected_resource_version: int,
        expected_catalog_release_id: int,
    ) -> None:
        if expected_resource_version != context.target.resource_version:
            raise PermissionVersionConflictError(msg="Resource permission version changed")
        if expected_catalog_release_id != context.current_catalog_release_id:
            raise PermissionVersionConflictError(msg="Permission Catalog release changed")

    def _apply_change(
        self,
        context: GrantMutationContext,
        grants: dict[str, GrantSnapshot],
        change: CanonicalGrantChange,
    ) -> tuple[ProjectionTupleDelta, ...]:
        operation = change.operation.upper()
        if operation == "ADD":
            if change.model_key is None or change.source is None:
                raise ValueError("ADD requires model_key and canonical source")
            if change.source.protected:
                raise ProtectedAssignmentMutationError(msg="Ordinary Grant API cannot create protected sources")
            model = self.require_grantable_model(context, change.model_key)
            grant = self._target_grant(grants, model)
            mutation = self._sources.add_source(grant, change.source)
            grants[model.model_key] = mutation.grant
            return mutation.deltas

        if operation not in {"MOVE", "REMOVE"}:
            raise ValueError(f"unsupported Grant mutation: {change.operation}")
        if change.assignee_id is None or change.expected_assignee_version is None:
            raise ValueError(f"{operation} requires assignee identity and version")
        source_model_key, source = self._find_source(
            grants,
            change.assignee_id,
        )
        if source.version != change.expected_assignee_version:
            raise PermissionVersionConflictError(msg="Grant assignee version changed")
        if source.protected:
            raise ProtectedAssignmentMutationError(msg="Protected permission source cannot be changed")
        self.require_grantable_model(context, source_model_key)
        source_grant = grants[source_model_key]

        if operation == "REMOVE":
            mutation = self._sources.remove_source(
                source_grant,
                source_id=source.source_id,
            )
            grants[source_model_key] = mutation.grant
            return mutation.deltas

        if not change.target_model_key:
            raise ValueError("MOVE requires target_model_key")
        target_model = self.require_grantable_model(
            context,
            change.target_model_key,
        )
        target_grant = self._target_grant(grants, target_model)
        mutation = self._sources.move_source(
            source_grant,
            target_grant,
            source_id=source.source_id,
        )
        grants[source_model_key] = mutation.source_grant
        grants[target_model.model_key] = mutation.target_grant
        return mutation.deltas

    @staticmethod
    def _target_grant(
        grants: dict[str, GrantSnapshot],
        model: GrantModelSnapshot,
    ) -> GrantSnapshot:
        grant = grants.get(model.model_key)
        if grant is None:
            raise PermissionModelStateConflictError(msg=f"No stable Grant row exists for model {model.model_key}")
        return replace(grant, model=model)

    @staticmethod
    def _find_source(
        grants: dict[str, GrantSnapshot],
        assignee_id: int,
    ) -> tuple[str, GrantSourceRecord]:
        matches = [
            (model_key, source)
            for model_key, grant in grants.items()
            for source in grant.sources
            if source.active and source.source_id == assignee_id
        ]
        if len(matches) != 1:
            raise PermissionVersionConflictError(msg="Grant assignee is missing or ambiguous")
        return matches[0]

    @staticmethod
    def _net_deltas(
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> tuple[ProjectionTupleDelta, ...]:
        net: dict[tuple[str, str, str], ProjectionTupleDelta] = {}
        for delta in deltas:
            key = delta.key
            previous = net.get(key)
            if previous is not None and previous.action != delta.action:
                del net[key]
            elif previous is None:
                net[key] = delta
        return tuple(
            replace(delta, phase="COMMIT", sequence=index)
            for index, delta in enumerate(
                sorted(
                    net.values(),
                    key=lambda row: (
                        row.user,
                        row.relation,
                        row.object,
                        row.action,
                    ),
                )
            )
        )

    async def _emit(
        self,
        context: GrantMutationContext,
        outcome: ProjectionOutcome,
        change_count: int,
        tuple_count: int,
    ) -> None:
        try:
            await self._events.emit(
                "permission_grant_mutation",
                {
                    "change_count": change_count,
                    "operation_id": outcome.operation_id,
                    "resource_type": context.target.resource_type,
                    "status": outcome.status,
                    "tenant_id": context.target.tenant_id,
                    "tuple_count": tuple_count,
                },
            )
        except Exception:
            logger.exception("Failed to emit the F048 Grant mutation event")
            return
