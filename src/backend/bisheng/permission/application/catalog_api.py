"""Production Catalog application, SQL state, impact, and OpenFGA adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import delete, func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    ImmutableStandardModelError,
    InvalidCatalogActionError,
    PermissionImpactExpiredError,
    PermissionModelStateConflictError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.authorization_model_f048 import (
    DEFAULT_ACTION_CODES,
    get_authorization_model_f048,
    required_relations_checksum,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogProjectionTuple,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionProjectionOperation,
)
from bisheng.permission.domain.schemas import (
    CatalogChangeRequest,
    CatalogChangeType,
    CatalogDraftRequest,
    CatalogPublishRequest,
)
from bisheng.permission.domain.services.catalog_policy import (
    CatalogAction,
    CatalogActionImpact,
    CatalogActionRelease,
    derive_action_release,
)
from bisheng.permission.domain.services.catalog_service import (
    CatalogCommitUnknownError,
    CatalogDraftBuildInput,
    CatalogDraftSnapshot,
    CatalogImpactSummary,
    CatalogPublishContext,
    CatalogService,
    CatalogTupleChange,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    PermissionModelImpact,
    PermissionModelRelease,
    derive_permission_models,
    effective_model_action_codes,
    ensure_model_deletable,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ZERO_CHECKSUM = "0" * 64
HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"
CATALOG_STAGE_BATCH_SIZE = 80
CATALOG_READ_CONCURRENCY = 8
ACTIVE_OPERATION_STATUSES = (
    "PREPARED",
    "STAGING",
    "COMMIT_UNKNOWN",
    "COMMITTED",
)


class CatalogRecentMarkerPort(Protocol):
    async def arm_catalog(self, release_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CatalogDraftReservation:
    release_id: int
    release_key: str
    version: int
    predecessor_id: int
    predecessor_key: str
    complete: bool


@asynccontextmanager
async def _default_session_factory() -> AsyncIterator[AsyncSession]:
    async with get_async_db_session() as session:
        yield session


def _tuple_checksum(user: str, relation: str, object_key: str) -> str:
    return sha256("\0".join((user, relation, object_key)).encode()).hexdigest()


def _utc_now_naive() -> datetime:
    """Return the repository's UTC database timestamp representation."""

    return datetime.now(UTC).replace(tzinfo=None)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _commit_checksum(changes: tuple[CatalogTupleChange, ...]) -> str:
    canonical = "\n".join("\0".join((change.action, change.user, change.relation, change.object)) for change in changes)
    return sha256(canonical.encode()).hexdigest()


