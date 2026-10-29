"""F055/F054 adapter for immutable deliveries and durable runtime operations."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeDelivery,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
from bisheng.app_runtime.domain.services.runtime_control_client import RuntimeControlClient
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.common.errcode.app_factory import (
    AppCapacityInsufficientError,
    AppOrchestratorUnavailableError,
    AppProbeFailedError,
)
from bisheng.common.errcode.app_publish import AppDependencyBuildFailedError
from bisheng.common.services.config_service import settings


class RuntimeDeliveryCoordinator:
    def __init__(self, repository=None, control=None):
        self.repo = repository or RuntimeDeliveryRepository()
        self.operations = RuntimeOperationService(self.repo)
        self.control = control or RuntimeControlClient()

    async def node(self, app):
        assignments = await self.repo.find(RuntimeAssignment, app_id=app.id)
        ident = assignments[0].node_id if assignments else settings.app_runtime.runtime_default_node_id
        node = await self.repo.get(RuntimeNode, ident) if ident else None
        if (
            node is None
            or (datetime.utcnow() - node.heartbeat_at).total_seconds()
            > settings.app_runtime.runtime_node_max_age_seconds
        ):
            raise AppOrchestratorUnavailableError(reason="node_stale")
        return node, assignments[0] if assignments else None

    async def submit(self, app, *, kind, key, version_id="", deployment_id="", payload=None):
        node, assignment = await self.node(app)
        payload = dict(payload or {})
        if kind in {"probe", "preview", "deploy", "restore"}:
            payload["environment_required"] = True
        try:
            doc = await self.operations.create(
                OperationInput(
                    app_id=app.id,
                    kind=kind,
                    idempotency_key=key,
                    version_id=version_id,
                    deployment_id=deployment_id,
                    node_id=node.id,
                    generation=assignment.generation + 1 if assignment else 1,
                    owner_epoch=assignment.owner_epoch if assignment else 1,
                    payload=payload or {},
                )
            )
        except RuntimeConflict as exc:
            if str(exc) in {"capacity_exhausted", "node_stale"}:
                raise AppCapacityInsufficientError() from exc
            raise
        return await self.repo.get(RuntimeOperation, doc["operation_id"])

    async def wake(self, op):
        try:
            await self.control.wakeup(op.id)
        except Exception:
            # A committed operation is discoverable from the node plan even if wakeup fails.
            logger.exception("runtime wakeup unavailable; operation {} remains durable", op.id)

    async def wait(self, op, *, ready=False):
        while True:
            current = await self.repo.get(RuntimeOperation, op.id)
            result = await self.operations.describe(current)
            if current.status in {"failed", "timed_out", "cancelled"}:
                raise AppProbeFailedError(
                    msg="应用执行失败",
                    reason=current.failure.get("reason", "execution_failed"),
                    operation_id=op.id,
                    runtime_stage=current.failure.get("failed_stage") or current.stage,
                    details={
                        "operation_id": op.id,
                        "reason": current.failure.get("reason", "execution_failed"),
                        "runtime_stage": current.failure.get("failed_stage") or current.stage,
                        "maintenance": bool(current.failure.get("maintenance")),
                        "data_may_have_changed": bool(current.failure.get("data_may_have_changed")),
                    },
                    maintenance=bool(current.failure.get("maintenance")),
                    data_may_have_changed=bool(current.failure.get("data_may_have_changed")),
                    failure=current.failure,
                )
            if current.status == "completed" or (ready and current.stage in {"ready", "serving"}):
                return result
            if datetime.utcnow() > current.deadline:
                raise AppProbeFailedError(
                    msg="应用操作超时, 正在确认清理状态",
                    operation_id=op.id,
                    details={"operation_id": op.id, "reason": "operation_timeout", "runtime_stage": current.stage},
                )
            await asyncio.sleep(0.5)

    async def source(self, deployment):
        from bisheng.app_publish.domain.services import package_service

        raw = await package_service.fetch_package(deployment.code_object_key)
        if raw is None:
            raise RuntimeConflict("source_artifact_not_found")
        digest = hashlib.sha256(raw).hexdigest()
        scope = f"{deployment.tenant_id}/{deployment.app_id}"
        rows = await self.repo.find(RuntimeArtifact, scope_key=scope, kind="source", sha256=digest)
        if rows:
            return rows[0]
        return await self.repo.save(
            RuntimeArtifact(
                tenant_id=deployment.tenant_id,
                app_id=deployment.app_id,
                scope_key=scope,
                kind="source",
                sha256=digest,
                size_bytes=len(raw),
                object_key=deployment.code_object_key,
                state="verified",
                confirmed_at=datetime.utcnow(),
            )
        )

    async def prepare(self, deployment, manifest, tier):
        existing_delivery = await self.repo.find(
            RuntimeDelivery, app_id=deployment.app_id, version_id=deployment.version_id
        )
        if existing_delivery:
            return existing_delivery[0]
        existing = await self.repo.find(
            RuntimeOperation,
            scope_key=f"{deployment.tenant_id}/{deployment.app_id}",
            idempotency_key="prepare:" + deployment.id,
        )
        if existing:
            op = existing[0]
            await self.wake(op)
            result = await self.wait(op)
            content = result["result"]["delivery"]
            return await self.repo.freeze_delivery(
                RuntimeDelivery(
                    tenant_id=deployment.tenant_id,
                    app_id=deployment.app_id,
                    version_id=deployment.version_id,
                    execution_mode=content["mode"],
                    profile_id=(content.get("profile") or {}).get("profile_id", ""),
                    resolved_platform=op.payload["platform"],
                    delivery_digest=content_digest(content),
                    content=content,
                )
            )
        app = await self.repo.get_application(deployment.app_id)
        node, _ = await self.node(app)
        source = await self.source(deployment)
        delivery = manifest.delivery.model_dump(mode="json") if manifest.delivery else {"mode": "source-image"}
        profile = (
            await RuntimeProfileService(self.repo).resolve(manifest.runtime, delivery.get("profile"), node.platform)
            if delivery["mode"] == "bundle"
            or (node.executor_kind == "kubernetes" and delivery["mode"] == "source-image")
            else None
        )
        if profile:
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                materials = await self.repo.find(RuntimeArtifact, kind="offline", state="verified")
            approved = [
                row.id
                for row in materials
                if row.platform == profile["platform"]
                and row.metadata_.get("profile_id") == profile["profile_id"]
                and row.metadata_.get("profile_digest") == profile["profile_digest"]
                and row.metadata_.get("enabled", True)
                and (
                    row.visibility == "public"
                    or (
                        (row.tenant_id, row.app_id) == (app.tenant_id, app.id)
                        and row.metadata_.get("authorized_owner_user_id") == app.owner_user_id
                    )
                )
            ]
            delivery = {
                **delivery,
                "dependencies": {
                    **delivery.get("dependencies", {}),
                    "offline_artifacts": sorted(
                        set(delivery.get("dependencies", {}).get("offline_artifacts", []) + approved)
                    ),
                },
            }
        payload = {
            "source_limits": {
                "compressed": settings.app_runtime.max_package_mb * 1024 * 1024,
                "unpacked": settings.app_runtime.max_unpacked_mb * 1024 * 1024,
                "entries": settings.app_runtime.max_package_entries,
            },
            "source_artifact_id": source.id,
            "delivery": delivery,
            "profile": profile,
            "platform": node.platform,
            "runtime": manifest.runtime,
            "slug": app.slug,
            "port": manifest.port,
            "offline": settings.app_runtime.runtime_offline,
            "tier": {"memory_mb": tier.memory_mb, "cpu_millicores": tier.cpu_millicores},
        }
        op = await self.submit(
            app,
            kind="prepare",
            key="prepare:" + deployment.id,
            version_id=deployment.version_id,
            deployment_id=deployment.id,
            payload=payload,
        )
        await self.wake(op)
        try:
            result = await self.wait(op)
        except AppProbeFailedError as exc:
            raise AppDependencyBuildFailedError(
                msg="应用依赖或交付准备失败",
                details={**exc.kwargs.get("details", {}), "operation_id": op.id},
            ) from exc
        content = result["result"]["delivery"]
        return await self.repo.freeze_delivery(
            RuntimeDelivery(
                tenant_id=app.tenant_id,
                app_id=app.id,
                version_id=deployment.version_id,
                execution_mode=content["mode"],
                profile_id=(content.get("profile") or {}).get("profile_id", ""),
                resolved_platform=node.platform,
                delivery_digest=content_digest(content),
                content=content,
            )
        )

    async def delivery(self, app_id, version_id):
        rows = await self.repo.find(RuntimeDelivery, app_id=app_id, version_id=version_id)
        if not rows:
            raise RuntimeConflict("frozen_delivery_not_found")
        return rows[0]

    async def probe(self, deployment, manifest, tier):
        app = await self.repo.get_application(deployment.app_id)
        delivery = await self.delivery(app.id, deployment.version_id)
        from bisheng.app_publish.domain.services.schema_evolution_service import migration_plan, tables_of

        body = {
            "resolved_delivery": delivery.content,
            "migration_plan": migration_plan([], tables_of(manifest)),
            "slug": app.slug,
            "port": manifest.port,
            "tier": {"memory_mb": tier.memory_mb, "cpu_millicores": tier.cpu_millicores},
        }
        op = await self.submit(
            app,
            kind="probe",
            key="probe:" + deployment.id,
            version_id=deployment.version_id,
            deployment_id=deployment.id,
            payload=body,
        )
        await self.inject_environment(
            op,
            capabilities=manifest.capabilities.model_dump(mode="json") if manifest.capabilities else {},
            preview=True,
        )
        await self.wake(op)
        return await self.wait(op)

    async def inject_environment(self, op, *, capabilities=None, environment=None, preview=False, secret_snapshot=None):
        from bisheng.app_publish.domain.services.app_credential_service import AppRuntimeCredentialService
        from bisheng.app_publish.domain.services.capability_bus_service import (
            derive_scopes,
            model_face_base_url,
            parse_declaration,
        )
        from bisheng.app_runtime.domain.services.app_storage_service import AppStorageService
        from bisheng.app_runtime.domain.services.runtime_payload import seal

        async with self.repo.transaction() as session:
            op = await self.repo.get(RuntimeOperation, op.id, lock=True)
            if op.payload.get("sealed_env"):
                return
            base = settings.app_runtime.runtime_platform_base_url
            if not base:
                raise RuntimeConflict("runtime_platform_base_url_required")
            storage = await AppStorageService(
                self.repo, max_file_bytes=settings.app_runtime.storage_max_file_mb * 1024 * 1024
            ).issue(op, base_url=base, preview_session=op.id if preview else None)
            env = {**(environment or {}), **storage["env"], "BISHENG_PLATFORM_API_BASE": base}
            # Preflight gets isolated data and no production application identity.
            from bisheng.app_publish.application.runtime_secrets import formal_snapshot, preview_environment

            if preview:
                env.update(preview_environment(capabilities or {}))
            else:
                if secret_snapshot is None:
                    from bisheng.database.models.app import App
                    from bisheng.database.models.app_version import AppVersion

                    app = await self.repo.get(App, op.app_id, lock=True)
                    version = await self.repo.get(AppVersion, op.version_id)
                    secret_snapshot = await formal_snapshot(app, version, session=session)
                env.update(secret_snapshot.env)
                op.payload = {
                    **op.payload,
                    "secret_config_revision": secret_snapshot.revision,
                    "sensitive_env_names": secret_snapshot.sensitive_env_names,
                    "approved_declaration_digest": secret_snapshot.declaration_digest,
                }
                declaration = parse_declaration(capabilities or {})
                token = await AppRuntimeCredentialService.stage_in_transaction(
                    op.app_id, operation=op, scopes=derive_scopes(declaration), session=session
                )
                env.update({"BISHENG_APP_TOKEN": token, "BISHENG_API_BASE_URL": base})
                if declaration.models:
                    env.update(
                        {
                            "OPENAI_API_KEY": token,
                            "BISHENG_MODEL_BASE_URL": model_face_base_url(),
                            "OPENAI_BASE_URL": model_face_base_url(),
                        }
                    )
            op.payload = {**op.payload, "sealed_env": seal(env)}
            await self.repo.save(op)

    async def deploy(self, app, version, tier, *, key=None, preserve_pending=False):
        from bisheng.app_publish.domain.schemas.app_manifest import egress_domains_of
        from bisheng.app_publish.domain.services.schema_evolution_service import (
            _reference_tables,
            migration_plan,
            tables_of,
        )
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

        routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app.id}")
        if routes and routes[0].status == "serving" and routes[0].version_id == version.id and app.state == "online":
            return {"instance_id": routes[0].exec_ref, "phase": "running", "operation_id": routes[0].operation_id}
        existing = await self.repo.find(RuntimeOperation, app_id=app.id, version_id=version.id, kind="deploy")
        active = [row for row in existing if row.status not in {"completed", "failed", "cancelled", "timed_out"}]
        if active:
            op = active[-1]
            await self.inject_environment(
                op, capabilities=version.capabilities, environment=(version.injections or {}).get("env", {})
            )
            await self.wake(op)
            result = await self.wait(op, ready=True)
            from bisheng.app_runtime.domain.services.app_state_service import AppStateService

            await AppStateService.commit_runtime_delivery(self.repo, op, result)
            routes = await self.repo.find(RuntimeRoute, route_key=f"app:{app.id}")
            return {"instance_id": routes[0].exec_ref, "phase": "running", "operation_id": op.id}
        delivery = await self.delivery(app.id, version.id)
        body = {
            "resolved_delivery": delivery.content,
            "slug": app.slug,
            "version_no": version.version_no,
            "port": int(version.manifest.get("port", 8080)),
            "tier": {
                "memory_mb": int(tier.get("mem", tier.get("memory_mb", 1024))),
                "cpu_millicores": int(tier.get("cpu", 1) * 1000),
            },
            "migration_plan": migration_plan(await _reference_tables(app.id), tables_of(version.manifest)),
            "expected_app_state": app.state,
            "expected_current_version_id": app.current_version_id,
            "expected_pending_version_id": app.pending_version_id,
            "uses_sqlite": True,
            "preserve_pending_version": preserve_pending,
            "egress_domains": egress_domains_of(version.manifest),
        }
        async with self.repo.transaction():
            from bisheng.database.models.app import App

            locked = await self.repo.get(App, app.id, lock=True)
            if locked is None or (locked.state, locked.current_version_id, locked.pending_version_id) != (
                app.state,
                app.current_version_id,
                app.pending_version_id,
            ):
                raise RuntimeConflict("application_state_changed")
            op = await self.submit(
                app, kind="deploy", key=key or "deploy:" + uuid4().hex, version_id=version.id, payload=body
            )
            await self.inject_environment(
                op, capabilities=version.capabilities, environment=(version.injections or {}).get("env", {})
            )
        await self.wake(op)
        result = await self.wait(op, ready=True)
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        await AppStateService.commit_runtime_delivery(self.repo, op, result)
        return {"instance_id": result["result"]["exec_ref"], "phase": "running", "operation_id": op.id}

    async def stop(self, app, *, destroy=False, purge_volume=False):
        from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService

        await RuntimeProjectionService(self.repo).block(app.id, "stopped")
        op = await self.submit(
            app,
            kind="destroy" if destroy else "stop",
            key=("destroy:" if destroy else "stop:") + uuid4().hex,
            payload={"purge_volume": purge_volume, "delete_secret_config": destroy},
        )
        await self.wake(op)
        return await self.wait(op)

    async def preview_start(self, app, version, row, payload):
        from bisheng.app_publish.domain.services.schema_evolution_service import migration_plan, tables_of

        delivery = await self.delivery(app.id, version.id)
        body = {
            "resolved_delivery": delivery.content,
            "session_id": row.id,
            "preview_expires_at": datetime.fromtimestamp(row.expires_at.timestamp(), UTC)
            .replace(tzinfo=None)
            .isoformat(),
            "base_path": payload["base_path"],
            "slug": app.slug,
            "version_no": version.version_no,
            "port": payload["port"],
            "health": payload["health"],
            "tier": {"memory_mb": payload["tier"]["mem"], "cpu_millicores": int(payload["tier"]["cpu"] * 1000)},
            "migration_plan": migration_plan([], tables_of(version.manifest)),
            "egress_domains": payload["egress_domains"],
        }
        op = await self.submit(app, kind="preview", key="preview:" + row.id, version_id=version.id, payload=body)
        await self.inject_environment(
            op, preview=True, capabilities=version.capabilities, environment=payload.get("env")
        )
        await self.wake(op)
        return await self.wait(op, ready=True)

    async def preview_stop(self, session_id):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

        async with self.repo.transaction():
            routes = await self.repo.find(RuntimeRoute, route_key="preview:" + session_id, lock=True)
            if not routes:
                return
            route = routes[0]
            route.status = "stopped"
            route.route_epoch += 1
            await self.repo.save(route)
            op = await self.repo.get(RuntimeOperation, route.operation_id, lock=True)
            if op and op.status not in {"completed", "failed", "cancelled", "timed_out"}:
                op.payload = {**op.payload, "cancel_requested": True}
                from bisheng.app_runtime.domain.models.runtime_delivery import (
                    RuntimeEgressPolicy,
                    RuntimeStorageBinding,
                )

                for binding in await self.repo.find(RuntimeStorageBinding, operation_id=op.id, lock=True):
                    binding.state = "revoked"
                    await self.repo.save(binding)
                for policy in await self.repo.find(RuntimeEgressPolicy, operation_id=op.id, lock=True):
                    policy.revoked_at = datetime.utcnow()
                    await self.repo.save(policy)

                await self.repo.save(op)

    async def recover(self, app, route, *, running):
        from bisheng.app_publish.domain.schemas.app_manifest import egress_domains_of
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        assignments = await self.repo.find(RuntimeAssignment, app_id=app.id)
        previous = await self.repo.get(RuntimeOperation, assignments[0].active_operation_id) if assignments else None
        if previous and previous.status not in {"completed", "failed", "cancelled", "timed_out"}:
            return
        if previous and previous.cleanup_status != "complete":
            return
        if (
            previous
            and previous.payload.get("purpose") == "config_restart"
            and previous.status in {"failed", "cancelled", "timed_out"}
        ):
            return
        attempt = (previous.payload.get("recovery_attempt", 0) if previous else 0) + 1
        if attempt > 3:
            return
        version = await AppStateService._load_version(app.id, route.version_id)
        delivery = await self.delivery(app.id, version.id)
        tier = await AppStateService._resolve_tier(version.tier_id)
        if not running:
            await self.repo.release(route.operation_id, stopped=True)
        payload = {
            "resolved_delivery": delivery.content,
            "slug": app.slug,
            "version_no": version.version_no,
            "port": version.manifest.get("port", 8080),
            "uses_sqlite": True,
            "preserve_pending_version": True,
            "migration_plan": [],
            "tier": {"memory_mb": tier["mem"], "cpu_millicores": int(tier["cpu"] * 1000)},
            "expected_app_state": app.state,
            "expected_current_version_id": app.current_version_id,
            "expected_pending_version_id": app.pending_version_id,
            "auto_commit": True,
            "recovery_attempt": attempt,
            # The egress policy is reissued per operation from this field; omitting it cuts the app off.
            "egress_domains": egress_domains_of(version.manifest),
        }
        async with self.repo.transaction():
            from bisheng.database.models.app import App

            locked = await self.repo.get(App, app.id, lock=True)
            if locked is None or (locked.state, locked.current_version_id, locked.pending_version_id) != (
                app.state,
                app.current_version_id,
                app.pending_version_id,
            ):
                return
            op = await self.submit(
                app,
                kind="deploy",
                key=f"recover:{route.id}:{route.route_epoch}:{attempt}",
                version_id=version.id,
                payload=payload,
            )
            await self.inject_environment(
                op, capabilities=version.capabilities, environment=(version.injections or {}).get("env", {})
            )
        await self.wake(op)
