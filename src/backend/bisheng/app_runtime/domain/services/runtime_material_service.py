"""Workload public identities and current-ownership material authorization.

The workload proves possession of its own key. Node/UID, frozen references and
continued authority are decided from platform records on every request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeDelivery,
    RuntimeDependencyPlan,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource, RuntimeMaterialDelegation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import MUTATING, RuntimeConflict
from bisheng.app_runtime.domain.repositories.runtime_kubernetes_repository import RuntimeKubernetesRepository
from bisheng.app_runtime.domain.services import runtime_material_protocol as wire
from bisheng.app_runtime.domain.services.runtime_operation_service import consume_runtime_nonce
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope


@dataclass(repr=False)
class MaterialScope:
    delegation: RuntimeMaterialDelegation
    operation: RuntimeOperation
    resource: RuntimeExecutionResource
    deadline: datetime | None
    request: dict = field(default_factory=dict)


def _manager(identity):
    if set(identity.roles) != {"manager"} or not identity.node_id:
        raise RuntimeConflict("material_manager_identity_required")


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RuntimeConflict("material_identity_invalid") from None
    return value


def _refused(reason="material_scope_refused", status=403):
    raise wire.MaterialProtocolError(reason, status)


async def _preview(session_id):
    from bisheng.app_publish.application.preview_access import preview_material

    return await preview_material(session_id)


class RuntimeMaterialService:
    def __init__(
        self,
        repository=None,
        *,
        clock=datetime.utcnow,
        nonce_store=consume_runtime_nonce,
        app_loader=None,
        preview_loader=_preview,
        proxy_key=None,
    ):
        self.repo = repository or RuntimeKubernetesRepository()
        self.clock = clock
        self.nonce_store = nonce_store
        self.app_loader = app_loader or self.repo.get_application
        self.preview_loader = preview_loader
        self._proxy_key = proxy_key

    def _proxy_token(self, delegation_id):
        key = self._proxy_key
        if key is None:
            from bisheng.app_runtime.domain.services.runtime_payload import cipher
            from bisheng.common.services.config_service import settings

            cipher()
            key = base64.urlsafe_b64decode(settings.app_runtime.runtime_payload_key)
        if not isinstance(key, bytes) or len(key) < 32:
            raise RuntimeConflict("material_proxy_key_unavailable")
        return hmac.new(key, b"runtime-material-egress-v1\0" + delegation_id.encode(), hashlib.sha256).hexdigest()

    @asynccontextmanager
    async def _scope(self, model, reference, *, node_id=None):
        with bypass_tenant_filter():
            row = await self.repo.get(model, reference)
        if row is None or (node_id is not None and row.node_id != node_id):
            raise RuntimeConflict("material_identity_not_found")
        with tenant_execution_scope(row.tenant_id):
            yield row

    async def _owner(self, op):
        owners = await self.repo.find(RuntimeAssignment, app_id=op.app_id)
        if not owners:
            _refused()
        owner = owners[0]
        active = owner.data_operation_id if op.kind == "data" else owner.active_operation_id
        if (owner.node_id, owner.generation, owner.owner_epoch, active) != (
            op.node_id,
            op.generation,
            op.owner_epoch,
            op.id,
        ):
            _refused()

    async def _lifetime(self, op, resource, app):
        now = self.clock()
        if op.status in {"failed", "cancelled", "timed_out"} or op.payload.get("cancel_requested"):
            _refused()
        if resource.purpose == "preview":
            if op.kind != "preview" or op.status not in {"running", "completed"}:
                _refused()
            preview = await self.preview_loader(op.payload.get("session_id", ""))
            if (
                preview is None
                or (
                    preview.tenant_id,
                    preview.app_id,
                    preview.version_id,
                )
                != (op.tenant_id, op.app_id, op.version_id)
                or preview.status not in {"starting", "running"}
                or getattr(preview, "operation_id", None) != op.id
                or (not preview.approval_active or preview.approver_user_id <= 0 or preview.expires_at <= now)
            ):
                _refused("material_preview_expired")
            return "deployment-init", preview.expires_at
        if resource.purpose == "serve":
            if op.kind not in {"deploy", "restore"} or op.version_id not in {
                app.current_version_id,
                app.pending_version_id,
            }:
                _refused("material_version_not_approved")
            await self._owner(op)
            if op.status == "completed":
                routes = await self.repo.find(RuntimeRoute, route_key="app:" + op.app_id, status="serving")
                if app.state != "online" or app.current_version_id != op.version_id or not routes:
                    _refused()
                route = routes[0]
                if (route.exec_ref, route.node_id, route.generation, route.owner_epoch, route.version_id) != (
                    resource.id,
                    op.node_id,
                    op.generation,
                    op.owner_epoch,
                    op.version_id,
                ):
                    _refused()
                return "deployment-init", None
            if op.status != "running" or op.deadline <= now:
                _refused("material_operation_expired")
            if "expected_app_state" in op.payload and (app.state, app.current_version_id, app.pending_version_id) != (
                op.payload["expected_app_state"],
                op.payload.get("expected_current_version_id"),
                op.payload.get("expected_pending_version_id"),
            ):
                _refused()
            return "deployment-init", op.deadline
        allowed = {
            "prepare": {"prepare-download", "prepare-upload", "assemble"},
            "probe": {"probe"},
            "deploy": {"migrate"},
            "migrate": {"migrate"},
            "restore": {"restore"},
            "data": {"data"},
        }
        if resource.purpose not in allowed.get(op.kind, set()) or op.status != "running" or op.deadline <= now:
            _refused("material_operation_expired")
        if op.kind in MUTATING or op.kind == "data":
            await self._owner(op)
        return "operation", op.deadline

    async def _authority(self, op, resource):
        if resource.kind != "Pod" or (
            resource.tenant_id,
            resource.app_id,
            resource.node_id,
            resource.operation_id,
            resource.generation,
            resource.owner_epoch,
        ) != (
            op.tenant_id,
            op.app_id,
            op.node_id,
            op.id,
            op.generation,
            op.owner_epoch,
        ):
            _refused()
        if (
            resource.cleanup_state == "complete"
            or resource.stop_requested_at is not None
            or resource.stop_state == "confirmed"
        ):
            _refused("material_resource_stopping")
        node = await self.repo.get(RuntimeNode, op.node_id)
        if (
            node is None
            or node.executor_kind != "kubernetes"
            or node.status != "ready"
            or node.engine_id != resource.cluster_id + "/" + resource.namespace
        ):
            _refused()
        app = await self.app_loader(op.app_id)
        if app is None or (app.id, app.tenant_id) != (op.app_id, op.tenant_id) or app.state == "deleted":
            _refused()
        scope_kind, deadline = await self._lifetime(op, resource, app)
        frozen = op.payload.get("resolved_delivery")
        delivery = None
        if frozen is not None:
            deliveries = await self.repo.find(RuntimeDelivery, app_id=op.app_id, version_id=op.version_id)
            if not deliveries:
                _refused("material_delivery_not_frozen")
            delivery = deliveries[0]
            if (
                delivery.content != frozen
                or delivery.delivery_digest != content_digest(delivery.content)
                or delivery.resolved_platform != node.platform
            ):
                _refused("material_delivery_not_frozen")
        elif resource.purpose not in {"prepare-download", "prepare-upload", "data"}:
            _refused("material_delivery_not_frozen")
        return scope_kind, deadline, delivery, node

    async def _materials(self, op, resource, delivery, node):
        purpose = resource.purpose
        frozen = delivery.content if delivery else {}
        refs = {}
        if purpose in {"serve", "probe", "preview", "assemble"}:
            for field_name, kind in (("compiled_artifact_id", "compiled"), ("dependency_artifact_id", "dependencies")):
                if frozen.get(field_name):
                    refs[frozen[field_name]] = kind
        if purpose == "prepare-download":
            if op.payload.get("source_artifact_id"):
                refs[op.payload["source_artifact_id"]] = "source"
            for reference in op.payload.get("delivery", {}).get("dependencies", {}).get("offline_artifacts", []):
                refs[reference] = "offline"
            selected = op.payload.get("dependency_resolution") or {}
            if selected.get("artifact_id"):
                plans = await self.repo.find(
                    RuntimeDependencyPlan,
                    scope_key=f"{op.tenant_id}/{op.app_id}",
                    input_key=selected.get("input_key", ""),
                )
                if (
                    not plans
                    or plans[0].artifact_id != selected["artifact_id"]
                    or plans[0].state not in {"materials_ready", "verified"}
                    or selected.get("state") not in {"materials_ready", "verified"}
                ):
                    _refused("material_dependency_selection_refused")
                from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeDependencyService

                await RuntimeDependencyService(self.repo).validated_artifact(
                    op, selected["input_key"], selected["artifact_id"], producer_operation_id=plans[0].operation_id
                )
                refs[selected["artifact_id"]] = "dependencies"
        if purpose == "restore" and op.payload.get("snapshot_id"):
            refs[op.payload["snapshot_id"]] = "snapshot"
        actions = ["download"] if refs else []
        if purpose == "prepare-upload":
            actions += ["upload:compiled", "upload:dependencies"]
        if purpose in {"migrate", "restore", "data"}:
            actions.append("upload:snapshot")
        profile = (op.payload.get("profile") if purpose.startswith("prepare") else frozen.get("profile")) or {}
        for reference, kind in refs.items():
            with bypass_tenant_filter():
                artifact = await self.repo.get(RuntimeArtifact, reference)
            owned = bool(artifact and (artifact.tenant_id, artifact.app_id) == (op.tenant_id, op.app_id))
            public = bool(
                artifact
                and kind == "offline"
                and artifact.visibility == "public"
                and bool(profile.get("profile_id"))
                and bool(profile.get("profile_digest"))
                and artifact.metadata_.get("profile_id") == profile.get("profile_id")
                and artifact.metadata_.get("profile_digest") == profile.get("profile_digest")
            )
            if (
                artifact is None
                or artifact.kind != kind
                or artifact.state != "verified"
                or not (owned or public)
                or (artifact.platform and artifact.platform != node.platform)
                or (kind == "offline" and not artifact.metadata_.get("enabled", True))
            ):
                _refused("material_artifact_refused")
        if not actions:
            _refused("material_actions_empty")
        return sorted(refs), actions

    def _document(self, row):
        token = self._proxy_token(row.id)
        return {
            "delegation_id": row.id,
            "key_id": row.key_id,
            "scope_kind": row.scope_kind,
            "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
            "proxy": {"principal": "material-" + row.id, "token": token},
        }

    async def create_delegation(self, identity, body):
        _manager(identity)
        if not isinstance(body, dict) or set(body) != {"operation_id", "exec_ref", "key_id", "public_key"}:
            raise RuntimeConflict("material_delegation_fields_invalid")
        _uuid(body["exec_ref"])
        if not isinstance(body["key_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body["key_id"]):
            raise RuntimeConflict("material_key_id_invalid")
        try:
            if not isinstance(body["public_key"], str) or not re.fullmatch(r"[a-f0-9]{64}", body["public_key"]):
                raise ValueError()
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(body["public_key"]))
        except (ValueError, TypeError):
            raise RuntimeConflict("material_public_key_invalid") from None
        try:
            async with self._scope(RuntimeOperation, body["operation_id"], node_id=identity.node_id) as op:
                async with self.repo.transaction():
                    resource = await self.repo.get(RuntimeExecutionResource, body["exec_ref"], lock=True)
                    if resource is None:
                        raise RuntimeConflict("material_resource_not_found")
                    scope_kind, deadline, delivery, node = await self._authority(op, resource)
                    artifacts, actions = await self._materials(op, resource, delivery, node)
                    with bypass_tenant_filter():
                        existing = await self.repo.find(RuntimeMaterialDelegation, key_id=body["key_id"], lock=True)
                    if existing:
                        row = existing[0]
                        if (row.tenant_id, row.app_id, row.operation_id, row.exec_ref, row.public_key) != (
                            op.tenant_id,
                            op.app_id,
                            op.id,
                            resource.id,
                            body["public_key"],
                        ) or row.revoked_at is not None:
                            raise RuntimeConflict("material_key_content_conflict")
                        return self._document(row)
                    row = RuntimeMaterialDelegation(
                        tenant_id=op.tenant_id,
                        app_id=op.app_id,
                        scope_kind=scope_kind,
                        version_id=op.version_id,
                        delivery_id=delivery.id if delivery else "",
                        operation_id=op.id,
                        node_id=op.node_id,
                        generation=op.generation,
                        owner_epoch=op.owner_epoch,
                        exec_ref=resource.id,
                        key_id=body["key_id"],
                        public_key=body["public_key"],
                        allowed_artifacts=artifacts,
                        allowed_actions=actions,
                        expires_at=(deadline if resource.purpose != "serve" else None),
                    )
                    row.proxy_credential_hash = hashlib.sha256(self._proxy_token(row.id).encode()).hexdigest()
                    await self.repo.save(row)
                    return self._document(row)
        except wire.MaterialProtocolError as exc:
            raise RuntimeConflict(str(exc)) from None
        except IntegrityError:
            # Concurrent claims must not expose SQL or silently create another key.
            raise RuntimeConflict("material_key_claim_conflict") from None

    async def bind_delegation(self, identity, delegation_id, *, pod_uid):
        _manager(identity)
        _uuid(delegation_id)
        _uuid(pod_uid)
        try:
            async with self._scope(RuntimeMaterialDelegation, delegation_id, node_id=identity.node_id):
                async with self.repo.transaction():
                    row = await self.repo.get(RuntimeMaterialDelegation, delegation_id, lock=True)
                    op = await self.repo.get(RuntimeOperation, row.operation_id)
                    resource = await self.repo.get(RuntimeExecutionResource, row.exec_ref)
                    if op is None or resource is None or resource.uid != pod_uid or row.revoked_at is not None:
                        raise RuntimeConflict("material_pod_uid_not_observed")
                    await self._authority(op, resource)
                    if row.pod_uid and row.pod_uid != pod_uid:
                        raise RuntimeConflict("material_pod_uid_changed")
                    row.pod_uid = pod_uid
                    await self.repo.save(row)
                    return {"delegation_id": row.id, "pod_uid": row.pod_uid}
        except wire.MaterialProtocolError as exc:
            raise RuntimeConflict(str(exc)) from None

    async def _current(self, delegation_id, *, key_id=None, pod_uid=None):
        async with self._scope(RuntimeMaterialDelegation, delegation_id) as row:
            if row.revoked_at is not None or (row.expires_at is not None and row.expires_at <= self.clock()):
                _refused("material_delegation_revoked")
            if key_id is not None and row.key_id != key_id:
                _refused("material_key_refused", 401)
            if not row.pod_uid:
                _refused("material_pod_not_bound", 409)
            if pod_uid is not None and row.pod_uid != pod_uid:
                _refused("material_pod_uid_refused")
            op = await self.repo.get(RuntimeOperation, row.operation_id)
            resource = await self.repo.get(RuntimeExecutionResource, row.exec_ref)
            if (
                op is None
                or resource is None
                or resource.uid != row.pod_uid
                or (
                    row.tenant_id,
                    row.app_id,
                    row.node_id,
                    row.generation,
                    row.owner_epoch,
                )
                != (op.tenant_id, op.app_id, op.node_id, op.generation, op.owner_epoch)
            ):
                _refused()
            scope_kind, deadline, delivery, node = await self._authority(op, resource)
            artifacts, actions = await self._materials(op, resource, delivery, node)
            if (
                row.scope_kind != scope_kind
                or set(row.allowed_artifacts) != set(artifacts)
                or row.allowed_actions != actions
                or row.delivery_id != (delivery.id if delivery else "")
            ):
                _refused("material_authority_changed")
            if row.expires_at is not None:
                deadline = min(deadline, row.expires_at) if deadline is not None else row.expires_at
            return MaterialScope(row, op, resource, deadline)

    async def revalidate(self, scope):
        try:
            return await self._current(
                scope.delegation.id, key_id=scope.delegation.key_id, pod_uid=scope.delegation.pod_uid
            )
        except RuntimeConflict:
            _refused()
        except SQLAlchemyError as exc:
            logger.warning("material authority unavailable ({})", type(exc).__name__)
            _refused("material_authorization_unavailable", 503)

    async def authenticate_request(self, method, target, body, headers, *, authorize_transfer=None):
        values = wire.authentication_headers(headers)
        try:
            with bypass_tenant_filter():
                row = await self.repo.get(RuntimeMaterialDelegation, values.get("delegation", ""))
            if row is None or row.key_id != values.get("key-id"):
                _refused("material_key_refused", 401)

            async def authorize(proof):
                scope = await self._current(proof.delegation_id, key_id=proof.key_id, pod_uid=proof.pod_uid)
                if scope.delegation.public_key != row.public_key:
                    _refused("material_key_refused", 401)
                if target.partition("?")[0] == wire.PREFIX + "/exchange":
                    request = wire.parse_control(
                        body,
                        allowed={"action", "artifact_id", "kind", "sha256", "size_bytes", "platform", "metadata"},
                        required={"action"},
                    )
                    action = request["action"]
                    if action == "download":
                        if set(request) != {"action", "artifact_id"}:
                            _refused("material_exchange_fields_invalid", 400)
                        if (
                            "download" not in scope.delegation.allowed_actions
                            or request["artifact_id"] not in scope.delegation.allowed_artifacts
                        ):
                            _refused("material_artifact_refused")
                    elif action == "upload":
                        if (
                            set(request) - {"action", "kind", "sha256", "size_bytes", "platform", "metadata"}
                            or not {"kind", "sha256", "size_bytes"} <= request.keys()
                        ):
                            _refused("material_exchange_fields_invalid", 400)
                        if "upload:" + str(request["kind"]) not in scope.delegation.allowed_actions:
                            _refused("material_upload_refused")
                        wire.unsigned_integer(request["size_bytes"])
                        if not isinstance(request.get("metadata", {}), dict) or not isinstance(
                            request.get("platform", ""), str
                        ):
                            _refused("material_upload_fields_invalid", 400)
                        if request.get("platform", "") not in {"", "linux/amd64", "linux/arm64"}:
                            _refused("material_upload_platform_invalid", 400)
                        if not isinstance(request["sha256"], str) or not re.fullmatch(
                            r"[a-f0-9]{64}", request["sha256"]
                        ):
                            _refused("material_digest_invalid", 400)
                    else:
                        _refused("material_action_invalid", 400)
                    scope.request = request
                elif authorize_transfer is None:
                    _refused("material_ticket_required", 401)
                else:
                    await authorize_transfer(proof, scope)
                return scope

            now = self.clock()
            stamp = now.replace(tzinfo=UTC).timestamp() if now.tzinfo is None else now.timestamp()
            return await wire.authenticate(
                method,
                target,
                body,
                headers,
                public_key=row.public_key,
                authorize=authorize,
                consume_nonce=self.nonce_store,
                now=stamp,
            )
        except RuntimeConflict:
            _refused()
        except SQLAlchemyError as exc:
            logger.warning("material authority unavailable ({})", type(exc).__name__)
            _refused("material_authorization_unavailable", 503)
