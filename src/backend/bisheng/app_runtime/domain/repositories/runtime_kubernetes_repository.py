"""Transactional execution evidence; no cluster SDK or object-storage access."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from sqlmodel import select

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    MUTATING,
    TERMINAL,
    RuntimeConflict,
    RuntimeDeliveryRepository,
    check_scope,
)

_PRODUCTION = {"serve", "migrate", "restore", "data", "purge"}
_INTENT_FIELDS = (
    "tenant_id",
    "app_id",
    "operation_id",
    "node_id",
    "cluster_id",
    "namespace",
    "name",
    "kind",
    "purpose",
    "generation",
    "owner_epoch",
    "spec_digest",
    "status_policy_revision",
    "approved_template",
)


def _time(raw):
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if result.tzinfo is not None:
            from datetime import UTC

            result = result.astimezone(UTC).replace(tzinfo=None)
        return result
    except (ValueError, TypeError, AttributeError):
        raise RuntimeConflict("stop_time_invalid") from None


class RuntimeKubernetesRepository(RuntimeDeliveryRepository):
    async def claim_controller(self, node_id, *, holder_id, expected_epoch, now=None):
        now = now or datetime.utcnow()
        if not isinstance(holder_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", holder_id):
            raise RuntimeConflict("controller_holder_invalid")
        if type(expected_epoch) is not int or expected_epoch < 0:
            raise RuntimeConflict("controller_epoch_invalid")
        async with self.transaction() as session:
            node = await self.get(RuntimeNode, node_id, lock=True)
            if node is None or node.executor_kind != "kubernetes" or node.status not in {"ready", "blocked"}:
                raise RuntimeConflict("controller_node_unavailable")
            if node.controller_epoch != expected_epoch:
                raise RuntimeConflict("controller_epoch_conflict")
            if node.lease_until is not None and node.lease_until > now:
                if node.controller_holder != holder_id:
                    raise RuntimeConflict("controller_lease_held")
                return node
            node.controller_holder, node.controller_epoch = holder_id, node.controller_epoch + 1
            node.lease_until = now + timedelta(seconds=30)
            await session.flush()
            return node

    async def _controller(self, node_id, holder_id, epoch, now):
        node = await self.get(RuntimeNode, node_id, lock=True)
        if (
            node is None
            or node.executor_kind != "kubernetes"
            or node.status not in {"ready", "blocked"}
            or (node.controller_holder, node.controller_epoch) != (holder_id, epoch)
            or node.lease_until is None
            or node.lease_until <= now
        ):
            raise RuntimeConflict("controller_lease_lost")
        return node

    async def renew_controller(self, node_id, *, holder_id, controller_epoch, now=None):
        now = now or datetime.utcnow()
        async with self.transaction() as session:
            node = await self._controller(node_id, holder_id, controller_epoch, now)
            node.lease_until = now + timedelta(seconds=30)
            await session.flush()
            return node

    async def _acting_operation(self, row, operation_id, now, *, allow_own_cleanup=False):
        op = await self.get(RuntimeOperation, operation_id, lock=True)
        if op is None or (op.tenant_id, op.app_id, op.node_id) != (row.tenant_id, row.app_id, row.node_id):
            raise RuntimeConflict("resource_operation_scope_refused")
        if allow_own_cleanup and row.operation_id == operation_id and op.status in TERMINAL:
            return op
        if op.status in TERMINAL or op.deadline <= now:
            raise RuntimeConflict("resource_operation_expired")
        if op.kind in MUTATING or op.kind == "data":
            matches = await self.find(RuntimeAssignment, app_id=row.app_id, lock=True)
            if not matches:
                raise RuntimeConflict("resource_owner_missing")
            owner = matches[0]
            active = owner.data_operation_id if op.kind == "data" else owner.active_operation_id
            if (active, owner.node_id, owner.generation, owner.owner_epoch) != (
                op.id,
                op.node_id,
                op.generation,
                op.owner_epoch,
            ):
                raise RuntimeConflict("resource_owner_fence_stale")
        return op

    async def create_resource_intent(self, row, *, holder_id, controller_epoch, now=None):
        now = now or datetime.utcnow()
        check_scope(row)
        if row.uid is not None:
            raise RuntimeConflict("resource_uid_requires_observation")
        if row.kind == "Secret" and any(k in row.approved_template for k in ("data", "stringData")):
            raise RuntimeConflict("resource_secret_plaintext_refused")
        async with self.transaction() as session:
            # Existing operation paths lock operation before node. Preserve that order.
            op = await self.get(RuntimeOperation, row.operation_id, lock=True)
            if op is None:
                raise RuntimeConflict("resource_operation_missing")
            node = await self._controller(row.node_id, holder_id, controller_epoch, now)
            if node.status != "ready":
                raise RuntimeConflict("runtime_prerequisites_blocked")
            await self._acting_operation(row, row.operation_id, now)
            if (row.generation, row.owner_epoch) != (op.generation, op.owner_epoch):
                raise RuntimeConflict("resource_fence_mismatch")
            current = await self.get(RuntimeExecutionResource, row.id, lock=True)
            if current is not None:
                if any(getattr(current, k) != getattr(row, k) for k in _INTENT_FIELDS):
                    raise RuntimeConflict("resource_intent_conflict")
                if current.uid is None and current.stop_requested_at is None:
                    current.controller_epoch = controller_epoch
                    await session.flush()
                return current
            production = row.kind == "Pod" and row.purpose in _PRODUCTION
            matches = await self.find(
                RuntimeExecutionResource, operation_id=row.operation_id, kind=row.kind, name=row.name, lock=True
            )
            for current in matches:
                if current.cleanup_state == "complete" and production:
                    continue
                if all(getattr(current, k) == getattr(row, k) for k in _INTENT_FIELDS):
                    # Legacy callers without a resource-ref in the projection.
                    return current
                if not production or current.purpose == row.purpose:
                    raise RuntimeConflict("resource_intent_conflict")
            if row.kind == "Pod":
                reservations = await self.find(RuntimeCapacityReservation, operation_id=row.operation_id, lock=True)
                if not reservations or reservations[0].state == "released":
                    raise RuntimeConflict("resource_capacity_not_held")
            if row.kind == "Pod" and row.purpose in _PRODUCTION:
                statement = (
                    select(RuntimeExecutionResource)
                    .where(
                        RuntimeExecutionResource.app_id == row.app_id,
                        RuntimeExecutionResource.kind == "Pod",
                        RuntimeExecutionResource.purpose.in_(_PRODUCTION),
                        (RuntimeExecutionResource.stop_state != "confirmed")
                        | (RuntimeExecutionResource.cleanup_state != "complete"),
                    )
                    .with_for_update()
                )
                if (await session.exec(statement)).first() is not None:
                    raise RuntimeConflict("production_writer_stop_unconfirmed")
            if row.kind == "Pod":
                row.observed_state = {"creation": {"version": 1, "state": "unattempted"}}
            row.controller_epoch = controller_epoch
            session.add(row)
            await session.flush()
            return row

    async def _resource_control(self, resource_id, holder_id, controller_epoch, now):
        # Operation->node->resource ordering matches create_resource_intent.
        current = await self.get(RuntimeExecutionResource, resource_id)
        if current is None:
            raise RuntimeConflict("resource_not_found")
        await self.get(RuntimeOperation, current.operation_id, lock=True)
        node = await self._controller(current.node_id, holder_id, controller_epoch, now)
        async with self.transaction() as session:
            # A prior scope read can populate the identity map before lock acquisition.
            # Refresh after taking the lock so a concurrent begin/fence cannot be lost.
            statement = select(RuntimeExecutionResource).where(RuntimeExecutionResource.id == resource_id)
            row = (await session.exec(statement.with_for_update().execution_options(populate_existing=True))).first()
            if row is None:
                raise RuntimeConflict("resource_not_found")
            check_scope(row)
        return row, node

    async def observe_resource_creation(
        self,
        resource_id,
        *,
        action,
        holder_id,
        controller_epoch,
        create_attempt_id=None,
        http_status=None,
        evidence=None,
        now=None,
    ):
        now = now or datetime.utcnow()
        if action in {"create_begin", "create_rejected"}:
            try:
                if not isinstance(create_attempt_id, str) or str(UUID(create_attempt_id)) != create_attempt_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise RuntimeConflict("resource_creation_attempt_invalid") from None
        async with self.transaction() as session:
            row, _ = await self._resource_control(resource_id, holder_id, controller_epoch, now)
            await self._acting_operation(row, row.operation_id, now, allow_own_cleanup=action != "create_begin")
            creation = dict((row.observed_state or {}).get("creation", {}))
            if (
                row.kind != "Pod"
                or row.uid is not None
                or type(creation.get("version")) is not int
                or creation.get("version") != 1
            ):
                raise RuntimeConflict("resource_creation_unconfirmed")
            state = creation.get("state")
            if action == "create_begin":
                if state != "unattempted" or row.stop_requested_at is not None:
                    raise RuntimeConflict("resource_creation_already_attempted")
                creation.update(state="started", create_attempt_id=create_attempt_id, controller_epoch=controller_epoch)
            elif action == "create_rejected":
                if (
                    state != "started"
                    or creation.get("create_attempt_id") != create_attempt_id
                    or creation.get("controller_epoch") != controller_epoch
                    or type(http_status) is not int
                    or http_status != 403
                ):
                    raise RuntimeConflict("resource_creation_rejection_unconfirmed")
                creation.update(state="rejected", http_status=403)
            elif action == "create_fence":
                if state not in {"unattempted", "rejected", "fenced", "not_created"}:
                    raise RuntimeConflict("resource_creation_unconfirmed")
                if state in {"unattempted", "rejected"}:
                    creation.update(state="fenced", outcome=state)
                if row.stop_requested_at is None:
                    row.stop_requested_at = now
                if row.stop_state != "confirmed":
                    row.stop_state = "requested"
            elif action == "not_created":
                fields = {"evidence_kind", "namespace", "name", "observed_at", "api_status"}
                if (
                    state not in {"fenced", "not_created"}
                    or creation.get("outcome") not in {"unattempted", "rejected"}
                    or not isinstance(evidence, dict)
                    or set(evidence) != fields
                    or (evidence["evidence_kind"], evidence["namespace"], evidence["name"])
                    != ("not_created", row.namespace, row.name)
                    or type(evidence["api_status"]) is not int
                    or evidence["api_status"] != 404
                    or row.stop_requested_at is None
                ):
                    raise RuntimeConflict("resource_not_created_unconfirmed")
                observed = _time(evidence["observed_at"])
                if (
                    observed < row.stop_requested_at - timedelta(seconds=1)
                    or observed > now + timedelta(seconds=5)
                    or now - observed > timedelta(seconds=60)
                ):
                    raise RuntimeConflict("resource_not_created_observation_stale")
                creation["state"] = "not_created"
                row.stop_state, row.stop_evidence, row.observed_at = "confirmed", dict(evidence), observed
            else:
                raise RuntimeConflict("resource_creation_action_refused")
            row.controller_epoch = controller_epoch
            row.observed_state = {"creation": creation}
            await session.flush()
            return row

    async def bind_resource(
        self, resource_id, *, uid, node_name, holder_id, controller_epoch, now=None, observed_state=None
    ):
        now = now or datetime.utcnow()
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", uid):
            raise RuntimeConflict("resource_uid_invalid")
        if not isinstance(node_name, str) or len(node_name) > 253:
            raise RuntimeConflict("resource_node_name_invalid")
        async with self.transaction() as session:
            row, node = await self._resource_control(resource_id, holder_id, controller_epoch, now)
            if row.stop_evidence.get("evidence_kind") == "not_created":
                raise RuntimeConflict("resource_creation_fenced")
            if row.uid is not None and row.uid != uid:
                raise RuntimeConflict("resource_uid_changed")
            if row.node_name and row.node_name != node_name:
                raise RuntimeConflict("resource_binding_changed")
            if observed_state is not None:
                if not isinstance(observed_state, dict) or row.kind != "Service":
                    raise RuntimeConflict("resource_observed_state_refused")
                if row.observed_state and row.observed_state != observed_state:
                    raise RuntimeConflict("resource_observed_state_changed")
                row.observed_state = dict(observed_state)
            first = row.uid is None
            row.uid, row.node_name, row.observed_at = uid, node_name, now
            row.controller_epoch = controller_epoch
            if first:
                capabilities = node.capabilities or {}
                row.protected_since_creation = bool(
                    capabilities.get("status_protection")
                    and capabilities.get("status_policy_revision") == row.status_policy_revision
                )
                row.binding_policy_verified = bool(capabilities.get("binding_protection"))
            await session.flush()
            return row

    async def request_resource_stop(self, resource_id, *, operation_id, holder_id, controller_epoch, now=None):
        now = now or datetime.utcnow()
        async with self.transaction() as session:
            # Lock the acting operation before the node to avoid an inversion with admission.
            await self.get(RuntimeOperation, operation_id, lock=True)
            row, _ = await self._resource_control(resource_id, holder_id, controller_epoch, now)
            acting = await self._acting_operation(row, operation_id, now, allow_own_cleanup=True)
            if (
                row.kind == "PersistentVolumeClaim"
                and acting.kind == "destroy"
                and acting.payload.get("purge_volume") is True
            ):
                row.stop_evidence = {**row.stop_evidence, "cleanup_operation_id": acting.id}
            # Refresh only the cleanup authority, never the writer's stop evidence.
            row.controller_epoch = controller_epoch
            if row.stop_requested_at is None:
                row.stop_requested_at = now
            if row.stop_state != "confirmed":
                row.stop_state = "requested"
            await session.flush()
            return row

    async def confirm_resource_stop(self, resource_id, evidence, *, holder_id, controller_epoch, now=None):
        now = now or datetime.utcnow()
        async with self.transaction() as session:
            row, _ = await self._resource_control(resource_id, holder_id, controller_epoch, now)
            if not isinstance(evidence, dict) or not row.uid or evidence.get("uid") != row.uid:
                raise RuntimeConflict("stop_uid_refused")
            if row.stop_state == "confirmed":
                return row
            if row.kind != "Pod" or row.stop_requested_at is None:
                raise RuntimeConflict("stop_request_required")
            if (
                evidence.get("namespace"),
                evidence.get("name"),
                evidence.get("policy_revision"),
                evidence.get("node_name"),
            ) != (row.namespace, row.name, row.status_policy_revision, row.node_name):
                raise RuntimeConflict("stop_scope_or_policy_refused")
            if (
                not evidence.get("resource_version")
                or evidence["resource_version"] == "0"
                or not re.fullmatch(r"[a-f0-9]{64}", str(evidence.get("status_digest", "")))
            ):
                raise RuntimeConflict("stop_version_or_digest_refused")
            observed, deleted = _time(evidence.get("observed_at")), _time(evidence.get("deletion_timestamp"))
            if (
                observed < row.stop_requested_at - timedelta(seconds=1)
                or observed > now + timedelta(seconds=5)
                or now - observed > timedelta(seconds=60)
                or deleted > observed
            ):
                raise RuntimeConflict("stop_observation_stale")
            kind = evidence.get("evidence_kind")
            if kind == "never_scheduled":
                valid = not row.node_name and row.binding_policy_verified
            elif kind == "kubelet_terminal":
                valid = bool(row.node_name and row.protected_since_creation)
            else:
                valid = False
            if not valid:
                raise RuntimeConflict("stop_evidence_unconfirmed")
            row.stop_state, row.stop_evidence, row.observed_at = "confirmed", dict(evidence), observed
            await session.flush()
            return row

    async def release_resources(self, operation_id):
        async with self.transaction() as session:
            op = await self.get(RuntimeOperation, operation_id, lock=True)
            if op is None:
                raise RuntimeConflict("resource_operation_missing")
            statement = (
                select(RuntimeExecutionResource)
                .where(
                    RuntimeExecutionResource.operation_id == operation_id,
                    RuntimeExecutionResource.kind == "Pod",
                    RuntimeExecutionResource.stop_state != "confirmed",
                )
                .with_for_update()
            )
            if (await session.exec(statement)).first() is not None:
                raise RuntimeConflict("execution_not_confirmed_stopped")
            await self.release(operation_id, stopped=True)

    async def resources_to_reconcile(self, node_id):
        async with self.transaction() as session:
            statement = (
                select(RuntimeExecutionResource)
                .where(
                    RuntimeExecutionResource.node_id == node_id, RuntimeExecutionResource.cleanup_state != "complete"
                )
                .order_by(RuntimeExecutionResource.create_time, RuntimeExecutionResource.id)
            )
            rows = list((await session.exec(statement)).all())
            for row in rows:
                check_scope(row)
            return rows

    async def complete_resource_cleanup(self, resource_id, *, uid, holder_id, controller_epoch, now=None):
        now = now or datetime.utcnow()
        async with self.transaction() as session:
            row, _ = await self._resource_control(resource_id, holder_id, controller_epoch, now)
            absent = bool(
                row.kind == "Pod"
                and row.uid is None
                and uid is None
                and row.stop_state == "confirmed"
                and row.stop_evidence.get("evidence_kind") == "not_created"
                and row.observed_state.get("creation", {}).get("state") == "not_created"
            )
            if not absent and (not uid or row.uid != uid):
                raise RuntimeConflict("resource_cleanup_uid_refused")
            if row.kind == "Pod" and row.stop_state != "confirmed":
                raise RuntimeConflict("execution_not_confirmed_stopped")
            row.cleanup_state = "complete"
            await session.flush()
            return row
