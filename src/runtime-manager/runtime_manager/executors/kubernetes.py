"""Namespace-scoped execution with platform intents and UID-fenced effects.

SQL receipts are authoritative. A missing object or an expired lease is never
proof that a previously scheduled process has stopped writing to its volume.
"""

from __future__ import annotations

import copy
import hashlib
import json
import stat
import time
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.k8s_admission import template_projection
from runtime_manager.k8s_client import KubernetesAPIError, KubernetesClient
from runtime_manager.k8s_lifecycle import StopIdentity, finish_stop, request_stop
from runtime_manager.k8s_templates import (
    RESOURCE_LABEL,
    PodPlan,
    pod_template,
    pvc_template,
    secret_template,
    service_template,
)
from runtime_manager.platform_client import PlatformClient, PlatformError

_RESOURCES = {
    "Pod": "pods",
    "Service": "services",
    "Secret": "secrets",
    "PersistentVolumeClaim": "persistentvolumeclaims",
}
_RESULT = "BISHENG_RUNTIME_RESULT "


def workload_signer(seed: bytes, resource_ref: str) -> Ed25519PrivateKey:
    if not isinstance(seed, bytes) or len(seed) != 32 or str(UUID(resource_ref)) != resource_ref:
        raise ValueError("material_issuer_identity_invalid")
    child = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"bisheng-runtime-material-v1",
        info=b"workload-ed25519\x00" + resource_ref.encode("ascii"),
    ).derive(seed)
    return Ed25519PrivateKey.from_private_bytes(child)


