"""Human management boundary: global profiles and owner-scoped application materials."""

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeOperation,
    RuntimeProfile,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.repositories.runtime_object_store import RuntimeObjectStore
from bisheng.app_runtime.domain.services.runtime_offline_package import validate_offline_package
from bisheng.app_runtime.domain.services.runtime_profile_service import (
    RuntimeProfileService,
    require_natural_owner,
    require_platform_super,
)
from bisheng.common.services.config_service import settings
from bisheng.permission.application.identity import resolve_permission_actor


class RuntimeManagementService:
    def __init__(self, repository=None, objects=None):
        self.repo = repository or RuntimeDeliveryRepository()
        self.objects = objects or RuntimeObjectStore()

    async def owner(self, app_id, actor):
        app = await self.repo.get_application(app_id)
        if app is None or app.state == "deleted":
            raise RuntimeConflict("natural_owner_required")
        require_natural_owner(app, await resolve_permission_actor(actor))
        return app

    async def import_materials(self, stream, *, app_id, profile_reference, platform, sha256, actor, public=False):
        if public:
            identity = await require_platform_super(actor)
            tenant = identity.tenant_id
            app_id = ""
            scope = "public"
        else:
            app = await self.owner(app_id, actor)
            tenant = app.tenant_id
            scope = f"{tenant}/{app_id}"
        code, sep, revision = profile_reference.rpartition("@")
        if not sep or not revision.isdigit():
            raise RuntimeConflict("profile_revision_required")
        rows = await self.repo.find(RuntimeProfile, code=code, revision=int(revision))
        if not rows:
            raise RuntimeConflict("profile_unavailable")
        profile = await RuntimeProfileService(self.repo).resolve(rows[0].language, profile_reference, platform)
        with TemporaryDirectory(prefix="runtime-materials-") as tmp:
            path = Path(tmp) / "offline.tar.gz"
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as output:
                async for chunk in stream:
                    size += len(chunk)
                    if size > settings.app_runtime.artifact_max_mb * 1024 * 1024:
                        raise RuntimeConflict("artifact_size_limit")
                    output.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != sha256:
                raise RuntimeConflict("artifact_digest_mismatch")
            try:
                manifest = await asyncio.to_thread(validate_offline_package, path, profile)
            except (ValueError, KeyError, TypeError, __import__("tarfile").TarError) as exc:
                raise RuntimeConflict("offline_package_invalid") from exc
            rows = await self.repo.find(RuntimeArtifact, scope_key=scope, kind="offline", sha256=sha256)
            if rows:
                row = rows[0]
                if not public:
                    row.metadata_ = {**row.metadata_, "authorized_owner_user_id": app.owner_user_id, "enabled": True}
                    await self.repo.save(row)
                return {"artifact_id": row.id, "state": row.state}
            key = (
                f"runtime/public/{profile['profile_id']}/{platform}/{sha256}.tar.gz"
                if public
                else f"tenants/{tenant}/apps/{app_id}/artifacts/offline/{sha256}.tar.gz"
            )
            await self.objects.put(key, path)
            row = await self.repo.save(
                RuntimeArtifact(
                    tenant_id=tenant,
                    app_id=app_id,
                    scope_key=scope,
                    kind="offline",
                    visibility="public" if public else "private",
                    sha256=sha256,
                    size_bytes=size,
                    object_key=key,
                    platform=platform,
                    state="verified",
                    confirmed_at=datetime.utcnow(),
                    metadata_={
                        "authorized_owner_user_id": app.owner_user_id if not public else None,
                        "enabled": True,
                        "profile_id": profile["profile_id"],
                        "profile_digest": profile["profile_digest"],
                        "abi": profile["abi"],
                        "offline_validation": "required-during-prepare",
                        "files": manifest["files"],
                    },
                )
            )
        return {"artifact_id": row.id, "state": row.state}

    async def state(self, app_id, actor):
        app = await self.owner(app_id, actor)
        assignments = await self.repo.find(RuntimeAssignment, app_id=app_id)
        assignment = assignments[0] if assignments else None
        return {
            "app_id": app.id,
            "state": app.state,
            "current_version_id": app.current_version_id,
            "generation": assignment.generation if assignment else 0,
            "operation_id": assignment.active_operation_id if assignment else None,
        }

    async def snapshots(self, app_id, actor):
        await self.owner(app_id, actor)
        return [
            {
                "snapshot_id": row.id,
                "size_bytes": row.size_bytes,
                "sha256": row.sha256,
                "confirmed_at": row.confirmed_at,
                "metadata": row.metadata_,
            }
            for row in await self.repo.find(RuntimeArtifact, app_id=app_id, kind="snapshot", state="verified")
        ]

    async def operation(self, app_id, operation_id, actor):
        await self.owner(app_id, actor)
        row = await self.repo.get(RuntimeOperation, operation_id)
        if row is None or row.app_id != app_id:
            raise RuntimeConflict("operation_not_found")
        return {
            "operation_id": row.id,
            "kind": row.kind,
            "stage": row.stage,
            "status": row.status,
            "cleanup_status": row.cleanup_status,
            "failure": row.failure,
            "deadline": row.deadline,
        }

    async def cancel(self, app_id, operation_id, actor):
        await self.owner(app_id, actor)
        async with self.repo.transaction():
            row = await self.repo.get(RuntimeOperation, operation_id, lock=True)
            if row is None or row.app_id != app_id:
                raise RuntimeConflict("operation_not_found")
            if row.stage in {"serving", "retiring"}:
                raise RuntimeConflict("serving_operation_cannot_cancel")
            if row.status not in {"completed", "failed", "cancelled", "timed_out"}:
                row.payload = {**row.payload, "cancel_requested": True}
                await self.repo.save(row)
        return {"operation_id": row.id, "cancel_requested": True}

    async def restore(self, app_id, request, actor):
        app = await self.owner(app_id, actor)
        if not request.acknowledge_data_loss:
            raise RuntimeConflict("restore_acknowledgement_required")
        assignments = await self.repo.find(RuntimeAssignment, app_id=app_id)
        if not assignments or assignments[0].generation != request.expected_current_generation:
            raise RuntimeConflict("restore_generation_conflict")
        snapshot = await self.repo.get(RuntimeArtifact, request.snapshot_id)
        if snapshot is None or (snapshot.tenant_id, snapshot.app_id, snapshot.kind, snapshot.state) != (
            app.tenant_id,
            app.id,
            "snapshot",
            "verified",
        ):
            raise RuntimeConflict("snapshot_not_found")
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator

        version = await AppStateService._load_version(app_id, app.current_version_id)
        tier = await AppStateService._resolve_tier(version.tier_id)
        coordinator = RuntimeDeliveryCoordinator(self.repo)
        delivery = await coordinator.delivery(app_id, version.id)
        body = {
            "resolved_delivery": delivery.content,
            "snapshot_id": snapshot.id,
            "audit": {
                "actor_kind": "user",
                "actor_id": int(actor.user_id),
                "action": "app.data_restore",
                "acknowledge_data_loss": True,
            },
            "expected_app_state": app.state,
            "expected_current_version_id": app.current_version_id,
            "expected_pending_version_id": app.pending_version_id,
            "tier": {"memory_mb": tier["mem"], "cpu_millicores": int(tier["cpu"] * 1000)},
            "slug": app.slug,
            "port": version.manifest.get("port", 8080),
            "uses_sqlite": True,
            "resume_after_restore": app.state == "online",
            "auto_commit": app.state == "online",
        }
        op = await coordinator.submit(
            app, kind="restore", key="restore:" + request.idempotency_key, version_id=version.id, payload=body
        )
        from bisheng.app_runtime.domain.constants import AppAuditAction
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        await AppDataService._audit(
            AppAuditAction.DATA_RESTORE,
            app,
            actor,
            reason="snapshot restore requested",
            detail={
                "operation_id": op.id,
                "snapshot_id": snapshot.id,
                "expected_generation": request.expected_current_generation,
                "acknowledge_data_loss": True,
            },
        )
        await coordinator.inject_environment(
            op, capabilities=version.capabilities, environment=(version.injections or {}).get("env", {})
        )
        await coordinator.wake(op)
        return {"operation_id": op.id, "status": op.status}

    async def set_material_enabled(self, app_id, artifact_id, enabled, actor):
        app = await self.owner(app_id, actor)
        row = await self.repo.get(RuntimeArtifact, artifact_id)
        if row is None or (row.tenant_id, row.app_id, row.kind, row.visibility) != (
            app.tenant_id,
            app.id,
            "offline",
            "private",
        ):
            raise RuntimeConflict("artifact_not_found")
        row.metadata_ = {**row.metadata_, "enabled": enabled, "authorized_owner_user_id": app.owner_user_id}
        await self.repo.save(row)
        return {"artifact_id": row.id, "enabled": enabled}
