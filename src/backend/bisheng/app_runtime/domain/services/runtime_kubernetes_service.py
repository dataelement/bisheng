"""Platform control-plane policy; Kubernetes effects remain in the executor.

Resource intentions commit before the manager makes a cluster request. Admission
reads only public projections and never waits for a transaction doing I/O.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import re
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeExecutionFact,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import MUTATING, TERMINAL, RuntimeConflict
from bisheng.app_runtime.domain.repositories.runtime_kubernetes_repository import RuntimeKubernetesRepository
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, content_digest
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope

_PREFIX = "runtime.bisheng.io/"
_FINALIZER = _PREFIX + "stop-confirmed"
_PRODUCTION = {"serve", "migrate", "restore", "data", "purge"}
_KINDS = {"Pod", "Service", "PersistentVolumeClaim", "Secret"}
_PURPOSES = {
    "prepare": {"prepare-download", "prepare-install", "prepare-upload", "assemble"},
    "probe": {"probe"},
    "preview": {"preview"},
    "deploy": {"serve", "migrate"},
    "migrate": {"migrate"},
    "restore": {"restore"},
    "data": {"data"},
    "destroy": {"purge"},
}
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")


def _ref(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RuntimeConflict("resource_ref_invalid") from None
    return value


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()[:40]


def _fields(body, required, optional=()):
    if not isinstance(body, dict) or set(body) - set(required) - set(optional) or set(required) - set(body):
        raise RuntimeConflict("resource_request_invalid")


def _identity(identity, role):
    if role not in identity.roles or not identity.node_id:
        raise RuntimeConflict("runtime_service_role_refused")
    return identity.node_id


def _epoch(value):
    if type(value) is not int or value < 1:
        raise RuntimeConflict("controller_epoch_invalid")


def _projection(template):
    if not isinstance(template, dict):
        raise RuntimeConflict("resource_template_invalid")
    try:
        if len(canonical_json(template)) > 512 * 1024:
            raise RuntimeConflict("resource_template_size_limit")
    except (ValueError, TypeError, RecursionError):
        raise RuntimeConflict("resource_template_invalid") from None
    if "data" in template or "stringData" in template:
        raise RuntimeConflict("resource_secret_plaintext_refused")
    if template.get("kind") == "Secret":
        if (
            template.get("immutable") is not True
            or template.get("type") != "Opaque"
            or not _DIGEST.fullmatch(str(template.get("data_sha256", "")))
        ):
            raise RuntimeConflict("resource_secret_projection_invalid")
    if template.get("kind") == "Pod":
        spec = template.get("spec", {})
        if not isinstance(spec, dict):
            raise RuntimeConflict("resource_template_invalid")
        containers = []
        for key in ("containers", "initContainers"):
            entries = spec.get(key, [])
            if (
                not isinstance(entries, list)
                or len(entries) > 16
                or any(not isinstance(item, dict) for item in entries)
            ):
                raise RuntimeConflict("resource_containers_invalid")
            containers.extend(entries)
        for container in containers:
            environment = container.get("env", [])
            if (
                not isinstance(environment, list)
                or len(environment) > 256
                or any(not isinstance(item, dict) for item in environment)
            ):
                raise RuntimeConflict("resource_environment_invalid")
            for entry in environment:
                if "value" in entry or (
                    "valueFrom" not in entry and not _DIGEST.fullmatch(str(entry.get("value_sha256", "")))
                ):
                    raise RuntimeConflict("resource_environment_plaintext_refused")
    return copy.deepcopy(template)


class RuntimeKubernetesService:
    def __init__(self, repository=None, *, clock=datetime.utcnow):
        self.repo = repository or RuntimeKubernetesRepository()
        self.clock = clock

    async def _node(self, node_id, *, allow_blocked=False):
        node = await self.repo.get(RuntimeNode, node_id)
        if (
            node is None
            or node.executor_kind != "kubernetes"
            or node.status not in ({"ready", "blocked"} if allow_blocked else {"ready"})
        ):
            raise RuntimeConflict("controller_node_unavailable")
        parts = node.engine_id.split("/")
        if (
            len(parts) != 2
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", parts[0])
            or not _NAME.fullmatch(parts[1])
        ):
            raise RuntimeConflict("controller_execution_domain_invalid")
        if parts[1] in {"default", "kubekey-system"} or parts[1].startswith("kube-"):
            raise RuntimeConflict("controller_execution_domain_invalid")
        return node, parts

    @asynccontextmanager
    async def _scope(self, identity, model, record_id):
        with bypass_tenant_filter():
            row = await self.repo.get(model, record_id)
        if row is None or row.node_id != identity.node_id:
            raise RuntimeConflict("resource_not_found")
        with tenant_execution_scope(row.tenant_id):
            yield row

    @staticmethod
    def _controller_document(node):
        return {
            "node_id": node.id,
            "holder_id": node.controller_holder,
            "controller_epoch": node.controller_epoch,
            "lease_until": node.lease_until.isoformat() + "Z",
        }

    async def claim_controller(self, identity, *, holder_id, expected_epoch):
        node_id = _identity(identity, "manager")
        await self._node(node_id, allow_blocked=True)
        node = await self.repo.claim_controller(
            node_id, holder_id=holder_id, expected_epoch=expected_epoch, now=self.clock()
        )
        return self._controller_document(node)

    async def renew_controller(self, identity, *, holder_id, controller_epoch):
        _epoch(controller_epoch)
        node_id = _identity(identity, "manager")
        await self._node(node_id, allow_blocked=True)
        node = await self.repo.renew_controller(
            node_id, holder_id=holder_id, controller_epoch=controller_epoch, now=self.clock()
        )
        return self._controller_document(node)

    async def _active(self, op, now):
        if op.status in TERMINAL or op.deadline <= now or op.payload.get("cancel_requested"):
            return False
        if op.kind in MUTATING or op.kind == "data":
            assignments = await self.repo.find(RuntimeAssignment, app_id=op.app_id)
            if not assignments:
                return False
            owner = assignments[0]
            active = owner.data_operation_id if op.kind == "data" else owner.active_operation_id
            if (active, owner.node_id, owner.generation, owner.owner_epoch) != (
                op.id,
                op.node_id,
                op.generation,
                op.owner_epoch,
            ):
                return False
        if "expected_app_state" in op.payload:
            app = await self.repo.get_application(op.app_id)
            if app is None or (app.state, app.current_version_id, app.pending_version_id) != (
                op.payload["expected_app_state"],
                op.payload.get("expected_current_version_id"),
                op.payload.get("expected_pending_version_id"),
            ):
                return False
        return True

    def _validate_template(self, body, op, node, domain):
        template = _projection(body["template"])
        kind, purpose = template.get("kind"), body["purpose"]
        if (
            not isinstance(kind, str)
            or not isinstance(purpose, str)
            or kind not in _KINDS
            or template.get("apiVersion") != "v1"
            or purpose not in _PURPOSES.get(op.kind, set())
        ):
            raise RuntimeConflict("resource_kind_or_purpose_refused")
        if (body["cluster_id"], body["namespace"]) != tuple(domain):
            raise RuntimeConflict("resource_execution_domain_refused")
        if purpose == "purge" and op.payload.get("purge_volume") is not True:
            raise RuntimeConflict("purge_operation_refused")
        meta = template.get("metadata", {})
        if (
            not isinstance(meta, dict)
            or not isinstance(meta.get("labels", {}), dict)
            or not isinstance(meta.get("annotations", {}), dict)
        ):
            raise RuntimeConflict("resource_metadata_invalid")
        name, labels, annotations = meta.get("name"), meta.get("labels", {}), meta.get("annotations", {})
        if not isinstance(name, str) or not _NAME.fullmatch(name) or meta.get("namespace") != domain[1]:
            raise RuntimeConflict("resource_metadata_scope_refused")
        expected_labels = {
            "bisheng.managed": "v2",
            _PREFIX + "resource": body["resource_ref"],
            _PREFIX + "app": _hash(op.app_id),
            _PREFIX + "node": _hash(op.node_id),
            _PREFIX + "purpose": purpose,
        }
        expected_annotations = {
            _PREFIX + "operation": op.id,
            _PREFIX + "generation": str(op.generation),
            _PREFIX + "owner-epoch": str(op.owner_epoch),
            _PREFIX + "status-policy": (node.capabilities or {}).get("status_policy_revision"),
        }
        if (
            not expected_annotations[_PREFIX + "status-policy"]
            or any(labels.get(key) != value for key, value in expected_labels.items())
            or any(annotations.get(key) != value for key, value in expected_annotations.items())
        ):
            raise RuntimeConflict("resource_frozen_scope_refused")
        if meta.get("ownerReferences") or meta.get("uid") or meta.get("generateName") or template.get("status"):
            raise RuntimeConflict("resource_server_fields_refused")
        if kind == "Pod":
            self._validate_pod(template, op, node, purpose, body["resource_ref"])
        return template, name, kind, expected_annotations[_PREFIX + "status-policy"]

    @staticmethod
    def _validate_pod(template, op, node, purpose, resource_ref):
        expected_name = ("app-" + _hash(op.app_id)) if purpose in _PRODUCTION else "task-" + _hash(resource_ref)
        if template["metadata"]["name"] != expected_name or template["metadata"].get("finalizers") != [_FINALIZER]:
            raise RuntimeConflict("resource_pod_location_refused")
        spec = template["spec"]
        if spec.get("nodeName") or spec.get("nodeSelector") != {
            "kubernetes.io/os": "linux",
            "kubernetes.io/arch": node.platform.split("/")[-1],
        }:
            raise RuntimeConflict("resource_pod_platform_refused")
        delivery = op.payload.get("resolved_delivery", op.payload.get("delivery", {})) or {}
        profile = delivery.get("profile") or op.payload.get("profile") or {}
        image = delivery.get("image_ref") or delivery.get("image") or profile.get("runtime_image")
        helper = (node.capabilities or {}).get("helper_image")
        assembler = (node.capabilities or {}).get("assembler_image") if purpose == "assemble" else None
        available = {
            value for value in (image, helper, assembler, profile.get("preparer_image")) if isinstance(value, str)
        }
        trusted = {"transfer", "data-layout", "schema-init", "material-fetch", "data-helper", "maintenance"}
        claims = [
            volume.get("persistentVolumeClaim", {}).get("claimName")
            for volume in spec.get("volumes", [])
            if "persistentVolumeClaim" in volume
        ]
        expected_claim = "data-" + _hash(op.app_id)
        if purpose == "purge" and (
            claims != [expected_claim] or any("secret" in volume for volume in spec.get("volumes", []))
        ):
            raise RuntimeConflict("purge_volume_scope_refused")
        containers = [*spec.get("containers", []), *spec.get("initContainers", [])]
        if not containers:
            raise RuntimeConflict("resource_pod_containers_required")
        for container in containers:
            ref = container.get("image", "")
            if not isinstance(ref, str) or not _IMAGE.fullmatch(ref) or ref not in available:
                raise RuntimeConflict("resource_image_not_frozen")
            if container.get("name") in trusted and ref != helper:
                raise RuntimeConflict("resource_helper_image_refused")

    async def register_resource(self, identity, body):
        _identity(identity, "manager")
        _fields(
            body,
            {
                "resource_ref",
                "operation_id",
                "holder_id",
                "controller_epoch",
                "cluster_id",
                "namespace",
                "purpose",
                "template",
            },
        )
        _ref(body["resource_ref"])
        _epoch(body["controller_epoch"])
        async with self._scope(identity, RuntimeOperation, body["operation_id"]) as op:
            now = self.clock()
            node, domain = await self._node(identity.node_id)
            if not await self._active(op, now):
                raise RuntimeConflict("resource_operation_expired")
            template, name, kind, policy = self._validate_template(body, op, node, domain)
            row = RuntimeExecutionResource(
                id=body["resource_ref"],
                tenant_id=op.tenant_id,
                app_id=op.app_id,
                operation_id=op.id,
                node_id=op.node_id,
                cluster_id=domain[0],
                namespace=domain[1],
                name=name,
                kind=kind,
                purpose=body["purpose"],
                generation=op.generation,
                owner_epoch=op.owner_epoch,
                controller_epoch=body["controller_epoch"],
                spec_digest=content_digest(template),
                approved_template=template,
                status_policy_revision=policy,
            )
            row = await self.repo.create_resource_intent(
                row, holder_id=body["holder_id"], controller_epoch=body["controller_epoch"], now=now
            )
            return self._resource_document(row)

    @staticmethod
    def _resource_document(row):
        return {
            "resource_ref": row.id,
            "operation_id": row.operation_id,
            "app_id": row.app_id,
            "node_id": row.node_id,
            "cluster_id": row.cluster_id,
            "generation": row.generation,
            "owner_epoch": row.owner_epoch,
            "purpose": row.purpose,
            "status_policy_revision": row.status_policy_revision,
            "protected_since_creation": row.protected_since_creation,
            "binding_policy_verified": row.binding_policy_verified,
            "stop_requested_at": row.stop_requested_at.isoformat() if row.stop_requested_at else None,
            "stop_evidence": copy.deepcopy(row.stop_evidence),
            "observed_state": copy.deepcopy(row.observed_state),
            "template": copy.deepcopy(row.approved_template),
            "namespace": row.namespace,
            "name": row.name,
            "kind": row.kind,
            "uid": row.uid,
            "node_name": row.node_name,
            "spec_digest": row.spec_digest,
            "controller_epoch": row.controller_epoch,
            "stop_state": row.stop_state,
            "cleanup_state": row.cleanup_state,
        }

    async def resource(self, identity, resource_ref):
        _identity(identity, "manager")
        _ref(resource_ref)
        async with self._scope(identity, RuntimeExecutionResource, resource_ref) as row:
            return self._resource_document(row)

    async def resources(self, identity, operation_id):
        _identity(identity, "manager")
        async with self._scope(identity, RuntimeOperation, operation_id):
            rows = await self.repo.find(RuntimeExecutionResource, operation_id=operation_id, limit=1001)
            if len(rows) > 1000 or any(row.node_id != identity.node_id for row in rows):
                raise RuntimeConflict("resource_recovery_scope_invalid")
            return {"resources": [self._resource_document(row) for row in rows]}

    async def _observed_state(self, resource, raw):
        if raw is None:
            return None
        if (
            resource.kind != "Service"
            or not isinstance(raw, dict)
            or set(raw) != {"cluster_ip", "port"}
            or type(raw["port"]) is not int
        ):
            raise RuntimeConflict("resource_observed_state_refused")
        node = await self.repo.get(RuntimeNode, resource.node_id)
        ports = resource.approved_template.get("spec", {}).get("ports", [])
        try:
            address = ipaddress.ip_address(raw["cluster_ip"])
            cidrs = (node.capabilities or {}).get("service_cidrs", []) if node else []
            valid = (
                address.is_private
                and not (address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified)
                and any(address in ipaddress.ip_network(cidr) for cidr in cidrs)
            )
        except (ValueError, TypeError):
            valid = False
        if not valid or len(ports) != 1 or raw["port"] != ports[0].get("port"):
            raise RuntimeConflict("resource_observed_endpoint_refused")
        return {"cluster_ip": str(address), "port": raw["port"]}

    async def observe_resource(self, identity, resource_ref, body):
        _identity(identity, "manager")
        _ref(resource_ref)
        _fields(
            body,
            {"action", "holder_id", "controller_epoch"},
            {"uid", "node_name", "operation_id", "evidence", "runtime_state"},
        )
        _epoch(body["controller_epoch"])
        async with self._scope(identity, RuntimeExecutionResource, resource_ref) as resource:
            auth = {"holder_id": body["holder_id"], "controller_epoch": body["controller_epoch"], "now": self.clock()}
            if body.get("runtime_state") is not None and body["action"] != "bind":
                raise RuntimeConflict("resource_observed_state_refused")
            if body["action"] == "bind":
                _ref(body.get("uid"))
                state = await self._observed_state(resource, body.get("runtime_state"))
                row = await self.repo.bind_resource(
                    resource_ref, uid=body["uid"], node_name=body.get("node_name", ""), observed_state=state, **auth
                )
            elif body["action"] == "stop":
                if body.get("uid") and body["uid"] != resource.uid:
                    raise RuntimeConflict("resource_uid_changed")
                row = await self.repo.request_resource_stop(
                    resource_ref, operation_id=body.get("operation_id", resource.operation_id), **auth
                )
            elif body["action"] == "stopped":
                row = await self.repo.confirm_resource_stop(resource_ref, body.get("evidence"), **auth)
                pods = await self.repo.find(RuntimeExecutionResource, operation_id=row.operation_id, kind="Pod")
                operation = await self.repo.get(RuntimeOperation, row.operation_id)
                if (
                    operation
                    and operation.status in TERMINAL
                    and pods
                    and all(pod.stop_state == "confirmed" for pod in pods)
                ):
                    await self.repo.release_resources(row.operation_id)
            elif body["action"] == "cleanup":
                row = await self.repo.complete_resource_cleanup(resource_ref, uid=body.get("uid"), **auth)
            else:
                raise RuntimeConflict("resource_observation_action_refused")
            return self._resource_document(row)

    async def admission_plan(self, identity, resource_ref):
        _identity(identity, "admission")
        _ref(resource_ref)
        async with self._scope(identity, RuntimeExecutionResource, resource_ref) as row:
            node, domain = await self._node(identity.node_id, allow_blocked=True)
            if (row.cluster_id, row.namespace) != tuple(domain):
                raise RuntimeConflict("resource_execution_domain_refused")
            op = await self.repo.get(RuntimeOperation, row.operation_id)
            now = self.clock()
            live = bool(op and await self._active(op, now))
            controller = bool(
                node.lease_until and node.lease_until > now and row.controller_epoch == node.controller_epoch
            )
            pending = row.cleanup_state != "complete"
            stopped = row.stop_state == "confirmed"
            deletable = row.kind != "PersistentVolumeClaim"
            if (
                row.kind == "PersistentVolumeClaim"
                and op
                and op.kind == "prepare"
                and row.purpose.startswith("prepare-")
            ):
                writers = await self.repo.find(RuntimeExecutionResource, operation_id=op.id, kind="Pod")
                deletable = bool(writers) and all(writer.stop_state == "confirmed" for writer in writers)
            if row.kind == "PersistentVolumeClaim" and row.stop_evidence.get("cleanup_operation_id"):
                cleanup_op = await self.repo.get(RuntimeOperation, row.stop_evidence["cleanup_operation_id"])
                if cleanup_op and (cleanup_op.app_id, cleanup_op.node_id) == (row.app_id, row.node_id):
                    facts = await self.repo.find(RuntimeExecutionFact, operation_id=cleanup_op.id)
                    result = max(facts, key=lambda item: item.sequence).detail if facts else {}
                    proof = result.get("maintenance_progress", {}).get("purge", {}).get("result", {})
                    writers = await self.repo.find(RuntimeExecutionResource, app_id=row.app_id, kind="Pod")
                    deletable = bool(
                        cleanup_op.kind == "destroy"
                        and cleanup_op.payload.get("purge_volume") is True
                        and await self._active(cleanup_op, now)
                        and proof.get("purged") is True
                        and any(
                            writer.purpose == "purge" and writer.operation_id == cleanup_op.id for writer in writers
                        )
                        and all(
                            writer.stop_state == "confirmed" and writer.cleanup_state == "complete"
                            for writer in writers
                        )
                    )
            return {
                "resource_ref": row.id,
                "namespace": row.namespace,
                "name": row.name,
                "kind": row.kind,
                "uid": row.uid,
                "template": copy.deepcopy(row.approved_template),
                "spec_digest": row.spec_digest,
                "stop_state": row.stop_state,
                "stop_confirmed": stopped,
                "cleanup_only": not live,
                "service_cidrs": (node.capabilities or {}).get("service_cidrs", []),
                "allow_create": bool(
                    pending
                    and controller
                    and live
                    and node.status == "ready"
                    and row.uid is None
                    and row.stop_requested_at is None
                ),
                "allow_update": bool(pending and controller and row.uid and (live or stopped)),
                "allow_delete": bool(pending and controller and row.uid and row.stop_requested_at and deletable),
            }
