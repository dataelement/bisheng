#!/usr/bin/env python3
"""Installer verification: read-only by default; --live creates scoped canaries.

The installer impersonates the manager for namespaced resource operations.
Only its own preflight resources are removed, with fresh UID/RV stop evidence.
Kubeconfig, HMAC credentials and private signing keys are never printed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

_RUNTIME = Path(__file__).resolve().parents[1] / "src/runtime-manager"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from runtime_manager.k8s_admission import template_projection  # noqa: E402 - Repository CLI bootstrap.
from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, descriptor_digest  # noqa: E402
from runtime_manager.k8s_config import validate_namespace  # noqa: E402
from runtime_manager.k8s_templates import (  # noqa: E402
    POLICY_ANNOTATION,
    RESOURCE_LABEL,
    STOP_FINALIZER,
    PodPlan,
    pod_template,
)
from runtime_manager.platform_protocol import signed_headers  # noqa: E402

_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
_RESULT = "BISHENG_RUNTIME_RESULT "
# A pattern match is insufficient: arbitrary secret text can look like a code.
_SAFE_PROBE_REASONS = frozenset(
    {
        "admission_negative_unconfirmed",
        "admission_negative_was_accepted",
        "admission_refresh_identity_changed",
        "admission_refresh_refused",
        "admission_refresh_revision_unconfirmed",
        "admission_refresh_scope_invalid",
        "admission_refresh_targets_unavailable",
        "assembly_registry_not_configured",
        "binding_canary_already_scheduled",
        "binding_delete_fence_unconfirmed",
        "binding_deletion_observation_invalid",
        "control_cleanup_identity_changed",
        "control_probe_failed",
        "control_probe_identity_changed",
        "control_probe_result_missing",
        "cri_architecture_mismatch",
        "cri_image_identity_unconfirmed",
        "cri_requested_image_changed",
        "descriptor_changed_during_probe",
        "direct_denial_targets_incomplete",
        "dns_control_unconfirmed",
        "dns_denial_target_invalid",
        "egress_proxy_target_invalid",
        "ingress_pod_ip_missing",
        "kubectl_request_failed",
        "namespace_budget_unconfirmed",
        "namespace_ownership_unconfirmed",
        "optional_runtime_class_not_configured",
        "platform_authenticated_probe_refused",
        "platform_node_scope_mismatch",
        "platform_origin_invalid",
        "platform_unsigned_probe_accepted",
        "preflight_absence_unconfirmed",
        "preflight_cleanup_identity_changed",
        "preflight_create_refused",
        "preflight_delete_identity_changed",
        "preflight_delete_refused",
        "preflight_finalizer_release_refused",
        "preflight_log_identity_changed",
        "preflight_plans_invalid",
        "preflight_pod_failed",
        "preflight_pod_replaced",
        "preflight_pvc_writer_unconfirmed",
        "preflight_recovery_identity_changed",
        "preflight_recovery_scope_invalid",
        "preflight_recovery_uid_unconfirmed",
        "preflight_result_missing",
        "probe_deadline_exceeded",
        "probe_driver_set_incomplete",
        "rbac_exec_allowed",
        "rbac_exec_api_not_refused",
        "rbac_scope_unconfirmed",
        "registry_probe_digest_invalid",
        "registry_probe_digest_mismatch",
        "registry_probe_failed",
        "runtime_profile_invalid",
        "runtime_profiles_not_verified",
        "status_negative_unconfirmed",
        "storage_capacity_not_bounded",
        "storage_not_qualified",
    }
)
_SAFE_CHECK_NAMES = REQUIRED_CHECKS | {"registry-push", "sandbox-recommended", "sandbox-hardened"}


class ProbeError(RuntimeError):
    """Only a safe reason is exposed; command output can contain private data."""


class ProbeRunFailure(RuntimeError):
    """Keep probe and cleanup failures without relying on traceback rendering."""

    def __init__(self, probe_error, cleanup_error, report=None):
        super().__init__("probe_run_failed")
        self.probe_error, self.cleanup_error, self.report = probe_error, cleanup_error, report


def safe_exception_type(name):
    return name if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) else "Exception"


def safe_failure(error):
    # Inspect only the exact constant argument; never invoke an exception's
    # __str__ or copy command output, response bodies, headers, or objects.
    reason = error.args[0] if isinstance(error, ProbeError) and len(error.args) == 1 else None
    return {
        "reason": reason if isinstance(reason, str) and reason in _SAFE_PROBE_REASONS else "probe_failed",
        "exception_type": safe_exception_type(type(error).__name__),
    }


def failure_details(error):
    if not isinstance(error, ProbeRunFailure):
        return [{"phase": "probe", **safe_failure(error)}]
    failures = []
    if error.probe_error is not None:
        failures.append({"phase": "probe", **safe_failure(error.probe_error)})
    for row in (error.report or {}).get("checks", []):
        if row.get("ok") is not False or row.get("name") not in _SAFE_CHECK_NAMES:
            continue
        exception_type = safe_exception_type(row.get("exception_type"))
        reason = row.get("reason")
        failures.append(
            {
                "phase": "check",
                "name": row["name"],
                "reason": reason
                if exception_type == "ProbeError" and reason in _SAFE_PROBE_REASONS
                else "probe_failed",
                "exception_type": exception_type,
            }
        )
    failures.append({"phase": "cleanup", **safe_failure(error.cleanup_error)})
    return failures


def log_failures(failures):
    print(
        json.dumps({"event": "runtime_installation_verification_failed", "failures": failures}, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


def network_plan(targets):
    result = []
    if not isinstance(targets, list) or not targets or len(targets) > 32:
        raise ValueError("probe_network_targets_invalid")
    for row in targets:
        if row.get("expected") == "denied" and row.get("control_confirmed") is not True:
            raise ValueError("probe_network_control_required")
        value = {key: row[key] for key in ("name", "host", "port", "expected")}
        if "protocol" in row:
            value["protocol"] = row["protocol"]
        if (
            value["expected"] not in {"allowed", "denied"}
            or type(value["port"]) is not int
            or not 1 <= value["port"] <= 65535
        ):
            raise ValueError("probe_network_target_invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value["name"]):
            raise ValueError("probe_network_name_invalid")
        ipaddress.ip_address(value["host"])
        if value.get("protocol", "tcp") not in {"tcp", "udp-dns"}:
            raise ValueError("probe_network_protocol_invalid")
        result.append(value)
    return {"targets": result}


def check_result(name, raw, uid):
    if str(UUID(uid)) != uid or not isinstance(raw, dict):
        raise ValueError("probe_result_invalid")
    if name == "storage-sqlite":
        passed = (
            all(raw.get(key) is True for key in ("locking", "fsync", "sqlite_integrity"))
            and raw.get("filesystem") in {"ext4", "xfs"}
            and type(raw.get("capacity_bytes")) is int
            and raw["capacity_bytes"] > 0
        )
    elif name.startswith("network-"):
        rows = raw.get("checks")
        passed = isinstance(rows, list) and bool(rows) and all(row.get("ok") is True for row in rows)
    else:
        passed = raw.get("verified") is True
    if not passed:
        raise ValueError("probe_result_unconfirmed")
    return {"ok": True, "evidence": {"uid": uid}}


def stop_confirmed(pod, *, binding_verified=False):
    meta, spec, status = (
        pod.get("metadata", {}),
        pod.get("spec", {}),
        pod.get("status", {}),
    )
    if not meta.get("name", "").startswith("preflight-") or not meta.get("uid") or not meta.get("deletionTimestamp"):
        return False
    if status.get("reason") in {"NodeLost", "Unknown"} or status.get("phase") == "Unknown":
        return False
    states = [
        row.get("state", {})
        for key in (
            "containerStatuses",
            "initContainerStatuses",
            "ephemeralContainerStatuses",
        )
        for row in status.get(key, [])
    ]
    return not any("running" in state for state in states) and (
        (not spec.get("nodeName") and not states and binding_verified) or status.get("phase") in {"Succeeded", "Failed"}
    )


def execute_checks(drivers, document, *, observed_at):
    rows, artifacts = [], {}
    for name, driver in sorted(drivers.items()):
        try:
            result = driver()
            uid = result["evidence"]["uid"]
            if result.get("ok") is not True or str(UUID(uid)) != uid:
                raise ValueError()
            row = {
                "name": name,
                "ok": True,
                "reason": "verified",
                "evidence": result["evidence"],
            }
            if result.get("observations"):
                artifacts[name] = result["observations"]
        except Exception as error:
            row = {"name": name, "ok": False, **safe_failure(error), "evidence": {}}
        rows.append({**row, "observed_at": observed_at})
    return {
        "artifacts": artifacts,
        "source": "cluster-probe",
        "observed_at": observed_at,
        "descriptor_digest": descriptor_digest(document),
        "checks": rows,
    }


def offline_inventory(manifest, document, dependencies=()):
    """Check supplied release metadata and local dependency bytes separately.

    This is inventory evidence only; live CRI and publication tests remain
    mandatory. No tag or local Docker image ID substitutes for a manifest ref.
    """
    platform = document["platform"]
    if manifest.get("schema_version") != 2:
        raise ValueError("offline_release_schema_invalid")
    if "platforms" in manifest:
        images = manifest["platforms"].get(platform, {})
    elif manifest.get("platform") == platform and manifest.get("state") == "published-native-verified":
        images = manifest.get("images", {})
    else:
        raise ValueError("offline_release_platform_unverified")
    required = {
        "runtime-manager",
        "app-proxy",
        "runtime-helper",
        "runtime-assembler",
        "app-python",
        "app-python-preparer",
        "app-node",
        "app-node-preparer",
        "app-static",
    }
    if set(images) != required:
        raise ValueError("offline_release_images_incomplete")
    known = set()
    for image in images.values():
        if (
            not _IMAGE.fullmatch(image.get("image") or "")
            or image.get("native_smoke") is not True
            or image.get("platform") != platform
        ):
            raise ValueError("offline_release_digest_or_native_unverified")
        known.add(image["image"])
    selected = [document["helper_image"], document.get("assembler_image", "")]
    selected += [profile["runtime_image"] for profile in document.get("canary_profiles", [])]
    if any(image and image not in known for image in selected):
        raise ValueError("offline_descriptor_release_mismatch")
    checked = []
    for item in dependencies:
        path = Path(item["path"])
        if path.is_symlink() or not path.is_file() or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
            raise ValueError("offline_dependency_inventory_invalid")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != item["sha256"]:
            raise ValueError("offline_dependency_digest_mismatch")
        checked.append({"sha256": digest.hexdigest(), "bytes": path.stat().st_size})
    return {
        "platform": platform,
        "image_references": sorted(known),
        "dependencies": checked,
        "cri_started": False,
        "dependency_resolution_executed": False,
        "platform_apis_verified": False,
    }


class Kubectl:
    def __init__(
        self,
        *,
        context,
        control_namespace,
        execution_namespace,
        manager_account,
        binary="kubectl",
    ):
        self.context, self.binary = context, binary
        self.control, self.execution = (
            validate_namespace(control_namespace),
            validate_namespace(execution_namespace),
        )
        if not _NAME.fullmatch(manager_account):
            raise ValueError("manager_account_invalid")
        self.account = manager_account

    def call(self, args, *, document=None, manager=False, accepted=(0,), timeout=40):
        command = [self.binary, "--context", self.context, "--request-timeout=30s"]
        if manager:
            command += [
                "--as",
                f"system:serviceaccount:{self.control}:{self.account}",
                "--as-group",
                "system:serviceaccounts",
                "--as-group",
                f"system:serviceaccounts:{self.control}",
                "--as-group",
                "system:authenticated",
            ]
        response = subprocess.run(
            command + args,
            input=json.dumps(document) if document is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if response.returncode not in accepted:
            raise ProbeError("kubectl_request_failed")
        return response

    def get(self, kind, name, *, namespace=None, manager=False):
        return json.loads(
            self.call(
                ["get", kind, name, "-n", namespace or self.execution, "-o", "json"],
                manager=manager,
            ).stdout
        )

    def list(self, kind, *, namespace=None, manager=False):
        return json.loads(
            self.call(
                ["get", kind, "-n", namespace or self.execution, "-o", "json"],
                manager=manager,
            ).stdout
        )["items"]

    def raw(self, method, path, *, document=None, manager=False, accepted=(0,)):
        verb = {"GET": "get", "POST": "create", "PUT": "replace", "DELETE": "delete"}[method]
        return self.call(
            [verb, "--raw", path] + (["-f", "-"] if method != "GET" else []),
            document=document,
            manager=manager,
            accepted=accepted,
        )

    def can(self, verb, resource, namespace):
        return (
            self.call(
                ["auth", "can-i", verb, resource, "-n", namespace],
                manager=True,
                accepted=(0, 1),
            ).stdout.strip()
            == "yes"
        )


class InstallationVerifier:
    def __init__(self, api, *, options, timeout=180):
        self.api, self.options, self.timeout = api, options, timeout
        self.cm = api.get("configmap", "runtime-deployment-descriptor", namespace=api.control)
        self.document = json.loads(self.cm["data"]["descriptor.json"])
        self.namespace = api.execution
        if self.document.get("namespace") != self.namespace or not _IMAGE.fullmatch(
            self.document.get("helper_image", "")
        ):
            raise ValueError("descriptor_scope_or_digest_invalid")
        self.created, self.control_created, self.idle = [], [], None
        self.binding_verified = False

    def baseline(self):
        namespace = self.api.get("namespace", self.namespace)
        quota = self.api.get("resourcequota", "runtime-budget")
        webhooks = self.api.get("validatingwebhookconfiguration", self.options["webhook_name"])
        return {
            "namespace_uid": namespace["metadata"]["uid"],
            "quota_uid": quota["metadata"]["uid"],
            "webhook_uid": webhooks["metadata"]["uid"],
            "descriptor_digest": descriptor_digest(self.document),
            "images": {
                key: self.document[key] for key in ("helper_image", "assembler_image") if self.document.get(key)
            },
            "live_probes_executed": False,
            "offline_inventory": self._offline_inventory(),
        }

    def _offline_inventory(self):
        path = self.options.get("release_manifest")
        return (
            offline_inventory(
                json.loads(Path(path).read_text()), self.document, self.options.get("dependency_files", [])
            )
            if path
            else {"verified": False, "reason": "release_manifest_not_supplied"}
        )

    def _path(self, resource, name=""):
        return "/api/v1/namespaces/" + self.namespace + "/" + resource + ("/" + name if name else "")

    def _wait(self, predicate):
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            result = predicate()
            if result:
                return result
            time.sleep(2)
        raise ProbeError("probe_deadline_exceeded")

    def _plans(self, ref, plan=None, *, remove=False):
        cm = self.api.get("configmap", "runtime-canary-plans", namespace=self.api.control)
        document = json.loads(cm["data"]["plans.json"])
        if set(document) - {"schema_version", "plans", "profile_images"} or document["schema_version"] != 1:
            raise ProbeError("preflight_plans_invalid")
        if remove:
            document["plans"].pop(ref, None)
        else:
            document["plans"][ref] = plan
        try:
            original = cm["metadata"]
            if (
                original["name"] != "runtime-canary-plans"
                or original["namespace"] != self.api.control
                or str(UUID(original["uid"])) != original["uid"]
                or not isinstance(original["resourceVersion"], str)
                or not original["resourceVersion"]
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProbeError("admission_refresh_revision_unconfirmed") from None
        cm["data"]["plans.json"] = json.dumps(document, sort_keys=True, separators=(",", ":"))
        response = self.api.call(["replace", "-f", "-", "-o", "json"], document=cm)
        try:
            saved = json.loads(response.stdout)
            original, observed = cm["metadata"], saved["metadata"]
            if (
                original["name"] != "runtime-canary-plans"
                or original["namespace"] != self.api.control
                or observed["name"] != original["name"]
                or observed["namespace"] != original["namespace"]
                or observed["uid"] != original["uid"]
                or str(UUID(observed["uid"])) != observed["uid"]
                or not isinstance(observed["resourceVersion"], str)
                or not 0 < len(observed["resourceVersion"]) <= 1024
            ):
                raise ValueError()
            # The annotation contains only an opaque public revision, never
            # canary templates or any credential/configuration bytes.
            revision = hashlib.sha256((observed["uid"] + "\0" + observed["resourceVersion"]).encode()).hexdigest()
        except (KeyError, TypeError, ValueError):
            raise ProbeError("admission_refresh_revision_unconfirmed") from None
        self._refresh_admission_plans(revision)

    def _admission_refresh_target(self, pod):
        metadata = pod.get("metadata", {})
        if (
            self.api.control == self.namespace
            or metadata.get("namespace") != self.api.control
            or metadata.get("labels", {}).get("app") != "runtime-admission"
            or metadata.get("deletionTimestamp")
            or not _NAME.fullmatch(metadata.get("name", ""))
            or pod.get("status", {}).get("phase") != "Running"
        ):
            raise ProbeError("admission_refresh_scope_invalid")
        try:
            if (
                str(UUID(metadata["uid"])) != metadata["uid"]
                or not isinstance(metadata["resourceVersion"], str)
                or not metadata["resourceVersion"]
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProbeError("admission_refresh_identity_changed") from None
        volumes = set()
        for volume in pod.get("spec", {}).get("volumes", []):
            references = [volume.get("configMap", {})]
            references += [source.get("configMap", {}) for source in volume.get("projected", {}).get("sources", [])]
            if any(reference.get("name") == "runtime-canary-plans" for reference in references):
                volumes.add(volume.get("name"))
        mounted = any(
            mount.get("name") in volumes
            and mount.get("mountPath") == "/run/preflight"
            and mount.get("readOnly") is True
            and not mount.get("subPath")
            and not mount.get("subPathExpr")
            for container in pod.get("spec", {}).get("containers", [])
            if container.get("name") == "runtime-admission"
            for mount in container.get("volumeMounts", [])
        )
        if not mounted:
            raise ProbeError("admission_refresh_scope_invalid")
        return metadata

    def _refresh_admission_plans(self, revision):
        # K8s 1.28 documentation explicitly recommends a Pod annotation update
        # for immediate mounted-ConfigMap refresh. This is only a refresh hint;
        # the existing actual admission request still verifies plan visibility.
        # https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/tasks/configure-pod-container/configure-pod-configmap.md#mounted-configmaps-are-updated-automatically
        try:
            response = self.api.call(
                ["get", "pods", "-n", self.api.control, "-l", "app=runtime-admission", "-o", "json"]
            )
            pods = json.loads(response.stdout)["items"]
        except Exception:
            raise ProbeError("admission_refresh_refused") from None
        if not isinstance(pods, list) or not pods:
            raise ProbeError("admission_refresh_targets_unavailable")
        annotation = "runtime.bisheng.io/canary-plans-revision"
        for listed in pods:
            previous = self._admission_refresh_target(listed)
            try:
                current = self.api.get("pod", previous["name"], namespace=self.api.control)
            except Exception:
                raise ProbeError("admission_refresh_refused") from None
            metadata = self._admission_refresh_target(current)
            if metadata["uid"] != previous["uid"] or metadata["name"] != previous["name"]:
                raise ProbeError("admission_refresh_identity_changed")
            patch = [
                {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
                {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
            ]
            if metadata.get("annotations") is None:
                patch.append({"op": "add", "path": "/metadata/annotations", "value": {annotation: revision}})
            else:
                patch.append(
                    {"op": "add", "path": "/metadata/annotations/" + annotation.replace("/", "~1"), "value": revision}
                )
            try:
                response = self.api.call(
                    [
                        "patch",
                        "pod",
                        previous["name"],
                        "-n",
                        self.api.control,
                        "--type=json",
                        "-p",
                        json.dumps(patch),
                        "-o",
                        "json",
                    ]
                )
                changed = json.loads(response.stdout)
            except Exception:
                raise ProbeError("admission_refresh_refused") from None
            result = self._admission_refresh_target(changed)
            if result["uid"] != previous["uid"] or result["name"] != previous["name"]:
                raise ProbeError("admission_refresh_identity_changed")
            if result.get("annotations", {}).get(annotation) != revision:
                raise ProbeError("admission_refresh_revision_unconfirmed")

    def _create(self, template):
        meta = template["metadata"]
        plan = {
            "resource_ref": meta["labels"][RESOURCE_LABEL],
            "namespace": self.namespace,
            "name": meta["name"],
            "kind": template["kind"],
            "uid": None,
            "template": template_projection(template),
            "stop_state": "held",
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "cleanup_only": False,
            "service_cidrs": self.document.get("service_cidrs", []),
            "expires_at": int(time.time()) + 3500,
        }
        self._plans(plan["resource_ref"], plan)
        resource = {"Pod": "pods", "PersistentVolumeClaim": "persistentvolumeclaims"}[template["kind"]]

        def attempt():
            result = self.api.raw(
                "POST",
                self._path(resource),
                document=template,
                manager=True,
                accepted=(0, 1),
            )
            if not result.returncode:
                return json.loads(result.stdout)
            if (
                "admission_plan_unavailable" not in result.stderr
                and "admission_plan_action_refused" not in result.stderr
            ):
                raise ProbeError("preflight_create_refused")
            return None

        observed = self._wait(attempt)
        plan.update(uid=observed["metadata"]["uid"], allow_create=False, allow_update=True, allow_delete=True)
        self.created.append(
            {
                "plan": plan,
                "resource": resource,
                "uid": plan["uid"],
                "name": plan["name"],
            }
        )
        self._plans(plan["resource_ref"], plan)
        return observed

    def _pod(self, action, *, targets=None, pvc="", unschedulable=False, image="", command=(), runtime_class=""):
        helper = self.document["helper_image"]
        plan = PodPlan(
            namespace=self.namespace,
            app_id="preflight",
            operation_id="preflight-" + uuid4().hex[:20],
            resource_ref=str(uuid4()),
            node_id="preflight",
            generation=1,
            owner_epoch=1,
            purpose="probe",
            platform=self.document["platform"],
            status_policy_revision=self.document["status_policy_revision"],
            image=image or helper,
            helper_image=helper,
            command=tuple(command) or ("python", "-I", "-m", "runtime_manager.k8s_capabilities", action),
            memory_mb=128,
            cpu_millicores=50,
            mode="image",
            deadline_seconds=600 if action == "idle" and not command else min(self.timeout + 60, 600),
            health_path="/healthz",
            runtime_class=runtime_class,
        )
        pod = pod_template(plan)
        pod["metadata"]["name"] = "preflight-" + uuid4().hex[:20]
        if unschedulable:
            pod["spec"]["nodeSelector"]["runtime.bisheng.io/preflight-unassigned"] = uuid4().hex
        app = pod["spec"]["containers"][0]
        for key in ("readinessProbe", "livenessProbe", "startupProbe"):
            app.pop(key, None)
        app["ports"] = [
            {"name": "http", "containerPort": 8080},
            {"name": "data-control", "containerPort": 8092},
        ]
        if targets is not None:
            app["env"] = [
                {
                    "name": "CAPABILITY_PLAN",
                    "value": json.dumps(network_plan(targets), sort_keys=True),
                }
            ]
        if pvc:
            pod["spec"]["volumes"].append({"name": "probe-volume", "persistentVolumeClaim": {"claimName": pvc}})
            app["volumeMounts"].append({"name": "probe-volume", "mountPath": "/probe-volume"})
        return self._create(pod)

    def _observe(self, pod, *, running=False):
        def ready():
            current = self.api.get("pod", pod["metadata"]["name"], manager=True)
            if current["metadata"]["uid"] != pod["metadata"]["uid"]:
                raise ProbeError("preflight_pod_replaced")
            phase = current.get("status", {}).get("phase")
            if phase == "Failed":
                raise ProbeError("preflight_pod_failed")
            return current if phase == ("Running" if running else "Succeeded") else None

        return self._wait(ready)

    def _result(self, pod):
        current = self._observe(pod)
        response = self.api.call(
            [
                "logs",
                "-n",
                self.namespace,
                pod["metadata"]["name"],
                "-c",
                "app",
                "--limit-bytes=65536",
            ],
            manager=True,
        )
        if self.api.get("pod", pod["metadata"]["name"], manager=True)["metadata"]["uid"] != current["metadata"]["uid"]:
            raise ProbeError("preflight_log_identity_changed")
        rows = [line[len(_RESULT) :] for line in response.stdout.splitlines() if line.startswith(_RESULT)]
        if len(rows) != 1:
            raise ProbeError("preflight_result_missing")
        return json.loads(rows[0])

    @staticmethod
    def _proof(obj, **extra):
        return {"ok": True, "evidence": {"uid": obj["metadata"]["uid"], **extra}}

    def _namespace_budget(self):
        namespace = self.api.get("namespace", self.namespace)
        if (
            namespace["metadata"].get("labels", {}).get("runtime.bisheng.io/installation")
            != self.options["installation_id"]
        ):
            raise ProbeError("namespace_ownership_unconfirmed")
        hard = self.api.get("resourcequota", "runtime-budget")["spec"]["hard"]
        if (
            hard.get("services.nodeports") != "0"
            or hard.get("services.loadbalancers") != "0"
            or not all(
                key in hard
                for key in (
                    "requests.cpu",
                    "limits.cpu",
                    "requests.memory",
                    "limits.memory",
                    "pods",
                )
            )
        ):
            raise ProbeError("namespace_budget_unconfirmed")
        return self._proof(namespace)

    def _rbac(self):
        denied = [
            ("list", "pods", self.api.control),
            ("get", "secrets", self.api.control),
            ("get", "nodes", self.namespace),
            ("create", "roles", self.namespace),
            ("get", "configmaps", self.namespace),
            ("patch", "pods/status", self.namespace),
        ]
        if not self.api.can("list", "pods", self.namespace) or any(self.api.can(*row) for row in denied):
            raise ProbeError("rbac_scope_unconfirmed")
        return self._proof(self.api.get("serviceaccount", self.api.account, namespace=self.api.control))

    def _no_exec(self):
        if any(
            self.api.can("create", resource, self.namespace)
            for resource in ("pods/exec", "pods/attach", "pods/portforward")
        ):
            raise ProbeError("rbac_exec_allowed")
        denied_call = self.api.raw(
            "POST",
            self._path("pods", self.idle["metadata"]["name"]) + "/exec?command=true&stdout=true&stderr=true",
            document={},
            manager=True,
            accepted=(0, 1),
        )
        if not denied_call.returncode or "Forbidden" not in denied_call.stderr:
            raise ProbeError("rbac_exec_api_not_refused")
        return self._proof(self.api.get("serviceaccount", self.api.account, namespace=self.api.control))

    def _admission_negative(self, *, psa=False):
        original = next(row["plan"] for row in self.created if row["resource"] == "pods")
        plan = copy.deepcopy(original)
        ref = str(uuid4())
        plan.update(
            resource_ref=ref,
            uid=None,
            name="preflight-deny-" + uuid4().hex[:12],
            allow_create=True,
            allow_update=False,
            allow_delete=False,
        )
        pod = copy.deepcopy(plan["template"])
        pod["metadata"]["name"] = plan["name"]
        pod["metadata"]["labels"][RESOURCE_LABEL] = ref
        plan["template"] = copy.deepcopy(pod)
        self._plans(ref, plan)
        if psa:
            pod["spec"]["containers"][0]["securityContext"]["privileged"] = True
        else:
            pod["spec"]["containers"][0]["image"] = "unauthorized.invalid/image:latest"

        def denied():
            response = self.api.raw(
                "POST", self._path("pods") + "?dryRun=All", document=pod, manager=True, accepted=(0, 1)
            )
            if not response.returncode:
                # Do not hide a failed isolation check or delete an unexpected
                # object by name: its same-UID cleanup requires operator review.
                raise ProbeError("admission_negative_was_accepted")
            expected = "violates PodSecurity" if psa else "admission_template_mismatch"
            if expected in response.stderr:
                return True
            if "admission_plan_unavailable" in response.stderr:
                return False
            raise ProbeError("admission_negative_unconfirmed")

        self._wait(denied)
        self._plans(ref, remove=True)
        return self._proof(self.idle)

    def _status(self):
        current = self.api.get("pod", self.idle["metadata"]["name"], manager=True)
        forged = copy.deepcopy(current)
        forged["status"] = {"phase": "Succeeded"}
        response = self.api.raw(
            "PUT",
            self._path("pods", current["metadata"]["name"]) + "/status",
            document=forged,
            accepted=(0, 1),
        )
        if not response.returncode or "admission_terminal_source_refused" not in response.stderr:
            raise ProbeError("status_negative_unconfirmed")
        return self._proof(current, policy_revision=self.document["status_policy_revision"])

    def _binding_fence(self):
        pod = self._pod("idle", unschedulable=True)
        current = self.api.get("pod", pod["metadata"]["name"], manager=True)
        if current["spec"].get("nodeName"):
            raise ProbeError("binding_canary_already_scheduled")
        self._delete_request(current, "pods")
        fresh = self.api.get("pod", current["metadata"]["name"], manager=True)
        if not fresh["metadata"].get("deletionTimestamp") or fresh["spec"].get("nodeName"):
            raise ProbeError("binding_deletion_observation_invalid")
        binding = {
            "apiVersion": "v1",
            "kind": "Binding",
            "metadata": {key: fresh["metadata"][key] for key in ("name", "namespace", "uid", "resourceVersion")},
            "target": {
                "apiVersion": "v1",
                "kind": "Node",
                "name": self.options["node_name"],
            },
        }
        response = self.api.raw(
            "POST",
            self._path("pods", fresh["metadata"]["name"]) + "/binding",
            document=binding,
            accepted=(0, 1),
        )
        if not response.returncode or "being deleted" not in response.stderr:
            raise ProbeError("binding_delete_fence_unconfirmed")
        self.binding_verified = True
        return self._proof(fresh)

    def _delete_request(self, current, resource):
        expected_uid, name = current["metadata"]["uid"], current["metadata"]["name"]

        def attempt():
            fresh = self.api.get(resource, name, manager=True)
            if fresh["metadata"]["uid"] != expected_uid:
                raise ProbeError("preflight_delete_identity_changed")
            if fresh["metadata"].get("deletionTimestamp"):
                return True
            body = {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "gracePeriodSeconds": 5,
                "preconditions": {"uid": expected_uid, "resourceVersion": fresh["metadata"]["resourceVersion"]},
            }
            result = self.api.raw("DELETE", self._path(resource, name), document=body, manager=True, accepted=(0, 1))
            if result.returncode and not any(
                reason in result.stderr
                for reason in (
                    "admission_uid_refused",
                    "admission_plan_action_refused",
                    "admission_plan_unavailable",
                    "Conflict",
                    "object has been modified",
                )
            ):
                raise ProbeError("preflight_delete_refused")
            return result.returncode == 0

        self._wait(attempt)

    def _storage(self):
        storage = self.document.get("storage", {})
        if storage.get("sqlite_compatible") is not True or storage.get("filesystem") not in {"ext4", "xfs"}:
            raise ProbeError("storage_not_qualified")
        pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": "preflight-" + uuid4().hex[:20],
                "namespace": self.namespace,
                "labels": {
                    RESOURCE_LABEL: str(uuid4()),
                    "bisheng.managed": "v2",
                    "runtime.bisheng.io/purpose": "probe",
                },
                "annotations": {
                    POLICY_ANNOTATION: self.document["status_policy_revision"],
                    "runtime.bisheng.io/operation": "preflight-" + uuid4().hex[:20],
                    "runtime.bisheng.io/generation": "1",
                    "runtime.bisheng.io/owner-epoch": "1",
                },
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": storage.get("class", ""),
                "volumeMode": "Filesystem",
                "resources": {"requests": {"storage": str(self.options.get("storage_size_mb", 1024)) + "Mi"}},
            },
        }
        if storage.get("static_pool"):
            pvc["spec"]["selector"] = {
                "matchLabels": {
                    "runtime.bisheng.io/namespace": self.namespace,
                    "runtime.bisheng.io/volume-role": "preflight",
                }
            }
        self._create(pvc)
        pod = self._pod("storage", pvc=pvc["metadata"]["name"])
        result = self._result(pod)
        expected = int(self.options.get("storage_size_mb", 1024)) * 1024 * 1024
        capacity = result.get("capacity_bytes", 0)
        if type(capacity) is not int or not 0.8 * expected <= capacity <= 1.1 * expected:
            raise ProbeError("storage_capacity_not_bounded")
        return check_result("storage-sqlite", result, pod["metadata"]["uid"])

    def _image_one(self, observed, expected_image):
        rows = observed.get("status", {}).get("containerStatuses", [])
        if not rows or any(not row.get("imageID") or "sha256:" not in row["imageID"] for row in rows):
            raise ProbeError("cri_image_identity_unconfirmed")
        node = self.api.get("node", observed["spec"]["nodeName"])
        if "linux/" + node["status"]["nodeInfo"]["architecture"] != self.document["platform"]:
            raise ProbeError("cri_architecture_mismatch")
        if observed["spec"]["containers"][0]["image"] != expected_image:
            raise ProbeError("cri_requested_image_changed")
        result = self._proof(observed, digest=expected_image.split("@", 1)[1])
        result["observations"] = [
            {
                "uid": observed["metadata"]["uid"],
                "resource_version": observed["metadata"]["resourceVersion"],
                "image_ref": expected_image,
                "image_id": row["imageID"],
                "platform": self.document["platform"],
            }
            for row in rows
        ]
        return result

    def _image(self):
        result = self._image_one(self.idle, self.document["helper_image"])
        profiles = self.document.get("canary_profiles", [])
        if not profiles:
            raise ProbeError("runtime_profiles_not_verified")
        for profile in profiles:
            command = profile.get("command")
            if command not in [
                ["python", "--version"],
                ["node", "--version"],
                ["nginx", "-v"],
            ] or not _IMAGE.fullmatch(profile.get("runtime_image", "")):
                raise ProbeError("runtime_profile_invalid")
            pod = self._pod("idle", image=profile["runtime_image"], command=command)
            observed = self._observe(pod)
            result["observations"].extend(self._image_one(observed, profile["runtime_image"])["observations"])
        return result

    def _sandbox(self, level):
        runtime_class = self.document.get("sandbox", {}).get("runtime_classes", {}).get(level, "")
        if not runtime_class:
            raise ProbeError("optional_runtime_class_not_configured")
        pod = self._observe(self._pod("idle", runtime_class=runtime_class), running=True)
        return self._proof(pod, profile=level)

    @staticmethod
    def _control_connect(row):
        if row.get("protocol", "tcp") == "udp-dns":
            from runtime_manager.k8s_capabilities import network_checks

            probe = {
                "targets": [
                    {key: row[key] for key in ("name", "host", "port")} | {"expected": "allowed", "protocol": "udp-dns"}
                ]
            }
            if not all(item["ok"] for item in network_checks(probe)["checks"]):
                raise ProbeError("dns_control_unconfirmed")
        else:
            with socket.create_connection((row["host"], row["port"]), timeout=2):
                pass

    def _network(self, group):
        targets = copy.deepcopy(self.options["network_targets"][group])
        for target in targets:
            if target.get("name") == "other-app" and target.get("host") == "@preflight":
                target["host"] = self.idle["status"]["podIP"]
        if group == "network-direct-denied":
            if not {"backend", "minio", "kubernetes-api", "other-app"} <= {row.get("name") for row in targets} or any(
                row.get("expected") != "denied" for row in targets
            ):
                raise ProbeError("direct_denial_targets_incomplete")
        elif group == "network-dns-denied":
            if not targets or any(
                row.get("expected") != "denied" or row.get("protocol") != "udp-dns" for row in targets
            ):
                raise ProbeError("dns_denial_target_invalid")
        else:
            service = self.api.get("service", "egress-proxy", namespace=self.api.control)
            if not targets or any(
                row.get("expected") != "allowed"
                or row.get("host") != service["spec"].get("clusterIP")
                or row.get("port") != 3128
                for row in targets
            ):
                raise ProbeError("egress_proxy_target_invalid")
        for row in targets:
            if row.get("expected") == "denied":
                self._control_connect(row)
                row["control_confirmed"] = True
        pod = self._pod("network", targets=targets)
        result = self._result(pod)
        for row in targets:
            if row.get("expected") == "denied":
                self._control_connect(row)
        return check_result(group, result, pod["metadata"]["uid"])

    def _control_probe(self, role, targets):
        plan = PodPlan(
            namespace=self.api.control,
            app_id="preflight",
            operation_id="preflight-" + uuid4().hex[:20],
            resource_ref=str(uuid4()),
            node_id="preflight",
            generation=1,
            owner_epoch=1,
            purpose="probe",
            platform=self.document["platform"],
            status_policy_revision=self.document["status_policy_revision"],
            image=self.document["helper_image"],
            helper_image=self.document["helper_image"],
            command=(
                "python",
                "-I",
                "-m",
                "runtime_manager.k8s_capabilities",
                "network",
            ),
            memory_mb=128,
            cpu_millicores=50,
            mode="image",
            deadline_seconds=self.timeout + 60,
        )
        pod = pod_template(plan)
        pod["metadata"]["name"] = "preflight-" + uuid4().hex[:20]
        pod["metadata"]["labels"] = {
            "app": role,
            "runtime.bisheng.io/preflight-installation": self.options["installation_id"],
        }
        pod["metadata"]["annotations"]["runtime.bisheng.io/preflight-expiry"] = str(int(time.time()) + 3500)
        app = pod["spec"]["containers"][0]
        app["env"] = [
            {
                "name": "CAPABILITY_PLAN",
                "value": json.dumps(network_plan(targets), sort_keys=True),
            }
        ]
        for key in ("readinessProbe", "livenessProbe", "startupProbe"):
            app.pop(key, None)
        response = self.api.call(["create", "-f", "-", "-o", "json"], document=pod)
        observed = json.loads(response.stdout)
        self.control_created.append(observed)

        def finished():
            current = self.api.get("pod", observed["metadata"]["name"], namespace=self.api.control)
            if current["metadata"]["uid"] != observed["metadata"]["uid"]:
                raise ProbeError("control_probe_identity_changed")
            if current.get("status", {}).get("phase") == "Failed":
                raise ProbeError("control_probe_failed")
            return current if current.get("status", {}).get("phase") == "Succeeded" else None

        self._wait(finished)
        response = self.api.call(
            [
                "logs",
                "-n",
                self.api.control,
                observed["metadata"]["name"],
                "-c",
                "app",
                "--limit-bytes=65536",
            ]
        )
        rows = [line[len(_RESULT) :] for line in response.stdout.splitlines() if line.startswith(_RESULT)]
        if len(rows) != 1:
            raise ProbeError("control_probe_result_missing")
        check_result("network-ingress", json.loads(rows[0]), observed["metadata"]["uid"])
        return observed

    def _ingress(self):
        host = self.idle.get("status", {}).get("podIP")
        if not host:
            raise ProbeError("ingress_pod_ip_missing")

        def targets(allowed, port=8080):
            return [
                {
                    "name": "http",
                    "host": host,
                    "port": port,
                    "expected": "allowed" if allowed else "denied",
                    "control_confirmed": True,
                }
            ]

        self._control_probe("app-proxy", targets(True))
        self._control_probe("runtime-manager", targets(True, 8092))
        self._control_probe("preflight-untrusted", targets(False))
        self._control_probe("app-proxy", targets(False, 8092))
        self._control_probe("runtime-manager", targets(True))
        return self._proof(self.idle)

    def _platform(self, *, tls_only=False):
        import httpx

        base = self.options["platform_origin"]
        parsed = urlsplit(base)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.path not in {"", "/"}:
            raise ProbeError("platform_origin_invalid")
        path = "/api/v1/internal/app-runtime/v2/nodes/plan"
        key_id, secret = (
            os.environ["RTM_VERIFY_PLATFORM_KEY_ID"],
            os.environ["RTM_VERIFY_PLATFORM_SECRET"],
        )
        with httpx.Client(
            verify=ssl.create_default_context(cafile=self.options["platform_ca_file"]),
            trust_env=False,
            timeout=10,
        ) as client:
            response = client.get(
                base.rstrip("/") + path,
                headers=signed_headers("GET", path, b"", key_id=key_id, secret=secret),
            )
            if response.status_code != 200 or not isinstance(response.json().get("node"), dict):
                raise ProbeError("platform_authenticated_probe_refused")
            if client.get(base.rstrip("/") + path).status_code not in {401, 403}:
                raise ProbeError("platform_unsigned_probe_accepted")
        node = response.json()["node"]
        if node.get("node_id", node.get("id")) != self.options["node_id"]:
            raise ProbeError("platform_node_scope_mismatch")
        return self._proof(
            self.api.get("namespace", self.namespace),
            code="control_side_tls" if tls_only else "control_side_authenticated_api",
        )

    def live(self):
        drivers = {
            "namespace-budget": self._namespace_budget,
            "restricted-psa": lambda: self._admission_negative(psa=True),
            "admission-create": self._admission_negative,
            "status-provenance": self._status,
            "binding-delete-fence": self._binding_fence,
            "rbac-namespace": self._rbac,
            "no-exec": self._no_exec,
            "storage-sqlite": self._storage,
            "image-cri": self._image,
            "network-ingress": self._ingress,
            "material-tls": lambda: self._platform(tls_only=True),
            "platform-capabilities": self._platform,
        }
        for group in (
            "network-direct-denied",
            "network-egress-allowed",
            "network-dns-denied",
        ):
            drivers[group] = lambda group=group: self._network(group)
        if set(drivers) != REQUIRED_CHECKS:
            raise ProbeError("probe_driver_set_incomplete")
        if self.options.get("verify_registry") is True:
            drivers["registry-push"] = self._registry
        requested = self.document.get("sandbox", {}).get("requested", "default")
        if requested in {"recommended", "hardened"}:
            drivers["sandbox-" + requested] = lambda: self._sandbox(requested)
        report, probe_error = None, None
        try:
            self.idle = self._observe(self._pod("idle"), running=True)
            report = execute_checks(drivers, self.document, observed_at=time.time())
            return report
        except BaseException as error:
            probe_error = error
            raise
        finally:
            try:
                self.cleanup()
            except Exception as cleanup_error:
                raise ProbeRunFailure(probe_error, cleanup_error, report) from None

    def _cleanup_one(self, record):
        current = self.api.get(record["resource"], record["name"], manager=True)
        if current["metadata"]["uid"] != record["uid"]:
            raise ProbeError("preflight_cleanup_identity_changed")
        if not current["metadata"].get("deletionTimestamp"):
            self._delete_request(current, record["resource"])
        if record["resource"] == "pods":

            def stopped():
                fresh = self.api.get("pod", record["name"], manager=True)
                if fresh["metadata"]["uid"] != record["uid"]:
                    raise ProbeError("preflight_cleanup_identity_changed")
                return fresh if stop_confirmed(fresh, binding_verified=self.binding_verified) else None

            self._wait(stopped)
            record["plan"]["stop_state"] = "confirmed"
            self._plans(record["plan"]["resource_ref"], record["plan"])

            def release():
                fresh = self.api.get("pod", record["name"], manager=True)
                if fresh["metadata"]["uid"] != record["uid"]:
                    raise ProbeError("preflight_cleanup_identity_changed")
                patch = {
                    "metadata": {
                        "resourceVersion": fresh["metadata"]["resourceVersion"],
                        "finalizers": [x for x in fresh["metadata"].get("finalizers", []) if x != STOP_FINALIZER],
                    }
                }
                result = self.api.call(
                    [
                        "patch",
                        "pod",
                        record["name"],
                        "-n",
                        self.namespace,
                        "--type=merge",
                        "-p",
                        json.dumps(patch),
                    ],
                    manager=True,
                    accepted=(0, 1),
                )
                if result.returncode and not any(
                    reason in result.stderr
                    for reason in ("admission_stop_unconfirmed", "Conflict", "object has been modified")
                ):
                    raise ProbeError("preflight_finalizer_release_refused")
                return not result.returncode

            self._wait(release)

        def absent():
            response = self.api.raw(
                "GET", self._path(record["resource"], record["name"]), manager=True, accepted=(0, 1)
            )
            if response.returncode:
                if "NotFound" in response.stderr:
                    return True
                raise ProbeError("preflight_absence_unconfirmed")
            observed = json.loads(response.stdout)
            if observed["metadata"]["uid"] != record["uid"]:
                raise ProbeError("preflight_cleanup_identity_changed")
            return False

        self._wait(absent)
        self._plans(record["plan"]["resource_ref"], remove=True)
        self.created.remove(record)

    def _cleanup_control(self, pod):
        name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
        current = self.api.get("pod", name, namespace=self.api.control)
        if current["metadata"]["uid"] != uid:
            raise ProbeError("control_cleanup_identity_changed")
        body = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "gracePeriodSeconds": 5,
            "preconditions": {
                "uid": uid,
                "resourceVersion": current["metadata"]["resourceVersion"],
            },
        }
        path = "/api/v1/namespaces/" + self.api.control + "/pods/" + name
        self.api.raw("DELETE", path, document=body)

        def stopped():
            fresh = self.api.get("pod", name, namespace=self.api.control)
            if fresh["metadata"]["uid"] != uid:
                raise ProbeError("control_cleanup_identity_changed")
            return fresh if stop_confirmed(fresh, binding_verified=self.binding_verified) else None

        fresh = self._wait(stopped)
        patch = {
            "metadata": {
                "resourceVersion": fresh["metadata"]["resourceVersion"],
                "finalizers": [x for x in fresh["metadata"].get("finalizers", []) if x != STOP_FINALIZER],
            }
        }
        self.api.call(
            [
                "patch",
                "pod",
                name,
                "-n",
                self.api.control,
                "--type=merge",
                "-p",
                json.dumps(patch),
            ]
        )
        self.control_created.remove(pod)

    def cleanup(self):
        for pod in list(self.control_created):
            self._cleanup_control(pod)
        for row in list(reversed(self.created)):
            if row["resource"] == "pods":
                self._cleanup_one(row)
        for row in list(reversed(self.created)):
            if any(
                v.get("persistentVolumeClaim", {}).get("claimName") == row["name"]
                for pod in self.api.list("pods", manager=True)
                for v in pod.get("spec", {}).get("volumes", [])
            ):
                raise ProbeError("preflight_pvc_writer_unconfirmed")
            self._cleanup_one(row)

    def recover_expired(self):
        cm = self.api.get("configmap", "runtime-canary-plans", namespace=self.api.control)
        document = json.loads(cm["data"]["plans.json"])
        now = time.time()
        for ref, plan in document.get("plans", {}).items():
            if plan.get("expires_at", now + 1) > now:
                continue
            if (
                str(UUID(ref)) != ref
                or plan.get("resource_ref") != ref
                or plan.get("namespace") != self.namespace
                or not plan.get("name", "").startswith("preflight-")
            ):
                raise ProbeError("preflight_recovery_scope_invalid")
            resource = {"Pod": "pods", "PersistentVolumeClaim": "persistentvolumeclaims"}.get(plan.get("kind"))
            if not resource or not plan.get("uid"):
                raise ProbeError("preflight_recovery_uid_unconfirmed")
            fresh = self.api.get(resource, plan["name"], manager=True)
            if (
                fresh["metadata"]["uid"] != plan["uid"]
                or fresh["metadata"].get("labels", {}).get(RESOURCE_LABEL) != ref
            ):
                raise ProbeError("preflight_recovery_identity_changed")
            plan["expires_at"] = int(now) + 3500
            self._plans(ref, plan)
            self.created.append({"plan": plan, "resource": resource, "name": plan["name"], "uid": plan["uid"]})
        for pod in self.api.list("pods", namespace=self.api.control):
            meta = pod["metadata"]
            expiry = meta.get("annotations", {}).get("runtime.bisheng.io/preflight-expiry", "")
            if (
                meta.get("name", "").startswith("preflight-")
                and meta.get("labels", {}).get("runtime.bisheng.io/preflight-installation")
                == self.options["installation_id"]
                and expiry.isdecimal()
                and int(expiry) <= now
            ):
                self.control_created.append(pod)
        self.cleanup()

    def _registry(self):
        repository = self.document.get("image_repository", "")
        if not repository or not self.document.get("assembler_image"):
            raise ProbeError("assembly_registry_not_configured")
        target = repository.rstrip("/") + "/preflight-" + uuid4().hex + ":probe"
        command = [os.environ.get("CRANE_BIN", "crane")]
        if self.document.get("insecure_registry") is True:
            command.append("--insecure")
        command += ["--platform", self.document["platform"]]

        def run(args):
            result = subprocess.run(command + args, capture_output=True, text=True, timeout=180, check=False)
            if result.returncode:
                raise ProbeError("registry_probe_failed")
            return result.stdout.strip()

        expected = run(["digest", self.document["helper_image"]])
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", expected):
            raise ProbeError("registry_probe_digest_invalid")
        run(["copy", self.document["helper_image"], target])
        if run(["digest", target]) != expected:
            raise ProbeError("registry_probe_digest_mismatch")
        # Only a fresh, isolated preflight repository can be removed.
        run(["delete", target.split(":probe")[0] + "@" + expected])
        return self._proof(self.api.get("namespace", self.namespace), digest=expected)

    def publish(self, report):
        cm = self.api.get("configmap", "runtime-deployment-descriptor", namespace=self.api.control)
        document = json.loads(cm["data"]["descriptor.json"])
        if descriptor_digest(document) != report["descriptor_digest"]:
            raise ProbeError("descriptor_changed_during_probe")
        document["probe_report"] = report
        cm["data"]["descriptor.json"] = json.dumps(document, sort_keys=True, separators=(",", ":"))
        self.api.call(["replace", "-f", "-"], document=cm)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--control-namespace", required=True)
    parser.add_argument("--execution-namespace", required=True)
    parser.add_argument("--manager-account", default="runtime-manager")
    parser.add_argument("--probe-plan", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--cleanup-expired", action="store_true")
    parser.add_argument("--repeat-seconds", type=int, default=0)
    args = parser.parse_args(argv)
    if args.cleanup_expired and (args.live or args.write_report or args.repeat_seconds):
        parser.error("--cleanup-expired is a separate recovery operation")
    if args.write_report and not args.live:
        parser.error("--write-report requires --live")
    if args.repeat_seconds and (not args.live or not args.write_report or args.repeat_seconds != 21600):
        parser.error("periodic refresh requires --live --write-report --repeat-seconds 21600")
    options = json.loads(args.probe_plan.read_text())
    api = Kubectl(
        context=args.context,
        control_namespace=args.control_namespace,
        execution_namespace=args.execution_namespace,
        manager_account=args.manager_account,
    )
    while True:
        verifier = InstallationVerifier(api, options=options)
        if args.cleanup_expired:
            verifier.recover_expired()
            print(json.dumps({"expired_canaries_cleaned": True, "ready": False}))
            return 0
        if not args.live:
            print(json.dumps(verifier.baseline(), sort_keys=True))
            return 0
        try:
            report = verifier.live()
        except Exception as error:
            failures = failure_details(error)
            summary = {key: failures[0][key] for key in ("reason", "exception_type")}
            report = {
                "source": "cluster-probe",
                "failures": failures,
                "observed_at": time.time(),
                "descriptor_digest": descriptor_digest(verifier.document),
                "checks": [{"name": name, "ok": False, **summary, "evidence": {}} for name in sorted(REQUIRED_CHECKS)],
            }
            if args.write_report:
                try:
                    verifier.publish(report)
                except Exception as publish_error:
                    report["failures"].append({"phase": "publish", **safe_failure(publish_error)})
            log_failures(report["failures"])
            print(json.dumps(report, sort_keys=True), flush=True)
            return 1
        if args.write_report:
            verifier.publish(report)
        print(json.dumps(report, sort_keys=True), flush=True)
        if not all(row["ok"] for row in report["checks"] if row["name"] in REQUIRED_CHECKS):
            return 1
        if not args.repeat_seconds:
            return 0
        time.sleep(args.repeat_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log_failures(failure_details(error))
        raise SystemExit(1) from None
