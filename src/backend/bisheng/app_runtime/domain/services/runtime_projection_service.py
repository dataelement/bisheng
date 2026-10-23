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

    async def activate(self, op, ready):
        async with self.repo.transaction():
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
                    row.state = "active" if row.operation_id == op.id else "revoked"
                    await self.repo.save(row)
            for row in await self.repo.find(RuntimeCapacityReservation, operation_id=op.id, lock=True):
                row.state = "active"
                await self.repo.save(row)

    async def terminal(self, op, detail):
        if not detail.get("stopped"):
            return
        async with self.repo.transaction():
            if not detail.get("serving"):
                for model in (RuntimeCredentialBinding, RuntimeStorageBinding):
                    for row in await self.repo.find(model, operation_id=op.id, lock=True):
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
