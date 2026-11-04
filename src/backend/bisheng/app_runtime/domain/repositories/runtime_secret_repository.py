"""Read only route-bound snapshots and explicit rebuild transaction reads."""

from sqlmodel import select

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation, RuntimeRoute
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.app import App
from bisheng.database.models.app_instance import AppInstance


class RuntimeSecretRepository:
    @staticmethod
    async def running_context(session, app_id):
        app = (await session.exec(select(App).where(App.id == app_id))).first()
        if app is None or app.tenant_id != get_current_tenant_id() or app.state != "online":
            return None
        route = (await session.exec(select(RuntimeRoute).where(RuntimeRoute.route_key == f"app:{app_id}"))).first()
        instance = (await session.exec(select(AppInstance).where(AppInstance.app_id == app_id))).first()
        if (
            route is None
            or route.status != "serving"
            or route.tenant_id != app.tenant_id
            or route.version_id != app.current_version_id
            or instance is None
            or instance.phase != "running"
            or instance.tenant_id != app.tenant_id
            or instance.exec_ref != route.exec_ref
            or instance.version_id != route.version_id
        ):
            return None
        op = (await session.exec(select(RuntimeOperation).where(RuntimeOperation.id == route.operation_id))).first()
        if (
            op is None
            or op.app_id != app.id
            or op.tenant_id != app.tenant_id
            or op.version_id != route.version_id
            or op.node_id != route.node_id
            or op.status not in {"running", "completed"}
            or op.stage not in {"serving", "completed"}
            or (op.stage == "completed" and op.status != "completed")
            or op.generation != route.generation
            or op.owner_epoch != route.owner_epoch
            or not op.payload.get("sealed_env")
        ):
            return None
        return route, op

    @staticmethod
    async def latest_rebuild(session, app_id):
        operations = (
            await session.exec(
                select(RuntimeOperation)
                .where(RuntimeOperation.app_id == app_id, RuntimeOperation.kind == "deploy")
                .order_by(RuntimeOperation.create_time.desc(), RuntimeOperation.id.desc())
            )
        ).all()
        for op in operations:
            if op.payload.get("purpose") == "config_restart":
                return {
                    "operation_id": op.id,
                    "status": op.status,
                    "stage": op.stage,
                    "failure_reason": op.failure.get("reason")
                    if op.status in {"failed", "cancelled", "timed_out"}
                    else None,
                }
        return None
