"""Production adapters for the business-independent F048 permission runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from loguru import logger
from sqlalchemy import func, update
from sqlmodel import select

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    AuthorizationModelReleaseStatus,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import (
    ProjectionRepository,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
)

RECENT_MARKER_PREFIX = "f048:permission:recent"
RECENT_MARKER_SENTINEL = f"{RECENT_MARKER_PREFIX}:sentinel"
RECENT_MARKER_RECOVERY_LOCK = f"{RECENT_MARKER_PREFIX}:recovery-lock"
RECENT_CATALOG_MARKER = f"{RECENT_MARKER_PREFIX}:catalog"
HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"


def stable_grant_key(
    *,
    tenant_id: int,
    resource_type: str,
    resource_id: str,
    model_key: str,
) -> str:
    """Return the Store identity shared by migration and online writes."""

    canonical = "|".join((str(tenant_id), resource_type, resource_id, model_key))
    return sha256(canonical.encode("utf-8")).hexdigest()[:32]


def stable_assignee_id(
    *,
    grant_key: str,
    source_fingerprint: str,
) -> int:
    """Allocate a deterministic positive BigInteger for a new source row."""

    value = sha256(f"{grant_key}|{source_fingerprint}".encode()).hexdigest()[:15]
    return int(value, 16) or 1


class SqlCatalogDecisionState:
    """Validate the sole CURRENT release and concrete action scope."""

    def __init__(
        self,
        *,
        expected_store_id: str,
        expected_model_id: str,
    ) -> None:
        if not expected_store_id or not expected_model_id:
            raise ValueError("Permission decision runtime requires a Store/model pin")
        self._expected_store_id = expected_store_id
        self._expected_model_id = expected_model_id

    async def ensure_runtime_ready(self) -> None:
        async with get_async_db_session() as session:
            statement = (
                select(
                    PermissionCatalogRelease,
                    AuthorizationModelRelease,
                )
                .join(
                    AuthorizationModelRelease,
                    AuthorizationModelRelease.id == PermissionCatalogRelease.required_authorization_model_release_id,
                )
                .where(PermissionCatalogRelease.status == "CURRENT")
                .order_by(PermissionCatalogRelease.id)
            )
            rows = list((await session.execute(statement)).all())
        if len(rows) != 1:
            raise PermissionPublishNotReadyError(msg="Permission Catalog must have exactly one CURRENT release")
        current, model_release = rows[0]
        if current.write_fenced:
            raise PermissionPublishNotReadyError(msg="CURRENT Permission Catalog is write fenced")
        if (
            model_release.status != AuthorizationModelReleaseStatus.ACTIVE.value
            or model_release.store_id != self._expected_store_id
            or model_release.model_id != self._expected_model_id
        ):
            raise PermissionPublishNotReadyError(
                msg=("CURRENT Permission Catalog does not match the process Store/model pin")
            )

    async def is_action_effective(
        self,
        resource_type: str,
        action: str,
    ) -> bool:
        async with get_async_db_session() as session:
            statement = (
                select(PermissionAction.id)
                .join(
                    PermissionCatalogRelease,
                    PermissionCatalogRelease.id == PermissionAction.catalog_release_id,
                )
                .join(
                    PermissionActionResourceScope,
                    PermissionActionResourceScope.action_id == PermissionAction.id,
                )
                .where(
                    PermissionCatalogRelease.status == "CURRENT",
                    PermissionCatalogRelease.write_fenced == 0,
                    PermissionAction.code == action,
                    PermissionAction.active == 1,
                    PermissionAction.level.is_not(None),
                    PermissionActionResourceScope.resource_type == resource_type,
                )
                .limit(1)
            )
            return (await session.execute(statement)).scalar_one_or_none() is not None

    async def effective_actions(self, resource_type: str) -> tuple[str, ...]:
        """Every active, assigned action code effective for one resource type.

        The bulk sibling of ``is_action_effective``: one query returns the whole
        effective action set (in catalog display order) so a privileged actor,
        who holds no grant rows, can be reported as able to do all of them.
        """

        async with get_async_db_session() as session:
            statement = (
                select(PermissionAction.code)
                .join(
                    PermissionCatalogRelease,
                    PermissionCatalogRelease.id == PermissionAction.catalog_release_id,
                )
                .join(
                    PermissionActionResourceScope,
                    PermissionActionResourceScope.action_id == PermissionAction.id,
                )
                .where(
                    PermissionCatalogRelease.status == "CURRENT",
                    PermissionCatalogRelease.write_fenced == 0,
                    PermissionAction.active == 1,
                    PermissionAction.level.is_not(None),
                    PermissionActionResourceScope.resource_type == resource_type,
                )
                .order_by(PermissionAction.sort_order, PermissionAction.code)
            )
            rows = (await session.execute(statement)).scalars().all()
        return tuple(dict.fromkeys(rows))


class SqlPermissionScopeFence:
    """Trust only a CURRENT permission-owned mirror of a verified target."""

    async def ensure_readable(
        self,
        target: VerifiedPermissionTarget,
    ) -> None:
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == target.tenant_id,
                ResourcePermissionMode.resource_type == target.resource_type,
                ResourcePermissionMode.resource_id == target.resource_id,
            )
            row = (await session.execute(statement)).scalars().first()
        if (
            row is None
            or row.version != target.resource_version
            or row.projection_state != "CURRENT"
            or row.parent_type != target.parent_type
            or row.parent_id != target.parent_id
        ):
            raise PermissionPublishNotReadyError(
                msg="Resource permission projection is not current",
                stored_parent_type=row.parent_type if row else None,
                stored_parent_id=row.parent_id if row else None,
                stored_version=row.version if row else None,
                stored_projection_state=row.projection_state if row else None,
                expected_parent_type=target.parent_type,
                expected_parent_id=target.parent_id,
                expected_version=target.resource_version,
                expected_projection_state="CURRENT",
            )


class RedisConsistencyMarker:
    """Arm recent-change markers before FGA commits and consume them on reads."""

    def __init__(
        self,
        *,
        window_seconds: int | None = None,
        recovery_wait_seconds: float | None = None,
    ) -> None:
        self._window_seconds = window_seconds or settings.openfga.recent_consistency_window_seconds
        self._recovery_wait_seconds = (
            float(self._window_seconds) if recovery_wait_seconds is None else recovery_wait_seconds
        )
        if self._recovery_wait_seconds < 0:
            raise ValueError("marker recovery wait must not be negative")
        self._recovery_token = uuid4().hex
        self._recovery_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Start safe sentinel recovery without declaring Redis ready early."""

        if not await self.is_ready():
            await self._ensure_recovery_started()

    async def is_ready(self) -> bool:
        redis = await get_redis_client()
        ready = await redis.aget(RECENT_MARKER_SENTINEL) == "ready"
        if not ready:
            await self._ensure_recovery_started(redis=redis)
        return ready

    async def arm(self, plan: ProjectionPlan) -> None:
        redis = await get_redis_client()
        if await redis.aget(RECENT_MARKER_SENTINEL) != "ready":
            await self._ensure_recovery_started(redis=redis)
            raise PermissionPublishNotReadyError(msg="Permission recent-change marker sentinel is not ready")
        if plan.scope_type == "resource":
            resource_type, separator, resource_id = plan.scope_key.partition(":")
            if not separator or not resource_type or not resource_id:
                raise ValueError("resource projection scope key is invalid")
            keys = (
                self._resource_key(
                    tenant_id=plan.tenant_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                ),
                self._resource_key(
                    tenant_id=plan.tenant_id,
                    resource_type=resource_type,
                    resource_id=None,
                ),
            )
        elif plan.scope_type in {"department", "tenant", "user_group"}:
            keys = (self._tenant_key(plan.tenant_id),)
        else:
            raise ValueError(f"unsupported permission marker scope: {plan.scope_type}")
        for key in dict.fromkeys(keys):
            await redis.aset(
                key,
                plan.idempotency_key,
                expiration=self._window_seconds,
            )

    async def arm_catalog(self, release_key: str) -> None:
        """Force higher consistency globally after an atomic Catalog switch."""

        redis = await get_redis_client()
        await redis.aset(
            RECENT_CATALOG_MARKER,
            release_key,
            expiration=self._window_seconds,
        )

    async def consistency_for(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | None,
    ) -> str | None:
        redis = await get_redis_client()
        if await redis.aget(RECENT_MARKER_SENTINEL) != "ready":
            await self._ensure_recovery_started(redis=redis)
            return HIGHER_CONSISTENCY
        if await redis.aget(RECENT_CATALOG_MARKER) is not None:
            return HIGHER_CONSISTENCY
        keys = [
            self._tenant_key(tenant_id),
            self._resource_key(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
            ),
        ]
        if resource_id is not None:
            keys.append(
                self._resource_key(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    resource_id=None,
                )
            )
        for key in keys:
            if await redis.aget(key) is not None:
                return HIGHER_CONSISTENCY
        return None

    @staticmethod
    def _tenant_key(tenant_id: int) -> str:
        return f"{RECENT_MARKER_PREFIX}:{tenant_id}:*"

    @staticmethod
    def _resource_key(
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | None,
    ) -> str:
        suffix = resource_id if resource_id is not None else "*"
        return f"{RECENT_MARKER_PREFIX}:{tenant_id}:{resource_type}:{suffix}"

    async def _ensure_recovery_started(self, *, redis=None) -> None:
        task = self._recovery_task
        if task is not None and not task.done():
            return
        redis = redis or await get_redis_client()
        acquired = await redis.asetNx(
            RECENT_MARKER_RECOVERY_LOCK,
            self._recovery_token,
            expiration=max(int(self._recovery_wait_seconds) + 10, 10),
        )
        if not acquired:
            return
        await redis.aset(
            RECENT_CATALOG_MARKER,
            "sentinel-recovery",
            expiration=max(int(self._recovery_wait_seconds) + 1, 1),
        )
        self._recovery_task = asyncio.create_task(
            self._recover_sentinel(),
            name="f048-permission-marker-recovery",
        )

    async def _recover_sentinel(self) -> None:
        try:
            await asyncio.sleep(self._recovery_wait_seconds)
            redis = await get_redis_client()
            if await redis.aget(RECENT_MARKER_RECOVERY_LOCK) != self._recovery_token:
                return
            await redis.aset(
                RECENT_MARKER_SENTINEL,
                "ready",
                expiration=0,
            )
            await redis.adelete(RECENT_MARKER_RECOVERY_LOCK)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("F048 marker sentinel recovery failed")


