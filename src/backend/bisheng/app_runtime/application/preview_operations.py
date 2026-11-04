"""Register preview state and execution using one runtime repository/UoW."""

from datetime import datetime, timedelta
from uuid import uuid4

from bisheng.app_publish.application import preview_runtime as lifecycle
from bisheng.app_publish.application.preview_access import qualify
from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeEgressPolicy,
    RuntimeOperation,
    RuntimeRoute,
    RuntimeStorageBinding,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.common.services.config_service import settings
from bisheng.database.models.app_version import AppVersion


def complete_registration(op, row):
    return bool(
        op
        and op.payload.get("sealed_env")
        and op.payload.get("session_id") == row.session_id
        and op.payload.get("preview_credential_id") == row.credential_id
        and not op.payload.get("cancel_requested")
        and op.status not in {"completed", "failed", "cancelled", "timed_out"}
        and op.deadline > datetime.utcnow()
    )


async def start_preview(qualification, *, actor, payload_factory, coordinator=None):
    c = coordinator or RuntimeDeliveryCoordinator()
    q = qualification
    key = {
        "tenant_id": q.tenant_id,
        "app_id": q.app_id,
        "version_id": q.version_id,
        "viewer_user_id": q.viewer_user_id,
        "purpose": q.purpose,
        "task_id": q.approval_task_id,
    }
    try:
        async with c.repo.transaction() as session:
            await lifecycle.lock_version(session, tenant_id=q.tenant_id, app_id=q.app_id, version_id=q.version_id)
            if await qualify(q.app_id, q.version_id, actor=actor, purpose=q.purpose) != q:
                raise RuntimeConflict("preview_qualification_changed")
            existing = await lifecycle.find_reusable(session, **key)
            if existing:
                op = await c.repo.get(RuntimeOperation, existing.operation_id, lock=True)
                if (
                    op is None
                    or not op.payload.get("sealed_env")
                    or op.payload.get("session_id") != existing.session_id
                ):
                    raise RuntimeConflict("preview_registration_incomplete")
                preview = existing
            else:
                app = await c.repo.get_application(q.app_id)
                version = await c.repo.get(AppVersion, q.version_id)
                if app is None or version is None or version.app_id != app.id:
                    raise RuntimeConflict("preview_version_invalid")
                preview = await lifecycle.register(
                    session,
                    {
                        "id": uuid4().hex,
                        "tenant_id": q.tenant_id,
                        "app_id": q.app_id,
                        "version_id": q.version_id,
                        "approver_user_id": q.viewer_user_id,
                        "purpose": q.purpose,
                        "approval_instance_id": q.approval_instance_id,
                        "approval_task_id": q.approval_task_id,
                        "status": "starting",
                        "expires_at": datetime.utcnow() + timedelta(days=max(1, settings.app_runtime.preview_ttl_days)),
                    },
                )
                payload = await payload_factory(app, version, preview)
                from bisheng.app_publish.application.runtime_delivery import preview_migration_plan

                delivery = await c.delivery(app.id, version.id)
                auth = (
                    await RuntimeAuthorizationService.capture_user(
                        actor, app, "management_preview", version_id=version.id
                    )
                    if q.purpose == "management"
                    else await RuntimeAuthorizationService.capture_approval_preview(actor, app, q)
                )
                body = {
                    "resolved_delivery": delivery.content,
                    "session_id": preview.session_id,
                    "preview_purpose": q.purpose,
                    "preview_expires_at": preview.expires_at.isoformat(),
                    "authorization_context": auth,
                    "base_path": payload["base_path"],
                    "slug": app.slug,
                    "version_no": version.version_no,
                    "port": payload["port"],
                    "health": payload["health"],
                    "tier": {"memory_mb": payload["tier"]["mem"], "cpu_millicores": int(payload["tier"]["cpu"] * 1000)},
                    "migration_plan": await preview_migration_plan(version.manifest),
                    "egress_domains": payload["egress_domains"],
                }
                op = await c.submit(
                    app, kind="preview", key="preview:" + preview.session_id, version_id=version.id, payload=body
                )
                from bisheng.app_publish.application.runtime_delivery import declared_scopes

                token = await lifecycle.issue_identity(
                    session,
                    app_id=app.id,
                    operation=op,
                    scopes=await declared_scopes(version.capabilities),
                    expires_at=preview.expires_at,
                    session_id=preview.session_id,
                )
                reference = await lifecycle.by_reference(session_id=preview.session_id, session=session)
                op = await c.repo.get(RuntimeOperation, op.id, lock=True)
                op.payload = {**op.payload, "preview_credential_id": reference.credential_id}
                await c.repo.save(op)
                await c.inject_environment(
                    op,
                    preview=True,
                    capabilities=version.capabilities,
                    environment=payload.get("env"),
                    preview_identity=token,
                )
                preview = await lifecycle.by_reference(session_id=preview.session_id, session=session)
    except Exception:
        # A lost COMMIT response is not proof of rollback. Recover only the same durable key.
        async with c.repo.transaction() as session:
            await lifecycle.lock_version(session, tenant_id=q.tenant_id, app_id=q.app_id, version_id=q.version_id)
            if await qualify(q.app_id, q.version_id, actor=actor, purpose=q.purpose) != q:
                raise RuntimeConflict("preview_qualification_changed")
            recovered = await lifecycle.find_reusable(session, **key)
            if recovered is None:
                raise
            op = await c.repo.get(RuntimeOperation, recovered.operation_id, lock=True)
            if not complete_registration(op, recovered):
                raise
            preview = recovered
    if preview.status == "starting":
        await c.wake(op)
        await c.wait(op, ready=True)
    return preview.session_id


