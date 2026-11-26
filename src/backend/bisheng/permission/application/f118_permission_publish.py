"""Stopped-service fixed-pin IO; callers close every SQL Session before entry."""

from contextlib import aclosing
from datetime import UTC, datetime, timedelta

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
    required_relations_checksum,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import discover_openfga_runtime, normalize_authorization_model
from bisheng.permission.application.catalog_api import OpenFGACatalogProjector, SqlCatalogState
from bisheng.permission.application.f118_permission_tuples import blocked
from bisheng.permission.application.sql_runtime import RedisConsistencyMarker
from bisheng.permission.domain.services.catalog_service import (
    CatalogDraftSnapshot,
    CatalogPublishContext,
    CatalogService,
)
from bisheng.permission.migration.f048_runtime_storage import OpenFGAMigrationModelPublisher
from bisheng.permission.migration.f118_plan import PermissionCatalogBaseline, _compile_catalog


class _FixedClient(FGAClient):
    """Guard public IO also when the original ModelPublisher calls the client."""

    def __init__(self, *, current, **kwargs):
        self._current = current
        super().__init__(**kwargs)

    async def list_authorization_models(self):
        self._current()
        result = await super().list_authorization_models()
        self._current()
        return result

    async def write_authorization_model(self, model):
        self._current()
        result = await super().write_authorization_model(model)
        self._current()
        return result

    async def write_tuples(self, writes=None, deletes=None):
        self._current()
        result = await super().write_tuples(writes=writes, deletes=deletes)
        self._current()
        return result


