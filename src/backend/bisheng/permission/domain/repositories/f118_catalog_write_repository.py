"""Exact stopped-service Catalog DRAFT SQL, in the caller's native transaction.

This Repository neither publishes FGA tuples nor activates any authorization
model or CURRENT pointer. Only a real reservation can receive frozen children.
"""

import re
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionModel,
    PermissionModelAction,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration import f118_plan as plans
from bisheng.resource_reference.application.contracts import TransactionIdentity

_ZERO = "0" * 64


def _blocked(reason):
    raise PermissionMigrationBlockedError(reason="f118_catalog_sql_" + reason)


def _positive(value):
    return type(value) is int and value > 0


class _Current:
    def __init__(self, session):
        self.session, self.tenant = session, get_current_tenant_id()
        if not isinstance(session, AsyncSession) or not session.in_transaction():
            _blocked("native_transaction_required")
        try:
            self.transaction = TransactionIdentity.capture(session)
        except (TypeError, ValueError) as error:
            raise PermissionMigrationBlockedError(reason="f118_catalog_sql_transaction_changed") from error
        self.check()

    def check(self):
        session = self.session
        if (
            type(self.tenant) is not int
            or self.tenant <= 0
            or type(get_current_tenant_id()) is not int
            or get_current_tenant_id() != self.tenant
            or is_tenant_filter_bypassed()
            or session.new
            or session.dirty
            or session.deleted
        ):
            _blocked("native_context_changed")
        try:
            self.transaction.assert_current(session)
        except (TypeError, ValueError) as error:
            raise PermissionMigrationBlockedError(reason="f118_catalog_sql_transaction_changed") from error

    async def execute(self, query, values=None):
        self.check()
        with self.session.no_autoflush:
            result = await self.session.execute(query) if values is None else await self.session.execute(query, values)
        self.check()
        return result