def _seconds(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        raise ExecutorError("operation_deadline_invalid") from None


def _ref(operation, purpose, ordinal="pod"):
    return str(uuid5(NAMESPACE_URL, "bisheng-runtime-v2:" + operation["operation_id"] + ":" + purpose + ":" + ordinal))


def _name(prefix, reference):
    return prefix + hashlib.sha256(reference.encode()).hexdigest()[:40]


class KubernetesExecutor:
    def __init__(
        self, config, settings, *, platform=None, client=None, clock=time, checkpoint=None, data_transport=None
    ):
        self.config, self.settings, self.clock = config, settings, clock
        self.descriptor = settings.descriptor()
        self.document = self.descriptor.document
        self.platform = platform or PlatformClient(config)
        self.checkpoint = checkpoint or (lambda: None)
        self.client = client or KubernetesClient(settings, checkpoint=self.checkpoint, sleep=clock.sleep)
        self.data_transport = data_transport
        self.holder_id, self.controller_epoch, self.renew_at = str(uuid4()), 0, 0.0
        self._lease_lock = RLock()
        self._seed = None
        path = config.material_issuer_key_file
        if path:
            try:
                if stat.S_IMODE(path.stat().st_mode) & 0o077:
                    raise ExecutorError("material_issuer_file_permissions_invalid")
                with path.open("rb") as source:
                    self._seed = source.read(33)
            except OSError:
                raise ExecutorError("material_issuer_file_unavailable") from None
            if len(self._seed) != 32:
                raise ExecutorError("material_issuer_file_invalid")

    def capabilities(self):
        capabilities = copy.deepcopy(self.document.get("capabilities", {}))
        try:
            self.client.list("pods", label_selector="bisheng.managed=v2")
            available = True
        except KubernetesAPIError:
            available = False
        return {
            **capabilities,
            "executor_kind": "kubernetes",
            "cluster_id": self.settings.cluster_id,
            "namespace": self.settings.namespace,
            "orchestration_available": available,
            "protocol_version": 2,
            "platform": self.descriptor.platform,
            "helper_image": self.document.get("helper_image", ""),
            "status_policy_revision": self.descriptor.status_policy_revision,
            "data_transport_ready": self.data_transport is not None,
        }

    def _controller(self):
        with self._lease_lock:
            self.checkpoint()
            if not self.controller_epoch:
                snapshot = self.platform.node_snapshot()["node"]
                receipt = self.platform.claim_controller(self.holder_id, snapshot.get("controller_epoch", 0))
                self.controller_epoch = receipt["controller_epoch"]
                self.renew_at = self.clock.time() + 10
            elif self.clock.time() >= self.renew_at:
                self.platform.renew_controller(self.holder_id, self.controller_epoch)
                self.renew_at = self.clock.time() + 10
            return {"holder_id": self.holder_id, "controller_epoch": self.controller_epoch}

    def _plan(self, operation, purpose, *, reference=None, image=None, deadline=None):
        payload = operation["payload"]
        delivery = payload.get("resolved_delivery") or payload.get("delivery") or {}
        profile = delivery.get("profile") or payload.get("profile") or {}
        platform = delivery.get("platform") or profile.get("platform")
        if platform != self.descriptor.platform:
            raise ExecutorError("frozen_platform_mismatch")
        mode = delivery.get("mode", "bundle")
        startup = delivery.get("startup") or {}
        command = startup.get("command") or []
        if not isinstance(command, (list, tuple)) or any(not isinstance(x, str) for x in command):
            raise ExecutorError("frozen_command_invalid")
        tier, health = payload.get("tier", {}), payload.get("health", {})
        reference = reference or _ref(operation, purpose)
        pvc = "" if purpose not in {"serve", "migrate", "restore", "data"} else _name("data-", operation["app_id"])
        env = payload.get("runtime_env", {}) if purpose in {"serve", "probe", "preview"} else {}
        if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
            raise ExecutorError("frozen_environment_invalid")
        if deadline is None and purpose != "serve":
            deadline = int(_seconds(operation["deadline"]) - self.clock.time())
            if purpose == "preview":
                deadline = int(_seconds(payload.get("preview_expires_at", operation["deadline"])) - self.clock.time())
        if purpose != "serve":
            try:
                recorded = self.platform.resource(reference)
            except PlatformError as exc:
                if exc.status != 404:
                    raise
            else:
                deadline = recorded["template"].get("spec", {}).get("activeDeadlineSeconds", deadline)
        return PodPlan(
            namespace=self.settings.namespace,
            app_id=operation["app_id"],
            operation_id=operation["operation_id"],
            resource_ref=reference,
            node_id=self.config.node_id,
            generation=operation["generation"],
            owner_epoch=operation["owner_epoch"],
            purpose=purpose,
            platform=platform,
            status_policy_revision=self.descriptor.status_policy_revision,
            image=image or delivery.get("image_ref") or profile.get("runtime_image", ""),
            helper_image=self.document.get("helper_image", ""),
            command=tuple(command),
            memory_mb=tier.get("memory_mb", 512),
            cpu_millicores=tier.get("cpu_millicores", 250),
            uid=profile.get("uid", 10001),
            gid=profile.get("gid", 10001),
            mode=mode,
            port=payload.get("port", 8080),
            health_path=health.get("path", "/health"),
            pvc_name=pvc,
            scratch_pvc=_name("scratch-", operation["operation_id"]) if purpose.startswith("prepare-") else "",
            material_secret=_name("material-", reference)
            if mode == "bundle" or purpose in {"prepare-download", "prepare-upload"}
            else "",
            app_secret=_name("credentials-", reference) if env else "",
            secret_env=tuple(sorted(env)),
            deadline_seconds=deadline,
            runtime_class=self.document.get("runtime_class", ""),
            pull_secret=self.document.get("pull_secret", ""),
        )

    def _intent(self, operation, plan, template, reference):
        return self.platform.register_resource(
            {
                **self._controller(),
                "resource_ref": reference,
                "operation_id": operation["operation_id"],
                "cluster_id": self.settings.cluster_id,
                "namespace": self.settings.namespace,
                "purpose": plan.purpose,
                "template": template_projection(template),
            }
        )

    def _observation(self, row, action, **detail):
        return self.platform.observe_resource(row["resource_ref"], {"action": action, **self._controller(), **detail})

    def _fresh(self, row):
        obj = self.client.get(_RESOURCES[row["kind"]], row["name"])
        meta = obj.get("metadata", {})
        if (meta.get("namespace"), meta.get("name"), meta.get("labels", {}).get(RESOURCE_LABEL)) != (
            row["namespace"],
            row["name"],
            row["resource_ref"],
        ) or (row.get("uid") and meta.get("uid") != row["uid"]):
            raise ExecutorError("resource_uid_or_scope_mismatch")
        if not meta.get("uid") or not meta.get("resourceVersion"):
            raise ExecutorError("resource_observation_incomplete")
        return obj

    def _create(self, row, template):
        self._controller()
        try:
            obj = self._fresh(row)
        except KubernetesAPIError as exc:
            if exc.status_code != 404:
                raise
            if row.get("uid"):
                raise ExecutorError("bound_resource_missing") from None
            try:
                self.client.create(_RESOURCES[row["kind"]], template)
            except KubernetesAPIError as conflict:
                if conflict.status_code != 409:
                    raise
            obj = self._fresh(row)
        meta = obj["metadata"]
        extra = {}
        if row["kind"] == "Service":
            extra["runtime_state"] = {"cluster_ip": obj["spec"]["clusterIP"], "port": obj["spec"]["ports"][0]["port"]}
        self._observation(row, "bind", uid=meta["uid"], node_name=obj.get("spec", {}).get("nodeName", ""), **extra)
        return obj

    def _resource(self, operation, plan, template, reference):
        row = self._intent(operation, plan, template, reference)
        obj = self._create(row, template)
        return self.platform.resource(reference), obj

    def _volume(self, operation, plan):
        if not plan.pvc_name and not plan.scratch_pvc:
            return
        production = bool(plan.pvc_name)
        name = plan.pvc_name or plan.scratch_pvc
        reference = (
            str(uuid5(NAMESPACE_URL, "bisheng-volume:" + self.config.node_id + ":" + operation["app_id"]))
            if production
            else _ref(operation, "prepare", "scratch")
        )
        try:
            row = self.platform.resource(reference)
        except PlatformError as exc:
            if exc.status != 404:
                raise
        else:
            if (
                (row["app_id"], row["node_id"], row["kind"], row["name"])
                != (
                    operation["app_id"],
                    self.config.node_id,
                    "PersistentVolumeClaim",
                    name,
                )
                or not row.get("uid")
                or (not production and row["operation_id"] != operation["operation_id"])
            ):
                raise ExecutorError("volume_identity_unconfirmed")
            self._fresh(row)
            return
        storage = self.document.get("storage", {})
        template = pvc_template(
            replace(plan, resource_ref=reference),
            name=name,
            size_mb=storage.get("size_mb" if production else "scratch_size_mb", 1024),
            storage_class=storage.get("class", ""),
        )
        # WaitForFirstConsumer volumes cannot bind until their Pod is scheduled.
        self._resource(operation, plan, template, reference)

    def _secret(self, operation, plan, name, data, ordinal):
        reference = _ref(operation, plan.purpose, plan.resource_ref + ":" + ordinal)
        template = secret_template(replace(plan, resource_ref=reference), name=name, data=data)
        self._resource(operation, plan, template, reference)

    def _material(self, operation, plan):
        if self._seed is None:
            raise ExecutorError("material_issuer_key_required")
        signer = workload_signer(self._seed, plan.resource_ref)
        key_id = "workload_" + plan.resource_ref.replace("-", "")
        grant = self.platform.create_material_delegation(
            {
                "operation_id": operation["operation_id"],
                "exec_ref": plan.resource_ref,
                "key_id": key_id,
                "public_key": signer.public_key().public_bytes_raw().hex(),
            }
        )
        identity = {
            "base_url": self.config.platform_base_url,
            "delegation_id": grant["delegation_id"],
            "key_id": key_id,
            "scope_kind": grant["scope_kind"],
            "private_key": signer.private_bytes_raw().hex(),
            "expires_at": _seconds(grant["expires_at"]) if grant.get("expires_at") else None,
            "phase_timeout_seconds": min(1800, plan.deadline_seconds or 1800),
        }
        if self.config.egress_proxy:
            target = urlsplit(
                self.config.egress_proxy if "://" in self.config.egress_proxy else "http://" + self.config.egress_proxy
            )
            if target.scheme != "http" or not target.hostname or target.username or target.password:
                raise ExecutorError("material_proxy_configuration_invalid")
            proxy = grant["proxy"]
            authority = quote(proxy["principal"], safe="") + ":" + quote(proxy["token"], safe="") + "@" + target.netloc
            identity["proxy_url"] = urlunsplit((target.scheme, authority, "", "", ""))
        data = {"identity.json": json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()}
        if self.config.platform_ca_file:
            try:
                data["ca.crt"] = self.config.platform_ca_file.read_bytes()
            except OSError:
                raise ExecutorError("platform_ca_unavailable") from None
        self._secret(operation, plan, plan.material_secret, data, "material-secret")
        return grant

    def launch(self, operation, *, preview=False):
        purpose = "preview" if preview else ("probe" if operation["kind"] == "probe" else "serve")
        plan = self._plan(operation, purpose)
        delivery = operation["payload"]["resolved_delivery"]
        plan = replace(plan, helper_env={"MATERIAL_PLAN": json.dumps(delivery, sort_keys=True, separators=(",", ":"))})
        template = pod_template(plan)
        row = self._intent(operation, plan, template, plan.resource_ref)
        self._volume(operation, plan)
        grant = self._material(operation, plan) if plan.mode == "bundle" else None
        if plan.app_secret:
            self._secret(
                operation,
                plan,
                plan.app_secret,
                {key: value.encode() for key, value in operation["payload"]["runtime_env"].items()},
                "app-secret",
            )
        pod = self._create(row, template)
        if grant:
            self.platform.bind_material_delegation(grant["delegation_id"], pod["metadata"]["uid"])
        service_ref = _ref(operation, purpose, "service")
        service = service_template(plan)
        service["metadata"]["labels"][RESOURCE_LABEL] = service_ref
        service_row, _ = self._resource(operation, plan, service, service_ref)
        deadline = min(_seconds(operation["deadline"]), self.clock.time() + 90)
        while True:
            self._controller()
            result = self.observe(plan.resource_ref)
            if result["ready"]:
                return {**result, "service_ref": service_ref, "service_uid": service_row["uid"]}
            if self.clock.time() >= deadline:
                raise ExecutorError("workload_readiness_timeout")
            self.clock.sleep(min(1, deadline - self.clock.time()))

    def observe(self, exec_ref):
        row = self.platform.resource(exec_ref)
        pod = self._fresh(row)
        status = pod.get("status", {})
        ready = (
            not pod["metadata"].get("deletionTimestamp")
            and status.get("phase") == "Running"
            and any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in status.get("conditions", [])
            )
        )
        services = [
            r
            for r in self.platform.resources(row["operation_id"])
            if r["kind"] == "Service"
            and r.get("template", {}).get("spec", {}).get("selector", {}).get(RESOURCE_LABEL) == exec_ref
        ]
        if not services:
            ready = False
            service = None
        else:
            service = services[0]
            self._fresh(service)
            endpoints = self.client.list(
                "endpointslices", label_selector="kubernetes.io/service-name=" + service["name"]
            )
            ready = ready and any(
                e.get("conditions", {}).get("ready") is True
                and e.get("targetRef", {}).get("kind") == "Pod"
                and e.get("targetRef", {}).get("uid") == row["uid"]
                and status.get("podIP") in e.get("addresses", [])
                for item in endpoints.get("items", [])
                for e in item.get("endpoints", [])
            )
        target = service.get("observed_state", {}) if service else {}
        return {
            "exec_ref": exec_ref,
            "pod_uid": row["uid"],
            "ready": bool(ready),
            "target": {"host": target.get("cluster_ip", ""), "port": target.get("port", 0)},
            "phase": status.get("phase", "Unknown"),
            "running": status.get("phase") == "Running" and not pod["metadata"].get("deletionTimestamp"),
            "restart_count": sum(
                int(c.get("restartCount", 0)) for c in status.get("containerStatuses", []) if c.get("name") == "app"
            ),
        }

    @staticmethod
    def _identity(row):
        return StopIdentity(
            row["namespace"],
            row["name"],
            row.get("uid") or "",
            row["status_policy_revision"],
            row["protected_since_creation"],
            row["binding_policy_verified"],
            row.get("node_name", ""),
        )

    def request_stop(self, exec_ref, operation):
        row = self.platform.resource(exec_ref)
        if row["kind"] != "Pod" or row["app_id"] != operation["app_id"]:
            raise ExecutorError("stop_resource_scope_refused")
        row = self._observation(row, "stop", operation_id=operation["operation_id"])
        observation = request_stop(self.client, self._identity(row))
        return {"stopped": False, "reason": observation.reason}

    def confirm_stopped(self, exec_ref):
        row = self.platform.resource(exec_ref)
        if row["kind"] != "Pod":
            raise ExecutorError("stop_resource_kind_refused")
        if row["stop_state"] == "confirmed":
            self._controller()
            try:
                pod = self._fresh(row)
            except KubernetesAPIError as exc:
                if exc.status_code != 404:
                    raise
            else:
                from runtime_manager.k8s_templates import STOP_FINALIZER

                finalizers = pod["metadata"].get("finalizers", [])
                if STOP_FINALIZER in finalizers:
                    self.client.patch(
                        "pods",
                        row["name"],
                        {"metadata": {"finalizers": [f for f in finalizers if f != STOP_FINALIZER]}},
                        resource_version=pod["metadata"]["resourceVersion"],
                    )
            evidence = row.get("stop_evidence", {})
            return {"stopped": True, "evidence_kind": evidence.get("evidence_kind", "confirmed"), "exec_ref": exec_ref}
        observation = finish_stop(
            self.client,
            self._identity(row),
            lambda evidence: self._observation(row, "stopped", evidence=evidence),
            now=datetime.fromtimestamp(self.clock.time(), UTC),
        )
        return {
            "stopped": observation.confirmed,
            "evidence_kind": observation.kind,
            "reason": observation.reason,
            "exec_ref": exec_ref,
        }

    def logs(self, exec_ref, *, since=None, tail=200):
        row = self.platform.resource(exec_ref)
        self._fresh(row)
        since_time = (
            datetime.fromtimestamp(since, UTC).isoformat().replace("+00:00", "Z") if since is not None else None
        )
        return self.client.logs(row["name"], since_time=since_time, tail=tail, container="app")

    def cleanup(self, operation):
        rows = self.platform.resources(operation["operation_id"])
        for row in rows:
            if row["kind"] == "Pod" and row["stop_state"] != "confirmed":
                self.request_stop(row["resource_ref"], operation)
                if not self.confirm_stopped(row["resource_ref"])["stopped"]:
                    return {"complete": False, "reason": "writer_stop_unconfirmed"}
        for row in rows:
            if row["kind"] == "PersistentVolumeClaim" and row["purpose"] in {"serve", "migrate", "restore", "data"}:
                continue
            if row["cleanup_state"] == "complete":
                continue
            try:
                obj = self._fresh(row)
            except KubernetesAPIError as exc:
                if exc.status_code != 404 or (
                    row["kind"] == "Pod" and self.platform.resource(row["resource_ref"])["stop_state"] != "confirmed"
                ):
                    raise
            else:
                if row["kind"] == "Pod":
                    self.confirm_stopped(row["resource_ref"])
                    try:
                        self._fresh(row)
                    except KubernetesAPIError as exc:
                        if exc.status_code != 404:
                            raise
                    else:
                        return {"complete": False, "reason": "pod_cleanup_pending"}
                else:
                    row = self._observation(row, "stop", operation_id=operation["operation_id"])
                    self._controller()
                    self.client.delete(
                        _RESOURCES[row["kind"]],
                        row["name"],
                        uid=row["uid"],
                        resource_version=obj["metadata"]["resourceVersion"],
                    )
                    try:
                        self._fresh(row)
                    except KubernetesAPIError as exc:
                        if exc.status_code != 404:
                            raise
                    else:
                        return {"complete": False, "reason": "resource_cleanup_pending"}
            self._observation(row, "cleanup", uid=row["uid"])
        return {"complete": True}

    def data(self, operation, action, parameters):
        if self.data_transport is None:
            raise ExecutorError("data_transport_unavailable")
        return self.data_transport.request(operation, action, parameters)

    def _save_progress(self, operation, stage, reference, result):
        current = self.platform.operation(operation["operation_id"])
        progress = copy.deepcopy(current.get("result", {}).get("prepare_progress", {}))
        progress[stage] = {"exec_ref": reference, "result": result}
        detail = {"prepare_progress": progress, "controller": self._controller()}
        try:
            self.platform.fact(
                current, int(current.get("fact_sequence", 0)) + 1, "preparing", exec_ref=reference, detail=detail
            )
        except PlatformError:
            # Never delete the only copy of a phase result after an ambiguous write.
            saved = self.platform.operation(operation["operation_id"]).get("result", {}).get("prepare_progress", {})
            if saved.get(stage) != progress[stage]:
                raise
        return result

    def _phase(self, operation, stage, purpose, document):
        current = self.platform.operation(operation["operation_id"])
        previous = current.get("result", {}).get("prepare_progress", {}).get(stage)
        if previous:
            self.request_stop(previous["exec_ref"], operation)
            if not self.confirm_stopped(previous["exec_ref"])["stopped"]:
                raise ExecutorError("preparation_writer_stop_unconfirmed")
            return previous["result"]
        profile = operation["payload"]["profile"]
        plan = self._plan(
            operation,
            purpose,
            reference=_ref(operation, purpose, stage),
            image=profile["preparer_image"],
            deadline=min(1800, int(_seconds(operation["deadline"]) - self.clock.time())),
        )
        if purpose == "prepare-install":
            plan = replace(
                plan,
                command=("python", "-I", "/runtime/tools/k8s_prepare.py"),
                material_secret="",
                app_secret="",
                secret_env=(),
            )
        else:
            plan = replace(
                plan, helper_env={"MATERIAL_PLAN": json.dumps(document, sort_keys=True, separators=(",", ":"))}
            )
        template = pod_template(plan)
        row = self._intent(operation, plan, template, plan.resource_ref)
        self._volume(operation, plan)
        grant = self._material(operation, plan) if purpose != "prepare-install" else None
        pod = self._create(row, template)
        if grant:
            self.platform.bind_material_delegation(grant["delegation_id"], pod["metadata"]["uid"])
        deadline = min(_seconds(operation["deadline"]), self.clock.time() + plan.deadline_seconds)
        while True:
            self._controller()
            pod = self._fresh(self.platform.resource(plan.resource_ref))
            status = pod.get("status", {})
            if status.get("phase") == "Failed":
                raise ExecutorError("preparation_phase_failed")
            if status.get("phase") == "Succeeded":
                if any("running" in c.get("state", {}) for c in status.get("containerStatuses", [])):
                    raise ExecutorError("preparation_phase_status_inconsistent")
                container = "prepare" if purpose == "prepare-install" else "transfer"
                output = self.client.logs(plan.name, container=container, tail=100)
                if purpose == "prepare-install":
                    result = {"installed": True}
                else:
                    lines = [line[len(_RESULT) :] for line in output.splitlines() if line.startswith(_RESULT)]
                    try:
                        if len(lines) != 1 or len(lines[0]) > 65536:
                            raise ValueError()
                        result = json.loads(lines[0])
                        if not isinstance(result, dict):
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise ExecutorError("preparation_result_invalid") from None
                break
            if self.clock.time() >= deadline:
                raise ExecutorError("preparation_phase_timeout")
            self.clock.sleep(min(1, deadline - self.clock.time()))
        self._save_progress(operation, stage, plan.resource_ref, result)
        self.request_stop(plan.resource_ref, operation)
        if not self.confirm_stopped(plan.resource_ref)["stopped"]:
            raise ExecutorError("preparation_writer_stop_unconfirmed")
        return result

    def prepare(self, operation):
        if operation["kind"] != "prepare" or operation["payload"].get("delivery", {}).get("mode", "bundle") != "bundle":
            raise ExecutorError("preparation_mode_unavailable")
        payload = operation["payload"]
        document = {
            key: copy.deepcopy(payload[key]) for key in ("tenant_id", "source_artifact_id", "profile", "delivery")
        }
        document["app_id"] = operation["app_id"]
        inputs = self._phase(operation, "inputs", "prepare-download", {**document, "phase": "inputs"})
        key = inputs.get("input_key")
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ExecutorError("preparation_input_key_invalid")
        self.platform.dependencies(operation["operation_id"], key)
        selected = self.platform.operation(operation["operation_id"])["payload"].get("dependency_resolution", {})
        if selected.get("input_key") != key:
            raise ExecutorError("preparation_dependency_selection_unconfirmed")
        document["dependency_resolution"] = selected
        self._phase(operation, "resolve", "prepare-download", {**document, "phase": "resolve"})
        self._phase(operation, "install", "prepare-install", document)
        result = self._phase(operation, "upload", "prepare-upload", document)
        self.platform.dependencies(
            operation["operation_id"], key, artifact_id=result["dependency_artifact_id"], verified=True
        )
        return result