class SqlCatalogState:
    """Persist complete draft snapshots and serialize the global pointer."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = _default_session_factory,
    ) -> None:
        self._session_factory = session_factory

    async def reserve_draft(
        self,
        *,
        base_release_id: int,
        operator_id: int,
        idempotency_key: str,
        expires_at: datetime,
    ) -> CatalogDraftReservation:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    existing = (
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(PermissionCatalogRelease.idempotency_key == idempotency_key)
                                .with_for_update()
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if existing is not None:
                        if existing.predecessor_id != base_release_id or existing.id is None:
                            raise PermissionVersionConflictError(msg="Catalog idempotency key has another request")
                        predecessor = await session.get(
                            PermissionCatalogRelease,
                            existing.predecessor_id,
                        )
                        if predecessor is None:
                            raise PermissionPublishNotReadyError(msg="Catalog draft predecessor is missing")
                        return CatalogDraftReservation(
                            release_id=int(existing.id),
                            release_key=existing.release_key,
                            version=existing.version,
                            predecessor_id=int(predecessor.id),
                            predecessor_key=predecessor.release_key,
                            complete=existing.checksum != ZERO_CHECKSUM,
                        )

                    current_rows = list(
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(PermissionCatalogRelease.status == "CURRENT")
                                .with_for_update()
                            )
                        ).scalars()
                    )
                    if len(current_rows) != 1 or current_rows[0].id != base_release_id or current_rows[0].write_fenced:
                        raise PermissionVersionConflictError(msg="Catalog base release is no longer current")
                    maximum = (
                        await session.execute(select(func.max(PermissionCatalogRelease.version)))
                    ).scalar_one_or_none()
                    version = int(maximum or 0) + 1
                    suffix = sha256(idempotency_key.encode()).hexdigest()[:10]
                    release = PermissionCatalogRelease(
                        release_key=f"catalog-v{version}-{suffix}",
                        version=version,
                        status="DRAFT",
                        write_fenced=False,
                        predecessor_id=base_release_id,
                        required_authorization_model_release_id=(
                            current_rows[0].required_authorization_model_release_id
                        ),
                        draft_owner_id=operator_id,
                        idempotency_key=idempotency_key,
                        expires_at=expires_at,
                        checksum=ZERO_CHECKSUM,
                    )
                    session.add(release)
                    await session.flush()
                    return CatalogDraftReservation(
                        release_id=int(release.id),
                        release_key=release.release_key,
                        version=release.version,
                        predecessor_id=base_release_id,
                        predecessor_key=current_rows[0].release_key,
                        complete=False,
                    )

    async def save_draft(
        self,
        draft: CatalogDraftSnapshot,
    ) -> CatalogDraftSnapshot:
        if draft.action_release is None or draft.model_release is None:
            raise PermissionPublishNotReadyError(msg="Catalog draft has no complete release payload")
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    release = (
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(PermissionCatalogRelease.id == draft.release_id)
                                .with_for_update()
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if release is None:
                        raise PermissionPublishNotReadyError(msg="Catalog draft reservation is missing")
                    if (
                        release.release_key != draft.release_key
                        or release.predecessor_id != draft.predecessor_release_id
                        or release.idempotency_key != draft.idempotency_key
                        or release.draft_owner_id != draft.draft_owner_id
                    ):
                        raise PermissionVersionConflictError(msg="Catalog draft reservation changed")
                    if release.checksum != ZERO_CHECKSUM:
                        if release.checksum != draft.release_checksum:
                            raise PermissionVersionConflictError(
                                msg=("Catalog idempotency key was reused with different changes")
                            )
                        return await self._load_snapshot(
                            session,
                            int(release.id),
                        )
                    await self._replace_children(
                        session,
                        release_id=int(release.id),
                        action_release=draft.action_release,
                        model_release=draft.model_release,
                    )
                    release.checksum = draft.release_checksum
                    # DRAFT uses commit_checksum as the durable impact binding.
                    # Publication replaces it with the active-pointer checksum.
                    release.commit_checksum = draft.impact_checksum
                    release.expires_at = draft.expires_at
                    await session.flush()
                    return draft

    async def load_snapshot(
        self,
        release_id: int,
    ) -> CatalogDraftSnapshot:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                return await self._load_snapshot(session, release_id)

    async def release_row(
        self,
        release_id: int,
    ) -> PermissionCatalogRelease:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                row = await session.get(PermissionCatalogRelease, release_id)
                if row is None:
                    raise PermissionPublishNotReadyError(msg="Permission Catalog release is missing")
                return row

    async def current_release(self) -> PermissionCatalogRelease:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                rows = list(
                    (
                        await session.execute(
                            select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                        )
                    ).scalars()
                )
        if len(rows) != 1:
            raise PermissionPublishNotReadyError(msg="Permission Catalog must have exactly one CURRENT release")
        return rows[0]

    async def authorization_release(
        self,
        release_id: int,
    ) -> AuthorizationModelRelease:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                release = await session.get(
                    PermissionCatalogRelease,
                    release_id,
                )
                row = (
                    await session.get(
                        AuthorizationModelRelease,
                        release.required_authorization_model_release_id,
                    )
                    if release is not None
                    else None
                )
        if row is None:
            raise AuthorizationModelMismatchError(msg="Catalog authorization model release is missing")
        return row

    async def grant_references(
        self,
    ) -> dict[str, tuple[str, ...]]:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                rows = list(
                    (
                        await session.execute(select(PermissionGrant).where(PermissionGrant.state != "INACTIVE"))
                    ).scalars()
                )
        references: dict[str, list[str]] = {}
        for row in rows:
            references.setdefault(row.model_key, []).append(
                "|".join(
                    (
                        str(row.tenant_id),
                        row.resource_type,
                        row.resource_id,
                        str(row.id),
                    )
                )
            )
        return {key: tuple(sorted(values)) for key, values in references.items()}

    async def prepare_publish(
        self,
        *,
        draft_id: int,
        expected_current_release_id: int,
        idempotency_key: str,
    ) -> CatalogPublishContext:
        if not idempotency_key:
            raise PermissionVersionConflictError()
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    draft = (
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(PermissionCatalogRelease.id == draft_id)
                                .with_for_update()
                            )
                        )
                        .scalars()
                        .first()
                    )
                    if draft is None or draft.predecessor_id is None:
                        raise PermissionPublishNotReadyError(msg="Catalog draft is missing")
                    predecessor = await session.get(
                        PermissionCatalogRelease,
                        draft.predecessor_id,
                    )
                    if predecessor is None:
                        raise PermissionPublishNotReadyError(msg="Catalog predecessor is missing")
                    snapshot = await self._load_snapshot(session, draft_id)
                    if draft.status == "CURRENT":
                        return self._context(
                            snapshot,
                            predecessor,
                            draft.status,
                            already_current=True,
                        )
                    if draft.status == "FAILED_CLOSED":
                        raise PermissionPublishNotReadyError(msg="Catalog publication is failed closed")
                    if draft.predecessor_id != expected_current_release_id:
                        raise PermissionVersionConflictError()
                    current_rows = list(
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(PermissionCatalogRelease.status == "CURRENT")
                                .with_for_update()
                            )
                        ).scalars()
                    )
                    if len(current_rows) != 1 or current_rows[0].id != expected_current_release_id:
                        raise PermissionVersionConflictError()
                    current = current_rows[0]
                    if draft.status == "COMMITTED":
                        return self._context(
                            snapshot,
                            current,
                            draft.status,
                        )
                    if draft.status not in {"DRAFT", "PROJECTING"}:
                        raise PermissionPublishNotReadyError(msg=f"Catalog draft status is {draft.status}")
                    if draft.expires_at is not None and draft.expires_at <= _utc_now_naive():
                        raise PermissionImpactExpiredError()
                    current.write_fenced = True
                    await session.flush()
                    in_flight = (
                        await session.execute(
                            select(func.count(PermissionProjectionOperation.id)).where(
                                PermissionProjectionOperation.status.in_(ACTIVE_OPERATION_STATUSES)
                            )
                        )
                    ).scalar_one()
                    if in_flight:
                        current.write_fenced = False
                        raise PermissionPublishNotReadyError(
                            msg=("Catalog publish is waiting for in-flight permission operations")
                        )
                    return self._context(
                        snapshot,
                        current,
                        draft.status,
                    )

    async def mark_projecting(
        self,
        context: CatalogPublishContext,
    ) -> None:
        await self._set_release_status(
            context.draft.release_id,
            statuses=("DRAFT", "PROJECTING"),
            target="PROJECTING",
        )

    async def mark_committed(
        self,
        context: CatalogPublishContext,
        *,
        commit_checksum: str,
    ) -> None:
        await self._set_release_status(
            context.draft.release_id,
            statuses=("PROJECTING", "COMMITTED"),
            target="COMMITTED",
            commit_checksum=commit_checksum,
        )

    async def finalize_publish(
        self,
        context: CatalogPublishContext,
    ) -> None:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    rows = list(
                        (
                            await session.execute(
                                select(PermissionCatalogRelease)
                                .where(
                                    col(PermissionCatalogRelease.id).in_(
                                        (
                                            context.current_release_id,
                                            context.draft.release_id,
                                        )
                                    )
                                )
                                .with_for_update()
                            )
                        ).scalars()
                    )
                    by_id = {int(row.id): row for row in rows}
                    old = by_id.get(context.current_release_id)
                    new = by_id.get(context.draft.release_id)
                    if new is None:
                        raise PermissionPublishNotReadyError()
                    if new.status == "CURRENT":
                        return
                    if old is None or new.status != "COMMITTED":
                        raise PermissionPublishNotReadyError(msg="Catalog SQL finalize state is invalid")
                    old.status = "RETIRED"
                    old.write_fenced = False
                    new.status = "CURRENT"
                    new.write_fenced = False
                    new.published_at = func.now()

    async def abort_before_commit(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None:
        del reason
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(PermissionCatalogRelease)
                        .where(
                            PermissionCatalogRelease.id == context.draft.release_id,
                            PermissionCatalogRelease.status.in_(("DRAFT", "PROJECTING")),
                        )
                        .values(status="DRAFT", update_time=func.now())
                    )
                    await session.execute(
                        update(PermissionCatalogRelease)
                        .where(
                            PermissionCatalogRelease.id == context.current_release_id,
                            PermissionCatalogRelease.status == "CURRENT",
                        )
                        .values(
                            write_fenced=False,
                            update_time=func.now(),
                        )
                    )

    async def fail_closed(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None:
        del reason
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(PermissionCatalogRelease)
                        .where(PermissionCatalogRelease.id == context.draft.release_id)
                        .values(
                            status="FAILED_CLOSED",
                            write_fenced=True,
                            update_time=func.now(),
                        )
                    )
                    await session.execute(
                        update(PermissionCatalogRelease)
                        .where(PermissionCatalogRelease.id == context.current_release_id)
                        .values(
                            write_fenced=True,
                            update_time=func.now(),
                        )
                    )

    async def get_publish_context(
        self,
        draft_id: int,
    ) -> CatalogPublishContext:
        draft = await self.load_snapshot(draft_id)
        row = await self.release_row(draft_id)
        predecessor = await self.release_row(draft.predecessor_release_id)
        return self._context(
            draft,
            predecessor,
            row.status,
            already_current=row.status == "CURRENT",
        )

    async def _set_release_status(
        self,
        release_id: int,
        *,
        statuses: tuple[str, ...],
        target: str,
        commit_checksum: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": target,
            "update_time": func.now(),
        }
        if commit_checksum is not None:
            values["commit_checksum"] = commit_checksum
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        update(PermissionCatalogRelease)
                        .where(
                            PermissionCatalogRelease.id == release_id,
                            PermissionCatalogRelease.status.in_(statuses),
                        )
                        .values(**values)
                    )
                    if not result.rowcount:
                        row = await session.get(
                            PermissionCatalogRelease,
                            release_id,
                        )
                        if row is None or row.status != target:
                            raise PermissionVersionConflictError()

    @staticmethod
    def _context(
        draft: CatalogDraftSnapshot,
        current: PermissionCatalogRelease,
        status: str,
        *,
        already_current: bool = False,
    ) -> CatalogPublishContext:
        return CatalogPublishContext(
            draft=draft,
            current_release_id=int(current.id),
            current_release_key=current.release_key,
            status=status,
            already_current=already_current,
        )

    async def _load_snapshot(
        self,
        session: AsyncSession,
        release_id: int,
    ) -> CatalogDraftSnapshot:
        release = await session.get(PermissionCatalogRelease, release_id)
        if release is None or release.id is None or release.checksum == ZERO_CHECKSUM:
            raise PermissionPublishNotReadyError(msg="Catalog release snapshot is incomplete")
        predecessor = (
            await session.get(
                PermissionCatalogRelease,
                release.predecessor_id,
            )
            if release.predecessor_id is not None
            else release
        )
        if predecessor is None:
            raise PermissionPublishNotReadyError(msg="Catalog predecessor is missing")
        actions = await self._load_actions(session, release_id)
        action_release = derive_action_release(actions)
        model_release = await self._load_models(
            session,
            release_id,
            action_release,
        )
        impact_checksum = (
            release.commit_checksum
            if release.status in {"DRAFT", "PROJECTING"} and release.commit_checksum
            else release.checksum
        )
        return CatalogDraftSnapshot(
            release_id=release_id,
            release_key=release.release_key,
            predecessor_release_id=int(predecessor.id),
            predecessor_release_key=predecessor.release_key,
            release_checksum=release.checksum,
            impact_checksum=impact_checksum,
            required_action_codes=tuple(action.code for action in action_release.actions),
            blockers=model_release.blockers,
            action_release=action_release,
            model_release=model_release,
            draft_owner_id=release.draft_owner_id,
            idempotency_key=release.idempotency_key,
            expires_at=release.expires_at,
        )

    @staticmethod
    async def _load_actions(
        session: AsyncSession,
        release_id: int,
    ) -> tuple[CatalogAction, ...]:
        rows = list(
            (
                await session.execute(
                    select(PermissionAction)
                    .where(PermissionAction.catalog_release_id == release_id)
                    .order_by(PermissionAction.sort_order)
                )
            ).scalars()
        )
        action_ids = [int(row.id) for row in rows if row.id is not None]
        scopes = (
            list(
                (
                    await session.execute(
                        select(
                            PermissionActionResourceScope.action_id,
                            PermissionActionResourceScope.resource_type,
                        ).where(col(PermissionActionResourceScope.action_id).in_(action_ids))
                    )
                ).all()
            )
            if action_ids
            else []
        )
        scope_by_action: dict[int, set[str]] = {}
        for action_id, resource_type in scopes:
            scope_by_action.setdefault(int(action_id), set()).add(str(resource_type))
        return tuple(
            CatalogAction(
                code=row.code,
                name=row.name,
                level=row.level,
                active=bool(row.active),
                resource_types=frozenset(scope_by_action.get(int(row.id or 0), ())),
                sort_order=row.sort_order,
            )
            for row in rows
        )

    @staticmethod
    async def _load_models(
        session: AsyncSession,
        release_id: int,
        actions: CatalogActionRelease,
    ) -> PermissionModelRelease:
        rows = list(
            (
                await session.execute(
                    select(PermissionModel)
                    .where(PermissionModel.catalog_release_id == release_id)
                    .order_by(PermissionModel.model_key)
                )
            ).scalars()
        )
        ids = [int(row.id) for row in rows if row.id is not None]
        pairs = (
            list(
                (
                    await session.execute(
                        select(
                            PermissionModelAction.model_id,
                            PermissionAction.code,
                        )
                        .join(
                            PermissionAction,
                            PermissionAction.id == PermissionModelAction.action_id,
                        )
                        .where(col(PermissionModelAction.model_id).in_(ids))
                    )
                ).all()
            )
            if ids
            else []
        )
        selected: dict[int, list[str]] = {}
        for model_id, action_code in pairs:
            selected.setdefault(int(model_id), []).append(str(action_code))
        customs = tuple(
            CustomModelSelection(
                model_key=row.model_key,
                name=row.name,
                action_codes=tuple(
                    action.code for action in actions.actions if action.code in selected.get(int(row.id or 0), ())
                ),
                active=bool(row.active),
                allow_same_level=bool(row.allow_same_level),
                config_scope=row.config_scope,
            )
            for row in rows
            if row.kind == "CUSTOM"
        )
        standard_policy = {row.model_key: bool(row.allow_same_level) for row in rows if row.kind == "STANDARD"}
        return derive_permission_models(
            actions,
            custom_models=customs,
            standard_allow_same_level=standard_policy,
        )

    @staticmethod
    async def _replace_children(
        session: AsyncSession,
        *,
        release_id: int,
        action_release: CatalogActionRelease,
        model_release: PermissionModelRelease,
    ) -> None:
        old_model_ids = list(
            (
                await session.execute(
                    select(PermissionModel.id).where(PermissionModel.catalog_release_id == release_id)
                )
            ).scalars()
        )
        old_action_ids = list(
            (
                await session.execute(
                    select(PermissionAction.id).where(PermissionAction.catalog_release_id == release_id)
                )
            ).scalars()
        )
        if old_model_ids:
            await session.execute(
                delete(PermissionModelAction).where(col(PermissionModelAction.model_id).in_(old_model_ids))
            )
        await session.execute(delete(PermissionModel).where(PermissionModel.catalog_release_id == release_id))
        if old_action_ids:
            await session.execute(
                delete(PermissionActionResourceScope).where(
                    col(PermissionActionResourceScope.action_id).in_(old_action_ids)
                )
            )
        await session.execute(delete(PermissionAction).where(PermissionAction.catalog_release_id == release_id))
        action_ids: dict[str, int] = {}
        for action in action_release.actions:
            row = PermissionAction(
                catalog_release_id=release_id,
                code=action.code,
                name=action.name,
                level=action.level,
                active=action.active,
                sort_order=action.sort_order,
            )
            session.add(row)
            await session.flush()
            action_ids[action.code] = int(row.id)
            session.add_all(
                [
                    PermissionActionResourceScope(
                        action_id=int(row.id),
                        resource_type=resource_type,
                    )
                    for resource_type in sorted(action.resource_types)
                ]
            )
        for model in model_release.models:
            row = PermissionModel(
                catalog_release_id=release_id,
                model_key=model.model_key,
                normalized_name=model.name.casefold(),
                name=model.name,
                kind=model.kind,
                config_scope=model.config_scope,
                derived_level=model.derived_level,
                active=model.active,
                allow_same_level=model.allow_same_level,
            )
            session.add(row)
            await session.flush()
            session.add_all(
                [
                    PermissionModelAction(
                        model_id=int(row.id),
                        action_id=action_ids[action_code],
                    )
                    for action_code in model.selected_action_codes
                ]
            )


class SqlCatalogImpact:
    """Calculate a cross-tenant impact checksum from permission-owned rows."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = _default_session_factory,
    ) -> None:
        self._session_factory = session_factory
        self._state = SqlCatalogState(session_factory=session_factory)

    async def analyze_draft(
        self,
        *,
        action_impact: CatalogActionImpact,
        model_impact: PermissionModelImpact,
        before_actions: CatalogActionRelease,
        after_actions: CatalogActionRelease,
        before_models: PermissionModelRelease,
        after_models: PermissionModelRelease,
    ) -> CatalogImpactSummary:
        candidate_keys = set(action_impact.affected_model_keys)
        candidate_keys.update(model_impact.changed_model_keys)
        before_by_key = {model.model_key: model for model in before_models.models}
        after_by_key = {model.model_key: model for model in after_models.models}
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                grants = (
                    list(
                        (
                            await session.execute(
                                select(PermissionGrant)
                                .where(
                                    PermissionGrant.state != "INACTIVE",
                                    col(PermissionGrant.model_key).in_(candidate_keys or {""}),
                                )
                                .order_by(
                                    PermissionGrant.tenant_id,
                                    PermissionGrant.resource_type,
                                    PermissionGrant.resource_id,
                                    PermissionGrant.model_key,
                                    PermissionGrant.id,
                                )
                            )
                        ).scalars()
                    )
                    if candidate_keys
                    else []
                )
                grant_ids = [int(row.id) for row in grants if row.id is not None]
                sources = (
                    list(
                        (
                            await session.execute(
                                select(PermissionGrantAssignee)
                                .where(
                                    col(PermissionGrantAssignee.grant_id).in_(grant_ids),
                                    PermissionGrantAssignee.state == "ACTIVE",
                                )
                                .order_by(
                                    PermissionGrantAssignee.grant_id,
                                    PermissionGrantAssignee.id,
                                )
                            )
                        ).scalars()
                    )
                    if grant_ids
                    else []
                )
        sources_by_grant: dict[int, list[PermissionGrantAssignee]] = {}
        for source in sources:
            sources_by_grant.setdefault(source.grant_id, []).append(source)
        affected: list[tuple[PermissionGrant, set[str], set[str]]] = []
        for grant in grants:
            before_model = before_by_key.get(grant.model_key)
            after_model = after_by_key.get(grant.model_key)
            before_effective = set(
                effective_model_action_codes(
                    before_model,
                    before_actions,
                    grant.resource_type,
                )
                if before_model is not None
                else ()
            )
            after_effective = set(
                effective_model_action_codes(
                    after_model,
                    after_actions,
                    grant.resource_type,
                )
                if after_model is not None
                else ()
            )
            if before_effective == after_effective:
                continue
            affected.append((grant, before_effective, after_effective))
        resource_keys = {(row.tenant_id, row.resource_type, row.resource_id) for row, _, _ in affected}
        assignee_count = sum(len(sources_by_grant.get(int(row.id), ())) for row, _, _ in affected)
        expansion_count = sum(
            len(after - before) * len(sources_by_grant.get(int(row.id), ())) for row, before, after in affected
        )
        revocation_count = sum(
            len(before - after) * len(sources_by_grant.get(int(row.id), ())) for row, before, after in affected
        )
        source_signatures = {
            int(row.id): tuple(
                (
                    source.source_fingerprint,
                    source.version,
                    source.protected,
                )
                for source in sources_by_grant.get(int(row.id), ())
            )
            for row, _, _ in affected
        }
        payload = (
            action_impact.checksum,
            model_impact.checksum,
            tuple(
                (
                    row.tenant_id,
                    row.resource_type,
                    row.resource_id,
                    row.model_key,
                    tuple(sorted(before)),
                    tuple(sorted(after)),
                    source_signatures[int(row.id)],
                )
                for row, before, after in affected
            ),
        )
        return CatalogImpactSummary(
            checksum=sha256(repr(payload).encode()).hexdigest(),
            resource_count=len(resource_keys),
            grant_count=len(affected),
            assignee_count=assignee_count,
            expansion_count=expansion_count,
            revocation_count=revocation_count,
            blockers=(),
        )

    async def recalculate(
        self,
        draft: CatalogDraftSnapshot,
    ) -> str:
        return (await self.describe(draft)).checksum

    async def describe(
        self,
        draft: CatalogDraftSnapshot,
    ) -> CatalogImpactSummary:
        before = await self._state.load_snapshot(draft.predecessor_release_id)
        if (
            before.action_release is None
            or before.model_release is None
            or draft.action_release is None
            or draft.model_release is None
        ):
            raise PermissionPublishNotReadyError()
        from bisheng.permission.domain.services.catalog_policy import (
            calculate_action_impact,
        )
        from bisheng.permission.domain.services.model_policy import (
            calculate_model_impact,
        )

        custom_actions = {
            model.model_key: frozenset(model.selected_action_codes)
            for model in before.model_release.models
            if model.kind == "CUSTOM"
        }
        custom_actions.update(
            {
                model.model_key: frozenset(model.selected_action_codes)
                for model in draft.model_release.models
                if model.kind == "CUSTOM"
            }
        )
        action_impact = calculate_action_impact(
            before.action_release,
            draft.action_release,
            custom_model_actions=custom_actions,
        )
        references = await self._state.grant_references()
        model_impact = calculate_model_impact(
            before.model_release,
            draft.model_release,
            grant_references=references,
        )
        return await self.analyze_draft(
            action_impact=action_impact,
            model_impact=model_impact,
            before_actions=before.action_release,
            after_actions=draft.action_release,
            before_models=before.model_release,
            after_models=draft.model_release,
        )


