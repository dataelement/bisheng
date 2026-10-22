"""Transactional runtime ledger; Engine side effects remain in the manager."""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeDelivery,
    RuntimeEgressPolicy,
    RuntimeExecutionFact,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
    ScopedRuntimeRecord,
)
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.core.database import get_async_db_session

TERMINAL = frozenset({"completed", "failed", "cancelled", "timed_out"})
MUTATING = frozenset({"deploy", "stop", "destroy", "migrate", "restore"})


class RuntimeConflict(ValueError):
    """A safe, stable reason; never carries database statements or secrets."""


def check_scope(row) -> None:
    if isinstance(row, ScopedRuntimeRecord) and not is_tenant_filter_bypassed():
        tenant = get_current_tenant_id()
        if tenant is None or row.tenant_id != tenant:
            raise RuntimeConflict("tenant_scope_mismatch")


class RuntimeDeliveryRepository:
    def __init__(self, session_factory=get_async_db_session):
        self._factory = session_factory
        self._active = ContextVar(f"runtime_uow_{id(self)}", default=None)

    @asynccontextmanager
    async def transaction(self):
        if self._active.get() is not None:
            yield self._active.get()
            return
        async with self._factory() as session:
            token = self._active.set(session)
            try:
                with strict_tenant_filter():
                    yield session
                    await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                self._active.reset(token)

    async def get_application(self, app_id):
        from bisheng.database.models.app import App

        return await self.get(App, app_id)

    async def get(self, model, record_id: str, *, lock: bool = False):
        async with self.transaction() as session:
            statement = select(model).where(model.id == record_id)
            if lock:
                statement = statement.with_for_update()
            row = (await session.exec(statement)).first()
            if row is not None:
                check_scope(row)
            return row

    async def find(self, model, *, lock: bool = False, shared: bool = False, limit: int | None = None, **fields):
        async with self.transaction() as session:
            statement = select(model)
            for name, value in fields.items():
                statement = statement.where(getattr(model, name) == value)
            statement = statement.order_by(model.create_time, model.id)
            if limit is not None:
                statement = statement.limit(min(limit, 10000))
            if lock or shared:
                statement = statement.with_for_update(read=shared)
            rows = (await session.exec(statement)).all()
            for row in rows:
                check_scope(row)
            return list(rows)

    async def capacity_snapshot(self, node_id):
        async with self.transaction() as session:
            node = await self.get(RuntimeNode, node_id)
            if node is None:
                raise RuntimeConflict("node_not_found")
            used = (
                await session.exec(
                    select(
                        func.coalesce(func.sum(RuntimeCapacityReservation.memory_mb), 0),
                        func.coalesce(func.sum(RuntimeCapacityReservation.cpu_millicores), 0),
                    ).where(
                        RuntimeCapacityReservation.node_id == node_id, RuntimeCapacityReservation.state != "released"
                    )
                )
            ).one()
            instances = (
                await session.exec(
                    select(func.count())
                    .select_from(RuntimeRoute)
                    .where(
                        RuntimeRoute.node_id == node_id,
                        RuntimeRoute.status == "serving",
                        RuntimeRoute.route_key.like("app:%"),
                    )
                )
            ).one()
            return {
                "memory_budget_mb": node.memory_budget_mb,
                "cpu_budget_millicores": node.cpu_budget_millicores,
                "committed_mb": int(used[0]),
                "committed_cpu": int(used[1]) / 1000,
                "instances": int(instances),
            }

    async def purge_diagnostics(self, node_id, now):
        async with self.transaction() as session:
            rows = (
                await session.exec(
                    select(RuntimeOperation)
                    .where(
                        RuntimeOperation.node_id == node_id,
                        RuntimeOperation.diagnostics_until <= now,
                        RuntimeOperation.status.in_(TERMINAL),
                    )
                    .order_by(RuntimeOperation.diagnostics_until, RuntimeOperation.id)
                    .limit(100)
                    .with_for_update()
                )
            ).all()
            for row in rows:
                row.failure = {key: value for key, value in row.failure.items() if key != "diagnostic_tail"}
                for fact in await self.find(RuntimeExecutionFact, operation_id=row.id, lock=True):
                    if "diagnostic_tail" in fact.detail:
                        fact.detail = {key: value for key, value in fact.detail.items() if key != "diagnostic_tail"}
                row.diagnostics_until = None
            await session.flush()

    async def node_operations(self, node_id):
        async with self.transaction() as session:
            active = select(RuntimeAssignment.active_operation_id).where(RuntimeAssignment.node_id == node_id)
            query = (
                select(RuntimeOperation)
                .where(
                    RuntimeOperation.node_id == node_id,
                    or_(
                        RuntimeOperation.status.notin_(TERMINAL),
                        RuntimeOperation.cleanup_status != "complete",
                        RuntimeOperation.id.in_(active),
                    ),
                )
                .order_by(RuntimeOperation.create_time, RuntimeOperation.id)
            )
            return list((await session.exec(query)).all())

    async def node_policies(self, node_id, now):
        async with self.transaction() as session:
            query = (
                select(RuntimeEgressPolicy)
                .join(RuntimeOperation, RuntimeOperation.id == RuntimeEgressPolicy.operation_id)
                .where(
                    RuntimeOperation.node_id == node_id,
                    RuntimeEgressPolicy.revoked_at.is_(None),
                    RuntimeEgressPolicy.not_after > now,
                )
                .order_by(RuntimeEgressPolicy.create_time, RuntimeEgressPolicy.id)
            )
            return list((await session.exec(query)).all())

    async def save(self, row):
        check_scope(row)
        async with self.transaction() as session:
            previous = await self.get(type(row), row.id, lock=True)
            if previous is not None:
                check_scope(previous)
            row.update_time = datetime.utcnow()
            result = await session.merge(row)
            await session.flush()
            await session.refresh(result)
            return result

    async def acquire_data_operation(self, operation: RuntimeOperation, *, offline=True):
        check_scope(operation)
        now = datetime.utcnow()
        if operation.kind != "data" or not now < operation.deadline <= now + timedelta(seconds=60):
            raise RuntimeConflict("data_operation_deadline_invalid")
        async with self.transaction() as session:
            node = await self.get(RuntimeNode, operation.node_id, lock=True)
            if (
                node is None
                or node.executor_kind != "kubernetes"
                or node.status != "ready"
                or (now - node.heartbeat_at).total_seconds() > 15
            ):
                raise RuntimeConflict("data_node_unavailable")
            matches = await self.find(
                RuntimeOperation, scope_key=operation.scope_key, idempotency_key=operation.idempotency_key
            )
            if matches:
                if matches[0].request_digest != operation.request_digest:
                    raise RuntimeConflict("idempotency_content_conflict")
                return matches[0]
            owners = await self.find(RuntimeAssignment, app_id=operation.app_id, lock=True)
            if not owners:
                raise RuntimeConflict("data_owner_missing")
            owner = owners[0]
            if (owner.node_id, owner.generation, owner.owner_epoch) != (
                operation.node_id,
                operation.generation,
                operation.owner_epoch,
            ):
                raise RuntimeConflict("data_owner_fence_stale")
            if owner.data_operation_id:
                raise RuntimeConflict("data_operation_in_progress")
            # Count only the global node allocation; never load other tenant data.
            with bypass_tenant_filter():
                active_data = (
                    await session.exec(
                        select(func.count())
                        .select_from(RuntimeAssignment)
                        .where(RuntimeAssignment.node_id == node.id, RuntimeAssignment.data_operation_id != "")
                    )
                ).one()
            if int(active_data) >= 2:
                raise RuntimeConflict("data_capacity_exhausted")
            for previous in await self.find(RuntimeOperation, app_id=operation.app_id):
                if previous.kind in MUTATING and (
                    previous.status not in TERMINAL or previous.cleanup_status != "complete"
                ):
                    raise RuntimeConflict("owner_operation_in_progress")
            result = await self.create_operation(operation)
            if offline:
                await self.admit(result.id, memory_mb=128, cpu_millicores=25)
            owner.data_operation_id = result.id
            await self.save(owner)
            return result

    async def create_operation(self, operation: RuntimeOperation):
        check_scope(operation)
        async with self.transaction() as session:
            matches = await self.find(
                RuntimeOperation, scope_key=operation.scope_key, idempotency_key=operation.idempotency_key
            )
            if matches:
                if matches[0].request_digest != operation.request_digest:
                    raise RuntimeConflict("idempotency_content_conflict")
                return matches[0]
            if operation.kind in MUTATING:
                # Same node -> assignment ordering as claim/data acquisition.
                await self.get(RuntimeNode, operation.node_id, lock=True)
                owners = await self.find(RuntimeAssignment, app_id=operation.app_id, lock=True)
                if owners and owners[0].data_operation_id:
                    raise RuntimeConflict("data_operation_in_progress")
            try:
                # The savepoint preserves an enclosing admission UoW after a concurrent insert.
                async with session.begin_nested():
                    session.add(operation)
                    await session.flush()
                return operation
            except IntegrityError:
                # Read the committed winner without upgrading duplicate-key shared locks.
                # An exclusive read here deadlocks concurrent MySQL duplicate inserts.
                matches = await self.find(
                    RuntimeOperation,
                    shared=True,
                    scope_key=operation.scope_key,
                    idempotency_key=operation.idempotency_key,
                )
                if matches and matches[0].request_digest == operation.request_digest:
                    return matches[0]
                raise RuntimeConflict("idempotency_content_conflict") from None

    async def admit(self, operation_id: str, *, memory_mb: int, cpu_millicores: int, max_age_seconds: int = 15):
        if memory_mb <= 0 or cpu_millicores <= 0:
            raise RuntimeConflict("invalid_capacity_request")
        async with self.transaction() as session:
            operation = await self.get(RuntimeOperation, operation_id, lock=True)
            if operation is None or operation.status in TERMINAL or operation.deadline <= datetime.utcnow():
                raise RuntimeConflict("operation_expired")
            node = await self.get(RuntimeNode, operation.node_id, lock=True)
            if (
                node is None
                or node.status != "ready"
                or (datetime.utcnow() - node.heartbeat_at).total_seconds() > max_age_seconds
            ):
                raise RuntimeConflict("node_stale")
            existing = await self.find(RuntimeCapacityReservation, operation_id=operation.id)
            if existing:
                row = existing[0]
                if row.memory_mb != memory_mb or row.cpu_millicores != cpu_millicores or row.state == "released":
                    raise RuntimeConflict("capacity_reservation_conflict")
                return row
            # Physical capacity is global across tenants; only the aggregate is read under bypass.
            with bypass_tenant_filter():
                used = (
                    await session.exec(
                        select(
                            func.coalesce(func.sum(RuntimeCapacityReservation.memory_mb), 0),
                            func.coalesce(func.sum(RuntimeCapacityReservation.cpu_millicores), 0),
                        ).where(
                            RuntimeCapacityReservation.node_id == node.id,
                            RuntimeCapacityReservation.state != "released",
                        )
                    )
                ).one()
            if (
                int(used[0]) + memory_mb > node.memory_budget_mb
                or int(used[1]) + cpu_millicores > node.cpu_budget_millicores
            ):
                raise RuntimeConflict("capacity_exhausted")
            row = RuntimeCapacityReservation(
                tenant_id=operation.tenant_id,
                app_id=operation.app_id,
                operation_id=operation.id,
                node_id=node.id,
                purpose=operation.kind,
                memory_mb=memory_mb,
                cpu_millicores=cpu_millicores,
            )
            session.add(row)
            operation.stage = "admitted"
            node.generation += 1
            await session.flush()
            return row

    async def release(self, operation_id: str, *, stopped: bool):
        if not stopped:
            raise RuntimeConflict("execution_not_confirmed_stopped")
        async with self.transaction():
            operation = await self.get(RuntimeOperation, operation_id, lock=True)
            if operation and operation.kind == "data":
                if operation.status not in TERMINAL or operation.cleanup_status != "complete":
                    raise RuntimeConflict("data_cleanup_unconfirmed")
                owners = await self.find(RuntimeAssignment, app_id=operation.app_id, lock=True)
                if owners and owners[0].data_operation_id == operation.id:
                    owners[0].data_operation_id = ""
                    await self.save(owners[0])
            rows = await self.find(RuntimeCapacityReservation, operation_id=operation_id, lock=True)
            for row in rows:
                row.state = "released"
                await self.save(row)

    async def claim(self, operation_id: str, *, node_id: str, generation: int, owner_epoch: int):
        async with self.transaction() as session:
            op = await self.get(RuntimeOperation, operation_id, lock=True)
            if op is None or (op.node_id, op.generation, op.owner_epoch) != (node_id, generation, owner_epoch):
                raise RuntimeConflict("execution_fence_mismatch")
            if op.status in TERMINAL or op.deadline <= datetime.utcnow():
                raise RuntimeConflict("operation_expired")
            if op.kind in MUTATING:
                # Serialize first-assignment creation on the fixed execution node.
                # Locking a missing assignment alone leaves an insert-gap race.
                if await self.get(RuntimeNode, node_id, lock=True) is None:
                    raise RuntimeConflict("node_not_found")
                assignments = await self.find(RuntimeAssignment, app_id=op.app_id, lock=True)
                if assignments:
                    assignment = assignments[0]
                    if assignment.data_operation_id:
                        raise RuntimeConflict("data_operation_in_progress")
                    if op.generation < assignment.generation or op.owner_epoch != assignment.owner_epoch:
                        raise RuntimeConflict("execution_fence_stale")
                    if assignment.node_id != node_id:
                        raise RuntimeConflict("owner_takeover_requires_stopped_proof")
                    if assignment.active_operation_id not in ("", op.id):
                        previous = await self.get(RuntimeOperation, assignment.active_operation_id)
                        if previous is None or previous.status not in TERMINAL or previous.cleanup_status != "complete":
                            raise RuntimeConflict("owner_operation_in_progress")
                    assignment.active_operation_id = op.id
                    assignment.generation = op.generation
                    assignment.owner_epoch = op.owner_epoch
                else:
                    assignment = RuntimeAssignment(
                        tenant_id=op.tenant_id,
                        app_id=op.app_id,
                        node_id=node_id,
                        generation=op.generation,
                        owner_epoch=owner_epoch,
                        active_operation_id=op.id,
                    )
                    session.add(assignment)
            elif op.kind == "data":
                await self.get(RuntimeNode, node_id, lock=True)
                owners = await self.find(RuntimeAssignment, app_id=op.app_id, lock=True)
                if not owners or (
                    owners[0].node_id,
                    owners[0].generation,
                    owners[0].owner_epoch,
                    owners[0].data_operation_id,
                ) != (node_id, generation, owner_epoch, op.id):
                    raise RuntimeConflict("data_execution_fence_stale")
            op.status = "running"
            await session.flush()
            return op

    async def record_fact(
        self,
        operation_id: str,
        *,
        sequence: int,
        node_id: str,
        generation: int,
        owner_epoch: int,
        phase: str,
        exec_ref: str = "",
        detail: dict | None = None,
    ):
        async with self.transaction() as session:
            existing = await self.find(RuntimeExecutionFact, operation_id=operation_id, sequence=sequence)
            if existing:
                row = existing[0]
                if (row.node_id, row.generation, row.owner_epoch, row.phase, row.exec_ref, row.detail) != (
                    node_id,
                    generation,
                    owner_epoch,
                    phase,
                    exec_ref,
                    detail or {},
                ):
                    raise RuntimeConflict("fact_sequence_conflict")
                return row
            if phase in TERMINAL or phase == "cleanup_pending":
                op = await self.get(RuntimeOperation, operation_id, lock=True)
                if op is None or (op.node_id, op.generation, op.owner_epoch) != (node_id, generation, owner_epoch):
                    raise RuntimeConflict("execution_fence_mismatch")
                assignments = await self.find(RuntimeAssignment, app_id=op.app_id)
                if op.kind in MUTATING and assignments and assignments[0].active_operation_id != op.id:
                    raise RuntimeConflict("execution_fence_stale")
                if op.kind == "data" and (not assignments or assignments[0].data_operation_id != op.id):
                    raise RuntimeConflict("data_execution_fence_stale")
            else:
                op = await self.claim(operation_id, node_id=node_id, generation=generation, owner_epoch=owner_epoch)
            previous = await self.find(RuntimeExecutionFact, operation_id=op.id, sequence=sequence)
            incoming = detail or {}
            if previous:
                row = previous[0]
                if (row.phase, row.exec_ref, row.detail) != (phase, exec_ref, incoming):
                    raise RuntimeConflict("fact_sequence_conflict")
                return row
            facts = await self.find(RuntimeExecutionFact, operation_id=op.id)
            if facts and sequence <= max(x.sequence for x in facts):
                raise RuntimeConflict("fact_sequence_stale")
            fact = RuntimeExecutionFact(
                tenant_id=op.tenant_id,
                app_id=op.app_id,
                operation_id=op.id,
                node_id=node_id,
                generation=generation,
                owner_epoch=owner_epoch,
                sequence=sequence,
                phase=phase,
                exec_ref=exec_ref,
                detail=incoming,
            )
            session.add(fact)
            op.stage = phase
            await session.flush()
            return fact

    async def freeze_delivery(self, delivery: RuntimeDelivery):
        async with self.transaction():
            matches = await self.find(RuntimeDelivery, version_id=delivery.version_id)
            if matches:
                if matches[0].delivery_digest != delivery.delivery_digest:
                    raise RuntimeConflict("immutable_delivery_conflict")
                return matches[0]
            return await self.save(delivery)

    async def commit_route(self, operation_id: str, route: RuntimeRoute):
        async with self.transaction():
            op = await self.get(RuntimeOperation, operation_id, lock=True)
            facts = await self.find(RuntimeExecutionFact, operation_id=operation_id, phase="ready")
            if (
                op is None
                or not facts
                or (route.app_id, route.node_id, route.generation, route.owner_epoch)
                != (op.app_id, op.node_id, op.generation, op.owner_epoch)
            ):
                raise RuntimeConflict("route_without_ready_fact")
            if op.status in TERMINAL or op.deadline <= datetime.utcnow():
                raise RuntimeConflict("operation_expired")
            await self.claim(op.id, node_id=op.node_id, generation=op.generation, owner_epoch=op.owner_epoch)
            fact = max(facts, key=lambda x: x.sequence)
            if fact.exec_ref != route.exec_ref or fact.detail.get("target") != route.target:
                raise RuntimeConflict("route_target_mismatch")
            current = await self.find(RuntimeRoute, route_key=route.route_key, lock=True)
            if current:
                previous = current[0]
                if previous.generation > route.generation:
                    raise RuntimeConflict("route_generation_stale")
                route.id = previous.id
                route.route_epoch = previous.route_epoch + 1
            route.status = "serving"
            result = await self.save(route)
            op.stage = "serving"
            return result
