"""Backend read projections and generation-bound handle activation."""

from datetime import datetime

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeCapacityReservation,
    RuntimeCredentialBinding,
    RuntimeEgressPolicy,
    RuntimeOperation,
    RuntimeRoute,
    RuntimeStorageBinding,
)
from bisheng.open_api.application.runtime_credentials import revoke_runtime_binding


class RuntimeProjectionService:
    def __init__(self, repository):
        self.repo = repository

    async def block(self, app_id, status):
        async with self.repo.transaction():
            for route in await self.repo.find(RuntimeRoute, route_key=f"app:{app_id}", lock=True):
                route.status = status
                route.route_epoch += 1
                await self.repo.save(route)
            for policy in await self.repo.find(RuntimeEgressPolicy, app_id=app_id, lock=True):
                policy.revoked_at = datetime.utcnow()
                await self.repo.save(policy)

    async def block_for_config_restart(self, operation, *, sequence):
        """Only this operation's exact origin transition can be replayed."""
        from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

        async with self.repo.transaction():
            op = await self.repo.get(RuntimeOperation, operation.id, lock=True)
            transition = op.payload.get("maintenance_transition")
            if transition:
                if transition["fact_sequence"] != sequence:
                    raise RuntimeConflict("maintenance_transition_conflict")
                return
            routes = await self.repo.find(RuntimeRoute, route_key=f"app:{op.app_id}", lock=True)
            route = routes[0] if routes else None
            if (
                route is None
                or route.id != op.payload["origin_route_id"]
                or route.operation_id != op.payload["origin_operation_id"]
                or route.exec_ref != op.payload["origin_exec_ref"]
                or route.route_epoch != op.payload["origin_route_epoch"]
                or route.status != "serving"
            ):
                raise RuntimeConflict("rebuild_origin_changed")
            before = route.route_epoch
            await self.block(op.app_id, "maintenance")
            op.payload = {
                **op.payload,
                "maintenance_transition": {
                    "fact_sequence": sequence,
                    "route_id": route.id,
                    "before_epoch": before,
                    "after_epoch": before + 1,
                },
            }
            await self.repo.save(op)

    async def verify_config_restart_origin(self, op):
        from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

        routes = await self.repo.find(RuntimeRoute, route_key=f"app:{op.app_id}", lock=True)
        route = routes[0] if routes else None
        transition = op.payload.get("maintenance_transition")
        expected_epoch = transition["after_epoch"] if transition else op.payload["origin_route_epoch"]
        expected_status = "maintenance" if transition else "serving"
        if (
            route is None
            or route.id != op.payload["origin_route_id"]
            or route.operation_id != op.payload["origin_operation_id"]
            or route.exec_ref != op.payload["origin_exec_ref"]
            or route.route_epoch != expected_epoch
            or route.status != expected_status
            or route.version_id != op.version_id
        ):
            raise RuntimeConflict("rebuild_origin_changed")

    async def activate(self, op, ready):
        async with self.repo.transaction() as session:
            current = await self.repo.get(RuntimeOperation, op.id, lock=True)
            if current.stage == "serving":
                return
            route = RuntimeRoute(
                tenant_id=op.tenant_id,
                app_id=op.app_id,
                operation_id=op.id,
                route_key=f"app:{op.app_id}",
                version_id=op.version_id,
                node_id=op.node_id,
                generation=op.generation,
                owner_epoch=op.owner_epoch,
                exec_ref=ready["result"]["exec_ref"],
                target=ready["result"]["target"],
            )
            previous = await self.repo.find(RuntimeRoute, route_key=f"app:{op.app_id}", lock=True)
            if previous and ready["result"].get("writers_stopped") and previous[0].operation_id != op.id:
                await self.repo.release(previous[0].operation_id, stopped=True)
            await self.repo.commit_route(op.id, route)
            for model in (RuntimeCredentialBinding, RuntimeStorageBinding):
                for row in await self.repo.find(model, app_id=op.app_id, lock=True):
                    if model is RuntimeStorageBinding and row.namespace != "production":
                        continue
                    if model is RuntimeCredentialBinding and row.operation_id != op.id:
                        # Production activation must not cancel another preview.
                        origin = await self.repo.get(RuntimeOperation, row.operation_id)
                        if origin and origin.kind == "preview":
                            continue
                        await revoke_runtime_binding(session, row, op, reason="runtime_replaced")
                    else:
                        row.state = "active" if row.operation_id == op.id else "revoked"
                        await self.repo.save(row)
            for row in await self.repo.find(RuntimeCapacityReservation, operation_id=op.id, lock=True):
                row.state = "active"
                await self.repo.save(row)

    async def terminal(self, op, detail):
        if not detail.get("stopped"):
            return
        async with self.repo.transaction() as session:
            if not detail.get("serving"):
                for model in (RuntimeCredentialBinding, RuntimeStorageBinding):
                    filters = {"app_id": op.app_id} if op.kind in {"stop", "destroy"} else {"operation_id": op.id}
                    for row in await self.repo.find(model, **filters, lock=True):
                        if model is RuntimeCredentialBinding:
                            origin = await self.repo.get(RuntimeOperation, row.operation_id)
                            if op.kind == "stop" and origin and origin.kind == "preview":
                                continue
                            await revoke_runtime_binding(session, row, op, reason="runtime_" + op.kind)
                        else:
                            if op.kind == "stop" and row.namespace != "production":
                                continue
                            row.state = "revoked"
                            await self.repo.save(row)
            if op.kind == "restore" and op.status == "completed" and not op.payload.get("resume_after_restore", True):
                for route in await self.repo.find(RuntimeRoute, route_key=f"app:{op.app_id}", lock=True):
                    route.status = "stopped"
                    await self.repo.save(route)
            if op.kind == "preview":
                for route in await self.repo.find(RuntimeRoute, operation_id=op.id, lock=True):
                    route.status = "stopped"
                    route.route_epoch += 1
                    await self.repo.save(route)
            if op.kind in {"stop", "destroy"}:
                for row in await self.repo.find(RuntimeCapacityReservation, app_id=op.app_id, lock=True):
                    if row.purpose in {"deploy", "legacy", "restore", "migrate"}:
                        row.state = "released"
                        await self.repo.save(row)
