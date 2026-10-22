"""Fail-closed validating admission, independent of the cluster control identity.

Status provenance uses only the authenticated AdmissionReview. It must never
call backend: that would couple kubelet termination to control-plane recovery.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import ipaddress
import json
import logging
import os
import ssl
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from fastapi import FastAPI, Request

from runtime_manager.k8s_config import validate_namespace
from runtime_manager.k8s_templates import POLICY_ANNOTATION, RESOURCE_LABEL, STOP_FINALIZER
from runtime_manager.platform_protocol import signed_headers

logger = logging.getLogger(__name__)
_TERMINAL = {"Succeeded", "Failed"}
_CNI_ANNOTATIONS = frozenset(
    {"cni.projectcalico.org/containerID", "cni.projectcalico.org/podIP", "cni.projectcalico.org/podIPs"}
)
_KINDS = {"pods": "Pod", "services": "Service", "secrets": "Secret", "persistentvolumeclaims": "PersistentVolumeClaim"}
_META_SERVER = {
    "uid",
    "resourceVersion",
    "creationTimestamp",
    "managedFields",
    "generation",
    "deletionTimestamp",
    "deletionGracePeriodSeconds",
}


class AdmissionRefused(ValueError):
    pass


def _deny(reason):
    raise AdmissionRefused(reason)


def _terminal_states(obj):
    status = obj.get("status", {})
    return [
        [
            {
                "name": x.get("name"),
                "terminated": x.get("state", {}).get("terminated"),
                "containerID": x.get("containerID"),
            }
            for x in status.get(key, [])
            if isinstance(x, dict) and "terminated" in x.get("state", {})
        ]
        for key in ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses")
    ]


def _bound_node(user, pod):
    name = pod.get("spec", {}).get("nodeName")
    return bool(name) and user.get("username") == f"system:node:{name}" and "system:nodes" in user.get("groups", [])


def _protected(pod, revision):
    return pod.get("metadata", {}).get("annotations", {}).get(POLICY_ANNOTATION) == revision


def _quantity(value):
    raw = str(value)
    if len(raw) > 64:
        _deny("resource_quantity_invalid")
    factors = {
        "m": Decimal("0.001"),
        "Ki": Decimal(1024),
        "Mi": Decimal(1024**2),
        "Gi": Decimal(1024**3),
        "Ti": Decimal(1024**4),
        "k": Decimal(1000),
        "M": Decimal(1000**2),
        "G": Decimal(1000**3),
    }
    try:
        number = None
        for suffix in sorted(factors, key=len, reverse=True):
            if raw.endswith(suffix):
                number = Decimal(raw[: -len(suffix)]) * factors[suffix]
                break
        if number is None:
            number = Decimal(raw)
        if not number.is_finite() or not Decimal("0") < number <= Decimal(2**63 - 1) or number.adjusted() < -9:
            _deny("resource_quantity_invalid")
        return format(number.normalize(), "f")
    except InvalidOperation:
        _deny("resource_quantity_invalid")


def _normalize(value, path=()):
    if isinstance(value, list):
        return [_normalize(x, (*path, "[]")) for x in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        # These are documented API defaults, not arbitrary extra fields.
        if path == ("metadata",) and key in _META_SERVER:
            continue
        if path == () and key == "status":
            continue
        if path == ("metadata",) and key == "finalizers" and child == []:
            # ObjectMeta.Finalizers uses omitempty after the last authorized
            # finalizer is removed; nonempty protection remains compared.
            continue
        if path == ("spec",) and (key, str(child)) in {
            ("serviceAccountName", "default"),
            ("serviceAccount", "default"),
            ("schedulerName", "default-scheduler"),
            ("priority", "0"),
            ("preemptionPolicy", "PreemptLowerPriority"),
            ("sessionAffinity", "None"),
            ("internalTrafficPolicy", "Cluster"),
            ("ipFamilyPolicy", "SingleStack"),
        }:
            continue
        if key == "env" and child == [] and path in {("spec", "containers", "[]"), ("spec", "initContainers", "[]")}:
            # Core/v1 Container.Env has json:"env,omitempty"; only this empty
            # list may disappear when the API serializes a defaulted Pod.
            continue
        if key == "terminationMessagePath" and child == "/dev/termination-log":
            continue
        if key == "terminationMessagePolicy" and child == "File":
            continue
        if key == "protocol" and child == "TCP":
            continue
        if key == "readOnly" and child is False:
            continue
        if key in {"initialDelaySeconds", "successThreshold"} and child == (0 if key == "initialDelaySeconds" else 1):
            continue
        if key == "scheme" and child == "HTTP" and "httpGet" in path:
            continue
        if key == "privileged" and child is False and "securityContext" in path:
            continue
        if key in {"cpu", "memory", "ephemeral-storage", "storage"} and path[-1:] in {("limits",), ("requests",)}:
            child = _quantity(child)
        if key == "sizeLimit":
            child = _quantity(child)
        if key == "value" and child == "" and "env" in path:
            continue
        result[key] = _normalize(child, (*path, key))
    return result


def _same_identity(a, b):
    ma, mb = a.get("metadata", {}), b.get("metadata", {})
    return bool(ma.get("uid")) and all(ma.get(k) == mb.get(k) for k in ("uid", "name", "namespace"))


class AdmissionPolicy:
    def __init__(
        self,
        *,
        namespace: str,
        manager_username: str,
        status_policy_revision: str,
        plan_reader: Callable[[str], dict],
        data_key_configmap: str = "runtime-data-public-keys",
        cni_username: str = "",
        storage_controller_usernames: tuple[str, ...] = ("system:kube-controller-manager", "system:kube-scheduler"),
    ):
        self.namespace = validate_namespace(namespace)
        if not manager_username.startswith("system:serviceaccount:") or not status_policy_revision:
            raise ValueError("admission_identity_or_policy_invalid")
        self.manager_username = manager_username
        self.revision = status_policy_revision
        self.plan_reader = plan_reader
        self.data_key_configmap = validate_namespace(data_key_configmap)
        if cni_username and not cni_username.startswith("system:serviceaccount:"):
            raise ValueError("admission_cni_identity_invalid")
        self.cni_username = cni_username
        if any(not isinstance(value, str) or not value.startswith("system:") for value in storage_controller_usernames):
            raise ValueError("admission_storage_identity_invalid")
        self.storage_controller_usernames = tuple(storage_controller_usernames)

    def review(self, review: dict) -> dict:
        uid = ""
        try:
            if (
                not isinstance(review, dict)
                or review.get("apiVersion") != "admission.k8s.io/v1"
                or review.get("kind") != "AdmissionReview"
            ):
                _deny("admission_review_invalid")
            req = review.get("request", {})
            uid = req.get("uid", "")
            if not isinstance(uid, str) or not uid:
                _deny("admission_uid_required")
            self.validate(req)
            result = {"uid": uid, "allowed": True}
        except AdmissionRefused as exc:
            result = {"uid": uid, "allowed": False, "status": {"code": 403, "message": str(exc)}}
        except (KeyError, TypeError, ValueError, AttributeError):
            result = {"uid": uid, "allowed": False, "status": {"code": 403, "message": "admission_input_invalid"}}
        return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": result}

    def validate(self, req):
        if req.get("namespace") != self.namespace:
            _deny("admission_namespace_refused")
        resource = req.get("resource", {})
        kind = _KINDS.get(resource.get("resource"))
        if resource.get("group") != "" or resource.get("version") != "v1" or not kind:
            _deny("admission_resource_refused")
        op, sub = req.get("operation"), req.get("subResource", "")
        old = req.get("oldObject") or {}
        obj = (req.get("object") or {}) if op != "DELETE" else old
        if sub:
            if sub != "status" or kind != "Pod" or op != "UPDATE":
                _deny("admission_subresource_refused")
            self._status(req, old, obj)
            return
        if op not in {"CREATE", "UPDATE", "DELETE"}:
            _deny("admission_operation_refused")
        # Kubelet shortens an already-terminal deleting Pod after local shutdown.
        # It does not remove the protection finalizer or write platform stop facts.
        if op == "DELETE" and kind == "Pod" and _bound_node(req.get("userInfo", {}), old):
            if self._terminal_delete(req, old):
                return
            _deny("admission_kubelet_delete_unconfirmed")
        if (
            kind == "PersistentVolumeClaim"
            and op == "UPDATE"
            and req.get("userInfo", {}).get("username") in self.storage_controller_usernames
        ):
            self._pvc_binding(old, obj)
            return
        if self.cni_username and req.get("userInfo", {}).get("username") == self.cni_username:
            if kind != "Pod" or op != "UPDATE":
                _deny("admission_cni_operation_refused")
            self._cni_metadata(old, obj)
            return
        if req.get("userInfo", {}).get("username") != self.manager_username:
            _deny("admission_actor_refused")
        meta = obj.get("metadata", {})
        if meta.get("namespace") != self.namespace or meta.get("name") != req.get("name"):
            _deny("admission_object_scope_refused")
        ref = meta.get("labels", {}).get(RESOURCE_LABEL, "")
        if not isinstance(ref, str) or not ref or len(ref) > 63:
            _deny("admission_resource_ref_required")
        try:
            plan = self.plan_reader(ref)
        except Exception as exc:
            # Only a safe type name is logged; backend failure must deny creation.
            logger.warning("admission plan unavailable (%s)", type(exc).__name__)
            _deny("admission_plan_unavailable")
        if not isinstance(plan, dict) or (
            plan.get("resource_ref"),
            plan.get("namespace"),
            plan.get("name"),
            plan.get("kind"),
        ) != (
            ref,
            self.namespace,
            meta.get("name"),
            kind,
        ):
            _deny("admission_plan_scope_refused")
        if not plan.get("allow_" + op.lower(), False) or (op == "CREATE" and plan.get("cleanup_only")):
            _deny("admission_plan_action_refused")
        if op != "CREATE" and (meta.get("uid") != plan.get("uid") or not meta.get("uid")):
            _deny("admission_uid_refused")
        if op == "DELETE":
            self._delete(req, obj)
            return
        expected = plan.get("template")
        if not isinstance(expected, dict):
            _deny("admission_template_required")
        comparison = copy.deepcopy(obj)
        expected = copy.deepcopy(expected)
        if op == "CREATE":
            self._create_status(kind, obj)
        if kind == "Pod":
            # The frozen plan predates CNI attachment. Never treat manager input
            # as CNI provenance, even when it also appears in that frozen plan.
            if self._cni_annotations(expected):
                _deny("admission_cni_prefilled_refused")
            if op == "CREATE" and self._cni_annotations(obj):
                _deny("admission_cni_prefilled_refused")
            self._pod_baseline(obj)
            if op == "CREATE" and obj["spec"].get("nodeName"):
                _deny("admission_node_binding_refused")
            if op == "UPDATE":
                if not _same_identity(old, obj) or old.get("spec", {}).get("nodeName") != obj["spec"].get("nodeName"):
                    _deny("admission_binding_changed")
                # oldObject is the API server's same-UID persisted state. Only
                # the configured CNI actor can have introduced these fields;
                # the manager may preserve them but never add/change/remove one.
                before_cni, after_cni = self._cni_annotations(old), self._cni_annotations(obj)
                if before_cni != after_cni or (before_cni and not self.cni_username):
                    _deny("admission_cni_source_mutation_refused")
                for key in before_cni:
                    comparison["metadata"]["annotations"].pop(key)
                comparison["spec"].pop("nodeName", None)
                if STOP_FINALIZER not in meta.get("finalizers", []):
                    if plan.get("stop_state") != "confirmed":
                        _deny("admission_stop_unconfirmed")
                    expected["metadata"]["finalizers"] = [
                        x for x in expected["metadata"].get("finalizers", []) if x != STOP_FINALIZER
                    ]
        elif kind == "PersistentVolumeClaim" and op == "CREATE":
            if comparison.get("metadata", {}).get("finalizers") == ["kubernetes.io/pvc-protection"]:
                comparison["metadata"].pop("finalizers")
        elif kind == "Service":
            self._service(comparison, plan)
        comparison = template_projection(comparison)
        if _normalize(comparison) != _normalize(expected):
            _deny("admission_template_mismatch")

    @staticmethod
    def _create_status(kind, obj):
        # Kubernetes v1.28.15 Store.Create calls BeforeCreate before validators.
        # Pod strategy resets status to Pending/GetPodQOS; PVC clears it, while
        # empty ServiceStatus serializes its loadBalancer struct as {}.
        # https://github.com/kubernetes/kubernetes/blob/v1.28.15/pkg/registry/core/pod/strategy.go
        if "status" not in obj:
            return
        status = obj["status"]
        if not isinstance(status, dict) or kind == "Secret":
            _deny("admission_prefilled_status_refused")
        if not status:
            return
        if kind == "Service" and status == {"loadBalancer": {}}:
            return
        if kind != "Pod":
            _deny("admission_prefilled_status_refused")
        spec = obj.get("spec", {})
        containers = [*spec.get("containers", []), *spec.get("initContainers", [])]
        # The mandatory baseline requires positive CPU/memory requests/limits
        # for every container, so BestEffort is impossible. GetPodQOS sums both
        # normal and init-container resources and compares equivalent quantities.
        qos = "Guaranteed"
        for resource in ("cpu", "memory"):
            totals = [
                sum(Decimal(_quantity(container["resources"][side][resource])) for container in containers)
                for side in ("requests", "limits")
            ]
            if totals[0] != totals[1]:
                qos = "Burstable"
        if status != {"phase": "Pending", "qosClass": qos}:
            _deny("admission_prefilled_status_refused")

    def _pvc_binding(self, old, obj):
        if not _same_identity(old, obj) or not _protected(old, self.revision) or not _protected(obj, self.revision):
            _deny("admission_pvc_identity_refused")
        previous, current = old.get("spec", {}).get("volumeName"), obj.get("spec", {}).get("volumeName")
        if previous and previous != current:
            _deny("admission_pvc_rebinding_refused")
        if current and (not isinstance(current, str) or len(current) > 253):
            _deny("admission_pvc_binding_invalid")
        if old.get("status", {}) != obj.get("status", {}):
            _deny("admission_pvc_status_refused")
        before, after = copy.deepcopy(old), copy.deepcopy(obj)
        annotations = {
            "pv.kubernetes.io/bind-completed",
            "pv.kubernetes.io/bound-by-controller",
            "volume.kubernetes.io/selected-node",
            "volume.kubernetes.io/storage-provisioner",
            "volume.beta.kubernetes.io/storage-provisioner",
        }
        for claim in (before, after):
            claim["spec"].pop("volumeName", None)
            meta = claim["metadata"]
            values = meta.get("annotations", {})
            for key in annotations:
                value = values.pop(key, "")
                if not isinstance(value, str) or len(value) > 256 or "\n" in value:
                    _deny("admission_pvc_annotation_invalid")
            if not values:
                meta.pop("annotations", None)
            finalizers = [value for value in meta.get("finalizers", []) if value != "kubernetes.io/pvc-protection"]
            if finalizers:
                meta["finalizers"] = finalizers
            else:
                meta.pop("finalizers", None)
        if _normalize(before) != _normalize(after):
            _deny("admission_pvc_controller_mutation_refused")

    @staticmethod
    def _cni_annotations(pod):
        annotations = pod.get("metadata", {}).get("annotations", {})
        if not isinstance(annotations, dict):
            _deny("admission_cni_annotation_invalid")
        values = {}
        for key in _CNI_ANNOTATIONS:
            if key not in annotations:
                continue
            value = annotations[key]
            if not isinstance(value, str) or len(value) > 256 or any(c in value for c in "\r\n\x00"):
                _deny("admission_cni_annotation_invalid")
            if value and key.endswith(("podIP", "podIPs")):
                try:
                    if any(not ipaddress.ip_interface(part).ip.is_private for part in value.split(",")):
                        raise ValueError()
                except ValueError:
                    _deny("admission_cni_annotation_invalid")
            values[key] = value
        return values

    def _cni_metadata(self, old, obj):
        if not _same_identity(old, obj) or not _protected(old, self.revision) or not _protected(obj, self.revision):
            _deny("admission_cni_identity_refused")
        if old.get("status", {}) != obj.get("status", {}):
            _deny("admission_cni_status_refused")
        before, after = copy.deepcopy(old), copy.deepcopy(obj)
        for pod in (before, after):
            values = self._cni_annotations(pod)
            annotations = pod["metadata"].get("annotations", {})
            for key in values:
                annotations.pop(key)
            if not annotations:
                pod["metadata"].pop("annotations", None)
        if _normalize(before) != _normalize(after):
            _deny("admission_cni_mutation_refused")
        self._pod_baseline(obj)

    def _pod_baseline(self, obj):
        spec, meta = obj.get("spec", {}), obj.get("metadata", {})
        if not _protected(obj, self.revision) or any(
            spec.get(k) for k in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")
        ):
            _deny("admission_pod_baseline_refused")
        if spec.get("automountServiceAccountToken") is not False or meta.get("ownerReferences"):
            _deny("admission_pod_identity_refused")
        if not spec.get("containers") or spec.get("ephemeralContainers"):
            _deny("admission_containers_invalid")
        for volume in spec.get("volumes", []):
            if set(volume) - {"name", "emptyDir", "secret", "persistentVolumeClaim", "configMap"}:
                _deny("admission_volume_refused")
            if "configMap" in volume and (
                volume.get("name") != "data-keys"
                or volume["configMap"]
                != {
                    "name": self.data_key_configmap,
                    "defaultMode": 292,
                    "items": [{"key": "public-keys.json", "path": "public-keys.json"}],
                }
            ):
                _deny("admission_public_keys_refused")
        for c in [*spec.get("containers", []), *spec.get("initContainers", [])]:
            security = c.get("securityContext", {})
            if (
                security.get("runAsNonRoot") is not True
                or security.get("runAsUser", 0) <= 0
                or security.get("runAsGroup", 0) <= 0
            ):
                _deny("admission_root_refused")
            if (
                security.get("allowPrivilegeEscalation") is not False
                or security.get("privileged")
                or security.get("readOnlyRootFilesystem") is not True
            ):
                _deny("admission_privilege_refused")
            if security.get("capabilities") != {"drop": ["ALL"]} or security.get("seccompProfile") != {
                "type": "RuntimeDefault"
            }:
                _deny("admission_security_profile_refused")
            if any(p.get("hostPort") or p.get("hostIP") for p in c.get("ports", [])):
                _deny("admission_host_port_refused")
            resources = c.get("resources", {})
            if not all(
                all(resources.get(k, {}).get(v) for v in ("cpu", "memory", "ephemeral-storage"))
                for k in ("requests", "limits")
            ):
                _deny("admission_resources_required")

    def _status(self, req, old, obj):
        # Calico maintains its network annotations through pods/status. Only
        # the installed CNI actor may do so, retaining the bound Pod's complete
        # spec and status; _cni_metadata fences UID and all other metadata.
        if self.cni_username and req.get("userInfo", {}).get("username") == self.cni_username:
            if not old.get("spec", {}).get("nodeName") or old.get("spec", {}) != obj.get("spec", {}):
                _deny("admission_cni_spec_refused")
            self._cni_metadata(old, obj)
            return
        # Other status actors, including the bound kubelet, preserve CNI fields.
        if self._cni_annotations(old) != self._cni_annotations(obj):
            _deny("admission_cni_source_mutation_refused")
        if not _same_identity(old, obj) or old.get("spec", {}).get("nodeName") != obj.get("spec", {}).get("nodeName"):
            _deny("admission_status_identity_refused")
        if not _protected(old, self.revision) or not _protected(obj, self.revision):
            _deny("admission_status_policy_refused")
        before, after = old.get("status", {}).get("phase"), obj.get("status", {}).get("phase")
        if before in _TERMINAL and after not in _TERMINAL:
            _deny("admission_terminal_reactivation_refused")
        terminal_change = (after in _TERMINAL and before != after) or _terminal_states(old) != _terminal_states(obj)
        if terminal_change and not _bound_node(req.get("userInfo", {}), obj):
            _deny("admission_terminal_source_refused")
        if before in _TERMINAL or after in _TERMINAL:
            for key in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses"):
                if any("running" in x.get("state", {}) for x in obj.get("status", {}).get(key, [])):
                    _deny("admission_terminal_running_refused")

    def _delete(self, req, obj):
        opts, meta = req.get("options") or {}, obj.get("metadata", {})
        cond = opts.get("preconditions", {})
        if cond.get("uid") != meta.get("uid") or cond.get("resourceVersion") != meta.get("resourceVersion"):
            _deny("admission_delete_precondition_required")
        grace = opts.get("gracePeriodSeconds")
        status = obj.get("status", {})
        # Core/v1 forces zero grace before admission for a never-bound Pod.
        # Exact UID/RV checks above still fence a concurrent scheduler binding;
        # zero grace is never accepted for a possible current or former writer.
        normalized_unbound = (
            obj.get("kind") == "Pod"
            and type(grace) is int
            and grace == 0
            and not obj.get("spec", {}).get("nodeName")
            and status.get("phase") == "Pending"
            and status.get("reason") not in {"Unknown", "NodeLost"}
            and not any(
                status.get(key) for key in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses")
            )
            and not any(
                item.get("type") == "PodScheduled" and item.get("status") == "True"
                for item in status.get("conditions", [])
            )
        )
        if not normalized_unbound and (type(grace) is not int or not 1 <= grace <= 120):
            _deny("admission_force_delete_refused")

    def _terminal_delete(self, req, obj):
        meta, status, opts = obj.get("metadata", {}), obj.get("status", {}), req.get("options") or {}
        return bool(
            meta.get("deletionTimestamp")
            and STOP_FINALIZER in meta.get("finalizers", [])
            and _protected(obj, self.revision)
            and status.get("phase") in _TERMINAL
            and status.get("reason") not in {"NodeLost", "Unknown"}
            and opts.get("preconditions", {}).get("uid") == meta.get("uid")
            and type(opts.get("gracePeriodSeconds")) is int
            and 0 <= opts["gracePeriodSeconds"] <= 30
            and not any(
                "running" in x.get("state", {})
                for key in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses")
                for x in status.get(key, [])
            )
        )

    def _service(self, obj, plan):
        spec = obj.get("spec", {})
        if (
            spec.get("type") != "ClusterIP"
            or spec.get("externalIPs")
            or spec.get("externalName")
            or spec.get("loadBalancerIP")
        ):
            _deny("admission_service_exposure_refused")
        cidrs = [ipaddress.ip_network(x) for x in plan.get("service_cidrs", [])]
        for key in ("clusterIP", "clusterIPs"):
            values = spec.pop(key, [])
            for value in [values] if isinstance(values, str) else values:
                address = ipaddress.ip_address(value)
                if not any(address in network for network in cidrs):
                    _deny("admission_service_ip_refused")
        families = spec.pop("ipFamilies", [])
        if any(x not in {"IPv4", "IPv6"} for x in families):
            _deny("admission_service_family_refused")


def secret_projection(obj: dict) -> dict:
    """The platform-approved form contains no raw material private key."""
    comparison = copy.deepcopy(obj)
    data = comparison.pop("data", {})
    if not isinstance(data, dict) or not data or "stringData" in comparison:
        _deny("admission_secret_invalid")
    if comparison.get("type") != "Opaque" or comparison.get("immutable") is not True:
        _deny("admission_secret_type_refused")
    try:
        size = sum(
            len(base64.b64decode(v, validate=True))
            for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str)
        )
        if size > 65536 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
            _deny("admission_secret_size_invalid")
    except (ValueError, binascii.Error):
        _deny("admission_secret_encoding_invalid")
    comparison["data_sha256"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return comparison


def template_projection(obj: dict) -> dict:
    """Safe for the backend ledger: no Secret bytes or environment values."""
    if obj.get("kind") == "Secret":
        return secret_projection(obj)
    projected = copy.deepcopy(obj)
    if projected.get("kind") == "Pod":
        spec = projected.get("spec", {})
        for container in [*spec.get("containers", []), *spec.get("initContainers", [])]:
            for env in container.get("env", []):
                if "valueFrom" in env:
                    if env.pop("value", ""):
                        _deny("admission_environment_ambiguous")
                    continue
                raw = env.pop("value", "")
                if not isinstance(raw, str):
                    _deny("admission_environment_invalid")
                env["value_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return projected


def create_app(policy: AdmissionPolicy):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/validate")
    async def validate(request: Request):
        raw = await request.body()
        if len(raw) > 2 * 1024 * 1024:
            return policy.review({})
        try:
            review = json.loads(raw)
        except (ValueError, UnicodeError):
            review = {}
        return policy.review(review)

    return app


class AdmissionPlanClient:
    """Separate read-only backend principal. No Kubernetes API client/token."""

    def __init__(self, base_url, *, key_id, secret_file, ca_file=None, transport=None):
        parsed = httpx.URL(base_url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("admission_backend_url_invalid")
        self.key_id, self.secret_file = key_id, Path(secret_file)
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            verify=context,
            timeout=2.0,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def __call__(self, resource_ref):
        if (
            not resource_ref
            or len(resource_ref) > 63
            or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_." for c in resource_ref)
        ):
            raise ValueError("admission_resource_ref_invalid")
        path = "/api/v1/internal/app-runtime/v2/admission/plans/" + resource_ref
        try:
            secret = self.secret_file.read_text().strip()
            if not 32 <= len(secret) <= 4096:
                raise ValueError("admission_key_invalid")
            headers = signed_headers("GET", path, b"", key_id=self.key_id, secret=secret)
            response = self.http.get(path, headers=headers)
            if response.status_code != 200 or len(response.content) > 1024 * 1024:
                raise ValueError("admission_backend_refused")
            result = response.json()
        except (httpx.HTTPError, OSError, UnicodeError, ValueError):
            raise AdmissionRefused("admission_plan_unavailable") from None
        if not isinstance(result, dict):
            raise AdmissionRefused("admission_plan_invalid")
        return result

    def close(self):
        self.http.close()


class CanaryPlanReader:
    """Installer-owned finite bootstrap plans; never backend business authority."""

    def __init__(self, fallback, path, *, namespace, helper_image, clock=None):
        import time

        self.fallback, self.path = fallback, Path(path)
        self.namespace, self.helper_image = validate_namespace(namespace), helper_image
        self.clock = clock or time.time

    def __call__(self, reference):
        from uuid import UUID

        try:
            with self.path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            return self.fallback(reference)
        if len(raw) > 1024 * 1024:
            raise ValueError("canary_document_invalid")
        document = json.loads(raw)
        if document.get("schema_version") != 1 or not isinstance(document.get("plans"), dict):
            raise ValueError("canary_document_invalid")
        plan = document["plans"].get(reference)
        if plan is None:
            return self.fallback(reference)
        try:
            if str(UUID(reference)) != reference:
                raise ValueError()
            expires = plan["expires_at"]
            if type(expires) not in {int, float} or not 0 < expires - self.clock() <= 3600:
                raise ValueError()
            name, template = plan["name"], plan["template"]
            meta = template["metadata"]
            if (plan["resource_ref"], plan["namespace"], template["kind"], meta["name"], meta["namespace"]) != (
                reference,
                self.namespace,
                plan["kind"],
                name,
                self.namespace,
            ):
                raise ValueError()
            if not name.startswith("preflight-") or meta.get("labels", {}).get(RESOURCE_LABEL) != reference:
                raise ValueError()
            if not meta.get("annotations", {}).get("runtime.bisheng.io/operation", "").startswith("preflight-"):
                raise ValueError()
            uid = plan.get("uid")
            if plan.get("allow_create") and uid is not None:
                raise ValueError()
            if (plan.get("allow_update") or plan.get("allow_delete")) and (
                not isinstance(uid, str) or str(UUID(uid)) != uid
            ):
                raise ValueError()
            if plan["kind"] == "Pod":
                spec = template["spec"]
                if meta.get("labels", {}).get("runtime.bisheng.io/purpose") != "probe":
                    raise ValueError()
                if type(spec.get("activeDeadlineSeconds")) is not int or not 1 <= spec["activeDeadlineSeconds"] <= 600:
                    raise ValueError()
                for volume in spec.get("volumes", []):
                    if set(volume) - {"name", "emptyDir", "persistentVolumeClaim"}:
                        raise ValueError()
                    if "persistentVolumeClaim" in volume and not volume["persistentVolumeClaim"].get(
                        "claimName", ""
                    ).startswith("preflight-"):
                        raise ValueError()
                commands = {
                    ("python", "-I", "-m", "runtime_manager.k8s_capabilities", action)
                    for action in ("network", "storage", "idle")
                } | {("python", "-I", "-m", "runtime_manager.k8s_helper", "data-layout")}
                native = {
                    ("python", "-I", "-c", "import platform; print(platform.machine())"),
                    ("node", "-e", "console.log(process.arch)"),
                    ("python", "--version"),
                    ("node", "--version"),
                    ("nginx", "-v"),
                    ("nginx", "-t"),
                }
                profile_images = document.get("profile_images", [])
                for container in [*spec.get("containers", []), *spec.get("initContainers", [])]:
                    command = tuple(container.get("command", []))
                    if container.get("args") or any("valueFrom" in env for env in container.get("env", [])):
                        raise ValueError()
                    if container.get("image") == self.helper_image:
                        if command not in commands | native:
                            raise ValueError()
                    elif container.get("image") not in profile_images or command not in native:
                        raise ValueError()
            elif plan["kind"] != "PersistentVolumeClaim":
                raise ValueError()
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ValueError("canary_plan_refused") from None
        return copy.deepcopy(plan)


def main():
    """Internal HTTPS endpoint; installer network policy restricts API-server access."""
    import uvicorn

    client = AdmissionPlanClient(
        os.environ["RTM_ADMISSION_PLATFORM_URL"],
        key_id=os.environ["RTM_ADMISSION_KEY_ID"],
        secret_file=os.environ["RTM_ADMISSION_SECRET_FILE"],
        ca_file=os.getenv("RTM_ADMISSION_PLATFORM_CA_FILE"),
    )
    reader = client
    if os.getenv("RTM_ADMISSION_CANARY_PLANS_FILE"):
        reader = CanaryPlanReader(
            client,
            os.environ["RTM_ADMISSION_CANARY_PLANS_FILE"],
            namespace=os.environ["RTM_K8S_NAMESPACE"],
            helper_image=os.environ["RTM_ADMISSION_HELPER_IMAGE"],
        )
    policy = AdmissionPolicy(
        namespace=os.environ["RTM_K8S_NAMESPACE"],
        manager_username=os.environ["RTM_ADMISSION_MANAGER_USERNAME"],
        status_policy_revision=os.environ["RTM_ADMISSION_STATUS_POLICY_REVISION"],
        plan_reader=reader,
        data_key_configmap=os.getenv("RTM_DATA_PUBLIC_KEYS_CONFIGMAP", "runtime-data-public-keys"),
        cni_username=os.getenv("RTM_ADMISSION_CNI_USERNAME", ""),
        storage_controller_usernames=tuple(
            json.loads(
                os.getenv(
                    "RTM_STORAGE_CONTROLLER_USERNAMES", '["system:kube-controller-manager","system:kube-scheduler"]'
                )
            )
        ),
    )
    try:
        uvicorn.run(
            create_app(policy),
            host="0.0.0.0",
            port=8443,
            access_log=False,
            ssl_certfile=os.environ["RTM_ADMISSION_TLS_CERT_FILE"],
            ssl_keyfile=os.environ["RTM_ADMISSION_TLS_KEY_FILE"],
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
