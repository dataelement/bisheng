"""Explicit owner-confirmed same-version rebuild, using the existing operation ledger."""

import hashlib
from copy import deepcopy
from datetime import datetime

from bisheng.app_publish.application.runtime_secrets import formal_snapshot
from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeDelivery,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    TERMINAL,
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError, AppSecretRebuildConflictError
from bisheng.common.services.config_service import settings
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion


class AppSecretRebuildService:
    def __init__(self, repository=None):
        self.repo = repository or RuntimeDeliveryRepository()
        self.coordinator = RuntimeDeliveryCoordinator(self.repo)

    @staticmethod
    def _owner(app, actor):
        if (
            app is None
            or not isinstance(actor, UserPayload)
            or app.tenant_id != actor.tenant_id
            or actor.user_id != app.owner_user_id
        ):
            raise AppPublishOwnerOnlyError()

    async def rebuild_current(self, app_id, *, request, actor):
        # Replay is checked after current authorization, before new-attempt CAS.
        app = await self.repo.get(App, app_id)
        self._owner(app, actor)
        key = "secret-rebuild:" + hashlib.sha256(request.request_id.encode()).hexdigest()
        digest = content_digest(request.model_dump(mode="json"))
        existing = await self.repo.find(RuntimeOperation, scope_key=f"{app.tenant_id}/{app.id}", idempotency_key=key)
        if existing:
            op = existing[0]
            if op.payload.get("confirmation_digest") != digest or op.payload.get("purpose") != "config_restart":
                raise AppSecretRebuildConflictError(reason="request_reused")
            return {"operation_id": op.id, "status": op.status}
        try:
            async with self.repo.transaction() as session:
                app = await self.repo.get(App, app_id, lock=True)
                self._owner(app, actor)
                # A concurrent identical confirmation may have committed while
                # this request waited for App. Replay it before fresh-attempt CAS.
                replay = await self.repo.find(
                    RuntimeOperation, scope_key=f"{app.tenant_id}/{app.id}", idempotency_key=key
                )
                if replay:
                    if (
                        replay[0].payload.get("confirmation_digest") != digest
                        or replay[0].payload.get("purpose") != "config_restart"
                    ):
                        raise AppSecretRebuildConflictError(reason="request_reused")
                    return {"operation_id": replay[0].id, "status": replay[0].status}
                if app.state != "online" or app.current_version_id != request.expected_version_id:
                    raise AppSecretRebuildConflictError(reason="application_changed")
                routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app.id}")
                if not routes:
                    raise AppSecretRebuildConflictError(reason="runtime_unknown")
                node = await self.repo.get(RuntimeNode, routes[0].node_id, lock=True)
                assignments = await self.repo.find(RuntimeAssignment, app_id=app.id, lock=True)
                routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app.id}", lock=True)
                route = routes[0]
                if (
                    node is None
                    or node.status != "ready"
                    or (datetime.utcnow() - node.heartbeat_at).total_seconds()
                    > settings.app_runtime.runtime_node_max_age_seconds
                    or route.status != "serving"
                    or route.version_id != app.current_version_id
                    or route.route_epoch != request.expected_route_epoch
                    or not assignments
                    or assignments[0].node_id != node.id
                    or assignments[0].data_operation_id
                ):
                    raise AppSecretRebuildConflictError(reason="runtime_changed")
                origin = await self.repo.get(RuntimeOperation, route.operation_id)
                if (
                    origin is None
                    or origin.app_id != app.id
                    or origin.tenant_id != app.tenant_id
                    or origin.version_id != app.current_version_id
                    or origin.stage != "serving"
                    or origin.generation != route.generation
                    or origin.owner_epoch != route.owner_epoch
                    or origin.cleanup_status != "complete"
                    or not origin.payload.get("sealed_env")
                ):
                    raise AppSecretRebuildConflictError(reason="runtime_unknown")
                for candidate in await self.repo.find(RuntimeOperation, app_id=app.id):
                    if (
                        candidate.id != origin.id
                        and candidate.kind in {"deploy", "restore", "stop", "destroy", "migrate", "data"}
                        and (candidate.status not in TERMINAL or candidate.cleanup_status != "complete")
                    ):
                        raise AppSecretRebuildConflictError(reason="operation_in_progress")
                version = await self.repo.get(AppVersion, app.current_version_id)
                deliveries = await self.repo.find(RuntimeDelivery, app_id=app.id, version_id=app.current_version_id)
                if (
                    version is None
                    or version.app_id != app.id
                    or not deliveries
                    or deliveries[0].content != origin.payload.get("resolved_delivery")
                    or not origin.payload.get("tier")
                ):
                    raise AppSecretRebuildConflictError(reason="delivery_unknown")
                snapshot = await formal_snapshot(
                    app, version, session=session, expected_revision=request.expected_config_revision
                )
                payload = {
                    "purpose": "config_restart",
                    "auto_commit": True,
                    "confirmation_digest": digest,
                    "resolved_delivery": deepcopy(origin.payload["resolved_delivery"]),
                    "tier": deepcopy(origin.payload["tier"]),
                    "slug": app.slug,
                    "version_no": version.version_no,
                    "port": version.manifest.get("port", 8080),
                    "uses_sqlite": origin.payload.get("uses_sqlite", True),
                    "egress_domains": deepcopy(origin.payload.get("egress_domains", [])),
                    "migration_plan": [],
                    "preserve_pending_version": True,
                    "expected_app_state": app.state,
                    "expected_current_version_id": app.current_version_id,
                    "expected_pending_version_id": app.pending_version_id,
                    "origin_operation_id": origin.id,
                    "origin_exec_ref": route.exec_ref,
                    "origin_route_id": route.id,
                    "origin_route_epoch": route.route_epoch,
                    "secret_config_revision": snapshot.revision,
                    "sensitive_env_names": snapshot.sensitive_env_names,
                    "approved_declaration_digest": snapshot.declaration_digest,
                }
                op = await self.coordinator.submit(app, kind="deploy", key=key, version_id=version.id, payload=payload)
                await self.coordinator.inject_environment(
                    op,
                    capabilities=version.capabilities,
                    environment=(version.injections or {}).get("env", {}),
                    secret_snapshot=snapshot,
                )
                from bisheng.app_publish.domain.repositories.app_secret_repository import AppSecretConfigRepository

                await AppSecretConfigRepository().append_audit(
                    session,
                    app,
                    actor,
                    name=None,
                    action="app.secret.rebuild",
                    revision=snapshot.revision,
                    present=None,
                )
        except RuntimeConflict as exc:
            raise AppSecretRebuildConflictError(reason=str(exc)) from None
        await self.coordinator.wake(op)
        return {"operation_id": op.id, "status": op.status}