async def stop_preview(session_id, *, reason, coordinator=None):
    c = coordinator or RuntimeDeliveryCoordinator()
    row = await lifecycle.by_reference(session_id=session_id)
    if row is None:
        return False
    async with c.repo.transaction() as session:
        await lifecycle.lock_version(session, tenant_id=row.tenant_id, app_id=row.app_id, version_id=row.version_id)
        op = await c.repo.get(RuntimeOperation, row.operation_id, lock=True)
        if op is None:
            raise RuntimeConflict("preview_operation_missing")
        await lifecycle.close(session, op, reason=reason)
        op.payload = {**op.payload, "cancel_requested": True}
        for route in await c.repo.find(RuntimeRoute, operation_id=op.id, lock=True):
            route.status = "stopped"
            route.route_epoch += 1
            await c.repo.save(route)
        for binding in await c.repo.find(RuntimeStorageBinding, operation_id=op.id, lock=True):
            binding.state = "revoked"
            await c.repo.save(binding)
        for policy in await c.repo.find(RuntimeEgressPolicy, operation_id=op.id, lock=True):
            policy.revoked_at = datetime.utcnow()
            await c.repo.save(policy)
        await c.repo.save(op)
    await c.wake(op)
    return True


async def verify_preview_execution(binding):
    from bisheng.core.context.tenant import tenant_execution_scope

    with tenant_execution_scope(binding.tenant_id):
        c = RuntimeDeliveryCoordinator()
        op = await c.repo.get(RuntimeOperation, binding.operation_id)
        if (
            op is None
            or (op.tenant_id, op.app_id, op.version_id, op.kind)
            != (binding.tenant_id, binding.app_id, binding.version_id, "preview")
            or op.payload.get("cancel_requested")
            or op.status in {"completed", "failed", "cancelled", "timed_out"}
            or op.deadline <= datetime.utcnow()
        ):
            return False
        context = op.payload.get("authorization_context") or {}
        expected_purpose = "management_preview" if binding.purpose == "management" else "approval_preview"
        if (
            context.get("purpose") != expected_purpose
            or (context.get("actor") or {}).get("subject_id") != binding.viewer_user_id
            or (
                op.payload.get("session_id"),
                op.payload.get("preview_purpose"),
                op.payload.get("preview_credential_id"),
            )
            != (binding.session_id, binding.purpose, binding.credential_id)
        ):
            return False
        if binding.purpose == "approval" and (context.get("approval_instance_id"), context.get("approval_task_id")) != (
            binding.approval_instance_id,
            binding.approval_task_id,
        ):
            return False
        if binding.status == "running":
            routes = await c.repo.find(RuntimeRoute, route_key="preview:" + binding.session_id, status="serving")
            if len(routes) != 1 or (
                routes[0].operation_id,
                routes[0].version_id,
                routes[0].generation,
                routes[0].owner_epoch,
            ) != (op.id, op.version_id, op.generation, op.owner_epoch):
                return False
        return True