class OpenFGACatalogProjector:
    """Stage model-release tuples and switch the global pointer atomically."""

    def __init__(
        self,
        *,
        client: FGAClient,
        marker: CatalogRecentMarkerPort,
        session_factory: SessionFactory = _default_session_factory,
    ) -> None:
        self._client = client
        self._marker = marker
        self._session_factory = session_factory

    async def validate_required_actions(
        self,
        action_codes: tuple[str, ...],
    ) -> None:
        if not set(action_codes) <= set(DEFAULT_ACTION_CODES):
            raise AuthorizationModelMismatchError(msg="Catalog contains actions absent from the pinned model")
        expected_relations = required_relations_checksum(get_authorization_model_f048())
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                rows = list(
                    (
                        await session.execute(
                            select(AuthorizationModelRelease).where(
                                AuthorizationModelRelease.store_id == self._client.store_id,
                                AuthorizationModelRelease.model_id == self._client.model_id,
                                AuthorizationModelRelease.status == "ACTIVE",
                            )
                        )
                    ).scalars()
                )
        if len(rows) != 1 or rows[0].required_relations_checksum != expected_relations:
            raise AuthorizationModelMismatchError(msg="Pinned authorization model relation surface differs")

    async def stage_model_releases(
        self,
        draft: CatalogDraftSnapshot,
    ) -> None:
        expected = self._expected_tuples(draft)
        await self._persist_plan(draft.release_id, expected)
        present = await self._read_present(expected)
        missing = [row for row in expected if (row["user"], row["relation"], row["object"]) not in present]
        for index in range(0, len(missing), CATALOG_STAGE_BATCH_SIZE):
            batch = missing[index : index + CATALOG_STAGE_BATCH_SIZE]
            self._client.validate_business_mutation_size(len(batch))
            await self._client.write_tuples(writes=batch)
        await self._mark_written(draft.release_id, expected)

    async def run_model_tests(
        self,
        draft: CatalogDraftSnapshot,
    ) -> None:
        planned = self._expected_tuples(draft)
        expected = {(row["user"], row["relation"], row["object"]) for row in planned}
        present = await self._read_present(planned)
        missing = expected - present
        if missing:
            raise PermissionProjectionFailedError(msg=f"Catalog staged tuple verification failed: {len(missing)}")
        if draft.model_release is None:
            raise PermissionPublishNotReadyError(msg="Catalog model release is missing")

    async def _read_present(
        self,
        planned: list[dict[str, str]],
    ) -> set[tuple[str, str, str]]:
        """Read only the tuples this plan touches, one concrete object at a time.

        An unfiltered Read walks the whole Store at 100 tuples per request, so
        checking a few hundred Catalog tuples against a 77k-tuple Store cost
        ~774 round trips — twice per publish, at HIGHER_CONSISTENCY. Scoping the
        reads to the planned objects makes the cost proportional to the plan
        instead of the Store, and the objects are independent so they overlap.
        """

        objects = sorted({row["object"] for row in planned})
        if not objects:
            return set()
        semaphore = asyncio.Semaphore(CATALOG_READ_CONCURRENCY)

        async def read(object_key: str) -> list[dict]:
            async with semaphore:
                return await self._client.read_tuples(
                    object=object_key,
                    consistency=HIGHER_CONSISTENCY,
                )

        pages = await asyncio.gather(*(read(key) for key in objects))
        return {(row["user"], row["relation"], row["object"]) for page in pages for row in page}

    async def arm_recent_marker(
        self,
        draft: CatalogDraftSnapshot,
    ) -> None:
        await self._marker.arm_catalog(draft.release_key)

    async def commit_active(
        self,
        changes: tuple[CatalogTupleChange, CatalogTupleChange],
    ) -> str:
        active = await self.read_active_release_keys()
        old_key = changes[0].object.partition(":")[2]
        new_key = changes[1].object.partition(":")[2]
        if active == frozenset({new_key}):
            return _commit_checksum(changes)
        if active != frozenset({old_key}):
            raise CatalogCommitUnknownError(f"Catalog active pointer is {sorted(active)}")
        await self._client.write_tuples(
            writes=[
                {
                    "user": changes[1].user,
                    "relation": changes[1].relation,
                    "object": changes[1].object,
                }
            ],
            deletes=[
                {
                    "user": changes[0].user,
                    "relation": changes[0].relation,
                    "object": changes[0].object,
                }
            ],
        )
        return _commit_checksum(changes)

    async def read_active_release_keys(self) -> frozenset[str]:
        # OpenFGA rejects a tuple_key without an object type, so the filter has
        # to name the type even though the prefix check below already does.
        rows = await self._client.read_tuples(
            user="user:*",
            relation="active",
            object="permission_catalog_release:",
            consistency=HIGHER_CONSISTENCY,
        )
        prefix = "permission_catalog_release:"
        return frozenset(row["object"].removeprefix(prefix) for row in rows if row["object"].startswith(prefix))

    @staticmethod
    def _expected_tuples(
        draft: CatalogDraftSnapshot,
    ) -> list[dict[str, str]]:
        if draft.model_release is None:
            raise PermissionPublishNotReadyError()
        catalog = f"permission_catalog_release:{draft.release_key}"
        tuples: dict[tuple[str, str, str], dict[str, str]] = {}

        def add(user: str, relation: str, object_key: str) -> None:
            tuples[(user, relation, object_key)] = {
                "user": user,
                "relation": relation,
                "object": object_key,
            }

        for model in draft.model_release.models:
            release = f"permission_model_release:{draft.release_key}~{model.model_key}"
            add(release, "release", f"permission_model:{model.model_key}")
            add(catalog, "catalog", release)
            add("user:*", "enabled_marker", release)
            for action in model.action_codes:
                add("user:*", f"{action}_marker", release)
            if "manage_permission" in model.action_codes and model.derived_level is not None:
                upper = model.derived_level if model.allow_same_level else model.derived_level - 1
                for level in range(1, max(upper, 0) + 1):
                    add(
                        "user:*",
                        f"grant_level_{level}_marker",
                        release,
                    )
        return list(tuples.values())

    async def _persist_plan(
        self,
        release_id: int,
        tuples: list[dict[str, str]],
    ) -> None:
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    existing = set(
                        (
                            await session.execute(
                                select(PermissionCatalogProjectionTuple.tuple_fingerprint).where(
                                    PermissionCatalogProjectionTuple.catalog_release_id == release_id,
                                    PermissionCatalogProjectionTuple.phase == "STAGE",
                                )
                            )
                        ).scalars()
                    )
                    for sequence, row in enumerate(tuples, start=1):
                        fingerprint = _tuple_checksum(
                            row["user"],
                            row["relation"],
                            row["object"],
                        )
                        if fingerprint in existing:
                            continue
                        session.add(
                            PermissionCatalogProjectionTuple(
                                catalog_release_id=release_id,
                                phase="STAGE",
                                sequence=sequence,
                                action="WRITE",
                                fga_user=row["user"],
                                relation=row["relation"],
                                fga_object=row["object"],
                                tuple_fingerprint=fingerprint,
                                status="PENDING",
                            )
                        )

    async def _mark_written(
        self,
        release_id: int,
        tuples: list[dict[str, str]],
    ) -> None:
        fingerprints = [
            _tuple_checksum(
                row["user"],
                row["relation"],
                row["object"],
            )
            for row in tuples
        ]
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(PermissionCatalogProjectionTuple)
                        .where(
                            PermissionCatalogProjectionTuple.catalog_release_id == release_id,
                            col(PermissionCatalogProjectionTuple.tuple_fingerprint).in_(fingerprints),
                        )
                        .values(status="WRITTEN", update_time=func.now())
                    )


