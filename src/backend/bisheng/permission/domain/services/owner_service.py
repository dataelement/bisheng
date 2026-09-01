"""OwnerService — convenience methods for resource ownership management (T13).

Provides the contract for F008 (resource adaptation) to call when creating resources.
INV-2: every resource must have exactly one owner tuple in OpenFGA.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    ProjectionOperationStatus,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
from bisheng.permission.domain.services.grant_source_service import (
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.projection_plan import (
    ProjectionOutcome,
    ProjectionTupleDelta,
    merge_projection_deltas,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import (
    build_create_plan,
)
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompilation,
    VisibilityProjectionCompiler,
)

logger = logging.getLogger(__name__)

SYSTEM_OWNED_RESOURCE_ALLOWLIST = frozenset({"workflow", "assistant", "tool"})


@dataclass(frozen=True, slots=True)
class OwnerProjectionContext:
    target: VerifiedPermissionTarget
    owner_grant: GrantSnapshot | None
    source_id: int
    owner_user_id: int | None
    system_owned: bool
    system_predicate: bool
    store_id: str
    model_id: str
    operator_id: int
    idempotency_key: str
    system_action_codes: tuple[str, ...] = ()
    permission_mode: str | None = None
    operation_type: str = "RESOURCE_CREATE"
    copy_grants: tuple[GrantSnapshot, ...] = ()
    copy_deltas: tuple[ProjectionTupleDelta, ...] = ()


@dataclass(frozen=True, slots=True)
class OwnerProjectionResult:
    grant: GrantSnapshot | None
    source: GrantSourceRecord | None
    projection: object


class OwnerProjectionPort(Protocol):
    async def prepare(self, plan) -> PermissionProjectionOperation: ...

    async def abandon_prepared(
        self,
        plan,
        error: Exception,
    ) -> None: ...

    async def execute(self, plan) -> ProjectionOutcome: ...


class OwnerProjectionStatePort(Protocol):
    async def prepare(
        self,
        context: OwnerProjectionContext,
        grant: GrantSnapshot | None,
        source: GrantSourceRecord | None,
        visibility: VisibilityProjectionCompilation | None,
        *,
        operation_id: int,
    ) -> None: ...

    async def finalize(
        self,
        context: OwnerProjectionContext,
        grant: GrantSnapshot | None,
        visibility: VisibilityProjectionCompilation | None,
        outcome: ProjectionOutcome,
    ) -> None: ...

    async def mark_compensation_required(
        self,
        context: OwnerProjectionContext,
        error: Exception,
    ) -> None: ...


class F048OwnerProjectionService:
    """Stage creator/system ownership before enabling a new resource."""

    def __init__(
        self,
        *,
        source_service: GrantSourceService,
        projection: OwnerProjectionPort,
        state: OwnerProjectionStatePort,
        visibility_compiler: VisibilityProjectionCompiler | None = None,
    ) -> None:
        self._sources = source_service
        self._projection = projection
        self._state = state
        self._visibility = visibility_compiler or VisibilityProjectionCompiler()

    async def project_created(
        self,
        context: OwnerProjectionContext,
    ) -> OwnerProjectionResult:
        self._validate_common(context)
        self._validate_copy(context)
        grant: GrantSnapshot | None
        source: GrantSourceRecord | None
        visibility: VisibilityProjectionCompilation | None
        protected_deltas: tuple[ProjectionTupleDelta, ...]
        if context.system_owned:
            self._validate_system_owned(context)
            grant = None
            source = None
            marker_relations = (
                "visible",
                *(f"system_{action}_marker" for action in context.system_action_codes if action != "visible"),
            )
            protected_deltas = tuple(
                ProjectionTupleDelta(
                    phase="STAGE",
                    sequence=index,
                    action="WRITE",
                    user="user:*",
                    relation=relation,
                    object=(f"{context.target.resource_type}:{context.target.resource_id}"),
                )
                for index, relation in enumerate(dict.fromkeys(marker_relations))
            )
            visibility = None
        else:
            grant, source, protected_deltas = self._protected_owner(context)
            visibility = self._visibility.compile(
                tenant_id=context.target.tenant_id,
                grants=self._projection_grants(context, grant),
                existing_sources=(),
            )
        all_deltas = merge_projection_deltas(
            context.copy_deltas,
            protected_deltas,
            visibility.deltas if visibility is not None else (),
        )
        plan = build_create_plan(
            context.target,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            idempotency_key=context.idempotency_key,
            protected_deltas=all_deltas,
            permission_mode=context.permission_mode,
            operation_type=context.operation_type,
        )
        operation = await self._projection.prepare(plan)
        if str(operation.status) == ProjectionOperationStatus.PREPARED.value:
            try:
                await self._state.prepare(
                    context,
                    grant,
                    source,
                    visibility,
                    operation_id=int(operation.id),
                )
            except Exception as exc:
                await self._projection.abandon_prepared(plan, exc)
                raise
        try:
            outcome = await self._projection.execute(plan)
        except Exception as exc:
            await self._state.mark_compensation_required(context, exc)
            raise
        await self._state.finalize(context, grant, visibility, outcome)
        return OwnerProjectionResult(
            grant=grant,
            source=source,
            projection=outcome,
        )

    def _protected_owner(
        self,
        context: OwnerProjectionContext,
    ) -> tuple[
        GrantSnapshot,
        GrantSourceRecord,
        tuple[ProjectionTupleDelta, ...],
    ]:
        grant = context.owner_grant
        if (
            grant is None
            or context.owner_user_id is None
            or context.owner_user_id <= 0
            or grant.tenant_id != context.target.tenant_id
            or grant.resource_type != context.target.resource_type
            or grant.resource_id != context.target.resource_id
            or grant.model.model_key != "owner"
        ):
            raise PermissionInvalidResourceError()
        source = self._sources.canonicalize_source(
            source_id=context.source_id,
            subject_type="user",
            subject_id=str(context.owner_user_id),
            source_type="CREATOR",
            source_ref=(f"{context.target.resource_type}:{context.target.resource_id}"),
            protected=True,
        )
        mutation = self._sources.add_source(grant, source)
        return mutation.grant, source, mutation.deltas

    @staticmethod
    def _projection_grants(
        context: OwnerProjectionContext,
        owner_grant: GrantSnapshot,
    ) -> tuple[GrantSnapshot, ...]:
        if not context.copy_grants:
            return (owner_grant,)
        by_model = {grant.model.model_key: grant for grant in context.copy_grants}
        by_model[owner_grant.model.model_key] = owner_grant
        return tuple(by_model[key] for key in sorted(by_model) if by_model[key].active and by_model[key].sources)

    @staticmethod
    def _validate_common(context: OwnerProjectionContext) -> None:
        if (
            context.target.resource_version != 0
            or context.source_id <= 0
            or context.operator_id <= 0
            or not context.store_id
            or not context.model_id
            or not context.idempotency_key
        ):
            raise PermissionInvalidResourceError()

    @staticmethod
    def _validate_system_owned(context: OwnerProjectionContext) -> None:
        if (
            context.target.resource_type not in SYSTEM_OWNED_RESOURCE_ALLOWLIST
            or not context.system_predicate
            or context.owner_grant is not None
            or context.owner_user_id is not None
            or not context.system_action_codes
            or any(action not in {"visible", "download", "use"} for action in context.system_action_codes)
        ):
            raise PermissionInvalidResourceError()

    @staticmethod
    def _validate_copy(context: OwnerProjectionContext) -> None:
        if context.operation_type == "RESOURCE_CREATE":
            if context.copy_grants or context.copy_deltas:
                raise PermissionInvalidResourceError()
            return
        if context.operation_type != "RESOURCE_COPY" or context.system_owned:
            raise PermissionInvalidResourceError()
        if context.permission_mode not in {"INHERIT", "CUSTOM"}:
            raise PermissionInvalidResourceError()
        if context.permission_mode == "INHERIT" and (context.copy_grants or context.copy_deltas):
            raise PermissionInvalidResourceError()
        for grant in context.copy_grants:
            if (
                grant.tenant_id != context.target.tenant_id
                or grant.resource_type != context.target.resource_type
                or grant.resource_id != context.target.resource_id
                or any(source.protected for source in grant.sources)
            ):
                raise PermissionInvalidResourceError()


def _run_async_safe(coro, *, timeout: float = 10):
    """Compatibility wrapper around the shared sync-to-async bridge."""
    from bisheng.utils.async_utils import run_async_safe

    return run_async_safe(coro, timeout=timeout)


class OwnerService:
    """Legacy identity tuple cleanup retained for user-group deletion only."""

    @classmethod
    def delete_resource_tuples_sync(
        cls,
        object_type: str,
        object_id: str,
    ) -> None:
        """Sync wrapper for delete_resource_tuples. Safe to call from FastAPI threadpool."""
        try:
            _run_async_safe(cls.delete_resource_tuples(object_type, object_id))
        except Exception as e:
            logger.warning("Failed to delete tuples (sync) for %s:%s: %s", object_type, object_id, e)

    @classmethod
    async def delete_resource_tuples(
        cls,
        object_type: str,
        object_id: str,
    ) -> None:
        """Delete all identity tuples for a removed user group."""
        if object_type != "user_group":
            raise RuntimeError(
                "OwnerService cleanup is identity-only after F048",
            )
        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = await PermissionService._aget_fga()
        if fga is None:
            logger.warning("FGAClient not available for tuple cleanup: %s:%s", object_type, object_id)
            return
        try:
            tuples = await fga.read_tuples(object=f"{object_type}:{object_id}")
            if not tuples:
                return
            from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

            operations = [
                TupleOperation(
                    action="delete",
                    user=t["user"],
                    relation=t["relation"],
                    object=t["object"],
                )
                for t in tuples
            ]
            await PermissionService.batch_write_tuples(operations)
            logger.info("Cleaned up %d tuples for %s:%s", len(operations), object_type, object_id)
        except Exception as e:
            logger.warning("Failed to cleanup tuples for %s:%s: %s", object_type, object_id, e)

    @classmethod
    async def delete_resource_tuples_strict(
        cls,
        object_type: str,
        object_id: str,
    ) -> int:
        """Delete and verify all tuples, propagating infrastructure failure.

        Durable deletion workers must not acknowledge a best-effort cleanup as
        success. The legacy delete path keeps using the tolerant method above.
        """

        from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = PermissionService._get_fga()
        if fga is None:
            raise RuntimeError("FGA client is unavailable for strict tuple cleanup")
        object_key = f"{object_type}:{object_id}"
        tuples = await fga.read_tuples(object=object_key, consistency="HIGHER_CONSISTENCY")
        operations = [
            TupleOperation(
                action="delete",
                user=tuple_row["user"],
                relation=tuple_row["relation"],
                object=tuple_row["object"],
            )
            for tuple_row in tuples
        ]
        if operations:
            await PermissionService.batch_write_tuples(
                operations,
                raise_on_failure=True,
                stop_on_failure=True,
                recovery_owner="caller",
            )
        remaining = await fga.read_tuples(object=object_key, consistency="HIGHER_CONSISTENCY")
        if remaining:
            raise RuntimeError(f"FGA tuple cleanup verification failed for {object_key}")
        return len(operations)


    @classmethod
    async def read_relation_subjects_strict(
        cls,
        object_type: str,
        object_id: str,
        relation: str,
    ) -> set[str]:
        """Read one resource relation with authoritative consistency."""

        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError("FGA client is unavailable for strict tuple verification")
        rows = await fga.read_tuples(
            object=f"{object_type}:{object_id}",
            relation=str(relation),
            consistency="HIGHER_CONSISTENCY",
        )
        return {str(row["user"]) for row in rows}


    @classmethod
    async def write_owner_tuple(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        *,
        enforce_fga_success: bool = False,
    ) -> None:
        """Write an owner tuple for a newly created resource.

        Called during resource creation (F008 integration point).
        By default this preserves legacy best-effort behavior. Callers that
        cannot safely continue without owner visibility should pass
        ``enforce_fga_success=True``.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService

        await PermissionService.authorize(
            object_type=object_type,
            object_id=object_id,
            grants=[
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=user_id,
                    relation="owner",
                    include_children=False,
                ),
            ],
            enforce_fga_success=enforce_fga_success,
        )

