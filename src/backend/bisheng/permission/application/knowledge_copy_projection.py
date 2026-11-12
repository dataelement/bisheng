"""Resume only the original RESOURCE_COPY; no knowledge SQL or new capability."""

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from bisheng.permission.application.knowledge_move_projection import KnowledgeMoveProjectionApplication
from bisheng.permission.application.runtime import _idempotency_key
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_plan import projection_request_checksum
from bisheng.permission.domain.services.projection_service import restore_projection_plan


def blocked():
    raise PermissionPublishNotReadyError(msg="Copy projection no longer matches its original complete operation")


class KnowledgeCopyProjectionApplication:
    def __init__(self, *, session_factory=get_async_db_session, components=None):
        self.repository = ProjectionRepository(session_factory)
        self.composition = KnowledgeMoveProjectionApplication(session_factory=session_factory, components=components)

    async def aexecute_or_resume(self, *, source, target, actor, owner_user_id, mode):
        tenant, ambient = get_current_tenant_id(), get_current_permission_actor()
        if (
            not isinstance(actor, PermissionActor)
            or tenant != source.tenant_id
            or tenant != target.tenant_id
            or is_tenant_filter_bypassed()
            or target.resource_version != 0
            or source.resource_type != target.resource_type
            or source.resource_id == target.resource_id
            or mode not in {"INHERIT", "CUSTOM"}
        ):
            blocked()
        components = await self.composition._composition()
        catalog = await components.facade._runtime_catalog()
        before_mode = await components.state.mode_for_target(source)
        if (
            before_mode.projection_state,
            before_mode.version,
            before_mode.mode,
            before_mode.parent_type,
            before_mode.parent_id,
        ) != ("CURRENT", source.resource_version, mode, source.parent_type, source.parent_id):
            blocked()
        key = _idempotency_key("copy", tenant, source.resource_type, source.resource_id, target.resource_id)
        fact = await self.repository.aget_operation_by_idempotency(key)
        if fact is not None:
            await self._plan(fact, source, target, actor, catalog)
            if fact.status == "FAILED_CLOSED":
                preview = await components.projection.inspect_failed_closed_recovery(fact.id)
                if (
                    any(
                        getattr(preview, name) != getattr(fact, name)
                        for name in (
                            "tenant_id",
                            "operation_type",
                            "scope_type",
                            "scope_key",
                            "expected_version",
                            "target_version",
                            "store_id",
                            "model_id",
                            "request_checksum",
                            "after_checksum",
                        )
                    )
                    or preview.operation_id != fact.id
                ):
                    blocked()
                await components.projection.recover_failed_closed_operation(
                    fact.id, confirmation_checksum=preview.confirmation_checksum
                )
            elif fact.status in {"STAGING", "COMMIT_UNKNOWN", "COMMITTED"}:
                await components.projection.reconcile_operation(fact.id)
            elif fact.status not in {"PREPARED", "FINALIZED"}:
                blocked()
        # A durable original copy must not be compiled again from its new
        # Grant rows. Restore its exact plan and verify every native mirror.
        current = await self.repository.aget_operation_by_idempotency(key)
        if current is not None and current.status == "FINALIZED":
            from bisheng.permission.domain.services.projection_plan import ProjectionOutcome

            outcome = ProjectionOutcome(
                current.id, current.target_version, "FINALIZED", current.request_checksum, idempotent=True
            )
        else:
            result = await components.facade.project_copy(
                source=source, target=target, actor=actor, owner_user_id=owner_user_id, mode=mode
            )
            outcome = getattr(result, "projection", None)
            current = await self.repository.aget_operation_by_idempotency(key)
        if current is None or current.status != "FINALIZED":
            blocked()
        plan = await self._plan(current, source, target, actor, catalog)
        if (
            outcome is None
            or outcome.status != "FINALIZED"
            or outcome.operation_id != current.id
            or outcome.request_checksum != current.request_checksum
            or not await components.projection._is_after(plan.deltas)
        ):
            blocked()
        state = await components.state.mode_for_target(target)
        if (
            state.projection_state != "CURRENT"
            or state.version != current.target_version
            or state.operation_id != current.id
            or state.mode != mode
            or (state.parent_type, state.parent_id) != (target.parent_type, target.parent_id)
        ):
            blocked()
        models = components.facade._models_for_target(catalog, target.resource_type)
        actual = await components.state.load_grants(target=target, models=models)
        expected = await components.state.load_grants(target=source, models=models) if mode == "CUSTOM" else ()

        def signature(grant, row):
            return (
                grant.model.model_key,
                row.subject_type,
                row.subject_id,
                row.userset_relation,
                row.include_children,
                row.source_type,
                row.source_ref,
                row.source_fingerprint,
                row.projected_subject,
            )

        wanted = {
            signature(grant, row)
            for grant in expected
            for row in grant.sources
            if grant.active and row.active and not row.protected
        }
        found = {
            signature(grant, row)
            for grant in actual
            for row in grant.sources
            if grant.active and row.active and not row.protected
        }
        protected = [row for grant in actual for row in grant.sources if grant.active and row.active and row.protected]
        if (
            wanted != found
            or len(protected) != 1
            or protected[0].subject_type != "user"
            or protected[0].subject_id != str(owner_user_id)
            or protected[0].source_type != "CREATOR"
            or protected[0].source_ref != f"{target.resource_type}:{target.resource_id}"
        ):
            blocked()
        grant_keys = {delta.key for delta in components.facade._sources.compile_existing_tuples(actual)}
        frozen_keys = {
            delta.key
            for delta in plan.deltas
            if delta.action == "WRITE"
            and delta.relation in {"model", "grant", "ordinary_assignee", "protected_assignee"}
        }
        if (
            grant_keys != frozen_keys
            or get_current_tenant_id() != tenant
            or get_current_permission_actor() is not ambient
            or is_tenant_filter_bypassed()
        ):
            blocked()
        return outcome

    async def _plan(self, fact, source, target, actor, catalog, *, tuples=None):
        if (
            fact.tenant_id != target.tenant_id
            or fact.operation_type != "RESOURCE_COPY"
            or fact.scope_type != "resource"
            or fact.scope_key != f"{target.resource_type}:{target.resource_id}"
            or fact.expected_version != 0
            or fact.target_version != 1
            or fact.operator_id != actor.user_id
            or (fact.store_id, fact.model_id) != (catalog.store_id, catalog.model_id)
            or fact.idempotency_key
            != _idempotency_key("copy", target.tenant_id, source.resource_type, source.resource_id, target.resource_id)
        ):
            blocked()
        if tuples is None:
            tuples = await self.repository.aget_operation_tuples(fact.id)
        plan = restore_projection_plan(fact, tuples)
        if projection_request_checksum(plan) != fact.request_checksum:
            blocked()
        parents = {
            delta.user
            for delta in plan.deltas
            if delta.relation == "parent" and delta.action == "WRITE" and delta.object == fact.scope_key
        }
        if parents != ({f"{target.parent_type}:{target.parent_id}"} if target.parent_type is not None else set()):
            blocked()
        return plan

    async def arequire_completed(self, session, *, pairs):
        """Verify original complete after facts in the caller's native TX."""
        from types import SimpleNamespace

        from bisheng.permission.domain.repositories.copy_projection_repository import CopyProjectionRepository
        from bisheng.resource_reference.application.contracts import TransactionIdentity

        tenant, tx = get_current_tenant_id(), TransactionIdentity.capture(session)
        if is_tenant_filter_bypassed() or session.new or session.dirty or session.deleted:
            blocked()
        repository = CopyProjectionRepository(environment=self.composition.repository.environment)
        pin = await repository._pin(session)
        catalog = SimpleNamespace(store_id=pin[0], model_id=pin[1])
        for source, target, mode, operator in pairs:
            key = _idempotency_key("copy", tenant, source.resource_type, source.resource_id, target.resource_id)
            fact, before, state, rows = await repository.aread_pair(session, source=source, target=target, key=key)
            if (before.projection_state, before.version, before.mode, before.parent_type, before.parent_id) != (
                "CURRENT",
                source.resource_version,
                mode,
                source.parent_type,
                source.parent_id,
            ):
                blocked()
            if fact.status != "FINALIZED" or (
                state.projection_state,
                state.operation_id,
                state.version,
                state.mode,
                state.parent_type,
                state.parent_id,
            ) != ("CURRENT", fact.id, 1, mode, target.parent_type, target.parent_id):
                blocked()
            await self._plan(fact, source, target, operator, catalog, tuples=rows)
            tx.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                blocked()