class ExternalProjectionScopePort(Protocol):
    """Business-owned durable state for a non-resource projection scope.

    ``reserve`` must atomically bind the expected business version to
    ``operation_id`` before the first OpenFGA write. Repeating the same
    operation is idempotent; a competing operation or version must fail.
    """

    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None: ...

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool: ...

    async def fail_closed(self, plan: ProjectionPlan, reason: str) -> None: ...

    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None: ...


class SqlProjectionScopeGuard:
    """Use the permission mirror version as the projection retry fence."""

    def __init__(
        self,
        *,
        external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
    ) -> None:
        self._external_scopes = dict(external_scopes or {})

    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        if plan.scope_type == "resource":
            if not await self.is_expected_version(plan, operation_id):
                raise PermissionPublishNotReadyError(msg="Permission resource scope changed before projection")
            return
        delegate = self._external_scope(plan.scope_type)
        await delegate.reserve(plan, operation_id)

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool:
        resource_type, separator, resource_id = plan.scope_key.partition(":")
        if plan.scope_type != "resource":
            return await self._external_scope(plan.scope_type).is_expected_version(
                plan,
                operation_id,
            )
        if not separator:
            return False
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode.id).where(
                ResourcePermissionMode.tenant_id == plan.tenant_id,
                ResourcePermissionMode.resource_type == resource_type,
                ResourcePermissionMode.resource_id == resource_id,
                ResourcePermissionMode.version == plan.expected_version,
                ResourcePermissionMode.operation_id == operation_id,
                ResourcePermissionMode.projection_state.in_(("PENDING", "PROJECTING", "CURRENT")),
            )
            row_id = (await session.execute(statement)).scalar_one_or_none()
        return row_id is not None

    async def fail_closed(
        self,
        plan: ProjectionPlan,
        reason: str,
    ) -> None:
        if plan.scope_type != "resource":
            await self._external_scope(plan.scope_type).fail_closed(
                plan,
                reason,
            )
            return
        del reason
        resource_type, separator, resource_id = plan.scope_key.partition(":")
        if not separator:
            return
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(ResourcePermissionMode)
                    .where(
                        ResourcePermissionMode.tenant_id == plan.tenant_id,
                        ResourcePermissionMode.resource_type == resource_type,
                        ResourcePermissionMode.resource_id == resource_id,
                    )
                    .values(
                        projection_state="FAILED_CLOSED",
                        update_time=func.now(),
                    )
                )

    def _external_scope(
        self,
        scope_type: str,
    ) -> ExternalProjectionScopePort:
        delegate = self._external_scopes.get(scope_type)
        if delegate is None:
            raise PermissionPublishNotReadyError(msg=(f"Permission projection scope is not configured: {scope_type}"))
        return delegate