class F048CatalogApi:
    """Translate HTTP-safe changes into complete, durable Catalog releases."""

    PRESETS: tuple[dict[str, object], ...] = (
        {
            "key": "collaborative_editing",
            "name": "协作编辑",
            "action_codes": (
                "download",
                "use",
                "rename",
                "edit",
                "create_folder",
                "upload_file",
                "move",
            ),
        },
        {
            "key": "permission_management",
            "name": "权限管理",
            "action_codes": (
                "download",
                "use",
                "manage_permission",
                "share",
            ),
        },
        {
            "key": "advanced_management",
            "name": "高级管理",
            "action_codes": DEFAULT_ACTION_CODES,
        },
    )

    def __init__(
        self,
        *,
        state: SqlCatalogState,
        service: CatalogService,
    ) -> None:
        self._state = state
        self._service = service
        self._impact = SqlCatalogImpact(session_factory=state._session_factory)

    async def get_current(self) -> dict:
        row = await self._state.current_release()
        snapshot = await self._state.load_snapshot(int(row.id))
        return await self._release_payload(snapshot, row=row)

    async def create_draft(
        self,
        *,
        request: CatalogDraftRequest,
        operator_id: int,
    ) -> dict:
        reservation = await self._state.reserve_draft(
            base_release_id=request.base_release_id,
            operator_id=operator_id,
            idempotency_key=request.idempotency_key,
            expires_at=_utc_now_naive() + timedelta(minutes=10),
        )
        before = await self._state.load_snapshot(reservation.predecessor_id)
        if before.action_release is None or before.model_release is None:
            raise PermissionPublishNotReadyError()
        actions, customs, standard_policy = await self._apply_change(
            request.change,
            before,
        )
        try:
            draft = await self._service.build_draft(
                CatalogDraftBuildInput(
                    release_id=reservation.release_id,
                    release_key=reservation.release_key,
                    predecessor_release_id=reservation.predecessor_id,
                    predecessor_release_key=reservation.predecessor_key,
                    before_actions=before.action_release,
                    before_models=before.model_release,
                    actions=actions,
                    custom_models=customs,
                    standard_allow_same_level=standard_policy,
                    grant_references=(await self._state.grant_references()),
                    draft_owner_id=operator_id,
                    idempotency_key=request.idempotency_key,
                    expires_at=_utc_now_naive() + timedelta(minutes=10),
                )
            )
        except (InvalidCatalogActionError, ImmutableStandardModelError):
            raise
        except ValueError as exc:
            raise InvalidCatalogActionError(
                exception=exc,
                msg=str(exc),
            ) from exc
        return await self._draft_payload(draft)

    async def get_draft(
        self,
        *,
        draft_id: int,
        operator_id: int,
    ) -> dict:
        del operator_id
        return await self._draft_payload(await self._state.load_snapshot(draft_id))

    async def publish_draft(
        self,
        *,
        draft_id: int,
        request: CatalogPublishRequest,
        operator_id: int,
    ) -> dict:
        del operator_id
        outcome = await self._service.publish(
            draft_id=draft_id,
            expected_current_release_id=(request.expected_current_release_id),
            idempotency_key=request.idempotency_key,
        )
        return {
            "release_id": outcome.release_id,
            "release_key": outcome.release_key,
            "status": outcome.status,
            "release_checksum": outcome.release_checksum,
        }

    async def _draft_payload(
        self,
        draft: CatalogDraftSnapshot,
    ) -> dict:
        impact = await self._impact.describe(draft)
        if impact.checksum != draft.impact_checksum:
            raise PermissionImpactExpiredError(msg="Catalog impact changed after draft creation")
        expires_at = draft.expires_at or (_utc_now_naive() + timedelta(minutes=10))
        return {
            "draft_id": draft.release_id,
            "base_release_id": draft.predecessor_release_id,
            "impact": {
                "checksum": impact.checksum,
                "resource_count": impact.resource_count,
                "grant_count": impact.grant_count,
                "assignee_count": impact.assignee_count,
                "expansion_count": impact.expansion_count,
                "revocation_count": impact.revocation_count,
                "blockers": sorted(set(draft.blockers) | set(impact.blockers)),
                "expires_at": _as_utc(expires_at).isoformat(),
            },
        }

    async def _release_payload(
        self,
        snapshot: CatalogDraftSnapshot,
        *,
        row: PermissionCatalogRelease,
    ) -> dict:
        if snapshot.action_release is None or snapshot.model_release is None:
            raise PermissionPublishNotReadyError()
        authorization = await self._state.authorization_release(snapshot.release_id)
        return {
            "id": snapshot.release_id,
            "release_key": snapshot.release_key,
            "version": row.version,
            "status": row.status,
            "authorization_model_id": authorization.model_id,
            "checksum": snapshot.release_checksum,
            "actions": [
                {
                    "code": action.code,
                    "name": action.name,
                    "level": action.level,
                    "active": action.active,
                    "sort_order": action.sort_order,
                    "resource_types": sorted(action.resource_types),
                }
                for action in snapshot.action_release.actions
            ],
            "models": [
                {
                    "key": model.model_key,
                    "name": model.name,
                    "kind": model.kind,
                    "config_scope": model.config_scope,
                    "derived_level": model.derived_level,
                    "active": model.active,
                    "allow_same_level": model.allow_same_level,
                    "action_codes": list(model.selected_action_codes),
                    "version": row.version,
                }
                for model in snapshot.model_release.models
            ],
            "presets": [
                {
                    **preset,
                    "action_codes": list(preset["action_codes"]),
                }
                for preset in self.PRESETS
            ],
            "published_at": (_as_utc(row.published_at).isoformat() if row.published_at is not None else None),
        }

    async def _apply_change(
        self,
        change: CatalogChangeRequest,
        before: CatalogDraftSnapshot,
    ) -> tuple[
        tuple[CatalogAction, ...],
        tuple[CustomModelSelection, ...],
        dict[str, bool],
    ]:
        assert before.action_release is not None
        assert before.model_release is not None
        actions = list(before.action_release.actions)
        custom_by_key = {
            model.model_key: CustomModelSelection(
                model_key=model.model_key,
                name=model.name,
                action_codes=model.selected_action_codes,
                active=model.active,
                allow_same_level=model.allow_same_level,
                config_scope=model.config_scope,
            )
            for model in before.model_release.models
            if model.kind == "CUSTOM"
        }
        standard_by_key = {model.model_key: model for model in before.model_release.models if model.kind == "STANDARD"}
        standard_policy = {key: model.allow_same_level for key, model in standard_by_key.items()}
        kind = change.type
        if kind in {
            CatalogChangeType.ASSIGN_ACTION_LEVEL,
            CatalogChangeType.SET_ACTION_ACTIVE,
        }:
            index = next(
                (index for index, action in enumerate(actions) if action.code == change.action_code),
                None,
            )
            if index is None:
                raise InvalidCatalogActionError()
            if kind == CatalogChangeType.ASSIGN_ACTION_LEVEL:
                actions[index] = replace(
                    actions[index],
                    level=(int(change.level) if change.level is not None else None),
                )
            elif change.active is None:
                raise InvalidCatalogActionError()
            else:
                actions[index] = replace(
                    actions[index],
                    active=change.active,
                )
        elif kind == CatalogChangeType.CREATE_MODEL:
            key = change.model_key or uuid4().hex
            if key in custom_by_key or key in standard_by_key or not change.name or not change.action_codes:
                raise PermissionModelStateConflictError()
            custom_by_key[key] = CustomModelSelection(
                model_key=key,
                name=change.name,
                action_codes=change.action_codes,
                active=change.active is not False,
                allow_same_level=bool(change.allow_same_level),
            )
        elif kind == CatalogChangeType.UPDATE_MODEL:
            model = self._custom_model(change.model_key, custom_by_key)
            custom_by_key[model.model_key] = replace(
                model,
                name=change.name if change.name is not None else model.name,
                action_codes=(change.action_codes if change.action_codes is not None else model.action_codes),
                active=(change.active if change.active is not None else model.active),
                allow_same_level=(
                    change.allow_same_level if change.allow_same_level is not None else model.allow_same_level
                ),
            )
        elif kind == CatalogChangeType.SET_MODEL_ACTIVE:
            if change.active is None:
                raise PermissionModelStateConflictError()
            model = self._custom_model(change.model_key, custom_by_key)
            custom_by_key[model.model_key] = replace(
                model,
                active=change.active,
            )
        elif kind == CatalogChangeType.DELETE_MODEL:
            model = self._custom_model(change.model_key, custom_by_key)
            derived = next(item for item in before.model_release.models if item.model_key == model.model_key)
            references = await self._state.grant_references()
            try:
                ensure_model_deletable(
                    derived,
                    reference_count=len(references.get(model.model_key, ())),
                )
            except ValueError as exc:
                raise PermissionModelStateConflictError(
                    exception=exc,
                    msg=str(exc),
                ) from exc
            del custom_by_key[model.model_key]
        elif kind == CatalogChangeType.SET_ALLOW_SAME_LEVEL:
            if change.allow_same_level is None or not change.model_key:
                raise PermissionModelStateConflictError()
            if change.model_key in standard_by_key:
                standard_policy[change.model_key] = change.allow_same_level
            else:
                model = self._custom_model(
                    change.model_key,
                    custom_by_key,
                )
                custom_by_key[model.model_key] = replace(
                    model,
                    allow_same_level=change.allow_same_level,
                )
        else:
            raise InvalidCatalogActionError()
        try:
            action_release = derive_action_release(actions)
            derive_permission_models(
                action_release,
                custom_models=custom_by_key.values(),
                standard_allow_same_level=standard_policy,
            )
        except ValueError as exc:
            if change.model_key in standard_by_key and kind not in {CatalogChangeType.SET_ALLOW_SAME_LEVEL}:
                raise ImmutableStandardModelError(
                    exception=exc,
                    msg=str(exc),
                ) from exc
            raise InvalidCatalogActionError(
                exception=exc,
                msg=str(exc),
            ) from exc
        return (
            tuple(actions),
            tuple(custom_by_key[key] for key in sorted(custom_by_key)),
            standard_policy,
        )

    @staticmethod
    def _custom_model(
        model_key: str | None,
        models: dict[str, CustomModelSelection],
    ) -> CustomModelSelection:
        if not model_key or model_key not in models:
            raise ImmutableStandardModelError(msg="Only custom models support this operation")
        return models[model_key]