class F118PermissionPublisher:
    def __init__(self, *, catalog_plan, session_factory):
        self.plan, self.sessions = catalog_plan, session_factory
        self.tenant = get_current_tenant_id()
        self.config = settings.openfga.model_copy(deep=True)
        self.config.validate_production_runtime()
        if not self.config.enabled:
            blocked("disabled_runtime")
        self.before = catalog_plan.before.authorization
        self.source = self.target = None
        self.source_schema = None
        self.target_schema = build_authorization_model_f048()
        if authorization_model_checksum(self.target_schema) != self.plan.target_model_checksum:
            blocked("target_model_changed")
        self.state = SqlCatalogState(session_factory=session_factory)
        self.marker = RedisConsistencyMarker()

    def check(self):
        if (
            type(self.tenant) is not int
            or self.tenant <= 0
            or type(get_current_tenant_id()) is not int
            or get_current_tenant_id() != self.tenant
            or is_tenant_filter_bypassed()
        ):
            blocked("publication_context_changed")
        if self.source is None or (self.source.store_id, self.source.model_id) != (
            self.before.store_id,
            self.before.model_id,
        ):
            blocked("source_transport_changed")
        if self.target is not None and (self.target.store_id, self.target.model_id) != (
            self.before.store_id,
            self.target_id,
        ):
            blocked("target_transport_changed")

    async def __aenter__(self):
        try:
            pin = await discover_openfga_runtime(
                self.config,
                expected_model=None,
                allow_bootstrap=False,
                required_store_id=self.before.store_id,
                required_model_id=self.before.model_id,
            )
            if pin.model_checksum != self.before.model_checksum:
                blocked("source_schema_changed")
            self.source = _FixedClient(
                current=self.check,
                api_url=self.config.api_url,
                store_id=self.before.store_id,
                model_id=self.before.model_id,
                timeout=self.config.timeout,
            )
            self.check()
            models = await self.source.list_authorization_models()
            self.check()
            selected = [
                normalize_authorization_model({"authorization_model": row})
                for row in models
                if (row.get("id") or row.get("authorization_model_id")) == self.before.model_id
            ]
            if (
                len(selected) != 1
                or authorization_model_checksum(selected[0]) != self.before.model_checksum
                or required_relations_checksum(selected[0]) != self.before.required_relations_checksum
            ):
                blocked("source_schema_unavailable")
            self.source_schema = selected[0]
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        for client in (self.target, self.source):
            if client is not None:
                await client.close()
        self.target = self.source = None

    async def aset_target(self, pin):
        self.check()
        if (
            pin.environment != self.before.environment
            or pin.store_id != self.before.store_id
            or pin.model_checksum != self.plan.target_model_checksum
            or pin.required_relations_checksum != required_relations_checksum(self.target_schema)
        ):
            blocked("target_schema_pin_changed")
        actual = await discover_openfga_runtime(
            self.config,
            expected_model=self.target_schema,
            allow_bootstrap=False,
            required_store_id=pin.store_id,
            required_model_id=pin.model_id,
        )
        self.check()
        if (actual.store_id, actual.model_id, actual.model_checksum) != (
            pin.store_id,
            pin.model_id,
            pin.model_checksum,
        ):
            blocked("target_pin_changed")
        self.target_id = pin.model_id
        self.target = _FixedClient(
            current=self.check,
            api_url=self.config.api_url,
            store_id=pin.store_id,
            model_id=pin.model_id,
            timeout=self.config.timeout,
        )
        self.projector = OpenFGACatalogProjector(client=self.target, marker=self.marker, session_factory=self.sessions)
        self.check()

    async def aprepare(self, *, operator_id, idempotency_key):
        self.check()
        model_id = self.before.model_id
        if self.plan.target_model_checksum != self.before.model_checksum:
            model_id = await OpenFGAMigrationModelPublisher(
                source_client=self.source,
                environment=self.before.environment,
                predecessor_model_id=self.before.model_id,
            ).aget_or_publish(
                store_id=self.before.store_id, model=self.target_schema, checksum=self.plan.target_model_checksum
            )
        self.check()
        reservation = await self.state.reserve_draft(
            base_release_id=self.plan.before.release.id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self.check()
        return model_id, reservation

    async def ascan(self):
        self.check()
        values = set()
        async with aclosing(self.source.iter_tuples(consistency="HIGHER_CONSISTENCY")) as stream:
            async for row in stream:
                self.check()
                if (
                    type(row) is not dict
                    or set(row)
                    not in (
                        {"user", "relation", "object"},
                        {"user", "relation", "object", "condition"},
                    )
                    or row.get("condition") is not None
                ):
                    blocked("live_tuple_shape")
                key = row["user"], row["relation"], row["object"]
                if any(type(value) is not str or not value or len(value) > 4096 or "\x00" in value for value in key):
                    blocked("live_tuple_value")
                if key in values:
                    blocked("duplicate_live_tuple")
                values.add(key)
        self.check()
        return values

    def stage_snapshot(self, actual):
        # Input was read and verified from the selected real release by the
        # bounded native Repository. Reuse canonical policy, not the generic
        # online reader's unbounded model-ID IN or fabricated runtime statuses.
        if (
            type(actual) is not PermissionCatalogBaseline
            or actual.release.predecessor_id != self.plan.before.release.id
        ):
            blocked("actual_catalog_snapshot_required")
        actions, models, _ = _compile_catalog(actual)
        if actions.checksum != self.plan.action_checksum or models.checksum != self.plan.model_checksum:
            blocked("actual_catalog_canonical_changed")
        row = actual.release
        return CatalogDraftSnapshot(
            row.id,
            row.release_key,
            row.predecessor_id,
            self.plan.before.release.release_key,
            row.checksum,
            row.commit_checksum if row.status in {"DRAFT", "PROJECTING"} and row.commit_checksum else row.checksum,
            tuple(action.code for action in actions.actions),
            models.blockers,
            action_release=actions,
            model_release=models,
            draft_owner_id=row.draft_owner_id,
            idempotency_key=row.idempotency_key,
            expires_at=row.expires_at,
        )

    def pointer_changes(self, draft):
        context = CatalogPublishContext(
            draft, self.plan.before.release.id, self.plan.before.release.release_key, "DRAFT"
        )
        return CatalogService._active_pointer_changes(context)

    async def aapply(self, operation, *, draft):
        self.check()
        action, keys = operation
        if not await self.marker.is_ready():
            blocked("recent_marker_unavailable")
        self.check()
        await self.marker.arm_catalog(draft.release_key)
        self.check()
        if action == "ACTIVE":
            result = await self.projector.commit_active(self.pointer_changes(draft))
        else:
            rows = [dict(zip(("user", "relation", "object"), row, strict=True)) for row in keys]
            if not rows or len(rows) > 90:
                blocked("finite_tuple_batch_required")
            if action == "WRITE":
                await self.target.write_tuples(writes=rows)
            elif action == "DELETE":
                await self.source.delete_tuples_store_scoped(rows)
            else:
                blocked("unknown_tuple_operation")
            result = None
        self.check()
        return result
