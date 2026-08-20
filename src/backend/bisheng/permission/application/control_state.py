"""SQL state adapters for F048 grants, modes, owners, and explanations."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import update
from sqlmodel import col, select

from bisheng.common.errcode.permission import (
    PermissionModelStateConflictError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.sql_runtime import (
    stable_assignee_id,
    stable_grant_key,
)
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import (
    VerifiedPermissionTarget,
    VisibleSourceProjectionDTO,
)
from bisheng.permission.domain.services.grant_service import (
    GrantMutationContext,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.mode_service import (
    ModeContext,
    PermissionModeDraft,
)
from bisheng.permission.domain.services.owner_service import (
    OwnerProjectionContext,
)
from bisheng.permission.domain.services.permission_explain_service import (
    InheritedGrantSet,
    PermissionSourceExplanation,
)
from bisheng.permission.domain.services.projection_plan import ProjectionOutcome
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompilation,
)


@dataclass(frozen=True, slots=True)
class RuntimeModelSnapshot:
    snapshot: GrantModelSnapshot
    name: str
    kind: str
    version: int


@dataclass(frozen=True, slots=True)
class RuntimeCatalogSnapshot:
    release_id: int
    release_key: str
    version: int
    checksum: str
    store_id: str
    model_id: str
    model_checksum: str
    models: tuple[RuntimeModelSnapshot, ...]


class SqlPermissionControlState:
    """Own all permission-table reads/writes needed by online services."""

    async def current_catalog(self) -> RuntimeCatalogSnapshot:
        async with get_async_db_session() as session:
            release_rows = list(
                (
                    await session.execute(
                        select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                    )
                )
                .scalars()
                .all()
            )
            if len(release_rows) != 1:
                raise PermissionPublishNotReadyError(msg="Permission Catalog must have exactly one CURRENT release")
            release = release_rows[0]
            if release.id is None or release.write_fenced:
                raise PermissionPublishNotReadyError()
            authorization_release = await session.get(
                AuthorizationModelRelease,
                release.required_authorization_model_release_id,
            )
            if authorization_release is None or authorization_release.status != "ACTIVE":
                raise PermissionPublishNotReadyError(msg="CURRENT Catalog authorization model is not active")
            model_rows = list(
                (
                    await session.execute(
                        select(PermissionModel)
                        .where(PermissionModel.catalog_release_id == release.id)
                        .order_by(PermissionModel.model_key)
                    )
                )
                .scalars()
                .all()
            )
            model_ids = [int(row.id) for row in model_rows if row.id is not None]
            action_pairs = (
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
                            .where(
                                col(PermissionModelAction.model_id).in_(model_ids),
                                PermissionAction.active == 1,
                            )
                        )
                    ).all()
                )
                if model_ids
                else []
            )
        actions: dict[int, list[str]] = {}
        for model_id, action_code in action_pairs:
            actions.setdefault(int(model_id), []).append(str(action_code))
        models = tuple(
            RuntimeModelSnapshot(
                snapshot=GrantModelSnapshot(
                    model_key=row.model_key,
                    active=bool(row.active),
                    action_codes=tuple(sorted(actions.get(int(row.id or 0), ()))),
                    derived_level=row.derived_level,
                    allow_same_level=bool(row.allow_same_level),
                ),
                name=row.name,
                kind=row.kind,
                version=release.version,
            )
            for row in model_rows
        )
        return RuntimeCatalogSnapshot(
            release_id=int(release.id),
            release_key=release.release_key,
            version=release.version,
            checksum=release.checksum,
            store_id=authorization_release.store_id,
            model_id=authorization_release.model_id,
            model_checksum=authorization_release.model_checksum,
            models=models,
        )

    async def mode_for_target(
        self,
        target: VerifiedPermissionTarget,
        *,
        for_update: bool = False,
    ) -> ResourcePermissionMode:
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == target.tenant_id,
                ResourcePermissionMode.resource_type == target.resource_type,
                ResourcePermissionMode.resource_id == target.resource_id,
            )
            if for_update:
                statement = statement.with_for_update()
            row = (await session.execute(statement)).scalars().first()
        if row is None:
            raise PermissionPublishNotReadyError(msg="Resource permission mode is missing")
        return row

    async def permission_version(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
    ) -> tuple[int, str]:
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == tenant_id,
                ResourcePermissionMode.resource_type == resource_type,
                ResourcePermissionMode.resource_id == resource_id,
            )
            row = (await session.execute(statement)).scalars().first()
        if row is None or row.projection_state != "CURRENT":
            raise PermissionPublishNotReadyError(msg="Resource permission projection is not current")
        context = "|".join(
            (
                str(row.version),
                row.mode,
                row.parent_type or "",
                row.parent_id or "",
                row.projection_state,
            )
        )
        return row.version, context[:64]

    async def load_grants(
        self,
        *,
        target: VerifiedPermissionTarget,
        models: tuple[GrantModelSnapshot, ...],
    ) -> tuple[GrantSnapshot, ...]:
        async with get_async_db_session() as session:
            grant_rows = list(
                (
                    await session.execute(
                        select(PermissionGrant)
                        .where(
                            PermissionGrant.tenant_id == target.tenant_id,
                            PermissionGrant.resource_type == target.resource_type,
                            PermissionGrant.resource_id == target.resource_id,
                        )
                        .order_by(PermissionGrant.model_key)
                    )
                )
                .scalars()
                .all()
            )
            grant_ids = [int(row.id) for row in grant_rows if row.id is not None]
            assignee_rows = (
                list(
                    (
                        await session.execute(
                            select(PermissionGrantAssignee)
                            .where(
                                col(PermissionGrantAssignee.grant_id).in_(grant_ids),
                                PermissionGrantAssignee.state == "ACTIVE",
                            )
                            .order_by(PermissionGrantAssignee.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                if grant_ids
                else []
            )
        by_grant: dict[int, list[PermissionGrantAssignee]] = {}
        for row in assignee_rows:
            by_grant.setdefault(int(row.grant_id), []).append(row)
        db_by_model = {row.model_key: row for row in grant_rows}
        result: list[GrantSnapshot] = []
        for model in models:
            row = db_by_model.get(model.model_key)
            sources = (
                tuple(self._source_snapshot(source) for source in by_grant.get(int(row.id or 0), ()))
                if row is not None
                else ()
            )
            result.append(
                GrantSnapshot(
                    grant_id=stable_grant_key(
                        tenant_id=target.tenant_id,
                        resource_type=target.resource_type,
                        resource_id=target.resource_id,
                        model_key=model.model_key,
                    ),
                    tenant_id=target.tenant_id,
                    resource_type=target.resource_type,
                    resource_id=target.resource_id,
                    model=model,
                    active=(row is not None and row.state == "ACTIVE" and bool(sources)),
                    version=row.version if row is not None else 0,
                    sources=sources,
                )
            )
        return tuple(result)

    async def load_visible_sources(
        self,
        *,
        target: VerifiedPermissionTarget,
    ) -> tuple[VisibleSourceProjectionDTO, ...]:
        """Load the complete active contribution set for one resource scope."""

        async with get_async_db_session() as session:
            rows = list(
                (
                    await session.execute(
                        select(PermissionVisibleSourceProjection)
                        .where(
                            PermissionVisibleSourceProjection.tenant_id == target.tenant_id,
                            PermissionVisibleSourceProjection.resource_type == target.resource_type,
                            PermissionVisibleSourceProjection.resource_id == target.resource_id,
                            PermissionVisibleSourceProjection.state == "ACTIVE",
                        )
                        .order_by(PermissionVisibleSourceProjection.id)
                    )
                )
                .scalars()
                .all()
            )
        return tuple(self._visible_source_snapshot(row) for row in rows)

    async def inherited_grants(
        self,
        *,
        target: VerifiedPermissionTarget,
        models: tuple[GrantModelSnapshot, ...],
    ) -> tuple[GrantSnapshot, ...]:
        inherited = await self.inherited_grant_set(
            target=target,
            models=models,
        )
        return inherited.grants if inherited is not None else ()

    async def inherited_grant_set(
        self,
        *,
        target: VerifiedPermissionTarget,
        models: tuple[GrantModelSnapshot, ...],
    ) -> InheritedGrantSet | None:
        if target.parent_type is None or target.parent_id is None:
            return None
        async with get_async_db_session() as session:
            ancestor_mode = await self._nearest_custom_ancestor_mode(
                session,
                tenant_id=target.tenant_id,
                resource_type=target.parent_type,
                resource_id=target.parent_id,
            )
        ancestor_target = VerifiedPermissionTarget.from_business_service(
            tenant_id=target.tenant_id,
            resource_type=ancestor_mode.resource_type,
            resource_id=ancestor_mode.resource_id,
            resource_version=ancestor_mode.version,
            context_version=(f"{ancestor_mode.version}:{ancestor_mode.projection_state}"),
            parent_type=ancestor_mode.parent_type,
            parent_id=ancestor_mode.parent_id,
        )
        return InheritedGrantSet(
            resource_type=ancestor_mode.resource_type,
            resource_id=ancestor_mode.resource_id,
            grants=await self.load_grants(
                target=ancestor_target,
                models=models,
            ),
        )

    async def load_source_page(
        self,
        *,
        target: VerifiedPermissionTarget,
        mode: str,
        models: tuple[GrantModelSnapshot, ...],
        after_id: int,
        limit: int,
    ) -> tuple[tuple[PermissionSourceExplanation, ...], bool]:
        """Read at most one bounded roster page from permission-owned tables."""

        if after_id < 0 or limit <= 0:
            raise ValueError("Permission source cursor bounds are invalid")
        normalized_mode = mode.upper()
        model_by_key = {model.model_key: model for model in models if model.active}
        if not model_by_key:
            return (), False
        fetch_limit = limit + 1
        inherited_mode: ResourcePermissionMode | None = None
        async with get_async_db_session() as session:
            local_rows = await self._source_rows(
                session,
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                model_keys=tuple(model_by_key),
                after_id=after_id,
                limit=fetch_limit,
                protected_only=normalized_mode == "INHERIT",
            )
            inherited_rows = []
            if normalized_mode == "INHERIT" and target.parent_type is not None and target.parent_id is not None:
                inherited_mode = await self._nearest_custom_ancestor_mode(
                    session,
                    tenant_id=target.tenant_id,
                    resource_type=target.parent_type,
                    resource_id=target.parent_id,
                )
                inherited_rows = await self._source_rows(
                    session,
                    tenant_id=target.tenant_id,
                    resource_type=inherited_mode.resource_type,
                    resource_id=inherited_mode.resource_id,
                    model_keys=tuple(model_by_key),
                    after_id=after_id,
                    limit=fetch_limit,
                    protected_only=False,
                )
                # The parent's creator carries no authority here — this resource
                # has its own protected creator row, and the inherited copy only
                # showed up as a second, identical entry that cannot be acted on.
                inherited_rows = [(row, model_key) for row, model_key in inherited_rows if row.source_type != "CREATOR"]
        combined = sorted(
            (
                *((row, model_key, "LOCAL") for row, model_key in local_rows),
                *((row, model_key, "INHERITED") for row, model_key in inherited_rows),
            ),
            key=lambda item: (int(item[0].id or 0), item[1], item[2]),
        )
        selected = combined[:limit]
        inherited_from = (
            f"{inherited_mode.resource_type}:{inherited_mode.resource_id}" if inherited_mode is not None else None
        )
        return (
            tuple(
                PermissionSourceExplanation(
                    source_id=int(row.id or 0),
                    source_version=row.version,
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    userset_relation=row.userset_relation,
                    include_children=bool(row.include_children),
                    source_type=row.source_type,
                    model_key=model_key,
                    model_level=model_by_key[model_key].derived_level,
                    scope=scope,
                    inherited_from=(inherited_from if scope == "INHERITED" else None),
                    protected=bool(row.protected),
                    editable=(scope == "LOCAL" and normalized_mode == "CUSTOM" and not row.protected),
                )
                for row, model_key, scope in selected
            ),
            len(combined) > limit,
        )

    @staticmethod
    async def _source_rows(
        session,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        model_keys: tuple[str, ...],
        after_id: int,
        limit: int,
        protected_only: bool,
    ) -> list[tuple[PermissionGrantAssignee, str]]:
        statement = (
            select(
                PermissionGrantAssignee,
                PermissionGrant.model_key,
            )
            .join(
                PermissionGrant,
                PermissionGrant.id == PermissionGrantAssignee.grant_id,
            )
            .where(
                PermissionGrant.tenant_id == tenant_id,
                PermissionGrant.resource_type == resource_type,
                PermissionGrant.resource_id == resource_id,
                PermissionGrant.model_key.in_(model_keys),
                PermissionGrant.state == "ACTIVE",
                PermissionGrant.projection_state == "CURRENT",
                PermissionGrantAssignee.tenant_id == tenant_id,
                PermissionGrantAssignee.state == "ACTIVE",
                PermissionGrantAssignee.id > after_id,
            )
            .order_by(
                PermissionGrantAssignee.id,
                PermissionGrant.model_key,
            )
            .limit(limit)
        )
        if protected_only:
            statement = statement.where(PermissionGrantAssignee.protected == 1)
        return [(row, str(model_key)) for row, model_key in (await session.execute(statement)).all()]

    async def ensure_mode_row(
        self,
        *,
        target: VerifiedPermissionTarget,
        mode: str,
    ) -> ResourcePermissionMode:
        async with get_async_db_session() as session:
            async with session.begin():
                await self._assert_catalog_writable(session)
                return await self._ensure_mode_row_in_session(
                    session,
                    target=target,
                    mode=mode,
                )

    async def owner_grant(
        self,
        *,
        target: VerifiedPermissionTarget,
        owner_user_id: int,
        source_service: GrantSourceService,
        owner_model: GrantModelSnapshot,
    ) -> tuple[GrantSnapshot, int]:
        grant_key = stable_grant_key(
            tenant_id=target.tenant_id,
            resource_type=target.resource_type,
            resource_id=target.resource_id,
            model_key=owner_model.model_key,
        )
        provisional = source_service.canonicalize_source(
            source_id=1,
            subject_type="user",
            subject_id=str(owner_user_id),
            source_type="CREATOR",
            source_ref=f"{target.resource_type}:{target.resource_id}",
            protected=True,
        )
        source_id = stable_assignee_id(
            grant_key=grant_key,
            source_fingerprint=provisional.source_fingerprint,
        )
        grants = await self.load_grants(
            target=target,
            models=(owner_model,),
        )
        grant = grants[0]
        existing = next(
            (source for source in grant.sources if source.source_fingerprint == provisional.source_fingerprint),
            None,
        )
        return grant, existing.source_id if existing is not None else source_id

    async def prepare_owner(
        self,
        context: OwnerProjectionContext,
        grant: GrantSnapshot | None,
        source: GrantSourceRecord | None,
        visibility: VisibilityProjectionCompilation | None,
        *,
        operation_id: int,
    ) -> None:
        mode = context.permission_mode or (
            "INHERIT" if context.target.resource_type in {"folder", "knowledge_file"} else "CUSTOM"
        )
        projection_grants = self._owner_projection_grants(
            context,
            grant,
        )
        async with get_async_db_session() as session:
            async with session.begin():
                await self._assert_catalog_writable(session)
                mode_row = await self._ensure_mode_row_in_session(
                    session,
                    target=context.target,
                    mode=mode,
                )
                self._claim_projection_operation(
                    mode_row,
                    expected_version=context.target.resource_version,
                    operation_id=operation_id,
                    allowed_initial_states=("PENDING",),
                )
                for projection_grant in projection_grants:
                    grant_row = await self._upsert_grant(
                        session,
                        grant=projection_grant,
                        state="PENDING",
                        projection_state="PROJECTING",
                    )
                    for projection_source in projection_grant.sources:
                        await self._upsert_assignee(
                            session,
                            grant_row=grant_row,
                            source=projection_source,
                            state="PENDING",
                        )
                if visibility is not None:
                    await self._prepare_visible_sources(
                        session,
                        tenant_id=context.target.tenant_id,
                        visibility=visibility,
                        operation_id=operation_id,
                    )

    async def finalize_owner(
        self,
        context: OwnerProjectionContext,
        grant: GrantSnapshot | None,
        visibility: VisibilityProjectionCompilation | None,
        outcome: ProjectionOutcome,
    ) -> None:
        projection_grants = self._owner_projection_grants(
            context,
            grant,
        )
        if not projection_grants and visibility is None:
            return
        async with get_async_db_session() as session:
            async with session.begin():
                for projection_grant in projection_grants:
                    grant_row = await self._grant_row(
                        session,
                        tenant_id=context.target.tenant_id,
                        resource_type=context.target.resource_type,
                        resource_id=context.target.resource_id,
                        model_key=projection_grant.model.model_key,
                    )
                    if grant_row is None or grant_row.id is None:
                        raise PermissionVersionConflictError(msg=("Owner/copy Grant disappeared before finalize"))
                    await session.execute(
                        update(PermissionGrant)
                        .where(PermissionGrant.id == grant_row.id)
                        .values(
                            state="ACTIVE",
                            projection_state="CURRENT",
                        )
                    )
                    await session.execute(
                        update(PermissionGrantAssignee)
                        .where(
                            PermissionGrantAssignee.grant_id == grant_row.id,
                            PermissionGrantAssignee.state == "PENDING",
                        )
                        .values(state="ACTIVE")
                    )
                if visibility is not None:
                    await self._finalize_visible_sources(
                        session,
                        tenant_id=context.target.tenant_id,
                        visibility=visibility,
                        operation_id=outcome.operation_id,
                    )

    async def mark_owner_compensation(
        self,
        context: OwnerProjectionContext,
        error: Exception,
    ) -> None:
        del error
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(ResourcePermissionMode)
                    .where(
                        ResourcePermissionMode.tenant_id == context.target.tenant_id,
                        ResourcePermissionMode.resource_type == context.target.resource_type,
                        ResourcePermissionMode.resource_id == context.target.resource_id,
                    )
                    .values(projection_state="FAILED_CLOSED")
                )
                await session.execute(
                    update(PermissionGrant)
                    .where(
                        PermissionGrant.tenant_id == context.target.tenant_id,
                        PermissionGrant.resource_type == context.target.resource_type,
                        PermissionGrant.resource_id == context.target.resource_id,
                    )
                    .values(projection_state="FAILED_CLOSED")
                )

    async def prepare_grants(
        self,
        context: GrantMutationContext,
        grants: tuple[GrantSnapshot, ...],
        visibility: VisibilityProjectionCompilation | None,
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None:
        del idempotency_key
        async with get_async_db_session() as session:
            async with session.begin():
                await self._assert_catalog_writable(
                    session,
                    expected_release_id=(context.current_catalog_release_id),
                )
                mode_row = await self._mode_row(
                    session,
                    target=context.target,
                )
                if mode_row is None:
                    raise PermissionVersionConflictError()
                self._claim_projection_operation(
                    mode_row,
                    expected_version=context.target.resource_version,
                    operation_id=operation_id,
                    allowed_initial_states=("CURRENT",),
                )
                for grant in grants:
                    grant_row = await self._upsert_grant(
                        session,
                        grant=grant,
                        state=("PENDING" if grant.active else "INACTIVE"),
                        projection_state="PROJECTING",
                    )
                    active_source_ids = {source.source_id for source in grant.sources if source.active}
                    for source in grant.sources:
                        await self._upsert_assignee(
                            session,
                            grant_row=grant_row,
                            source=source,
                            state="PENDING",
                        )
                    if grant_row.id is not None:
                        await session.execute(
                            update(PermissionGrantAssignee)
                            .where(
                                PermissionGrantAssignee.grant_id == grant_row.id,
                                PermissionGrantAssignee.state == "ACTIVE",
                                col(PermissionGrantAssignee.id).not_in(active_source_ids or {-1}),
                            )
                            .values(state="PENDING_DELETE")
                        )
                if visibility is not None:
                    await self._prepare_visible_sources(
                        session,
                        tenant_id=context.target.tenant_id,
                        visibility=visibility,
                        operation_id=operation_id,
                    )

    async def finalize_grants(
        self,
        context: GrantMutationContext,
        grants: tuple[GrantSnapshot, ...],
        visibility: VisibilityProjectionCompilation | None,
        outcome: ProjectionOutcome,
    ) -> None:
        async with get_async_db_session() as session:
            async with session.begin():
                for grant in grants:
                    row = await self._grant_row(
                        session,
                        tenant_id=context.target.tenant_id,
                        resource_type=context.target.resource_type,
                        resource_id=context.target.resource_id,
                        model_key=grant.model.model_key,
                    )
                    if row is None or row.id is None:
                        continue
                    await session.execute(
                        update(PermissionGrant)
                        .where(PermissionGrant.id == row.id)
                        .values(
                            state=("ACTIVE" if grant.active else "INACTIVE"),
                            projection_state="CURRENT",
                        )
                    )
                    await session.execute(
                        update(PermissionGrantAssignee)
                        .where(
                            PermissionGrantAssignee.grant_id == row.id,
                            PermissionGrantAssignee.state == "PENDING",
                        )
                        .values(state="ACTIVE")
                    )
                    await session.execute(
                        update(PermissionGrantAssignee)
                        .where(
                            PermissionGrantAssignee.grant_id == row.id,
                            PermissionGrantAssignee.state == "PENDING_DELETE",
                        )
                        .values(
                            state="INACTIVE",
                            version=PermissionGrantAssignee.version + 1,
                        )
                    )
                if visibility is not None:
                    await self._finalize_visible_sources(
                        session,
                        tenant_id=context.target.tenant_id,
                        visibility=visibility,
                        operation_id=outcome.operation_id,
                    )

    async def allocate_source_ids(self, count: int) -> tuple[int, ...]:
        if count < 0:
            raise ValueError("source count must not be negative")
        if count == 0:
            return ()
        # IDs are persisted inside the draft and remain stable for every apply
        # retry. Random allocation avoids racing MAX(id)+1 across concurrent
        # draft creators; the database remains the final collision guard.
        while True:
            candidates = tuple(dict.fromkeys(secrets.randbits(62) or 1 for _ in range(count)))
            if len(candidates) != count:
                continue
            async with get_async_db_session() as session:
                existing = set(
                    (
                        await session.execute(
                            select(PermissionGrantAssignee.id).where(col(PermissionGrantAssignee.id).in_(candidates))
                        )
                    )
                    .scalars()
                    .all()
                )
            if not existing:
                return candidates

    async def save_mode_draft(self, draft: PermissionModeDraft) -> None:
        redis = await self._redis()
        await redis.aset(
            self._draft_key(draft.draft_id),
            draft,
            expiration=600,
        )

    async def get_mode_draft(
        self,
        draft_id: str,
    ) -> PermissionModeDraft | None:
        redis = await self._redis()
        value = await redis.aget(self._draft_key(draft_id))
        return value if isinstance(value, PermissionModeDraft) else None

    async def prepare_mode(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        grants: tuple[GrantSnapshot, ...],
        visibility: VisibilityProjectionCompilation,
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None:
        grant_context = GrantMutationContext(
            target=context.target,
            current_catalog_release_id=context.current_catalog_release_id,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            mode=context.mode,
            system_authorized=False,
            capabilities=(),
            models=tuple(grant.model for grant in grants),
            grants=context.local_grants,
        )
        await self.prepare_grants(
            grant_context,
            grants,
            visibility,
            idempotency_key=idempotency_key,
            operation_id=operation_id,
        )

    async def finalize_mode(
        self,
        context: ModeContext,
        draft: PermissionModeDraft,
        grants: tuple[GrantSnapshot, ...],
        visibility: VisibilityProjectionCompilation,
        outcome: ProjectionOutcome,
    ) -> None:
        grant_context = GrantMutationContext(
            target=context.target,
            current_catalog_release_id=context.current_catalog_release_id,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            mode=draft.target_mode,
            system_authorized=False,
            capabilities=(),
            models=tuple(grant.model for grant in grants),
            grants=grants,
        )
        await self.finalize_grants(grant_context, grants, visibility, outcome)
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(ResourcePermissionMode)
                    .where(
                        ResourcePermissionMode.tenant_id == context.target.tenant_id,
                        ResourcePermissionMode.resource_type == context.target.resource_type,
                        ResourcePermissionMode.resource_id == context.target.resource_id,
                        ResourcePermissionMode.version == outcome.target_version,
                    )
                    .values(mode=draft.target_mode)
                )
        redis = await self._redis()
        await redis.adelete(self._draft_key(draft.draft_id))

    async def mark_projecting(
        self,
        *,
        target: VerifiedPermissionTarget,
        operation_id: int,
        parent_type: str | None = None,
        parent_id: str | None = None,
        expected_catalog_release_id: int | None = None,
    ) -> None:
        async with get_async_db_session() as session:
            async with session.begin():
                await self._assert_catalog_writable(
                    session,
                    expected_release_id=expected_catalog_release_id,
                )
                mode_row = await self._mode_row(
                    session,
                    target=target,
                )
                if mode_row is None:
                    raise PermissionVersionConflictError()
                self._claim_projection_operation(
                    mode_row,
                    expected_version=target.resource_version,
                    operation_id=operation_id,
                    allowed_initial_states=("CURRENT",),
                )
                if parent_type is not None and parent_id is not None:
                    mode_row.parent_type = parent_type
                    mode_row.parent_id = parent_id

    @staticmethod
    async def _assert_catalog_writable(
        session,
        *,
        expected_release_id: int | None = None,
    ) -> PermissionCatalogRelease:
        rows = list(
            (
                await session.execute(
                    select(PermissionCatalogRelease)
                    .where(PermissionCatalogRelease.status == "CURRENT")
                    .with_for_update()
                )
            ).scalars()
        )
        if (
            len(rows) != 1
            or rows[0].write_fenced
            or (expected_release_id is not None and rows[0].id != expected_release_id)
        ):
            raise PermissionPublishNotReadyError(msg="Permission Catalog is fenced or changed")
        return rows[0]

    @staticmethod
    async def _ensure_mode_row_in_session(
        session,
        *,
        target: VerifiedPermissionTarget,
        mode: str,
    ) -> ResourcePermissionMode:
        statement = (
            select(ResourcePermissionMode)
            .where(
                ResourcePermissionMode.tenant_id == target.tenant_id,
                ResourcePermissionMode.resource_type == target.resource_type,
                ResourcePermissionMode.resource_id == target.resource_id,
            )
            .with_for_update()
        )
        row = (await session.execute(statement)).scalars().first()
        if row is None:
            row = ResourcePermissionMode(
                tenant_id=target.tenant_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                mode=mode,
                parent_type=target.parent_type,
                parent_id=target.parent_id,
                version=0,
                projection_state="PENDING",
            )
            session.add(row)
            await session.flush()
        elif (
            row.version != target.resource_version
            or row.mode != mode
            or row.parent_type != target.parent_type
            or row.parent_id != target.parent_id
        ):
            raise PermissionVersionConflictError(msg="Resource permission create state already differs")
        return row

    @staticmethod
    def _claim_projection_operation(
        row: ResourcePermissionMode,
        *,
        expected_version: int,
        operation_id: int,
        allowed_initial_states: tuple[str, ...],
    ) -> None:
        if operation_id <= 0 or row.version != expected_version:
            raise PermissionVersionConflictError(msg="Resource permission version changed before projection")
        if row.projection_state == "PROJECTING" and row.operation_id == operation_id:
            return
        if row.projection_state not in allowed_initial_states:
            raise PermissionVersionConflictError(msg="Resource permission projection is already reserved")
        row.projection_state = "PROJECTING"
        row.operation_id = operation_id

    @staticmethod
    def _source_snapshot(
        row: PermissionGrantAssignee,
    ) -> GrantSourceRecord:
        return GrantSourceRecord(
            source_id=int(row.id or 0),
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            userset_relation=row.userset_relation,
            include_children=bool(row.include_children),
            source_type=row.source_type,
            source_ref=row.source_ref,
            source_locator=row.source_locator,
            source_fingerprint=row.source_fingerprint,
            projected_subject=row.projected_subject,
            protected=bool(row.protected),
            active=row.state == "ACTIVE",
            version=row.version,
        )

    @staticmethod
    def _visible_source_snapshot(
        row: PermissionVisibleSourceProjection,
    ) -> VisibleSourceProjectionDTO:
        return VisibleSourceProjectionDTO(
            tenant_id=int(row.tenant_id or 0),
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            visibility_class=row.visibility_class,
            projected_subject=row.projected_subject,
            source_kind=row.source_kind,
            source_owner_key=row.source_owner_key,
            source_locator=row.source_locator,
            source_fingerprint=row.source_fingerprint,
            contribution_fingerprint=row.contribution_fingerprint,
            model_key=row.model_key,
            source_version=row.source_version,
            tuple_fingerprint=row.tuple_fingerprint,
            state=row.state,
            operation_id=row.operation_id,
            migration_item_id=row.migration_item_id,
        )

    @staticmethod
    def _owner_projection_grants(
        context: OwnerProjectionContext,
        owner_grant: GrantSnapshot | None,
    ) -> tuple[GrantSnapshot, ...]:
        if not context.copy_grants:
            return (owner_grant,) if owner_grant is not None else ()
        by_model = {grant.model.model_key: grant for grant in context.copy_grants}
        if owner_grant is not None:
            by_model[owner_grant.model.model_key] = owner_grant
        return tuple(by_model[key] for key in sorted(by_model) if by_model[key].active and by_model[key].sources)

    @staticmethod
    async def _nearest_custom_ancestor_mode(
        session,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
    ) -> ResourcePermissionMode:
        current = (resource_type, resource_id)
        visited: set[tuple[str, str]] = set()
        while current not in visited:
            visited.add(current)
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == tenant_id,
                ResourcePermissionMode.resource_type == current[0],
                ResourcePermissionMode.resource_id == current[1],
                ResourcePermissionMode.projection_state == "CURRENT",
            )
            row = (await session.execute(statement)).scalars().first()
            if row is None:
                raise PermissionPublishNotReadyError(msg="Inherited permission scope is not current")
            normalized_mode = row.mode.upper()
            if normalized_mode == "CUSTOM":
                return row
            if normalized_mode != "INHERIT" or row.parent_type is None or row.parent_id is None:
                raise PermissionPublishNotReadyError(msg="Inherited permission chain has no custom ancestor")
            current = (row.parent_type, row.parent_id)
        raise PermissionPublishNotReadyError(msg="Inherited permission chain contains a cycle")

    @staticmethod
    async def _mode_row(session, *, target):
        return (
            (
                await session.execute(
                    select(ResourcePermissionMode)
                    .where(
                        ResourcePermissionMode.tenant_id == target.tenant_id,
                        ResourcePermissionMode.resource_type == target.resource_type,
                        ResourcePermissionMode.resource_id == target.resource_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    async def _grant_row(
        session,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        model_key: str,
    ):
        return (
            (
                await session.execute(
                    select(PermissionGrant).where(
                        PermissionGrant.tenant_id == tenant_id,
                        PermissionGrant.resource_type == resource_type,
                        PermissionGrant.resource_id == resource_id,
                        PermissionGrant.model_key == model_key,
                    )
                )
            )
            .scalars()
            .first()
        )

    async def _upsert_grant(
        self,
        session,
        *,
        grant: GrantSnapshot,
        state: str,
        projection_state: str,
    ) -> PermissionGrant:
        row = await self._grant_row(
            session,
            tenant_id=grant.tenant_id,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            model_key=grant.model.model_key,
        )
        if row is None:
            row = PermissionGrant(
                tenant_id=grant.tenant_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                model_key=grant.model.model_key,
                state=state,
                version=max(grant.version, 1),
                projection_state=projection_state,
            )
            session.add(row)
            await session.flush()
        else:
            row.state = state
            row.projection_state = projection_state
        return row

    @staticmethod
    async def _prepare_visible_sources(
        session,
        *,
        tenant_id: int,
        visibility: VisibilityProjectionCompilation,
        operation_id: int,
    ) -> None:
        desired = (*visibility.active_sources, *visibility.retired_sources)
        for source in desired:
            row = (
                (
                    await session.execute(
                        select(PermissionVisibleSourceProjection)
                        .where(
                            PermissionVisibleSourceProjection.tenant_id == tenant_id,
                            PermissionVisibleSourceProjection.resource_type == source.resource_type,
                            PermissionVisibleSourceProjection.resource_id == source.resource_id,
                            PermissionVisibleSourceProjection.visibility_class == source.visibility_class,
                            PermissionVisibleSourceProjection.projected_subject == source.projected_subject,
                            PermissionVisibleSourceProjection.contribution_fingerprint
                            == source.contribution_fingerprint,
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = PermissionVisibleSourceProjection(
                    tenant_id=tenant_id,
                    resource_type=source.resource_type,
                    resource_id=source.resource_id,
                    visibility_class=source.visibility_class,
                    projected_subject=source.projected_subject,
                    source_kind=source.source_kind,
                    source_owner_key=source.source_owner_key,
                    source_locator=source.source_locator,
                    source_fingerprint=source.source_fingerprint,
                    contribution_fingerprint=source.contribution_fingerprint,
                    model_key=source.model_key,
                    source_version=source.source_version,
                    tuple_fingerprint=source.tuple_fingerprint,
                    state="PENDING",
                    operation_id=operation_id,
                    migration_item_id=source.migration_item_id,
                )
                session.add(row)
                continue

            immutable_fields = (
                "resource_type",
                "resource_id",
                "visibility_class",
                "projected_subject",
                "source_kind",
                "source_owner_key",
                "source_locator",
                "source_fingerprint",
                "contribution_fingerprint",
                "model_key",
                "tuple_fingerprint",
            )
            if any(getattr(row, field) != getattr(source, field) for field in immutable_fields):
                raise PermissionVersionConflictError(
                    msg="Visible source contribution fingerprint collision",
                )
            if source.source_version < row.source_version:
                raise PermissionVersionConflictError(msg="Visible source version is stale")
            row.source_version = source.source_version
            row.state = "PENDING"
            row.operation_id = operation_id
            session.add(row)

        await session.flush()

    @staticmethod
    async def _finalize_visible_sources(
        session,
        *,
        tenant_id: int,
        visibility: VisibilityProjectionCompilation,
        operation_id: int,
    ) -> None:
        for sources, state in (
            (visibility.active_sources, "ACTIVE"),
            (visibility.retired_sources, "RETIRED"),
        ):
            fingerprints = tuple(source.contribution_fingerprint for source in sources)
            if not fingerprints:
                continue
            result = await session.execute(
                update(PermissionVisibleSourceProjection)
                .where(
                    PermissionVisibleSourceProjection.tenant_id == tenant_id,
                    PermissionVisibleSourceProjection.operation_id == operation_id,
                    col(PermissionVisibleSourceProjection.contribution_fingerprint).in_(fingerprints),
                    col(PermissionVisibleSourceProjection.state).in_(("PENDING", state)),
                )
                .values(state=state)
            )
            if result.rowcount != len(fingerprints):
                raise PermissionVersionConflictError(
                    msg="Visible source after-state changed before projection finalize",
                )

    @staticmethod
    async def _upsert_assignee(
        session,
        *,
        grant_row: PermissionGrant,
        source: GrantSourceRecord,
        state: str,
    ) -> PermissionGrantAssignee:
        if grant_row.id is None:
            raise PermissionVersionConflictError(msg="Grant row has no persistent identity")
        row = (
            (
                await session.execute(
                    select(PermissionGrantAssignee).where(
                        PermissionGrantAssignee.tenant_id == grant_row.tenant_id,
                        PermissionGrantAssignee.grant_id == grant_row.id,
                        PermissionGrantAssignee.source_fingerprint == source.source_fingerprint,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            id_collision = await session.get(
                PermissionGrantAssignee,
                source.source_id,
            )
            if id_collision is not None:
                signature = (
                    id_collision.subject_type,
                    id_collision.subject_id,
                    id_collision.userset_relation,
                    id_collision.source_locator,
                    bool(id_collision.protected),
                )
                expected = (
                    source.subject_type,
                    source.subject_id,
                    source.userset_relation,
                    source.source_locator,
                    source.protected,
                )
                if (
                    id_collision.tenant_id != grant_row.tenant_id
                    or id_collision.source_fingerprint != source.source_fingerprint
                    or signature != expected
                    or id_collision.version + 1 != source.version
                ):
                    raise PermissionVersionConflictError(
                        msg="Stable assignee identity collision",
                    )
                id_collision.grant_id = int(grant_row.id)
                id_collision.state = state
                id_collision.version = source.version
                return id_collision
            row = PermissionGrantAssignee(
                id=source.source_id,
                tenant_id=grant_row.tenant_id,
                grant_id=int(grant_row.id),
                subject_type=source.subject_type,
                subject_id=source.subject_id,
                userset_relation=source.userset_relation,
                include_children=source.include_children,
                source_type=source.source_type,
                source_ref=source.source_ref,
                source_locator=source.source_locator,
                source_fingerprint=source.source_fingerprint,
                projected_subject=source.projected_subject,
                protected=source.protected,
                state=state,
                version=source.version,
            )
            session.add(row)
            await session.flush()
        else:
            signature = (
                row.subject_type,
                row.subject_id,
                row.userset_relation,
                row.source_locator,
                bool(row.protected),
            )
            expected = (
                source.subject_type,
                source.subject_id,
                source.userset_relation,
                source.source_locator,
                source.protected,
            )
            if signature != expected:
                raise PermissionVersionConflictError(msg="Permission source fingerprint collision")
            row.state = state
        return row

    @staticmethod
    async def _redis():
        from bisheng.core.cache.redis_manager import get_redis_client

        return await get_redis_client()

    @staticmethod
    def _draft_key(draft_id: str) -> str:
        return f"f048:permission:mode-draft:{draft_id}"


class SqlOwnerProjectionState:
    def __init__(self, state: SqlPermissionControlState) -> None:
        self._state = state

    async def prepare(
        self,
        context,
        grant,
        source,
        visibility,
        *,
        operation_id,
    ) -> None:
        await self._state.prepare_owner(
            context,
            grant,
            source,
            visibility,
            operation_id=operation_id,
        )

    async def finalize(self, context, grant, visibility, outcome) -> None:
        await self._state.finalize_owner(context, grant, visibility, outcome)

    async def mark_compensation_required(self, context, error) -> None:
        await self._state.mark_owner_compensation(context, error)


class SqlGrantMutationState:
    def __init__(self, state: SqlPermissionControlState) -> None:
        self._state = state

    async def prepare(
        self,
        context,
        grants,
        visibility,
        *,
        idempotency_key,
        operation_id,
    ) -> None:
        await self._state.prepare_grants(
            context,
            grants,
            visibility,
            idempotency_key=idempotency_key,
            operation_id=operation_id,
        )

    async def finalize(self, context, grants, visibility, outcome) -> None:
        await self._state.finalize_grants(context, grants, visibility, outcome)


class SqlModeState:
    def __init__(self, state: SqlPermissionControlState) -> None:
        self._state = state

    async def allocate_source_ids(self, count: int) -> tuple[int, ...]:
        return await self._state.allocate_source_ids(count)

    async def save_draft(self, draft: PermissionModeDraft) -> None:
        await self._state.save_mode_draft(draft)

    async def prepare(
        self,
        context,
        draft,
        grants,
        visibility,
        *,
        idempotency_key,
        operation_id,
    ) -> None:
        await self._state.prepare_mode(
            context,
            draft,
            grants,
            visibility,
            idempotency_key=idempotency_key,
            operation_id=operation_id,
        )

    async def finalize(self, context, draft, grants, visibility, outcome) -> None:
        await self._state.finalize_mode(
            context,
            draft,
            grants,
            visibility,
            outcome,
        )


def require_owner_model(
    catalog: RuntimeCatalogSnapshot,
) -> GrantModelSnapshot:
    row = next(
        (item.snapshot for item in catalog.models if item.snapshot.model_key == "owner"),
        None,
    )
    if row is None or not row.active or not row.action_codes:
        raise PermissionModelStateConflictError(msg="The current Catalog has no active owner model")
    return row