class F118CatalogWriteRepository:
    def __init__(self, *, snapshot_repository=None):
        if snapshot_repository is not None and not isinstance(
            snapshot_repository, PermissionMigrationSnapshotRepository
        ):
            _blocked("actual_snapshot_repository_required")
        self.snapshots = snapshot_repository or PermissionMigrationSnapshotRepository()

    async def _read(self, current, release_id):
        current.check()
        try:
            result = await self.snapshots.aload_catalog_release(current.session, release_id=release_id)
        except (TypeError, ValueError, KeyError) as error:
            raise PermissionMigrationBlockedError(reason="f118_catalog_sql_invalid_typed_catalog") from error
        current.check()
        return result

    async def _before(self, current, expected):
        if type(expected) is not plans.PermissionCatalogBaseline:
            _blocked("original_catalog_required")
        plans._validate_catalog(expected)
        table = PermissionCatalogRelease.__table__
        rows = (
            await current.execute(select(table.c.id).where(table.c.status == "CURRENT").order_by(table.c.id).limit(2))
        ).all()
        if len(rows) != 1 or rows[0][0] != expected.release.id:
            _blocked("current_catalog_changed")
        if await self._read(current, expected.release.id) != expected:
            _blocked("original_catalog_changed")
        if (
            expected.release.status != "CURRENT"
            or expected.release.write_fenced
            or expected.authorization.status != "ACTIVE"
        ):
            _blocked("original_catalog_not_ready")

    async def averify_before(self, session: AsyncSession, *, expected: plans.PermissionCatalogBaseline) -> None:
        current = _Current(session)
        await self._before(current, expected)
        current.check()

    @staticmethod
    def _arguments(permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key):
        if (
            type(permission_planner) is not plans.ResourceRetirementPlanner
            or not _positive(draft_id)
            or not _positive(target_authorization_release_id)
            or type(operator_id) is not int
            or operator_id < 0
            or type(idempotency_key) is not str
            or not idempotency_key.strip()
            or len(idempotency_key) > 64
            or "\x00" in idempotency_key
        ):
            _blocked("invalid_reservation_arguments")
        return permission_planner.catalog_plan

    async def _locked(self, current, plan, draft_id, target_id, operator_id, key):
        # Global lock order: sole CURRENT, selected DRAFT, then auth PKs ascending.
        # No source/resource locks or FGA IO are acquired while these are held.
        release, auth = PermissionCatalogRelease.__table__, AuthorizationModelRelease.__table__
        originals = (
            (
                await current.execute(
                    select(*release.c)
                    .where(release.c.status == "CURRENT")
                    .order_by(release.c.id)
                    .limit(2)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        if len(originals) != 1 or originals[0]["id"] != plan.before.release.id or draft_id == plan.before.release.id:
            _blocked("current_catalog_changed")
        drafts = (
            (await current.execute(select(*release.c).where(release.c.id == draft_id).with_for_update()))
            .mappings()
            .all()
        )
        if len(drafts) != 1:
            _blocked("reservation_missing")
        draft = drafts[0]
        expected_key = f"catalog-v{draft['version']}-{sha256(key.encode()).hexdigest()[:10]}"
        if (
            draft["status"] != "DRAFT"
            or draft["predecessor_id"] != plan.before.release.id
            or type(draft["version"]) is not int
            or draft["version"] <= plan.before.release.version
            or draft["release_key"] != expected_key
            or draft["draft_owner_id"] != operator_id
            or draft["idempotency_key"] != key
            or draft["write_fenced"]
            or draft["commit_checksum"] is not None
            or draft["projection_checkpoint"] != 0
            or draft["published_at"] is not None
        ):
            _blocked("reservation_changed")
        rows = (
            (
                await current.execute(
                    select(*auth.c)
                    .where(auth.c.id.in_(sorted({plan.before.authorization.id, target_id})))
                    .order_by(auth.c.id)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        targets = [row for row in rows if row["id"] == target_id]
        if len(targets) != 1:
            _blocked("target_authorization_missing")
        self._target(plan, targets[0], target_id)
        await self._before(current, plan.before)
        return draft

    @staticmethod
    def _target(plan, target, target_id, *, status="STAGED"):
        before = plan.before.authorization
        if target["id"] != target_id:
            _blocked("target_authorization_changed")
        if plan.target_model_checksum == before.model_checksum:
            if target_id != before.id or any(target[name] != value for name, value in asdict(before).items()):
                _blocked("same_schema_pin_changed")
        elif (
            target_id == before.id
            or target["status"] != status
            or target["environment"] != before.environment
            or target["store_id"] != before.store_id
            or target["model_checksum"] != plan.target_model_checksum
            or target["predecessor_model_id"] != before.model_id
            or target["model_id"] == before.model_id
            or any(
                type(target[name]) is not str or not target[name].strip()
                for name in ("model_id", "model_version", "openfga_version")
            )
            or type(target["required_relations_checksum"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", target["required_relations_checksum"]) is None
        ):
            _blocked("target_authorization_changed")

    @staticmethod
    def _checksum(plan, draft):
        return plans._checksum(
            {
                "actions": plan.action_checksum,
                "models": plan.model_checksum,
                "predecessor_release_id": plan.before.release.id,
                "release_key": draft["release_key"],
            }
        )

    async def _verified(self, current, plan, draft, target_id):
        if (
            draft["checksum"] != self._checksum(plan, draft)
            or draft["required_authorization_model_release_id"] != target_id
        ):
            _blocked("staged_binding_changed")
        result = await self._read(current, draft["id"])
        if asdict(result.release) != {field.name: draft[field.name] for field in fields(plans.CatalogReleaseBaseline)}:
            _blocked("staged_header_changed")
        self._target(plan, asdict(result.authorization), target_id)
        expected = {row.model_key: row for row in plan.after_models}
        if (
            result.actions != plan.after_actions
            or len(result.models) != len(expected)
            or {row.model_key for row in result.models} != expected.keys()
            or any(replace(row, id=expected[row.model_key].id) != expected[row.model_key] for row in result.models)
        ):
            _blocked("staged_provenance_changed")
        # Same canonical policy as the real CURRENT loader, including floors.
        # Exact typed comparison above additionally binds legacy_source_key,
        # which intentionally does not participate in the online model hash.
        try:
            actions, models, _ = plans._compile_catalog(result)
        except (TypeError, ValueError) as error:
            raise PermissionMigrationBlockedError(reason="f118_catalog_sql_invalid_canonical_catalog") from error
        if actions.checksum != plan.action_checksum or models.checksum != plan.model_checksum:
            _blocked("staged_canonical_changed")
        current.check()
        return result

    async def averify_staged_catalog(
        self,
        session: AsyncSession,
        *,
        permission_planner: plans.ResourceRetirementPlanner,
        draft_id: int,
        target_authorization_release_id: int,
        operator_id: int,
        idempotency_key: str,
    ) -> plans.PermissionCatalogBaseline:
        plan = self._arguments(
            permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        current = _Current(session)
        draft = await self._locked(
            current, plan, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        return await self._verified(current, plan, draft, target_authorization_release_id)

    async def _insert(self, current, model, rows):
        for start in range(0, len(rows), 200):
            await current.execute(insert(model.__table__), rows[start : start + 200])

    async def _ids(self, current, model, draft_id, name):
        table, result, after = model.__table__, {}, 0
        while True:
            rows = (
                await current.execute(
                    select(table.c.id, table.c[name])
                    .where(table.c.catalog_release_id == draft_id, table.c.id > after)
                    .order_by(table.c.id)
                    .limit(200)
                )
            ).all()
            for ident, value in rows:
                result[value] = ident
            if len(rows) < 200:
                return result
            after = rows[-1][0]

    async def _write(self, current, plan, draft, target_id):
        ident = draft["id"]
        await self._insert(
            current,
            PermissionAction,
            [
                {
                    "catalog_release_id": ident,
                    "code": row.code,
                    "name": row.name,
                    "level": row.level,
                    "active": row.active,
                    "sort_order": row.sort_order,
                }
                for row in plan.after_actions
            ],
        )
        actions = await self._ids(current, PermissionAction, ident, "code")
        await self._insert(
            current,
            PermissionActionResourceScope,
            [
                {"action_id": actions[row.code], "resource_type": kind}
                for row in plan.after_actions
                for kind in sorted(row.resource_types)
            ],
        )
        models = []
        for row in plan.after_models:
            values = asdict(row)
            for name in ("id", "selected_action_codes", "effective_action_codes"):
                del values[name]
            values["visibility_only_resource_types"] = list(row.visibility_only_resource_types)
            models.append({"catalog_release_id": ident, **values})
        await self._insert(current, PermissionModel, models)
        model_ids = await self._ids(current, PermissionModel, ident, "model_key")
        await self._insert(
            current,
            PermissionModelAction,
            [
                {"model_id": model_ids[row.model_key], "action_id": actions[code]}
                for row in plan.after_models
                for code in row.selected_action_codes
            ],
        )
        table = PermissionCatalogRelease.__table__
        changed = await current.execute(
            update(table)
            .where(
                table.c.id == ident,
                table.c.status == "DRAFT",
                table.c.checksum == _ZERO,
                table.c.required_authorization_model_release_id == plan.before.authorization.id,
            )
            .values(
                checksum=self._checksum(plan, draft),
                required_authorization_model_release_id=target_id,
                update_time=table.c.update_time,
            )
        )
        if changed.rowcount != 1:
            _blocked("reservation_write_conflict")

    async def astage_catalog(
        self,
        session: AsyncSession,
        *,
        permission_planner: plans.ResourceRetirementPlanner,
        draft_id: int,
        target_authorization_release_id: int,
        operator_id: int,
        idempotency_key: str,
    ) -> plans.PermissionCatalogBaseline:
        plan = self._arguments(
            permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        current = _Current(session)
        draft = await self._locked(
            current, plan, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        if draft["checksum"] != _ZERO:
            return await self._verified(current, plan, draft, target_authorization_release_id)
        if (
            draft["required_authorization_model_release_id"] != plan.before.authorization.id
            or draft["expires_at"] is None
            or draft["expires_at"] <= datetime.now(UTC).replace(tzinfo=None)
        ):
            _blocked("initial_reservation_changed_or_expired")
        initial = await self._read(current, draft_id)
        if initial.actions or initial.models:
            _blocked("partial_reservation")
        current.check()
        async with session.begin_nested():
            owned = _Current(session)
            if owned.tenant != current.tenant:
                _blocked("native_context_changed")
            await self._write(owned, plan, draft, target_authorization_release_id)
            final = await self._locked(
                owned, plan, draft_id, target_authorization_release_id, operator_id, idempotency_key
            )
            if any(
                final[name] != value
                for name, value in draft.items()
                if name not in {"checksum", "required_authorization_model_release_id", "update_time"}
            ):
                _blocked("reservation_audit_or_identity_changed")
            result = await self._verified(owned, plan, final, target_authorization_release_id)
            owned.check()
        current.check()
        return result

    async def aresolve_target(self, session, *, permission_planner, model_id):
        current = _Current(session)
        plan = permission_planner.catalog_plan
        table = AuthorizationModelRelease.__table__
        rows = (
            (
                await current.execute(
                    select(*table.c).where(
                        table.c.environment == plan.before.authorization.environment,
                        table.c.store_id == plan.before.authorization.store_id,
                        table.c.model_id == model_id,
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != 1:
            _blocked("target_authorization_missing")
        self._target(plan, rows[0], rows[0]["id"])
        return plans.AuthorizationPinBaseline(
            **{field.name: rows[0][field.name] for field in fields(plans.AuthorizationPinBaseline)}
        )

    async def averify_published(
        self, session, *, permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key
    ):
        from bisheng.permission.migration.f118_verify import verify_catalog_retirement

        plan = self._arguments(
            permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        current = _Current(session)
        result = await self._read(current, draft_id)
        if (
            result.release.status != "CURRENT"
            or result.release.write_fenced
            or result.release.draft_owner_id != operator_id
            or result.release.idempotency_key != idempotency_key
            or result.release.release_key
            != f"catalog-v{result.release.version}-{sha256(idempotency_key.encode()).hexdigest()[:10]}"
        ):
            _blocked("published_binding_changed")
        self._target(plan, asdict(result.authorization), target_authorization_release_id, status="ACTIVE")
        verify_catalog_retirement(plan=plan, actual=result)
        previous = await self._read(current, plan.before.release.id)
        if (
            previous.release.status != "RETIRED"
            or any(
                getattr(previous.release, field.name) != getattr(plan.before.release, field.name)
                for field in fields(plans.CatalogReleaseBaseline)
                if field.name != "status"
            )
            or previous.actions != plan.before.actions
            or previous.models != plan.before.models
        ):
            _blocked("original_catalog_history_changed")
        wanted = "ACTIVE" if target_authorization_release_id == plan.before.authorization.id else "RETIRED"
        if previous.authorization.status != wanted or any(
            getattr(previous.authorization, field.name) != getattr(plan.before.authorization, field.name)
            for field in fields(plans.AuthorizationPinBaseline)
            if field.name != "status"
        ):
            _blocked("original_authorization_history_changed")
        rows = (
            await current.execute(
                select(PermissionCatalogRelease.__table__.c.id).where(
                    PermissionCatalogRelease.__table__.c.status == "CURRENT"
                )
            )
        ).all()
        if rows != [(draft_id,)]:
            _blocked("current_catalog_changed")
        current.check()
        return result

    async def afinalize_catalog(
        self,
        session,
        *,
        permission_planner,
        draft_id,
        target_authorization_release_id,
        operator_id,
        idempotency_key,
        commit_checksum,
    ):
        plans._digest(commit_checksum)
        current = _Current(session)
        release, auth = PermissionCatalogRelease.__table__, AuthorizationModelRelease.__table__
        state = (await current.execute(select(release.c.status).where(release.c.id == draft_id))).scalar_one_or_none()
        args = {
            "permission_planner": permission_planner,
            "draft_id": draft_id,
            "target_authorization_release_id": target_authorization_release_id,
            "operator_id": operator_id,
            "idempotency_key": idempotency_key,
        }
        if state == "CURRENT":
            result = await self.averify_published(session, **args)
            if result.release.commit_checksum != commit_checksum:
                _blocked("published_commit_changed")
            return result
        plan = self._arguments(
            permission_planner, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        draft = await self._locked(
            current, plan, draft_id, target_authorization_release_id, operator_id, idempotency_key
        )
        await self._verified(current, plan, draft, target_authorization_release_id)
        original_rows = []
        for table, ids in (
            (release, (plan.before.release.id, draft_id)),
            (auth, tuple({plan.before.authorization.id, target_authorization_release_id})),
        ):
            rows = (
                (await current.execute(select(*table.c).where(table.c.id.in_(ids)).order_by(table.c.id)))
                .mappings()
                .all()
            )
            original_rows.append((table, rows))
        async with session.begin_nested():
            owned = _Current(session)
            if owned.tenant != current.tenant:
                _blocked("native_context_changed")
            for ident, values in (
                (plan.before.release.id, {"status": "RETIRED"}),
                (draft_id, {"status": "CURRENT", "published_at": func.now(), "commit_checksum": commit_checksum}),
            ):
                changed = await owned.execute(update(release).where(release.c.id == ident).values(**values))
                if changed.rowcount != 1:
                    _blocked("catalog_finalize_conflict")
            if target_authorization_release_id != plan.before.authorization.id:
                await owned.execute(
                    update(auth)
                    .where(auth.c.id == plan.before.authorization.id, auth.c.status == "ACTIVE")
                    .values(status="RETIRED", retired_at=func.now())
                )
                await owned.execute(
                    update(auth)
                    .where(auth.c.id == target_authorization_release_id, auth.c.status == "STAGED")
                    .values(status="ACTIVE", activated_at=func.now(), retired_at=None)
                )
            result = await self.averify_published(session, **args)
            for table, previous_rows in original_rows:
                rows = (
                    (
                        await owned.execute(
                            select(*table.c)
                            .where(table.c.id.in_(tuple(row["id"] for row in previous_rows)))
                            .order_by(table.c.id)
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(rows) != len(previous_rows):
                    _blocked("final_raw_rows_changed")
                for previous, row in zip(previous_rows, rows, strict=True):
                    if table is release:
                        allowed = {"status", "update_time"} | (
                            {"published_at", "commit_checksum"} if row["id"] == draft_id else set()
                        )
                    elif target_authorization_release_id == plan.before.authorization.id:
                        allowed = set()
                    else:
                        allowed = {"status", "retired_at", "update_time"} | (
                            {"activated_at"} if row["id"] == target_authorization_release_id else set()
                        )
                    if any(row[name] != value for name, value in previous.items() if name not in allowed):
                        _blocked("final_raw_history_changed")
            owned.check()
        current.check()
        return result
