"""Installer-constrained templates from platform-frozen execution inputs.

These functions accept typed plans, never a user PodSpec or user volume path.
Admission independently compares the resulting resources with committed plans.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field

from runtime_manager.k8s_config import validate_namespace

STOP_FINALIZER = "runtime.bisheng.io/stop-confirmed"
POLICY_ANNOTATION = "runtime.bisheng.io/status-policy"
RESOURCE_LABEL = "runtime.bisheng.io/resource"
PRODUCTION = {"serve", "migrate", "restore", "data", "purge"}
PREPARATION = {"prepare-download", "prepare-install", "prepare-upload", "assemble"}
PURPOSES = PRODUCTION | PREPARATION | {"probe", "preview"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_BLOCKED_ENV = {"LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "NODE_OPTIONS"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:40]


def production_name(app_id: str) -> str:
    if not isinstance(app_id, str) or not _IDENTIFIER.fullmatch(app_id):
        raise ValueError("k8s_app_id_invalid")
    return "app-" + _hash(app_id)


@dataclass(frozen=True)
class PodPlan:
    namespace: str
    app_id: str
    operation_id: str
    resource_ref: str
    node_id: str
    generation: int
    owner_epoch: int
    purpose: str
    platform: str
    status_policy_revision: str
    image: str
    helper_image: str
    command: tuple[str, ...]
    memory_mb: int
    cpu_millicores: int
    uid: int = 10001
    gid: int = 10001
    mode: str = "bundle"
    port: int = 8080
    health_path: str = "/health"
    pvc_name: str = ""
    scratch_pvc: str = ""
    material_secret: str = ""
    app_secret: str = ""
    secret_env: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict, repr=False)
    helper_env: dict[str, str] = field(default_factory=dict, repr=False)
    deadline_seconds: int | None = None
    runtime_class: str = ""
    pull_secret: str = ""
    data_key_configmap: str = "runtime-data-public-keys"
    registry_secret: str = ""
    prepare_environment: bool = False
    schema_plan: tuple[dict, ...] = field(default_factory=tuple, repr=False)
    temporary_mb: int = 256

    def validate(self):
        validate_namespace(self.namespace)
        for value in (self.app_id, self.operation_id, self.resource_ref, self.node_id, self.status_policy_revision):
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                raise ValueError("k8s_identity_invalid")
        for value in (
            self.generation,
            self.owner_epoch,
            self.uid,
            self.gid,
            self.memory_mb,
            self.cpu_millicores,
            self.temporary_mb,
        ):
            if type(value) is not int or not 0 < value <= 2**31 - 1:
                raise ValueError("k8s_resources_or_identity_invalid")
        if self.platform not in {"linux/amd64", "linux/arm64"} or self.mode not in {"bundle", "image"}:
            raise ValueError("k8s_profile_invalid")
        if self.purpose not in PURPOSES:
            raise ValueError("k8s_purpose_invalid")
        for value in (self.image, self.helper_image):
            if not _IMAGE.fullmatch(value):
                raise ValueError("k8s_image_digest_required")
        for value in (
            self.pvc_name,
            self.scratch_pvc,
            self.material_secret,
            self.app_secret,
            self.runtime_class,
            self.pull_secret,
            self.data_key_configmap,
            self.registry_secret,
        ):
            if value and not _NAME.fullmatch(value):
                raise ValueError("k8s_reference_invalid")
        if not isinstance(self.command, tuple) or any(
            not isinstance(x, str) or "\x00" in x or len(x) > 32768 for x in self.command
        ):
            raise ValueError("k8s_command_invalid")
        if self.mode == "bundle" and self.purpose in {"serve", "probe", "preview"} and not self.command:
            raise ValueError("k8s_command_required")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("k8s_port_invalid")
        if (
            not self.health_path.startswith("/")
            or self.health_path.startswith("//")
            or any(c in self.health_path for c in "\r\n\x00")
        ):
            raise ValueError("k8s_health_path_invalid")
        if self.purpose == "serve":
            if self.deadline_seconds is not None:
                raise ValueError("k8s_serving_total_deadline_refused")
        elif type(self.deadline_seconds) is not int or not 1 <= self.deadline_seconds <= (
            604800 if self.purpose == "preview" else 1800
        ):
            raise ValueError("k8s_task_deadline_required")
        if self.purpose == "data" and self.deadline_seconds > 60:
            raise ValueError("k8s_data_deadline_invalid")
        if self.purpose in PRODUCTION and not self.pvc_name:
            raise ValueError("k8s_production_pvc_required")
        if self.purpose not in PRODUCTION and self.pvc_name:
            raise ValueError("k8s_isolated_data_required")
        if self.purpose in PREPARATION and not self.scratch_pvc:
            raise ValueError("k8s_scratch_pvc_required")
        material = self.purpose in {"prepare-download", "prepare-upload"} or (
            self.mode == "bundle" and self.purpose in {"serve", "probe", "preview"}
        )
        if type(self.prepare_environment) is not bool or (
            self.prepare_environment and self.purpose != "prepare-install"
        ):
            raise ValueError("k8s_preparation_environment_refused")
        if self.registry_secret and self.purpose != "assemble":
            raise ValueError("k8s_registry_secret_purpose_refused")
        if material and not self.material_secret:
            raise ValueError("k8s_material_secret_required")
        if (
            not isinstance(self.secret_env, tuple)
            or len(self.secret_env) > 256
            or any(not isinstance(k, str) or not _ENV.fullmatch(k) for k in self.secret_env)
        ):
            raise ValueError("k8s_secret_environment_invalid")
        if len(set(self.secret_env)) != len(self.secret_env) or set(self.secret_env) & set(self.env):
            raise ValueError("k8s_secret_environment_overlap")
        if bool(self.app_secret) != bool(self.secret_env):
            raise ValueError("k8s_app_secret_required")
        if self.secret_env and self.purpose not in {"serve", "probe", "preview"}:
            raise ValueError("k8s_app_credentials_purpose_refused")
        if any(
            k.startswith(("RTM_", "KUBERNETES_", "MINIO_"))
            or k in _BLOCKED_ENV
            or (self.mode == "bundle" and k == "PATH")
            for k in self.secret_env
        ):
            raise ValueError("k8s_secret_environment_refused")
        if {"MATERIAL_POD_UID", "DATA_POD_UID", "PATH"} & self.helper_env.keys():
            raise ValueError("k8s_material_uid_literal_refused")
        for env in (self.env, self.helper_env):
            if not isinstance(env, dict) or len(env) > 256:
                raise ValueError("k8s_environment_invalid")
            for key, value in env.items():
                if not _ENV.fullmatch(key) or key.startswith(("RTM_", "KUBERNETES_", "MINIO_")) or key in _BLOCKED_ENV:
                    raise ValueError("k8s_environment_refused")
                if not isinstance(value, str) or len(value) > 32768 or "\x00" in value:
                    raise ValueError("k8s_environment_invalid")

    @property
    def name(self):
        return production_name(self.app_id) if self.purpose in PRODUCTION else "task-" + _hash(self.resource_ref)


def metadata(plan: PodPlan, name: str) -> dict:
    return {
        "name": name,
        "namespace": plan.namespace,
        "labels": {
            "bisheng.managed": "v2",
            RESOURCE_LABEL: plan.resource_ref,
            "runtime.bisheng.io/app": _hash(plan.app_id),
            "runtime.bisheng.io/node": _hash(plan.node_id),
            "runtime.bisheng.io/purpose": plan.purpose,
        },
        "annotations": {
            "runtime.bisheng.io/operation": plan.operation_id,
            "runtime.bisheng.io/generation": str(plan.generation),
            "runtime.bisheng.io/owner-epoch": str(plan.owner_epoch),
            POLICY_ANNOTATION: plan.status_policy_revision,
        },
    }


def _mount(name, path, *, readonly=False, subpath=None):
    item = {"name": name, "mountPath": path, "readOnly": readonly}
    if subpath:
        item["subPath"] = subpath
    return item


def _container(plan, name, *, image=None, command=None, mounts=(), helper=False, env=None):
    budget = {
        "cpu": "25m" if helper else f"{plan.cpu_millicores}m",
        "memory": "128Mi" if helper else f"{plan.memory_mb}Mi",
        "ephemeral-storage": f"{plan.temporary_mb}Mi",
    }
    item = {
        "name": name,
        "image": image or plan.image,
        "imagePullPolicy": "IfNotPresent",
        "securityContext": {
            "runAsUser": plan.uid,
            "runAsGroup": plan.gid,
            "runAsNonRoot": True,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "resources": {"requests": dict(budget), "limits": dict(budget)},
        "volumeMounts": [*mounts, _mount("tmp", "/tmp")],
        "env": [{"name": k, "value": v} for k, v in sorted((env or {}).items())],
    }
    if command:
        item["command"] = list(command)
    if name in {"transfer", "material-fetch"}:
        item["env"].append({"name": "MATERIAL_POD_UID", "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}}})
    if name == "data-helper":
        item["env"].append({"name": "DATA_POD_UID", "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}}})
    return item


def pod_template(plan: PodPlan) -> dict:
    plan.validate()
    meta = metadata(plan, plan.name)
    meta["finalizers"] = [STOP_FINALIZER]
    spec = {
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "restartPolicy": "Always" if plan.purpose in {"serve", "preview"} else "Never",
        "terminationGracePeriodSeconds": 30,
        "tolerations": [
            {"key": key, "operator": "Exists", "effect": "NoExecute", "tolerationSeconds": 300}
            for key in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
        ],
        "dnsPolicy": "None",
        "dnsConfig": {"nameservers": ["127.0.0.1"]},
        "nodeSelector": {"kubernetes.io/os": "linux", "kubernetes.io/arch": plan.platform.split("/")[1]},
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": plan.uid,
            "runAsGroup": plan.gid,
            "fsGroup": plan.gid,
            "fsGroupChangePolicy": "OnRootMismatch",
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": f"{plan.temporary_mb}Mi"}}],
        "containers": [],
        "initContainers": [],
    }
    if plan.runtime_class:
        spec["runtimeClassName"] = plan.runtime_class
    if plan.pull_secret:
        spec["imagePullSecrets"] = [{"name": plan.pull_secret}]
    if plan.deadline_seconds is not None:
        spec["activeDeadlineSeconds"] = plan.deadline_seconds
    volumes, containers, init = spec["volumes"], spec["containers"], spec["initContainers"]
    if plan.purpose == "assemble":
        volumes.append({"name": "scratch", "persistentVolumeClaim": {"claimName": plan.scratch_pvc}})
        mounts = [_mount("scratch", "/work", readonly=True)]
        if plan.registry_secret:
            volumes.append(
                {
                    "name": "registry-auth",
                    "secret": {
                        "secretName": plan.registry_secret,
                        "defaultMode": 288,
                        "items": [{"key": ".dockerconfigjson", "path": "config.json"}],
                    },
                }
            )
            mounts.append(_mount("registry-auth", "/run/registry", readonly=True))
        containers.append(_container(plan, "assembler", command=plan.command, mounts=mounts, env=plan.helper_env))
    elif plan.purpose in PREPARATION:
        volumes.append({"name": "scratch", "persistentVolumeClaim": {"claimName": plan.scratch_pvc}})
        trusted = plan.purpose in {"prepare-download", "prepare-upload"}
        mounts = (
            [_mount("scratch", "/work")]
            if trusted
            else [
                _mount("scratch", "/workspace/app", subpath="source"),
                _mount("scratch", "/original", subpath="original", readonly=True),
                _mount("scratch", "/materials", subpath="materials", readonly=True),
                _mount("scratch", "/output", subpath="output"),
                _mount("scratch", "/runtime/tools", subpath="tools", readonly=True),
            ]
        )
        if plan.purpose == "prepare-install" and plan.prepare_environment:
            mounts.append(_mount("scratch", "/opt/venv", subpath="environment"))
        if trusted:
            volumes.append(
                {"name": "material-auth", "secret": {"secretName": plan.material_secret, "defaultMode": 256}}
            )
            mounts.append(_mount("material-auth", "/run/material", readonly=True))
        container = _container(
            plan,
            "transfer" if trusted else "prepare",
            image=plan.helper_image if trusted else plan.image,
            command=("python", "-I", "-m", "runtime_manager.k8s_helper", plan.purpose) if trusted else plan.command,
            mounts=mounts,
            env=plan.helper_env if trusted else {},
        )
        container["workingDir"] = "/work" if trusted else "/workspace/app"
        containers.append(container)
    else:
        production = plan.purpose in PRODUCTION
        volumes.append(
            {"name": "data", "persistentVolumeClaim": {"claimName": plan.pvc_name}}
            if production
            else {"name": "data", "emptyDir": {"sizeLimit": "1024Mi"}}
        )
        init.append(
            _container(
                plan,
                "data-layout",
                image=plan.helper_image,
                command=("python", "-I", "-m", "runtime_manager.k8s_helper", "data-layout"),
                mounts=[_mount("data", "/volume")],
                helper=True,
            )
        )
        if plan.purpose in {"probe", "preview"} and plan.schema_plan:
            init.append(
                _container(
                    plan,
                    "schema-init",
                    image=plan.helper_image,
                    command=("python", "-I", "-m", "runtime_manager.k8s_data_helper", "schema-init"),
                    mounts=[_mount("data", "/volume")],
                    helper=True,
                    env={
                        "SCHEMA_PLAN": json.dumps(
                            {"app_id": plan.app_id, "plan": plan.schema_plan}, sort_keys=True, separators=(",", ":")
                        )
                    },
                )
            )
        if plan.purpose in {"serve", "probe", "preview"}:
            mounts = [_mount("data", "/data", subpath="business")]
            if plan.mode == "bundle":
                for name in ("code", "environment", "materials", "tools"):
                    volumes.append({"name": name, "emptyDir": {"sizeLimit": "4096Mi"}})
                volumes.append(
                    {"name": "material-auth", "secret": {"secretName": plan.material_secret, "defaultMode": 256}}
                )
                fetch_mounts = [
                    _mount("code", "/workspace/app"),
                    _mount("materials", "/materials"),
                    _mount("tools", "/runtime/tools"),
                    _mount("material-auth", "/run/material", readonly=True),
                ]
                init.append(
                    _container(
                        plan,
                        "material-fetch",
                        image=plan.helper_image,
                        command=("python", "-I", "-m", "runtime_manager.k8s_helper", "material-fetch"),
                        mounts=fetch_mounts,
                        helper=True,
                        env=plan.helper_env,
                    )
                )
                init.append(
                    _container(
                        plan,
                        "environment",
                        command=("/bin/sh", "/runtime/tools/environment.sh"),
                        mounts=[
                            _mount("code", "/workspace/app"),
                            _mount("materials", "/materials", readonly=True),
                            _mount("tools", "/runtime/tools", readonly=True),
                            _mount("environment", "/opt/venv"),
                        ],
                    )
                )
                mounts += [
                    _mount("code", "/workspace/app", readonly=True),
                    _mount("environment", "/opt/venv", readonly=True),
                ]
            app = _container(plan, "app", command=plan.command, mounts=mounts, env=plan.env)
            app["env"].extend(
                {"name": key, "valueFrom": {"secretKeyRef": {"name": plan.app_secret, "key": key}}}
                for key in sorted(plan.secret_env)
            )
            if plan.mode == "bundle":
                app["workingDir"] = "/workspace/app"
                app["env"].append(
                    {
                        "name": "PATH",
                        "value": "/opt/venv/bin:/workspace/app/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
                    }
                )
            app["ports"] = [{"name": "http", "containerPort": plan.port, "protocol": "TCP"}]
            for probe in ("readinessProbe", "livenessProbe"):
                app[probe] = {
                    "httpGet": {"path": plan.health_path, "port": "http"},
                    "periodSeconds": 10,
                    "timeoutSeconds": 2,
                    "failureThreshold": 3,
                }
            app["startupProbe"] = {
                "httpGet": {"path": plan.health_path, "port": "http"},
                "periodSeconds": 3,
                "failureThreshold": 30,
                "timeoutSeconds": 2,
            }
            containers.append(app)
        if plan.purpose in PRODUCTION:
            name = "data-helper" if plan.purpose in {"serve", "data"} else "maintenance"
            mounts = [_mount("data", "/volume")]
            environment = plan.helper_env
            command = ("python", "-I", "-m", "runtime_manager.k8s_data_helper", "maintenance")
            if name == "maintenance" and plan.material_secret:
                volumes.append(
                    {"name": "material-auth", "secret": {"secretName": plan.material_secret, "defaultMode": 256}}
                )
                mounts.append(_mount("material-auth", "/run/material", readonly=True))
            if name == "data-helper":
                volumes.append(
                    {
                        "name": "data-keys",
                        "configMap": {
                            "name": plan.data_key_configmap,
                            "defaultMode": 292,
                            "items": [{"key": "public-keys.json", "path": "public-keys.json"}],
                        },
                    }
                )
                mounts.append(_mount("data-keys", "/run/data", readonly=True))
                environment = {
                    "DATA_CONTEXT": json.dumps(
                        {"app_id": plan.app_id, "exec_ref": plan.resource_ref}, sort_keys=True, separators=(",", ":")
                    )
                }
                command = ("python", "-I", "-m", "runtime_manager.k8s_data_helper")
            container = _container(
                plan, name, image=plan.helper_image, command=command, mounts=mounts, helper=True, env=environment
            )
            if name == "data-helper":
                container["ports"] = [{"name": "data-control", "containerPort": 8092, "protocol": "TCP"}]
                container["readinessProbe"] = {
                    "httpGet": {"path": "/healthz", "port": "data-control"},
                    "periodSeconds": 2,
                    "timeoutSeconds": 1,
                    "failureThreshold": 3,
                }
            containers.append(container)
    return {"apiVersion": "v1", "kind": "Pod", "metadata": meta, "spec": spec}


def service_template(plan: PodPlan) -> dict:
    plan.validate()
    if plan.purpose not in {"serve", "probe", "preview"}:
        raise ValueError("k8s_service_purpose_refused")
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": metadata(plan, "svc-" + _hash(plan.resource_ref)),
        "spec": {
            "type": "ClusterIP",
            "selector": {RESOURCE_LABEL: plan.resource_ref},
            "ports": [{"name": "http", "protocol": "TCP", "port": plan.port, "targetPort": plan.port}],
        },
    }


def pvc_template(plan: PodPlan, *, name: str, size_mb: int, storage_class: str, static_pool: bool = False) -> dict:
    plan.validate()
    if not _NAME.fullmatch(name) or type(size_mb) is not int or size_mb <= 0:
        raise ValueError("k8s_pvc_invalid")
    if storage_class and (len(storage_class) > 253 or not all(_NAME.fullmatch(x) for x in storage_class.split("."))):
        raise ValueError("k8s_storage_class_invalid")
    result = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": metadata(plan, name),
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": storage_class,
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": f"{size_mb}Mi"}},
        },
    }

    if static_pool:
        result["spec"]["selector"] = {
            "matchLabels": {
                "runtime.bisheng.io/namespace": plan.namespace,
                "runtime.bisheng.io/volume-role": "production" if plan.pvc_name else "scratch",
            }
        }
    return result


def secret_template(plan: PodPlan, *, name: str, data: dict[str, bytes]) -> dict:
    plan.validate()
    if (
        not _NAME.fullmatch(name)
        or not data
        or any(
            not isinstance(k, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,253}", k)
            or k in {".", ".."}
            or not isinstance(v, bytes)
            for k, v in data.items()
        )
    ):
        raise ValueError("k8s_secret_invalid")
    if sum(len(v) for v in data.values()) > 65536:
        raise ValueError("k8s_secret_too_large")
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": metadata(plan, name),
        "type": "Opaque",
        "immutable": True,
        "data": {k: base64.b64encode(v).decode("ascii") for k, v in sorted(data.items())},
    }


def template_digest(template: dict) -> str:
    return hashlib.sha256(
        json.dumps(template, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def capability_probe_template(plan, *, network=None, storage_claim=""):
    """Installer-only probes, never caller application code or a production PVC."""
    from dataclasses import replace

    if plan.operation_id[:10] != "preflight-" or plan.purpose != "probe":
        raise ValueError("k8s_preflight_scope_refused")
    if storage_claim and (not _NAME.fullmatch(storage_claim) or not storage_claim.startswith("preflight-")):
        raise ValueError("k8s_preflight_volume_refused")
    if bool(storage_claim) == (network is not None):
        raise ValueError("k8s_preflight_action_invalid")
    action = "storage" if storage_claim else "network"
    plan = replace(
        plan,
        mode="image",
        image=plan.helper_image,
        material_secret="",
        app_secret="",
        secret_env=(),
        schema_plan=(),
        command=("python", "-I", "-m", "runtime_manager.k8s_capabilities", action),
        env={"CAPABILITY_PLAN": json.dumps(network, sort_keys=True, separators=(",", ":"))}
        if network is not None
        else {},
    )
    pod = pod_template(plan)
    pod["metadata"]["name"] = "preflight-" + _hash(plan.resource_ref)
    if storage_claim:
        pod["spec"]["volumes"].append({"name": "probe-volume", "persistentVolumeClaim": {"claimName": storage_claim}})
        pod["spec"]["containers"][0]["volumeMounts"].append(_mount("probe-volume", "/probe-volume"))
    return pod
