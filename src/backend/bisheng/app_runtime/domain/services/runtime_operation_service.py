"""Runtime coordinator: trusted scope, durable execution facts and read projections."""

from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeEgressPolicy,
    RuntimeExecutionFact,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
    RuntimeTransfer,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    TERMINAL,
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id


async def consume_runtime_nonce(key, ttl):
    from bisheng.core.cache.redis_manager import get_redis_client

    redis = await get_redis_client()
    await redis.acluster_nodes(key)
    return bool(await redis.async_connection.set(key, b"1", nx=True, ex=ttl))


class RuntimeOperationService:
    def __init__(self, repository=None, artifacts=None, *, nonce_store=consume_runtime_nonce, app_loader=None):
        self.repo = repository or RuntimeDeliveryRepository()
        self.artifacts = artifacts or RuntimeArtifactService(
            self.repo,
            artifact_limit=settings.app_runtime.artifact_max_mb * 1024 * 1024,
            snapshot_limit=settings.app_runtime.snapshot_max_mb * 1024 * 1024,
        )
        self.nonce_store = nonce_store
        self.app_loader = app_loader or self.repo.get_application

    async def create(self, request):
        if {"sealed_env", "runtime_env", "build_env"} & request.payload.keys():
            raise RuntimeConflict("caller_environment_refused")
        app = await self.app_loader(request.app_id)
        if app is None or app.state == "deleted":
            raise RuntimeConflict("app_not_found")
        digest = content_digest(request.model_dump(mode="json", exclude={"generation", "owner_epoch"}))
        existing = await self.repo.find(
            RuntimeOperation, scope_key=f"{app.tenant_id}/{app.id}", idempotency_key=request.idempotency_key
        )
        if existing:
            if existing[0].request_digest != digest:
                raise RuntimeConflict("idempotency_content_conflict")
            return await self.describe(existing[0])
        assignments = await self.repo.find(RuntimeAssignment, app_id=app.id)
        generation = max(request.generation, assignments[0].generation + 1 if assignments else 1)
        op = RuntimeOperation(
            tenant_id=app.tenant_id,
            app_id=app.id,
            scope_key=f"{app.tenant_id}/{app.id}",
            idempotency_key=request.idempotency_key,
            request_digest=digest,
            kind=request.kind,
            node_id=request.node_id,
            generation=generation,
            owner_epoch=request.owner_epoch,
            deadline=datetime.utcnow() + timedelta(seconds=settings.app_runtime.runtime_task_timeout_seconds),
            payload={**request.payload, "tenant_id": app.tenant_id},
            diagnostics_until=datetime.utcnow() + timedelta(days=settings.app_runtime.runtime_diagnostic_days),
            version_id=request.version_id,
            deployment_id=request.deployment_id,
        )
        async with self.repo.transaction():
            op = await self.repo.create_operation(op)
            if op.kind in {"prepare", "probe", "deploy", "preview", "restore", "migrate"}:
                tier = op.payload.get("tier", {})
                await self.repo.admit(
                    op.id,
                    memory_mb=int(tier.get("memory_mb", 1024)),
                    cpu_millicores=int(tier.get("cpu_millicores", 1000)),
                )
        return await self.describe(op)

    async def heartbeat(self, identity, body):
        if not identity.node_id:
            raise RuntimeConflict("node_identity_required")
        async with self.repo.transaction():
            node = await self.repo.get(RuntimeNode, identity.node_id, lock=True)
            if node and node.engine_id != body.engine_id:
                raise RuntimeConflict("engine_replacement_requires_operator")
            node = node or RuntimeNode(
                id=identity.node_id,
                engine_id=body.engine_id,
                platform=body.platform,
                memory_budget_mb=body.memory_budget_mb,
                cpu_budget_millicores=body.cpu_budget_millicores,
                heartbeat_at=datetime.utcnow(),
            )
            node.platform = body.platform
            node.memory_budget_mb = body.memory_budget_mb
            node.cpu_budget_millicores = body.cpu_budget_millicores
            node.heartbeat_at = datetime.utcnow()
            await self.repo.save(node)
        return {"node_id": node.id, "platform": node.platform}

    @asynccontextmanager
    async def scope(self, identity, *, operation_id=None, transfer_id=None):
        model = RuntimeOperation if operation_id else RuntimeTransfer
        with bypass_tenant_filter():
            row = await self.repo.get(model, operation_id or transfer_id)
        if row is None or not identity.node_id or row.node_id != identity.node_id:
            raise RuntimeConflict("operation_not_found")
        token = current_tenant_id.set(row.tenant_id)
        try:
            yield row
        finally:
            current_tenant_id.reset(token)

    async def describe(self, op):
        facts = await self.repo.find(RuntimeExecutionFact, operation_id=op.id)
        result = max(facts, key=lambda f: f.sequence).detail if facts else {}
        document = op.model_dump(mode="json")
        if document["payload"].get("sealed_env"):
            from bisheng.app_runtime.domain.services.runtime_payload import unseal

            document["payload"] = {**document["payload"], "runtime_env": unseal(document["payload"]["sealed_env"])}
            document["payload"].pop("sealed_env", None)
        if (
            op.kind in {"deploy", "restore", "migrate"}
            and "expected_app_state" in op.payload
            and op.stage not in {"serving", "retiring", "completed"}
        ):
            app = await self.app_loader(op.app_id)
            if app is None or (app.state, app.current_version_id, app.pending_version_id) != (
                op.payload["expected_app_state"],
                op.payload.get("expected_current_version_id"),
                op.payload.get("expected_pending_version_id"),
            ):
                document["payload"] = {**document["payload"], "cancel_requested": True}
        routes = await self.repo.find(RuntimeRoute, operation_id=op.id, status="serving")
        execution = (
            {"exec_ref": routes[0].exec_ref, "target": routes[0].target, "route_epoch": routes[0].route_epoch}
            if routes
            else None
        )
        return {
            "execution": execution,
            **document,
            "operation_id": op.id,
            "result": result,
            "fact_sequence": max((f.sequence for f in facts), default=0),
        }

    async def claim(self, op, identity, *, command_nonce=None):
        if op.payload.get("environment_required") and not op.payload.get("sealed_env"):
            raise RuntimeConflict("environment_not_ready")
        if command_nonce and not await self.nonce_store(f"runtime:v2:command:{identity.key_id}:{command_nonce}", 3600):
            raise RuntimeConflict("command_replayed")
        if op.kind in {"prepare", "probe", "preview", "deploy", "restore", "migrate"}:
            reservations = await self.repo.find(RuntimeCapacityReservation, operation_id=op.id)
            if not reservations or reservations[0].state not in {"held", "active"}:
                raise RuntimeConflict("capacity_reservation_required")
        return await self.describe(
            await self.repo.claim(op.id, node_id=identity.node_id, generation=op.generation, owner_epoch=op.owner_epoch)
        )

    async def fact(self, op, identity, body):
        if body.node_id != identity.node_id:
            raise RuntimeConflict("node_identity_mismatch")
        if body.phase == "ready" and op.kind in {"deploy", "restore", "preview"}:
            target = body.detail.get("target", {})
            try:
                host = ipaddress.ip_address(target["host"])
                port = int(target["port"])
                if (
                    host.is_loopback
                    or host.is_link_local
                    or host.is_reserved
                    or host.is_multicast
                    or host.is_unspecified
                    or not host.is_private
                    or not 1 <= port <= 65535
                ):
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise RuntimeConflict("invalid_runtime_target") from None
        if "diagnostic_tail" in body.detail:
            body.detail["diagnostic_tail"] = str(body.detail["diagnostic_tail"])[-16384:]
        async with self.repo.transaction():
            fact = await self.repo.record_fact(op.id, **body.model_dump())
            if body.detail.get("legacy_build_state"):
                if (
                    op.kind != "prepare"
                    or op.payload.get("delivery", {}).get("mode") != "source-image"
                    or body.phase != "preparing"
                ):
                    raise RuntimeConflict("legacy_build_state_refused")
                state = body.detail["legacy_build_state"]
                if state not in {"started", "finished"}:
                    raise RuntimeConflict("legacy_build_state_refused")
                op = await self.repo.get(RuntimeOperation, op.id, lock=True)
                if op.payload.get("legacy_build_state") == "finished" and state != "finished":
                    raise RuntimeConflict("legacy_build_state_refused")
                op.payload = {**op.payload, "legacy_build_state": state}
                await self.repo.save(op)
            if body.phase == "maintenance":
                from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService

                await RuntimeProjectionService(self.repo).block(op.app_id, "maintenance")
            if body.phase == "ready" and op.kind == "preview":
                from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

                op = await self.repo.get(RuntimeOperation, op.id, lock=True)
                expiry = datetime.fromisoformat(op.payload["preview_expires_at"])
                op.deadline = expiry
                from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeStorageBinding

                for binding in await self.repo.find(RuntimeStorageBinding, operation_id=op.id, lock=True):
                    binding.expires_at = expiry
                    await self.repo.save(binding)
                for policy in await self.repo.find(RuntimeEgressPolicy, operation_id=op.id, lock=True):
                    policy.not_after = expiry
                    await self.repo.save(policy)

                await self.repo.save(op)
                await self.repo.commit_route(
                    op.id,
                    RuntimeRoute(
                        tenant_id=op.tenant_id,
                        app_id=op.app_id,
                        operation_id=op.id,
                        route_key="preview:" + op.payload["session_id"],
                        version_id=op.version_id,
                        node_id=op.node_id,
                        exec_ref=body.exec_ref,
                        generation=op.generation,
                        owner_epoch=op.owner_epoch,
                        target=body.detail["target"],
                    ),
                )

        if body.phase in TERMINAL:
            op = await self.repo.get(RuntimeOperation, op.id, lock=True)
            op.status = body.phase
            op.cleanup_status = (
                ("storage_pending" if op.kind in {"preview", "destroy"} else "complete")
                if body.detail.get("cleanup_complete")
                else "pending"
            )
            op.failure = (
                {
                    key: value
                    for key, value in body.detail.items()
                    if key in {"reason", "failed_stage", "maintenance", "data_may_have_changed", "diagnostic_tail"}
                }
                if body.phase != "completed"
                else {}
            )
            await self.repo.save(op)
            if body.detail.get("stopped"):
                await self.repo.release(op.id, stopped=True)
                from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService

                await RuntimeProjectionService(self.repo).terminal(op, body.detail)
        if (
            body.phase in TERMINAL
            and body.detail.get("stopped")
            and body.detail.get("cleanup_complete")
            and op.kind in {"preview", "destroy"}
        ):
            from loguru import logger

            from bisheng.app_runtime.domain.services.runtime_cleanup_service import RuntimeCleanupService

            try:
                await RuntimeCleanupService(self.repo).cleanup(op)
                op = await self.repo.get(RuntimeOperation, op.id, lock=True)
                op.cleanup_status = "complete"
                await self.repo.save(op)
            except Exception:
                logger.exception("runtime storage cleanup pending for operation {}", op.id)
        if body.phase == "ready" and op.kind in {"deploy", "restore"} and op.payload.get("auto_commit"):
            from bisheng.app_runtime.domain.services.app_state_service import AppStateService

            await AppStateService.commit_runtime_delivery(self.repo, op, {"result": body.detail})
        return fact.model_dump(mode="json")

    async def node_plan(self, identity):
        if not identity.node_id:
            raise RuntimeConflict("node_identity_required")
        with bypass_tenant_filter():
            await self.repo.purge_diagnostics(identity.node_id, datetime.utcnow())
            operations = await self.repo.node_operations(identity.node_id)
            assignments = await self.repo.find(RuntimeAssignment, node_id=identity.node_id, limit=10000)
            active = {x.active_operation_id for x in assignments}
            result = []
            for op in operations:
                if op.payload.get("environment_required") and not op.payload.get("sealed_env"):
                    continue
                if op.status not in TERMINAL or op.id in active or op.cleanup_status != "complete":
                    result.append(await self.describe(op))
            return {"operations": result, "capacity": await self.repo.capacity_snapshot(identity.node_id)}

    async def route(self, route_key):
        with bypass_tenant_filter():
            rows = await self.repo.find(RuntimeRoute, route_key=route_key)
        if not rows:
            return {"decision": "transition", "phase": "not_ready"}
        route = rows[0]
        if route.status != "serving":
            return {"decision": "transition", "phase": route.status}
        return {
            "decision": "allow",
            "app_id": route.app_id,
            "version_id": route.version_id,
            "generation": route.generation,
            "route_epoch": route.route_epoch,
            "target": route.target,
            "phase": "running",
        }

    async def policies(self, identity):
        if not identity.node_id:
            raise RuntimeConflict("node_identity_required")
        now = datetime.utcnow()
        items = []
        with bypass_tenant_filter():
            for row in await self.repo.node_policies(identity.node_id, now):
                if row.revoked_at or row.not_after <= now:
                    continue
                op = await self.repo.get(RuntimeOperation, row.operation_id)
                if op is None or op.node_id != identity.node_id:
                    continue
                if op.payload.get("cancel_requested"):
                    continue
                if row.phase == "runtime" and op.kind in {"deploy", "restore"}:
                    routes = await self.repo.find(RuntimeRoute, route_key=f"app:{op.app_id}")
                    serving = bool(routes and routes[0].status == "serving" and routes[0].operation_id == op.id)
                    assignments = await self.repo.find(RuntimeAssignment, app_id=op.app_id)
                    candidate = bool(
                        op.status not in TERMINAL
                        and op.deadline > now
                        and assignments
                        and assignments[0].active_operation_id == op.id
                    )
                    if not (serving or candidate):
                        continue
                elif op.status in TERMINAL or op.deadline <= now:
                    continue
                items.append(
                    {
                        "principal": row.principal_id,
                        "credential_hash": row.credential_hash,
                        "destinations": row.destinations,
                        "phase": row.phase,
                        "policy_epoch": row.policy_epoch,
                        "not_after": min(row.not_after, now + timedelta(seconds=5)).replace(tzinfo=UTC).timestamp(),
                    }
                )
        return {
            "revision": content_digest(items),
            "policies": items,
            "not_after": (now + timedelta(seconds=5)).replace(tzinfo=UTC).timestamp(),
        }

    async def application(self, identity, app_id):
        with bypass_tenant_filter():
            assignments = await self.repo.find(RuntimeAssignment, app_id=app_id)
            if not assignments or assignments[0].node_id != identity.node_id:
                raise RuntimeConflict("application_not_found")
            app = await self.app_loader(app_id)
            if app is None or app.state == "deleted":
                raise RuntimeConflict("application_not_found")
            routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app_id}")
            route = routes[0] if routes else None
            return {
                "app_id": app.id,
                "tenant_id": app.tenant_id,
                "node_id": identity.node_id,
                "generation": assignments[0].generation,
                "owner_epoch": assignments[0].owner_epoch,
                "phase": route.status if route else app.state,
                "exec_ref": route.exec_ref if route else None,
                "runtime_user": (await self.repo.get(RuntimeOperation, route.operation_id))
                .payload.get("resolved_delivery", {})
                .get("profile", {})
                if route and route.operation_id
                else {},
                "operation_id": route.operation_id if route else None,
                "target": route.target if route else None,
            }

    async def observation(self, identity, body):
        with bypass_tenant_filter():
            routes = await self.repo.find(RuntimeRoute, route_key=f"app:{body.app_id}")
        if not routes:
            raise RuntimeConflict("route_not_found")
        route = routes[0]
        if (route.node_id, route.operation_id, route.exec_ref, route.generation, route.route_epoch) != (
            identity.node_id,
            body.operation_id,
            body.exec_ref,
            body.generation,
            body.route_epoch,
        ):
            raise RuntimeConflict("observation_fence_mismatch")
        token = current_tenant_id.set(route.tenant_id)
        try:
            if body.ready or route.status != "serving":
                return {"accepted": True}
            app = await self.app_loader(route.app_id)
            if app is None or app.state != "online" or app.current_version_id != route.version_id:
                return {"accepted": False}
            from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator

            await RuntimeDeliveryCoordinator(self.repo).recover(app, route, running=body.running)
            return {"accepted": True}
        finally:
            current_tenant_id.reset(token)
