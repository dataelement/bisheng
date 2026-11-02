"""Server-owned authorization origins, rechecked before new runtime effects."""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime

from bisheng.app_runtime.domain.schemas.app_authorization import required_actions
from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.application.runtime_authorization import runtime_credential_context, without_open_api_identity
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.user.application.runtime_identity import resolve_web_runtime_identity


class RuntimeAuthorizationService:
    @staticmethod
    async def capture_user(identity, app, purpose, *, version_id="", resume=False):
        await AppAuthorizationService.authorize_loaded_app(identity, app, purpose, resume=resume)
        actor = await AppAuthorizationService.resolve_actor(identity)
        principal = get_current_open_api_principal()
        if principal is not None:
            if (
                principal.mode != "S"
                or principal.actor_kind != "service_account"
                or not principal.has_scope("app:manage")
            ):
                raise PermissionDeniedError(reason="runtime_credential_mode_refused")
            reference = {
                "kind": "api_credential",
                "credential_id": principal.credential_id,
                "tenant_id": principal.tenant_id,
            }
            self_review = principal.resource_owner_user_id
        else:
            reference = deepcopy(getattr(identity, "_runtime_credential_reference", None))
            if not reference or reference.get("kind") != "web_session":
                raise PermissionDeniedError(reason="runtime_web_identity_unavailable")
            self_review = actor.subject_id
        return {
            "schema": 1,
            "origin_kind": "user_request",
            "purpose": str(purpose),
            "actor": {"subject_type": actor.subject_type, "subject_id": actor.subject_id, "tenant_id": actor.tenant_id},
            "actor_name": principal.actor_name if principal else getattr(identity, "user_name", None),
            "credential_ref": reference,
            "mode": principal.mode if principal else None,
            "self_review_user_id": int(self_review or 0),
            "required_actions": list(required_actions(purpose, resume=resume)),
            "resume_after_restore": bool(resume),
            "target": {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": str(version_id)},
        }

    @staticmethod
    async def capture_approval_preview(identity, app, qualification):
        from bisheng.app_publish.application.preview_access import qualify

        checked = await qualify(app.id, qualification.version_id, actor=identity, purpose="approval")
        if checked != qualification:
            raise PermissionDeniedError(reason="preview_task_changed")
        actor = await AppAuthorizationService.resolve_actor(identity)
        reference = deepcopy(getattr(identity, "_runtime_credential_reference", None))
        if actor.subject_type != "user" or not reference or reference.get("kind") != "web_session":
            raise PermissionDeniedError(reason="preview_web_identity_required")
        return {
            "schema": 1,
            "origin_kind": "user_request",
            "purpose": "approval_preview",
            "actor": {"subject_type": "user", "subject_id": actor.subject_id, "tenant_id": actor.tenant_id},
            "credential_ref": reference,
            "required_actions": [],
            "resume_after_restore": False,
            "target": {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": qualification.version_id},
            "approval_instance_id": qualification.approval_instance_id,
            "approval_task_id": qualification.approval_task_id,
        }

    @staticmethod
    def validate_shape(context, app, version_id):
        try:
            if (
                not isinstance(context, dict)
                or context.get("schema") != 1
                or context.get("origin_kind") != "user_request"
                or context.get("target")
                != {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": str(version_id)}
                or type(context.get("resume_after_restore", False)) is not bool
                or set(context.get("required_actions", ()))
                != (
                    set()
                    if context.get("purpose") == "approval_preview"
                    else set(required_actions(context["purpose"], resume=context.get("resume_after_restore", False)))
                )
            ):
                raise ValueError("source mismatch")
            actor, reference = context["actor"], context["credential_ref"]
            if actor["subject_type"] not in {"user", "service_account"} or int(actor["subject_id"]) <= 0:
                raise ValueError("actor unavailable")
            return actor, reference
        except (KeyError, TypeError, ValueError) as exc:
            raise PermissionDeniedError(reason="runtime_authorization_source_invalid") from exc

    @classmethod
    @asynccontextmanager
    async def user_context(cls, context, app, *, version_id):
        actor_ref, reference = cls.validate_shape(context, app, version_id)
        with tenant_execution_scope(app.tenant_id):
            if reference.get("kind") == "api_credential":
                async with runtime_credential_context(reference) as principal:
                    actor = await AppAuthorizationService.resolve_actor(principal)
                    if context.get("mode") != principal.mode:
                        raise PermissionDeniedError(reason="runtime_identity_changed")
                    identity = principal
                    if actor_ref != {
                        "subject_type": actor.subject_type,
                        "subject_id": actor.subject_id,
                        "tenant_id": actor.tenant_id,
                    }:
                        raise PermissionDeniedError(reason="runtime_identity_changed")
                    yield identity
            elif reference.get("kind") == "web_session":
                principal_scope = without_open_api_identity()
                principal_scope.__enter__()
                actor_token = set_current_permission_actor(None)
                try:
                    identity = await resolve_web_runtime_identity(reference)
                    actor = await AppAuthorizationService.resolve_actor(identity)
                    if actor_ref != {
                        "subject_type": actor.subject_type,
                        "subject_id": actor.subject_id,
                        "tenant_id": actor.tenant_id,
                    }:
                        raise PermissionDeniedError(reason="runtime_identity_changed")
                    with management_tenant_scope(app.tenant_id):
                        yield identity
                finally:
                    reset_current_permission_actor(actor_token)
                    principal_scope.__exit__(None, None, None)
            else:
                raise PermissionDeniedError(reason="runtime_credential_unavailable")

    @classmethod
    async def validate_user(cls, context, app, *, version_id):
        async with cls.user_context(context, app, version_id=version_id) as identity:
            if context["purpose"] == "approval_preview":
                from bisheng.approval.application.app_review import pending_app_reviews

                grants = await pending_app_reviews(identity.user_id, app.id, {str(version_id)})
                if not any(
                    (g.tenant_id, g.version_id, g.instance_id, g.task_id)
                    == (
                        app.tenant_id,
                        str(version_id),
                        context.get("approval_instance_id"),
                        context.get("approval_task_id"),
                    )
                    for g in grants
                ):
                    raise PermissionDeniedError(reason="preview_pending_task_required")
            else:
                await AppAuthorizationService.authorize_loaded_app(
                    identity, app, context["purpose"], resume=context.get("resume_after_restore", False)
                )

    @staticmethod
    def route_snapshot(route):
        if route is None:
            return None
        return {
            key: getattr(route, key)
            for key in (
                "id",
                "tenant_id",
                "app_id",
                "operation_id",
                "version_id",
                "node_id",
                "exec_ref",
                "generation",
                "owner_epoch",
                "route_epoch",
                "status",
            )
        }

    @classmethod
    def capture_system(cls, app, route, source_operation, delivery, observation):
        from bisheng.app_runtime.domain.services.runtime_protocol import content_digest

        if (
            app.state != "online"
            or app.current_version_id != route.version_id
            or route.status != "serving"
            or route.tenant_id != app.tenant_id
            or route.app_id != app.id
            or source_operation.id != route.operation_id
            or source_operation.kind not in {"deploy", "restore"}
            or source_operation.payload.get("resolved_delivery") != delivery.content
            or delivery.delivery_digest != content_digest(delivery.content)
            or not observation.get("key_id")
            or any(
                observation.get(key) != getattr(route, key)
                for key in ("node_id", "operation_id", "exec_ref", "generation", "owner_epoch", "route_epoch")
            )
        ):
            raise PermissionDeniedError(reason="runtime_recovery_source_invalid")
        return {
            "schema": 1,
            "origin_kind": "system_recovery",
            "purpose": "system_recovery",
            "target": {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": route.version_id},
            "source": {
                "route": cls.route_snapshot(route),
                "operation_id": source_operation.id,
                "request_digest": source_operation.request_digest,
                "delivery_digest": delivery.delivery_digest,
                "observation": deepcopy(observation),
            },
        }

    @classmethod
    async def validate_system(cls, context, app, op, repo):
        from bisheng.app_runtime.domain.models.runtime_delivery import (
            RuntimeDelivery,
            RuntimeExecutionFact,
            RuntimeOperation,
            RuntimeRoute,
        )
        from bisheng.app_runtime.domain.services.runtime_protocol import content_digest

        def refuse():
            raise PermissionDeniedError(reason="runtime_recovery_source_invalid")

        if (
            not isinstance(context, dict)
            or context.get("schema") != 1
            or context.get("origin_kind") != "system_recovery"
            or context.get("purpose") != "system_recovery"
            or "actor" in context
            or "credential_ref" in context
            or context.get("target") != {"tenant_id": app.tenant_id, "app_id": app.id, "version_id": op.version_id}
            or app.state != "online"
            or app.current_version_id != op.version_id
            or op.kind != "deploy"
        ):
            refuse()
        source = context.get("source") or {}
        before = source.get("route")
        if not isinstance(before, dict) or before.get("status") != "serving":
            refuse()
        original = await repo.get(RuntimeOperation, source.get("operation_id"))
        deliveries = await repo.find(RuntimeDelivery, app_id=app.id, version_id=op.version_id)
        routes = await repo.find(RuntimeRoute, route_key=f"app:{app.id}", lock=True)
        if (
            original is None
            or original.id != before.get("operation_id")
            or (original.tenant_id, original.app_id, original.version_id) != (app.tenant_id, app.id, op.version_id)
            or original.request_digest != source.get("request_digest")
            or original.kind not in {"deploy", "restore"}
            or not deliveries
            or deliveries[0].delivery_digest != source.get("delivery_digest")
            or content_digest(deliveries[0].content) != source.get("delivery_digest")
            or original.payload.get("resolved_delivery") != deliveries[0].content
            or op.payload.get("resolved_delivery") != deliveries[0].content
            or not routes
        ):
            refuse()
        current = cls.route_snapshot(routes[0])
        observation = source.get("observation") or {}
        if not observation.get("key_id") or any(
            observation.get(key) != before.get(key)
            for key in ("node_id", "operation_id", "exec_ref", "generation", "owner_epoch", "route_epoch")
        ):
            refuse()
        if current == before:
            return
        transition = op.payload.get("maintenance_transition") or {}
        expected_after = {**before, "status": "maintenance", "route_epoch": before["route_epoch"] + 1}
        if (
            transition.get("operation_id") != op.id
            or transition.get("generation") != op.generation
            or transition.get("owner_epoch") != op.owner_epoch
            or transition.get("before") != before
            or transition.get("after") != expected_after
            or current != expected_after
        ):
            refuse()
        facts = await repo.find(RuntimeExecutionFact, operation_id=op.id, sequence=transition.get("fact_sequence"))
        if not facts or (facts[0].phase, facts[0].node_id, facts[0].generation, facts[0].owner_epoch) != (
            "maintenance",
            op.node_id,
            op.generation,
            op.owner_epoch,
        ):
            refuse()

    @classmethod
    async def validate_operation(cls, repo, op):
        app = await repo.get_application(op.app_id)
        if app is None or app.tenant_id != op.tenant_id or app.state == "deleted":
            raise PermissionDeniedError(reason="runtime_target_unavailable")
        if "expected_app_state" in op.payload and (
            app.state,
            app.current_version_id,
            getattr(app, "pending_version_id", None),
        ) != (
            op.payload["expected_app_state"],
            op.payload.get("expected_current_version_id"),
            op.payload.get("expected_pending_version_id"),
        ):
            raise PermissionDeniedError(reason="runtime_intent_superseded")
        if op.kind in {"deploy", "restore", "migrate"} and op.version_id not in {
            app.current_version_id,
            getattr(app, "pending_version_id", None),
        }:
            raise PermissionDeniedError(reason="runtime_version_not_approved")
        context = op.payload.get("authorization_context") or {}
        if context.get("origin_kind") == "system_recovery":
            await cls.validate_system(context, app, op, repo)
        else:
            permitted = {
                "release_submit": {"prepare", "probe", "deploy"},
                "approved_start": {"deploy"},
                "config_restart": {"deploy"},
                "restore": {"restore"},
                "management_preview": {"preview"},
                "approval_preview": {"preview"},
            }
            if op.kind not in permitted.get(context.get("purpose"), set()):
                raise PermissionDeniedError(reason="runtime_operation_purpose_mismatch")
            if op.kind == "restore" and context.get("resume_after_restore") != op.payload.get("resume_after_restore"):
                raise PermissionDeniedError(reason="runtime_operation_purpose_mismatch")
            await cls.validate_user(context, app, version_id=op.version_id)
            if op.kind == "preview":
                from bisheng.app_publish.application.preview_access import resolve_preview_context

                preview = await resolve_preview_context(operation_id=op.id, allow_starting=True)
                if preview is None or (preview.app_id, preview.version_id, preview.session_id) != (
                    op.app_id,
                    op.version_id,
                    op.payload.get("session_id"),
                ):
                    raise PermissionDeniedError(reason="preview_operation_binding_invalid")

    @classmethod
    async def validate_commit(cls, repo, op):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeExecutionFact, RuntimeNode

        await cls.validate_operation(repo, op)
        node = await repo.get(RuntimeNode, op.node_id)
        if node and node.executor_kind == "kubernetes":
            facts = await repo.find(RuntimeExecutionFact, operation_id=op.id, phase="ready")
            latest = max(facts, key=lambda fact: fact.sequence) if facts else None
            receipt = latest.detail.get("controller") if latest else None
            if (
                node.lease_until is None
                or node.lease_until <= datetime.utcnow()
                or node.status != "ready"
                or receipt != {"holder_id": node.controller_holder, "controller_epoch": node.controller_epoch}
            ):
                raise PermissionDeniedError(reason="runtime_control_lease_expired")
