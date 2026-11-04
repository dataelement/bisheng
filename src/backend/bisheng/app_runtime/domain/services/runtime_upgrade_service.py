"""Import deployment bindings without changing any historical AppVersion fields."""

from datetime import datetime

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeDelivery,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest


class RuntimeUpgradeService:
    def __init__(self, repository=None):
        self.repo = repository or RuntimeDeliveryRepository()

    async def import_binding(self, body, actor):
        app = await AppStateService._load(body["app_id"])
        await AppStateService._require_operator(app, actor)
        from bisheng.app_runtime.domain.services.runtime_control_client import RuntimeControlClient

        live = await RuntimeControlClient().inventory()
        entries = [item for item in live["applications"] if item["app_id"] == app.id]
        if len(entries) != 1 or live["node_id"] != body["node_id"] or live["engine_id"] != body["engine_id"]:
            raise RuntimeConflict("upgrade_inventory_changed")
        if any(
            entries[0].get(key) != body.get(key)
            for key in (
                "version_id",
                "generation",
                "exec_ref",
                "image_id",
                "platform",
                "running",
                "labels",
                "tier",
                "target",
            )
        ):
            raise RuntimeConflict("upgrade_inventory_changed")
        version = await AppStateService._load_version(app.id, body["version_id"])
        if app.current_version_id != version.id:
            raise RuntimeConflict("upgrade_current_version_mismatch")
        labels = body.get("labels", {})
        if (
            labels.get("bisheng.app.id") != app.id
            or labels.get("bisheng.version.id") != version.id
            or labels.get("bisheng.managed") != "true"
        ):
            raise RuntimeConflict("upgrade_execution_labels_mismatch")
        node = await self.repo.get(RuntimeNode, body["node_id"])
        if node is None or node.engine_id != body["engine_id"] or node.platform != body["platform"]:
            raise RuntimeConflict("upgrade_engine_mismatch")
        if entries[0].get("storage_bucket", "bisheng-apps") != "bisheng-apps":
            raise RuntimeConflict("legacy_storage_bucket_migration_required")
        reference = body["image_id"]
        if not __import__("re").fullmatch(r"sha256:[0-9a-f]{64}", reference):
            raise RuntimeConflict("upgrade_image_identity_required")
        content = {
            "mode": "source-image",
            "image_ref": reference,
            "image_id": reference,
            "platform": node.platform,
            "runtime": version.runtime,
            "legacy_code_object_key": version.code_object_key,
            "legacy_storage_prefix": f"apps/{app.id}/attachments/",
        }
        if not body.get("apply"):
            return {
                "app_id": app.id,
                "version_id": version.id,
                "can_import": True,
                "running": body["running"],
                "requires_rebind": True,
            }
        if not body.get("acknowledge_maintenance"):
            raise RuntimeConflict("upgrade_maintenance_acknowledgement_required")
        async with self.repo.transaction():
            assignments = await self.repo.find(RuntimeAssignment, app_id=app.id, lock=True)
            if assignments:
                return {"app_id": app.id, "already_imported": True}
            frozen = await self.repo.freeze_delivery(
                RuntimeDelivery(
                    tenant_id=app.tenant_id,
                    app_id=app.id,
                    version_id=version.id,
                    execution_mode="source-image",
                    resolved_platform=node.platform,
                    delivery_digest=content_digest(content),
                    content=content,
                )
            )
            # Mark the old execution as a protected binding. v2 is not allowed to adopt it as a new candidate.
            operation = await self.repo.save(
                RuntimeOperation(
                    tenant_id=app.tenant_id,
                    app_id=app.id,
                    scope_key=f"{app.tenant_id}/{app.id}",
                    idempotency_key="legacy:" + version.id,
                    request_digest=content_digest(body),
                    version_id=version.id,
                    kind="deploy",
                    node_id=node.id,
                    generation=int(body["generation"]),
                    owner_epoch=1,
                    stage="completed",
                    status="completed",
                    cleanup_status="complete",
                    deadline=datetime.utcnow(),
                    payload={"legacy_exec_ref": body["exec_ref"], "resolved_delivery": frozen.content},
                )
            )
            await self.repo.save(
                RuntimeAssignment(
                    tenant_id=app.tenant_id,
                    app_id=app.id,
                    node_id=node.id,
                    generation=operation.generation,
                    active_operation_id=operation.id,
                )
            )
            await self.repo.save(
                RuntimeRoute(
                    tenant_id=app.tenant_id,
                    app_id=app.id,
                    operation_id=operation.id,
                    route_key=f"app:{app.id}",
                    version_id=version.id,
                    node_id=node.id,
                    exec_ref=body["exec_ref"],
                    generation=operation.generation,
                    owner_epoch=1,
                    status="maintenance",
                    target=body["target"],
                )
            )
            if body["running"]:
                await self.repo.save(
                    RuntimeCapacityReservation(
                        tenant_id=app.tenant_id,
                        app_id=app.id,
                        operation_id=operation.id,
                        node_id=node.id,
                        purpose="legacy",
                        memory_mb=body["tier"]["memory_mb"],
                        cpu_millicores=body["tier"]["cpu_millicores"],
                        state="active",
                    )
                )
        return {"app_id": app.id, "imported": True, "requires_rebind": True}

    async def rebind(self, app_id, actor):
        app = await AppStateService._load(app_id)
        await AppStateService._require_operator(app, actor)
        version = await AppStateService._load_version(app_id, app.current_version_id)
        tier = await AppStateService._resolve_tier(version.tier_id)
        return await RuntimeDeliveryCoordinator(self.repo).deploy(app, version, tier, preserve_pending=True)
