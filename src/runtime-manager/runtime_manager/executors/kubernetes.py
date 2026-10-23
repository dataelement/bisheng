"""Namespace-scoped execution with platform intents and UID-fenced effects.

SQL receipts are authoritative. A missing object or an expired lease is never
proof that a previously scheduled process has stopped writing to its volume.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
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
    POLICY_ANNOTATION,
    PREPARATION,
    PRODUCTION,
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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).timestamp()
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
        self._lease_time = getattr(clock, "monotonic", time.monotonic)
        self._seed = None
        path = config.material_issuer_key_file
        if path:
            try:
                metadata = path.stat()
                mode = stat.S_IMODE(metadata.st_mode)
                if mode & 0o027 or (mode & 0o040 and metadata.st_gid not in {os.getegid(), *os.getgroups()}):
                    raise ExecutorError("material_issuer_file_permissions_invalid")
                with path.open("rb") as source:
                    self._seed = source.read(33)
            except OSError:
                raise ExecutorError("material_issuer_file_unavailable") from None
            if len(self._seed) != 32:
                raise ExecutorError("material_issuer_file_invalid")

    def _probe_state(self):
        from runtime_manager.k8s_capabilities import (
            assess_capabilities,
            descriptor_digest,
            protection_baseline_digest,
            protection_observation,
        )
        from runtime_manager.k8s_config import KubernetesConfigurationError

        now = self.clock.time()
        original = copy.deepcopy(self.document)
        try:
            fresh = self.settings.descriptor().document
            if descriptor_digest(fresh) == descriptor_digest(original):
                self.document["probe_report"] = fresh.get("probe_report", {})
                original["probe_report"] = fresh.get("probe_report", {})
            else:
                return (
                    {
                        "ready": False,
                        "checks": [],
                        "warnings": ["installation_changed_restart_required"],
                        "paths": {},
                    },
                    protection_observation(original, now=now, projected=fresh),
                )
        except KubernetesConfigurationError:
            return (
                {"ready": False, "checks": [], "warnings": ["installation_descriptor_unavailable"], "paths": {}},
                {"version": 1, "baseline_digest": protection_baseline_digest(original), "state": "unconfirmed"},
            )
        return assess_capabilities(original, now=now), protection_observation(original, now=now)

    def probe_report(self):
        return self._probe_state()[0]

    def _package_sources(self):
        sources = [
            self.config.build_index_url or "https://pypi.org/simple",
            self.config.build_extra_index_url,
            self.config.build_npm_registry or "https://registry.npmjs.org",
            *self.document.get("package_endpoints", []),
        ]
        if not self.config.build_index_url or urlsplit(self.config.build_index_url).hostname == "pypi.org":
            sources.append("https://files.pythonhosted.org")
        result = set()
        for source in sources:
            if not source:
                continue
            parsed = urlsplit(source)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ExecutorError("package_source_invalid")
            host = parsed.hostname
            if ":" in host:
                host = "[" + host + "]"
            result.add(parsed.scheme + "://" + host + (":" + str(parsed.port) if parsed.port else ""))
        return sorted(result)

    def capabilities(self):
        capabilities = copy.deepcopy(self.document.get("capabilities", {}))
        try:
            self.client.list("pods", label_selector="bisheng.managed=v2")
            available = True
        except KubernetesAPIError:
            available = False
        report, protection = self._probe_state()
        passed = {check["name"] for check in report.get("checks", []) if check.get("ok")}
        return {
            **capabilities,
            "mandatory_isolation": bool(report["ready"]),
            "status_protection": "status-provenance" in passed,
            "binding_protection": "binding-delete-fence" in passed,
            "protection_observation": protection,
            "paths": report.get("paths", {}),
            "sandbox": report.get("sandbox", {}),
            "package_sources": self._package_sources(),
            "executor_kind": "kubernetes",
            "cluster_id": self.settings.cluster_id,
            "namespace": self.settings.namespace,
            "orchestration_available": available,
            "protocol_version": 2,
            "platform": self.descriptor.platform,
            "helper_image": self.document.get("helper_image", ""),
            "assembler_image": self.document.get("assembler_image", ""),
            "status_policy_revision": self.descriptor.status_policy_revision,
            "data_transport_ready": self.data_transport is not None,
        }

    def _controller_node(self):
        node = self.platform.node_snapshot().get("node")
        if (
            not isinstance(node, dict)
            or node.get("node_id") != self.config.node_id
            or type(node.get("controller_epoch")) is not int
            or node["controller_epoch"] < 0
        ):
            raise ExecutorError("controller_node_receipt_invalid")
        return node

    def _controller_receipt(self, receipt, expected_epoch, *, claiming=False):
        allowed = {expected_epoch, expected_epoch + 1} if claiming else {expected_epoch}
        if (
            not isinstance(receipt, dict)
            or receipt.get("node_id") != self.config.node_id
            or receipt.get("holder_id") != self.holder_id
            or type(receipt.get("controller_epoch")) is not int
            or receipt["controller_epoch"] <= 0
            or receipt["controller_epoch"] not in allowed
        ):
            raise ExecutorError("controller_lease_receipt_invalid")
        try:
            _seconds(receipt.get("lease_until"))
        except ExecutorError:
            raise ExecutorError("controller_lease_receipt_invalid") from None
        return receipt["controller_epoch"]

    def _controller_failed(self, error):
        self.controller_epoch, self.renew_at = 0, 0.0
        try:
            return self._controller_node()
        except (PlatformError, ExecutorError) as recheck:
            raise error from recheck

    def _renew_controller(self, epoch):
        started = self._lease_time()
        receipt = self.platform.renew_controller(self.holder_id, epoch)
        self._controller_receipt(receipt, epoch)
        # The server grants 30s from its own clock. Starting our conservative
        # budget before the request avoids wall-clock skew and slow replies.
        if self._lease_time() - started >= 20:
            raise ExecutorError("controller_lease_receipt_expired")
        self.controller_epoch, self.renew_at = epoch, started + 10
        return {"holder_id": self.holder_id, "controller_epoch": epoch}

    def _claim_controller(self, node=None):
        node = node if node is not None else self._controller_node()
        try:
            receipt = self.platform.claim_controller(self.holder_id, node["controller_epoch"])
            epoch = self._controller_receipt(receipt, node["controller_epoch"], claiming=True)
            # A same-holder claim can return an almost-expired lease unchanged.
            # Renew it explicitly before caching any permission to act.
            return self._renew_controller(epoch)
        except (PlatformError, ExecutorError) as exc:
            self._controller_failed(exc)
            raise

    def _controller(self):
        with self._lease_lock:
            self.checkpoint()
            if not self.controller_epoch:
                return self._claim_controller()
            if self._lease_time() < self.renew_at:
                return {"holder_id": self.holder_id, "controller_epoch": self.controller_epoch}
            try:
                return self._renew_controller(self.controller_epoch)
            except (PlatformError, ExecutorError) as exc:
                node = self._controller_failed(exc)
                if isinstance(exc, PlatformError) and exc.status == 409 and str(exc) == "controller_lease_lost":
                    return self._claim_controller(node)
                # Unknown writes are re-read, but never permit this action.
                raise

    @staticmethod
    def _delivery_profile(operation, *, purge=False):
        payload = operation["payload"]
        preparing = operation["kind"] == "prepare"
        delivery = payload.get("delivery") if preparing else payload.get("resolved_delivery")
        if delivery is None and purge:
            delivery = {}
        if not isinstance(delivery, dict):
            raise ExecutorError("frozen_delivery_invalid")
        # Manifest delivery.profile is only a reference string. The backend
        # resolves it before prepare and freezes the resulting object on output.
        profile = payload.get("profile") if preparing else delivery.get("profile")
        optional = purge or delivery.get("mode") == "image"
        if profile is None and optional:
            profile = {}
        if not isinstance(profile, dict) or (not profile and not optional):
            raise ExecutorError("frozen_profile_invalid")
        return delivery, profile

    def _plan(self, operation, purpose, *, reference=None, image=None, deadline=None):
        payload = operation["payload"]
        delivery, profile = self._delivery_profile(operation, purge=purpose == "purge")
        platform = (
            self.descriptor.platform if purpose == "purge" else (delivery.get("platform") or profile.get("platform"))
        )
        if platform != self.descriptor.platform:
            raise ExecutorError("frozen_platform_mismatch")
        mode = "image" if purpose == "purge" else delivery.get("mode", "bundle")
        if mode == "source-image":
            mode = "bundle" if purpose.startswith("prepare-") else "image"
        startup = delivery.get("startup") or {}
        command = startup.get("command") or []
        if not isinstance(command, (list, tuple)) or any(not isinstance(x, str) for x in command):
            raise ExecutorError("frozen_command_invalid")
        tier, health = payload.get("tier", {}), payload.get("health", {})
        reference = reference or _ref(operation, purpose)
        pvc = (
            ""
            if purpose not in {"serve", "migrate", "restore", "data", "purge"}
            else _name("data-", operation["app_id"])
        )
        env = dict(payload.get("runtime_env", {})) if purpose in {"serve", "probe", "preview"} else {}
        if not isinstance(env, dict) or any(not isinstance(v, str) for v in env.values()):
            raise ExecutorError("frozen_environment_invalid")
        defaults = {}
        if purpose in {"serve", "probe", "preview"}:
            defaults = {
                "PORT": str(payload.get("port", 8080)),
                "BISHENG_APP_PORT": str(payload.get("port", 8080)),
                "BISHENG_APP_ID": operation["app_id"],
                "BISHENG_APP_DB_URL": "sqlite:////data/app.db",
                "BISHENG_APP_DB_PATH": "/data/app.db",
                "PYTHONDONTWRITEBYTECODE": "1",
                "BISHENG_APP_BASE_PATH": payload.get("base_path", "/apps/" + payload.get("slug", operation["app_id"])),
            }
            env = {key: value for key, value in env.items() if key not in defaults}
        if deadline is None and purpose != "serve":
            deadline = int(_seconds(operation["deadline"]) - self.clock.time())
            if purpose == "preview":
                deadline = int(_seconds(payload.get("preview_expires_at", operation["deadline"])) - self.clock.time())
        recorded = None
        try:
            recorded = self.platform.resource(reference)
        except PlatformError as exc:
            if exc.status != 404:
                raise
        if recorded is not None:
            expected = {
                "resource_ref": reference,
                "operation_id": operation["operation_id"],
                "app_id": operation["app_id"],
                "node_id": self.config.node_id,
                "cluster_id": self.settings.cluster_id,
                "namespace": self.settings.namespace,
                "purpose": purpose,
                "generation": operation["generation"],
                "owner_epoch": operation["owner_epoch"],
                "kind": "Pod",
            }
            if any(recorded.get(key) != value for key, value in expected.items()):
                raise ExecutorError("frozen_resource_scope_mismatch")
            frozen_spec = recorded["template"].get("spec", {})
            if purpose != "serve":
                deadline = frozen_spec.get("activeDeadlineSeconds", deadline)
            runtime_class = frozen_spec.get("runtimeClassName", "")
        else:
            runtime_class = self.probe_report().get("sandbox", {}).get("runtime_class", "")
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
            runtime_language=profile.get("language", ""),
            port=payload.get("port", 8080),
            health_path=health.get("path", "/"),
            env=defaults,
            schema_plan=tuple(payload.get("migration_plan", [])) if purpose in {"probe", "preview"} else (),
            temporary_mb=self.document.get("temporary_storage_mb", 4096),
            volume_guard={
                "namespace": self.settings.namespace,
                "installation_id": self.document.get("installation_id", self.settings.cluster_id),
                "filesystem": self.document.get("storage", {}).get("filesystem", "ext4"),
                "capacity_bytes": self.document.get("storage", {}).get(
                    "scratch_size_mb" if purpose in PREPARATION else "size_mb", 1024
                )
                * 1024**2,
                "marker_required": self.document.get("storage", {}).get("static_pool") is True,
            }
            if purpose in PRODUCTION | PREPARATION
            else {},
            pvc_name=pvc,
            scratch_pvc=_name("scratch-", operation["operation_id"])
            if purpose.startswith("prepare-") or purpose == "assemble"
            else "",
            material_secret=_name("material-", reference)
            if mode == "bundle" or purpose in {"prepare-download", "prepare-upload"}
            else "",
            app_secret=_name("credentials-", reference) if env else "",
            secret_env=tuple(sorted(env)),
            deadline_seconds=deadline,
            runtime_class=runtime_class,
            pull_secret=self.document.get("pull_secret", ""),
            data_key_configmap=self.document.get("data_public_keys_configmap", "runtime-data-public-keys"),
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

    @staticmethod
    def _creation(row):
        state = row.get("observed_state", {}).get("creation", {})
        if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1:
            return {}
        return state

    @staticmethod
    def _creation_receipt(before, after, state, *, attempt_id=None, controller_epoch=None):
        keys = (
            "resource_ref",
            "operation_id",
            "app_id",
            "node_id",
            "cluster_id",
            "namespace",
            "name",
            "kind",
            "generation",
            "owner_epoch",
            "spec_digest",
            "uid",
        )
        creation = KubernetesExecutor._creation(after)
        if (
            any(after.get(key) != before.get(key) for key in keys)
            or after.get("uid") is not None
            or creation.get("state") != state
            or (attempt_id is not None and creation.get("create_attempt_id") != attempt_id)
            or (
                controller_epoch is not None
                and (creation.get("controller_epoch"), after.get("controller_epoch"))
                != (controller_epoch, controller_epoch)
            )
        ):
            raise ExecutorError("pod_creation_receipt_refused")
        return after

    def _create(self, row, template):
        self._controller()
        if row["kind"] == "Pod" and self._creation(row).get("state") == "not_created":
            raise ExecutorError("pod_creation_already_closed")
        try:
            obj = self._fresh(row)
        except KubernetesAPIError as exc:
            if exc.status_code != 404:
                raise
            if row.get("uid"):
                raise ExecutorError("bound_resource_missing") from None
            attempt_id = None
            if row["kind"] == "Pod":
                if self._creation(row).get("state") != "unattempted":
                    raise ExecutorError("pod_creation_unconfirmed") from None
                attempt_id = str(uuid4())
                row = self._creation_receipt(
                    row,
                    self._observation(row, "create_begin", create_attempt_id=attempt_id),
                    "started",
                    attempt_id=attempt_id,
                    controller_epoch=self.controller_epoch,
                )
            try:
                self.client.create(_RESOURCES[row["kind"]], template)
            except KubernetesAPIError as conflict:
                if attempt_id is not None and conflict.status_code == 403:
                    self._creation_receipt(
                        row,
                        self._observation(row, "create_rejected", create_attempt_id=attempt_id, http_status=403),
                        "rejected",
                        attempt_id=attempt_id,
                        controller_epoch=self.controller_epoch,
                    )
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
            static_pool=bool(storage.get("static_pool")),
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

    def _startup_checkpoint(self, expected):
        current = self.platform.operation(expected["operation_id"])
        if any(
            current.get(key) != expected.get(key)
            for key in ("operation_id", "app_id", "node_id", "generation", "owner_epoch")
        ):
            raise ExecutorError("execution_fence_mismatch")
        if (
            current.get("status") not in {"pending", "running"}
            or current.get("cancel_requested")
            or current.get("payload", {}).get("cancel_requested")
        ):
            raise ExecutorError("operation_cancelled")
        deadline = min(_seconds(expected["deadline"]), _seconds(current["deadline"]))
        if self.clock.time() >= deadline:
            raise ExecutorError("operation_timeout")
        return deadline

    def _startup_window(self, operation, row, pod):
        now = self.clock.time()

        def timestamp(raw):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
                value = parsed.timestamp()
                if value > now + 5:
                    raise ValueError()
                return value
            except (ValueError, TypeError, AttributeError, OverflowError, OSError):
                raise ExecutorError("workload_stage_time_invalid") from None

        anchor = timestamp(pod.get("metadata", {}).get("creationTimestamp"))
        expected = [c["name"] for c in row["template"]["spec"].get("initContainers", [])]
        actual = [c["name"] for c in pod.get("spec", {}).get("initContainers", [])]
        if (
            expected != actual
            or not row.get("protected_since_creation")
            or pod.get("metadata", {}).get("annotations", {}).get(POLICY_ANNOTATION) != row["status_policy_revision"]
        ):
            raise ExecutorError("workload_stage_state_invalid")
        statuses = pod.get("status", {}).get("initContainerStatuses", [])
        if not isinstance(statuses, list):
            raise ExecutorError("workload_stage_state_invalid")
        states = {}
        for item in statuses:
            if not isinstance(item, dict) or item.get("name") not in expected or item["name"] in states:
                raise ExecutorError("workload_stage_state_invalid")
            state = item.get("state", {})
            if (
                not isinstance(state, dict)
                or len(state) > 1
                or set(state) - {"terminated", "waiting", "running"}
                or any(not isinstance(value, dict) for value in state.values())
                or ("terminated" in state and type(state["terminated"].get("exitCode")) is not int)
            ):
                raise ExecutorError("workload_stage_state_invalid")
            states[item["name"]] = state
        for index, name in enumerate(expected):
            state = states.get(name, {})
            terminated = state.get("terminated")
            if terminated is not None and terminated["exitCode"] == 0:
                finished = timestamp(terminated.get("finishedAt"))
                if finished < anchor - 5:
                    raise ExecutorError("workload_stage_time_invalid")
                if finished > anchor + 90:
                    raise ExecutorError("workload_readiness_timeout")
                # A bounded API-server/kubelet clock skew cannot move an anchor backwards.
                anchor = max(anchor, finished)
                continue
            if any(set(states.get(later, {})) & {"running", "terminated"} for later in expected[index + 1 :]):
                raise ExecutorError("workload_stage_state_invalid")
            return min(_seconds(operation["deadline"]), anchor + 90), False
        return min(_seconds(operation["deadline"]), anchor + 90), True

    def launch(self, operation, *, preview=False):
        expected = {
            key: operation[key]
            for key in ("operation_id", "app_id", "node_id", "generation", "owner_epoch", "deadline")
        }
        self._startup_checkpoint(expected)
        if self.config.egress_enabled:
            from runtime_manager.egress import egress_env

            credentials = self.platform.egress(operation["operation_id"], "runtime")
            operation["payload"]["runtime_env"] = {
                **operation["payload"].get("runtime_env", {}),
                **egress_env(self.config, **credentials),
            }
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
                {key: operation["payload"]["runtime_env"][key].encode() for key in plan.secret_env},
                "app-secret",
            )
        pod = self._create(row, template)
        if grant:
            self.platform.bind_material_delegation(grant["delegation_id"], pod["metadata"]["uid"])
        service_ref = _ref(operation, purpose, "service")
        service = service_template(plan)
        service["metadata"]["labels"][RESOURCE_LABEL] = service_ref
        service_row, _ = self._resource(operation, plan, service, service_ref)
        while True:
            self._controller()
            operation_deadline = self._startup_checkpoint(expected)
            row = self.platform.resource(plan.resource_ref)
            pod = self._fresh(row)
            try:
                deadline, initialized = self._startup_window(expected, row, pod)
            except ExecutorError as exc:
                raise ExecutorError(str(exc), tail=self._diagnostic(operation, plan.resource_ref)) from None
            deadline = min(deadline, operation_deadline)
            if self.clock.time() >= deadline:
                raise ExecutorError("workload_readiness_timeout", tail=self._diagnostic(operation, plan.resource_ref))
            result = self._observed(row, pod)
            if self.clock.time() >= deadline:
                raise ExecutorError("workload_readiness_timeout", tail=self._diagnostic(operation, plan.resource_ref))
            if result["ready"] and initialized:
                deadline = min(deadline, self._startup_checkpoint(expected))
                if self.clock.time() >= deadline:
                    raise ExecutorError(
                        "workload_readiness_timeout", tail=self._diagnostic(operation, plan.resource_ref)
                    )
                return {**result, "service_ref": service_ref, "service_uid": service_row["uid"]}
            self.clock.sleep(max(0, min(1, deadline - self.clock.time())))

    def observe(self, exec_ref):
        row = self.platform.resource(exec_ref)
        return self._observed(row, self._fresh(row))

    def _observed(self, row, pod):
        exec_ref = row["resource_ref"]
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

    def _track_binding(self, row, pod):
        node_name = pod.get("spec", {}).get("nodeName", "")
        previous = row.get("node_name", "")
        if not isinstance(node_name, str) or (previous and node_name != previous):
            raise ExecutorError("resource_binding_changed")
        if node_name and not previous:
            if row["stop_state"] == "confirmed":
                raise ExecutorError("resource_binding_changed")
            receipt = self._observation(row, "bind", uid=row["uid"], node_name=node_name)
            if (receipt.get("resource_ref"), receipt.get("uid"), receipt.get("node_name")) != (
                row["resource_ref"],
                row["uid"],
                node_name,
            ):
                raise ExecutorError("resource_binding_receipt_refused")
            return receipt
        return row

    def _unbound_stop(self, row):
        self._controller()
        creation = self._creation(row)
        if creation.get("state") == "not_created":
            self.confirm_stopped(row["resource_ref"])
            return row
        try:
            pod = self._fresh(row)
        except KubernetesAPIError as exc:
            if exc.status_code != 404:
                raise
            if creation.get("state") not in {"unattempted", "rejected", "fenced"}:
                return row
            if creation["state"] != "fenced":
                row = self._creation_receipt(row, self._observation(row, "create_fence"), "fenced")
            # Read again only after the SQL fence closes admission to creation.
            try:
                pod = self._fresh(row)
            except KubernetesAPIError as absent:
                if absent.status_code != 404:
                    raise
                evidence = {
                    "evidence_kind": "not_created",
                    "namespace": row["namespace"],
                    "name": row["name"],
                    "observed_at": datetime.fromtimestamp(self.clock.time(), UTC).isoformat(),
                    "api_status": 404,
                }
                return self._creation_receipt(
                    row, self._observation(row, "not_created", evidence=evidence), "not_created"
                )
        meta = pod["metadata"]
        return self._observation(row, "bind", uid=meta["uid"], node_name=pod.get("spec", {}).get("nodeName", ""))

    def request_stop(self, exec_ref, operation):
        row = self.platform.resource(exec_ref)
        if row["kind"] != "Pod" or row["app_id"] != operation["app_id"]:
            raise ExecutorError("stop_resource_scope_refused")
        if row.get("uid") is None:
            row = self._unbound_stop(row)
            if self._creation(row).get("state") == "not_created":
                return {"stopped": True, "reason": "not_created"}
        if row.get("uid"):
            try:
                row = self._track_binding(row, self._fresh(row))
            except KubernetesAPIError:
                self._observation(row, "stop", operation_id=operation["operation_id"])
                return {"stopped": False, "reason": "stop_api_unconfirmed"}
        row = self._observation(row, "stop", operation_id=operation["operation_id"])
        observation = request_stop(self.client, self._identity(row))
        return {"stopped": False, "reason": observation.reason}

    def confirm_stopped(self, exec_ref):
        row = self.platform.resource(exec_ref)
        if row["kind"] != "Pod":
            raise ExecutorError("stop_resource_kind_refused")
        evidence = row.get("stop_evidence", {})
        if self._creation(row).get("state") == "not_created" or evidence.get("evidence_kind") == "not_created":
            if (
                row.get("uid") is not None
                or row["stop_state"] != "confirmed"
                or self._creation(row).get("state") != "not_created"
                or evidence.get("evidence_kind") != "not_created"
            ):
                raise ExecutorError("pod_noncreation_proof_refused")
            self._controller()
            try:
                self._fresh(row)
            except KubernetesAPIError as exc:
                if exc.status_code != 404:
                    raise
            else:
                raise ExecutorError("pod_noncreation_object_present")
            return {"stopped": True, "evidence_kind": "not_created", "exec_ref": exec_ref}
        if row["stop_state"] == "confirmed":
            self._controller()
            try:
                pod = self._fresh(row)
            except KubernetesAPIError as exc:
                if exc.status_code != 404:
                    raise
            else:
                self._track_binding(row, pod)
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
        if row.get("uid"):
            try:
                row = self._track_binding(row, self._fresh(row))
            except KubernetesAPIError:
                return {
                    "stopped": False,
                    "evidence_kind": "unknown",
                    "reason": "stop_api_unconfirmed",
                    "exec_ref": exec_ref,
                }
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

    def _diagnostic(self, operation, reference):
        from runtime_manager.container_runner import redact

        try:
            row = self.platform.resource(reference)
            pod = self._fresh(row)
        except (KubernetesAPIError, PlatformError, ExecutorError):
            return "Execution observation unavailable"
        output = []
        for container in [*pod.get("spec", {}).get("initContainers", []), *pod.get("spec", {}).get("containers", [])]:
            name = container["name"]
            try:
                text = self.client.logs(row["name"], container=name, tail=80)
            except KubernetesAPIError:
                continue
            output.append(name + ":\n" + text)
        for item in [
            *pod.get("status", {}).get("initContainerStatuses", []),
            *pod.get("status", {}).get("containerStatuses", []),
        ]:
            waiting = item.get("state", {}).get("waiting", {}).get("reason")
            if waiting:
                output.append(item.get("name", "container") + ": " + str(waiting)[:128])
        env = {
            **operation["payload"].get("runtime_env", {}),
            "PIP_INDEX_URL": self.config.build_index_url,
            "PIP_EXTRA_INDEX_URL": self.config.build_extra_index_url,
            "NPM_REGISTRY": self.config.build_npm_registry,
        }
        return redact("\n".join(output), env).encode()[-16384:].decode("utf-8", errors="ignore")

    def logs(self, exec_ref, *, since=None, tail=200):
        row = self.platform.resource(exec_ref)
        pod = self._fresh(row)
        since_time = (
            datetime.fromtimestamp(since, UTC).isoformat().replace("+00:00", "Z") if since is not None else None
        )
        parts = []
        restarted = any(
            c.get("name") == "app" and c.get("restartCount", 0) > 0
            for c in pod.get("status", {}).get("containerStatuses", [])
        )
        if restarted:
            try:
                parts.append(
                    self.client.logs(row["name"], since_time=since_time, tail=tail, container="app", previous=True)
                )
            except KubernetesAPIError as exc:
                if exc.status_code not in {400, 404}:
                    raise
        parts.append(self.client.logs(row["name"], since_time=since_time, tail=tail, container="app"))
        self._fresh(row)
        return "\n".join(parts).encode()[-1024 * 1024 :].decode("utf-8", errors="ignore")

    def cleanup(self, operation):
        if operation["kind"] == "data" and operation["payload"].get("online"):
            if self.data_transport is None:
                return {"complete": False, "reason": "data_transport_unavailable"}
            return self.data_transport.cleanup_session(operation)
        rows = self.platform.resources(operation["operation_id"])
        for row in rows:
            if row["kind"] == "Pod":
                if row["stop_state"] != "confirmed":
                    self.request_stop(row["resource_ref"], operation)
                    if not self.confirm_stopped(row["resource_ref"])["stopped"]:
                        return {"complete": False, "reason": "writer_stop_unconfirmed"}
                elif self._creation(row).get("state") == "not_created":
                    self.confirm_stopped(row["resource_ref"])
        # An initially unbound Pod may have acquired its real UID while stopping.
        rows = self.platform.resources(operation["operation_id"])
        for row in rows:
            if row["kind"] == "PersistentVolumeClaim" and row["purpose"] in {
                "serve",
                "migrate",
                "restore",
                "data",
                "purge",
            }:
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

    def purge_volume(self, operation):
        reference = str(uuid5(NAMESPACE_URL, "bisheng-volume:" + self.config.node_id + ":" + operation["app_id"]))
        row = self.platform.resource(reference)
        if row["cleanup_state"] == "complete":
            return {"complete": True}
        if (row["app_id"], row["node_id"], row["kind"]) != (
            operation["app_id"],
            self.config.node_id,
            "PersistentVolumeClaim",
        ):
            raise ExecutorError("purge_volume_scope_refused")
        row = self._observation(row, "stop", operation_id=operation["operation_id"])
        try:
            obj = self._fresh(row)
        except KubernetesAPIError as exc:
            if exc.status_code != 404:
                raise
        else:
            self._controller()
            self.client.delete(
                "persistentvolumeclaims",
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
                raise ExecutorError("purge_volume_cleanup_pending")
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

    def _phase(self, operation, stage, purpose, document, *, plan=None, result_container=None):
        self._startup_checkpoint(operation)
        current = self.platform.operation(operation["operation_id"])
        previous = current.get("result", {}).get("prepare_progress", {}).get(stage)
        if previous:
            self.request_stop(previous["exec_ref"], operation)
            if not self.confirm_stopped(previous["exec_ref"])["stopped"]:
                raise ExecutorError("preparation_writer_stop_unconfirmed")
            self._startup_checkpoint(operation)
            return previous["result"]
        if plan is None:
            _, profile = self._delivery_profile(operation)
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
                    prepare_environment=operation["payload"].get("delivery", {}).get("mode") == "source-image",
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
        grant = self._material(operation, plan) if plan.material_secret else None
        self._startup_checkpoint(operation)
        pod = self._create(row, template)
        if grant:
            self.platform.bind_material_delegation(grant["delegation_id"], pod["metadata"]["uid"])
        deadline = min(_seconds(operation["deadline"]), self.clock.time() + plan.deadline_seconds)
        while True:
            deadline = min(deadline, self._startup_checkpoint(operation))
            self._controller()
            pod = self._fresh(self.platform.resource(plan.resource_ref))
            status = pod.get("status", {})
            if status.get("phase") == "Failed":
                raise ExecutorError("preparation_phase_failed", tail=self._diagnostic(operation, plan.resource_ref))
            if status.get("phase") == "Succeeded":
                if any("running" in c.get("state", {}) for c in status.get("containerStatuses", [])):
                    raise ExecutorError("preparation_phase_status_inconsistent")
                container = result_container or ("prepare" if purpose == "prepare-install" else "transfer")
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
                raise ExecutorError("preparation_phase_timeout", tail=self._diagnostic(operation, plan.resource_ref))
            self.clock.sleep(min(1, deadline - self.clock.time()))
        self._startup_checkpoint(operation)
        self._save_progress(operation, stage, plan.resource_ref, result)
        self.request_stop(plan.resource_ref, operation)
        if not self.confirm_stopped(plan.resource_ref)["stopped"]:
            raise ExecutorError("preparation_writer_stop_unconfirmed")
        return result

    def prepare(self, operation):
        if operation["kind"] != "prepare":
            raise ExecutorError("preparation_mode_unavailable")
        payload = operation["payload"]
        delivery, _ = self._delivery_profile(operation)
        mode = delivery.get("mode", "bundle")
        if mode == "image":
            reference = payload["delivery"].get("image", "")
            if not isinstance(reference, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}", reference
            ):
                raise ExecutorError("image_digest_required")
            if payload.get("platform") != self.descriptor.platform:
                raise ExecutorError("frozen_platform_mismatch")
            return {
                "mode": "image",
                "image_ref": reference,
                "platform": payload["platform"],
                "startup": payload["delivery"].get("startup", {}),
            }
        if mode not in {"bundle", "source-image"}:
            raise ExecutorError("preparation_mode_unavailable")
        document = {
            key: copy.deepcopy(payload[key]) for key in ("tenant_id", "source_artifact_id", "profile", "delivery")
        }
        if "source_limits" in payload:
            document["source_limits"] = copy.deepcopy(payload["source_limits"])
        document["app_id"] = operation["app_id"]
        document["offline"] = bool(payload.get("offline"))
        document["package_environment"] = {
            key: value
            for key, value in {
                "PIP_INDEX_URL": self.config.build_index_url,
                "PIP_EXTRA_INDEX_URL": self.config.build_extra_index_url,
                "npm_config_registry": self.config.build_npm_registry,
            }.items()
            if value
        }
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
        return self.assemble(operation, result) if mode == "source-image" else result

    def assemble(self, operation, delivery):
        from runtime_manager.oci_assembler import KubernetesAssembler

        return KubernetesAssembler(self).prepare(operation, delivery)