class FGAProjectionAdapter:
    """Translate ledger deltas to exact model-scoped OpenFGA calls."""

    def __init__(self, client: FGAClient) -> None:
        self._client = client

    async def write_atomic(
        self,
        *,
        writes: tuple[ProjectionTupleDelta, ...],
        deletes: tuple[ProjectionTupleDelta, ...],
    ) -> str:
        self._client.validate_business_mutation_size(len(writes) + len(deletes))
        await self._client.write_tuples(
            writes=[self._tuple(row) for row in writes],
            deletes=[self._tuple(row) for row in deletes],
        )
        canonical = "\n".join(
            "\0".join((row.action, row.user, row.relation, row.object)) for row in (*writes, *deletes)
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    async def read_present(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
        *,
        consistency: str,
    ) -> frozenset[tuple[str, str, str]]:
        present: set[tuple[str, str, str]] = set()
        for delta in dict.fromkeys(deltas):
            rows = await self._client.read_tuples(
                user=delta.user,
                relation=delta.relation,
                object=delta.object,
                consistency=consistency,
            )
            if any(
                row.get("user") == delta.user
                and row.get("relation") == delta.relation
                and row.get("object") == delta.object
                for row in rows
            ):
                present.add(delta.key)
        return frozenset(present)

    @staticmethod
    def _tuple(delta: ProjectionTupleDelta) -> dict[str, str]:
        return {
            "user": delta.user,
            "relation": delta.relation,
            "object": delta.object,
        }


class SqlProjectionFinalizer:
    """Advance the permission mirror only after higher-consistency verify."""

    def __init__(
        self,
        *,
        external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
    ) -> None:
        self._external_scopes = dict(external_scopes or {})

    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        if plan.scope_type != "resource":
            delegate = self._external_scopes.get(plan.scope_type)
            if delegate is None:
                raise PermissionPublishNotReadyError(
                    msg=(f"Permission projection finalizer is not configured: {plan.scope_type}")
                )
            await delegate.finalize(plan, operation_id)
            return
        resource_type, separator, resource_id = plan.scope_key.partition(":")
        if not separator:
            raise PermissionPublishNotReadyError(msg="Permission resource scope key is invalid")
        async with get_async_db_session() as session:
            async with session.begin():
                mode_row = (
                    (
                        await session.execute(
                            select(ResourcePermissionMode)
                            .where(
                                ResourcePermissionMode.tenant_id == plan.tenant_id,
                                ResourcePermissionMode.resource_type == resource_type,
                                ResourcePermissionMode.resource_id == resource_id,
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .first()
                )
                if mode_row is None or mode_row.operation_id != operation_id:
                    raise PermissionPublishNotReadyError(
                        msg=("Permission scope operation changed before projection finalize")
                    )
                if mode_row.version == plan.target_version and mode_row.projection_state == "CURRENT":
                    return
                if mode_row.version != plan.expected_version or mode_row.projection_state != "PROJECTING":
                    raise PermissionPublishNotReadyError(msg=("Permission scope changed before projection finalize"))

                grant_ids = tuple(
                    (
                        await session.execute(
                            select(PermissionGrant.id).where(
                                PermissionGrant.tenant_id == plan.tenant_id,
                                PermissionGrant.resource_type == resource_type,
                                PermissionGrant.resource_id == resource_id,
                                PermissionGrant.projection_state == "PROJECTING",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if grant_ids:
                    await session.execute(
                        update(PermissionGrantAssignee)
                        .where(
                            PermissionGrantAssignee.tenant_id == plan.tenant_id,
                            PermissionGrantAssignee.grant_id.in_(grant_ids),
                            PermissionGrantAssignee.state == "PENDING",
                        )
                        .values(state="ACTIVE", update_time=func.now())
                    )
                    await session.execute(
                        update(PermissionGrantAssignee)
                        .where(
                            PermissionGrantAssignee.tenant_id == plan.tenant_id,
                            PermissionGrantAssignee.grant_id.in_(grant_ids),
                            PermissionGrantAssignee.state == "PENDING_DELETE",
                        )
                        .values(
                            state="INACTIVE",
                            version=PermissionGrantAssignee.version + 1,
                            update_time=func.now(),
                        )
                    )
                    await session.execute(
                        update(PermissionGrant)
                        .where(
                            PermissionGrant.id.in_(grant_ids),
                            PermissionGrant.state == "PENDING",
                        )
                        .values(state="ACTIVE", update_time=func.now())
                    )
                    await session.execute(
                        update(PermissionGrant)
                        .where(PermissionGrant.id.in_(grant_ids))
                        .values(
                            projection_state="CURRENT",
                            update_time=func.now(),
                        )
                    )

                visible_sources = list(
                    (
                        await session.execute(
                            select(PermissionVisibleSourceProjection)
                            .where(
                                PermissionVisibleSourceProjection.tenant_id == plan.tenant_id,
                                PermissionVisibleSourceProjection.operation_id == operation_id,
                                PermissionVisibleSourceProjection.state == "PENDING",
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for source in visible_sources:
                    prefix = "grant_assignee:"
                    if source.source_kind != "GRANT_ASSIGNEE" or not source.source_owner_key.startswith(prefix):
                        raise PermissionPublishNotReadyError(
                            msg="Visible source recovery cannot infer its canonical owner state",
                        )
                    try:
                        assignee_id = int(source.source_owner_key.removeprefix(prefix))
                    except ValueError as exc:
                        raise PermissionPublishNotReadyError(
                            msg="Visible source recovery owner identity is invalid",
                        ) from exc
                    assignee_state = (
                        await session.execute(
                            select(PermissionGrantAssignee.state).where(
                                PermissionGrantAssignee.tenant_id == plan.tenant_id,
                                PermissionGrantAssignee.id == assignee_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if assignee_state not in {"ACTIVE", "INACTIVE"}:
                        raise PermissionPublishNotReadyError(
                            msg="Visible source recovery owner state is incomplete",
                        )
                    source.state = "ACTIVE" if assignee_state == "ACTIVE" else "RETIRED"
                    session.add(source)

                target_mode = self._target_mode(plan)
                mode_values: dict[str, object] = {
                    "version": plan.target_version,
                    "projection_state": "CURRENT",
                    "update_time": func.now(),
                }
                if target_mode is not None:
                    mode_values["mode"] = target_mode
                result = await session.execute(
                    update(ResourcePermissionMode)
                    .where(
                        ResourcePermissionMode.id == mode_row.id,
                        ResourcePermissionMode.operation_id == operation_id,
                        ResourcePermissionMode.version == plan.expected_version,
                        ResourcePermissionMode.projection_state == "PROJECTING",
                    )
                    .values(**mode_values)
                )
                if not result.rowcount:
                    raise PermissionPublishNotReadyError(msg=("Permission scope changed during projection finalize"))

    @staticmethod
    def _target_mode(plan: ProjectionPlan) -> str | None:
        modes = {
            delta.relation.removesuffix("_mode").upper()
            for delta in plan.deltas
            if delta.action == "WRITE" and delta.relation in {"custom_mode", "inherit_mode"}
        }
        if len(modes) > 1:
            raise PermissionPublishNotReadyError(msg="Projection writes more than one resource permission mode")
        return next(iter(modes), None)


class DenyListObjectsPolicy:
    """Keep ListObjects disabled until BENCH-01 approves a concrete caller."""

    async def allows(
        self,
        resource_type: str,
        action: str,
        max_results: int,
    ) -> bool:
        del resource_type, action, max_results
        return False


@dataclass(slots=True)
class SqlProjectionRuntime:
    repository: ProjectionRepository
    marker: RedisConsistencyMarker
    scope_guard: SqlProjectionScopeGuard
    fga: FGAProjectionAdapter
    finalizer: SqlProjectionFinalizer


async def build_sql_projection_runtime(
    client: FGAClient,
    *,
    external_scopes: dict[str, ExternalProjectionScopePort] | None = None,
) -> SqlProjectionRuntime:
    marker = RedisConsistencyMarker()
    await marker.initialize()
    return SqlProjectionRuntime(
        repository=ProjectionRepository(),
        marker=marker,
        scope_guard=SqlProjectionScopeGuard(
            external_scopes=external_scopes,
        ),
        fga=FGAProjectionAdapter(client),
        finalizer=SqlProjectionFinalizer(
            external_scopes=external_scopes,
        ),
    )
