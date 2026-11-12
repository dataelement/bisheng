"""Post-cutover cleanup; only a business deletion owner may invoke this port.

RESOURCE_DELETE remains the original business cutover proof. A separate native
DELETE-only journal removes residual object/grant relations before SQL mirrors
are purged. The original operation/tuple ledgers and business audit survive.
"""

from dataclasses import replace

from bisheng.common.errcode.permission import PermissionPublishNotReadyError, PermissionVersionConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.models import ProjectionOperationStatus
from bisheng.permission.domain.repositories.deleted_resource_repository import DeletedResourceRepository
from bisheng.permission.domain.services.projection_plan import MAX_ATOMIC_TUPLES, ProjectionTupleDelta
from bisheng.permission.domain.services.projection_service import restore_projection_plan
from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan


class DeletedResourceCleanup:
    def __init__(self, runtime, *, repository=None, session_factory=None):
        self.runtime = runtime
        self.repository = repository or (
            DeletedResourceRepository(session_factory) if session_factory else DeletedResourceRepository()
        )

    async def _keys(self, objects):
        keys = set()
        for obj in objects:
            rows = await self.runtime._client.read_tuples(object=obj, consistency="HIGHER_CONSISTENCY")
            for row in rows:
                if row.get("object") != obj or not row.get("user") or not row.get("relation"):
                    raise PermissionPublishNotReadyError(msg="Incomplete deleted-resource tuple inventory")
                keys.add((row["user"], row["relation"], obj))
        return tuple(sorted(keys))

    async def run(self, *, actor, target, delete_idempotency_key):
        """Call only after business cutover, using its original frozen target."""
        if (
            actor.current_tenant_id != target.tenant_id
            or get_current_tenant_id() != target.tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise PermissionVersionConflictError(msg="Deletion cleanup tenant changed")
        catalog = await self.runtime._runtime_catalog()
        original = await self.repository.aget_operation_by_idempotency(delete_idempotency_key)
        if original is None or original.status != "FINALIZED":
            raise PermissionPublishNotReadyError(msg="Original deletion has not finalized")
        original_plan = restore_projection_plan(original, await self.repository.aget_operation_tuples(original.id))
        if original_plan != build_delete_plan(
            target,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            operator_id=actor.user_id,
            idempotency_key=delete_idempotency_key,
        ):
            raise PermissionVersionConflictError(msg="Original deletion receipt or catalog pin changed")
        key = f"resource-purge:{original.id}"
        cleanup = await self.repository.aget_operation_by_idempotency(key)
        mode, grants = await self.repository.snapshot(target)
        if mode is None:
            # A finalized receipt is not a claim that later external writes
            # cannot exist. Verify the originally owned objects on replay too.
            objects = {f"{target.resource_type}:{target.resource_id}"}
            if cleanup is not None:
                plan = restore_projection_plan(cleanup, await self.repository.aget_operation_tuples(cleanup.id))
                if (
                    cleanup.status != "FINALIZED"
                    or plan.operation_type != "RESOURCE_DELETE_PURGE"
                    or plan.tenant_id != target.tenant_id
                    or plan.scope_type != "resource"
                    or plan.scope_key != original_plan.scope_key
                    or (plan.store_id, plan.model_id) != (catalog.store_id, catalog.model_id)
                    or plan.expected_version != original.target_version
                    or plan.target_version != original.target_version + 1
                    or plan.operator_id != original.operator_id
                    or any(delta.action != "DELETE" for delta in plan.deltas)
                ):
                    raise PermissionVersionConflictError(
                        msg="Deletion mirrors disappeared before their receipt finalized"
                    )
                objects.update(delta.object for delta in plan.deltas)
            if await self._keys(tuple(sorted(objects))):
                raise PermissionPublishNotReadyError(msg="Deleted-resource relations reappeared after cleanup")
            return
        objects = (
            f"{target.resource_type}:{target.resource_id}",
            *(
                "permission_grant:"
                + stable_grant_key(
                    tenant_id=target.tenant_id,
                    resource_type=target.resource_type,
                    resource_id=target.resource_id,
                    model_key=grant.model_key,
                )
                for grant in grants
            ),
        )
        if cleanup is None:
            if (mode.operation_id, mode.version, mode.projection_state) != (
                original.id,
                original.target_version,
                "CURRENT",
            ):
                raise PermissionVersionConflictError(msg="Deletion cleanup no longer owns the resource")
            keys = await self._keys(objects)
            if any(
                relation == "grant" and obj == objects[0] and user.partition("#")[0] not in objects
                for user, relation, obj in keys
            ):
                raise PermissionPublishNotReadyError(msg="Deleted resource has an unowned grant relation")
            if not keys:
                await self.repository.purge(target, original)
                return
            # Reserve at least one actually present tuple for COMMIT. A fake
            # already-absent marker would make uncertain commit recovery unsafe.
            commit_start = max(0, len(keys) - MAX_ATOMIC_TUPLES)
            plan = replace(
                original_plan,
                operation_type="RESOURCE_DELETE_PURGE",
                idempotency_key=key,
                expected_version=original.target_version,
                target_version=original.target_version + 1,
                deltas=tuple(
                    ProjectionTupleDelta(
                        "STAGE" if index < commit_start else "COMMIT",
                        index,
                        "DELETE",
                        *value,
                    )
                    for index, value in enumerate(keys)
                ),
            )
            cleanup = await self.runtime._projection.prepare(plan)
        else:
            plan = restore_projection_plan(cleanup, await self.repository.aget_operation_tuples(cleanup.id))
            if (
                plan.tenant_id != target.tenant_id
                or plan.scope_type != "resource"
                or plan.scope_key != original_plan.scope_key
                or plan.operation_type != "RESOURCE_DELETE_PURGE"
                or (plan.store_id, plan.model_id) != (catalog.store_id, catalog.model_id)
                or plan.expected_version != original.target_version
                or plan.target_version != original.target_version + 1
                or plan.operator_id != original.operator_id
                or any(delta.action != "DELETE" or delta.object not in objects for delta in plan.deltas)
            ):
                raise PermissionVersionConflictError(msg="Deletion cleanup journal changed")
        if str(cleanup.status) == ProjectionOperationStatus.PREPARED.value:
            if (mode.version, mode.operation_id, mode.projection_state) not in {
                (original.target_version, original.id, "CURRENT"),
                (original.target_version, cleanup.id, "PROJECTING"),
            }:
                raise PermissionVersionConflictError(msg="Deletion cleanup reservation changed")
            await self.runtime._state.mark_projecting(
                target=target.model_copy(update={"resource_version": original.target_version}),
                expected_catalog_release_id=catalog.release_id,
                operation_id=cleanup.id,
            )
        await self.runtime._projection.execute(plan)
        if await self._keys(objects):
            raise PermissionPublishNotReadyError(msg="Deleted-resource relations remain after cleanup")
        finalized = await self.repository.aget_operation(cleanup.id)
        await self.repository.purge(target, finalized)
