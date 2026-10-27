"""Installer-owned Kubernetes settings; no platform storage credentials."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_NAMESPACE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_PROTECTED = {"default", "kube-system", "kube-public", "kube-node-lease"}
_SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubernetesConfigurationError(ValueError):
    """A safe reason without file contents or credentials."""


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise KubernetesConfigurationError("k8s_descriptor_duplicate_field")
        result[key] = value
    return result


def validate_namespace(value: str) -> str:
    if not _NAMESPACE.fullmatch(value) or value in _PROTECTED or value.startswith("kube-"):
        raise KubernetesConfigurationError("k8s_namespace_refused")
    return value


def _positive_int(document: dict, key: str) -> int:
    value = document.get(key)
    if type(value) is not int or value <= 0:
        raise KubernetesConfigurationError("k8s_descriptor_budget_invalid")
    return value


@dataclass(frozen=True)
class DeploymentDescriptor:
    cluster_id: str
    namespace: str
    platform: str
    memory_budget_mb: int
    cpu_budget_millicores: int
    status_policy_revision: str
    document: dict


@dataclass(frozen=True)
class KubernetesConfig:
    namespace: str
    cluster_id: str
    descriptor_file: Path
    api_server: str = "https://kubernetes.default.svc"
    token_file: Path = _SERVICE_ACCOUNT / "token"
    ca_file: Path = _SERVICE_ACCOUNT / "ca.crt"
    request_timeout: float = 10.0
    retry_attempts: int = 3
    page_size: int = 200
    sandbox: str = ""

    def __post_init__(self):
        validate_namespace(self.namespace)
        if self.sandbox not in {"", "default", "recommended", "hardened"}:
            raise KubernetesConfigurationError("k8s_sandbox_invalid")
        if not _IDENTIFIER.fullmatch(self.cluster_id):
            raise KubernetesConfigurationError("k8s_cluster_id_invalid")
        try:
            url = urlsplit(self.api_server)
            port = url.port
        except ValueError:
            raise KubernetesConfigurationError("k8s_api_server_invalid") from None
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise KubernetesConfigurationError("k8s_api_server_invalid")
        if not math.isfinite(self.request_timeout) or not 0 < self.request_timeout <= 60:
            raise KubernetesConfigurationError("k8s_timeout_invalid")
        if type(self.retry_attempts) is not int or not 1 <= self.retry_attempts <= 5:
            raise KubernetesConfigurationError("k8s_retries_invalid")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 500:
            raise KubernetesConfigurationError("k8s_page_size_invalid")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> KubernetesConfig:
        env = os.environ if environ is None else environ
        descriptor = env.get("RTM_K8S_DEPLOYMENT_DESCRIPTOR", "").strip()
        if not descriptor:
            raise KubernetesConfigurationError("k8s_descriptor_required")
        try:
            timeout = float(env.get("RTM_K8S_REQUEST_TIMEOUT_SECONDS", "10"))
            attempts = int(env.get("RTM_K8S_RETRY_ATTEMPTS", "3"))
        except ValueError:
            raise KubernetesConfigurationError("k8s_transport_settings_invalid") from None
        return cls(
            namespace=env.get("RTM_K8S_NAMESPACE", "").strip(),
            cluster_id=env.get("RTM_K8S_CLUSTER_ID", "").strip(),
            descriptor_file=Path(descriptor),
            api_server=env.get("RTM_K8S_API_SERVER", "https://kubernetes.default.svc").strip(),
            token_file=Path(env.get("RTM_K8S_TOKEN_FILE", str(_SERVICE_ACCOUNT / "token"))),
            ca_file=Path(env.get("RTM_K8S_CA_FILE", str(_SERVICE_ACCOUNT / "ca.crt"))),
            sandbox=env.get("RTM_K8S_SANDBOX", ""),
            request_timeout=timeout,
            retry_attempts=attempts,
        )

    def read_token(self) -> str:
        try:
            with self.token_file.open("r", encoding="utf-8") as source:
                value = source.read(16385).strip()
        except (OSError, UnicodeError):
            raise KubernetesConfigurationError("k8s_token_unavailable") from None
        if not 0 < len(value) <= 16384 or not re.fullmatch(r"[A-Za-z0-9._~-]+", value):
            raise KubernetesConfigurationError("k8s_token_invalid")
        return value

    def descriptor(self) -> DeploymentDescriptor:
        try:
            with self.descriptor_file.open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise KubernetesConfigurationError("k8s_descriptor_too_large")
            document = json.loads(raw, object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise KubernetesConfigurationError("k8s_descriptor_unavailable") from None
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int:
            raise KubernetesConfigurationError("k8s_descriptor_invalid")
        if document["schema_version"] != 1:
            raise KubernetesConfigurationError("k8s_descriptor_version_unsupported")
        if (document.get("cluster_id"), document.get("namespace")) != (self.cluster_id, self.namespace):
            raise KubernetesConfigurationError("k8s_descriptor_scope_mismatch")
        if self.sandbox and self.sandbox != document.get("sandbox", {}).get("requested", "default"):
            raise KubernetesConfigurationError("k8s_sandbox_descriptor_mismatch")
        platform = document.get("platform")
        policy = document.get("status_policy_revision")
        if platform not in {"linux/amd64", "linux/arm64"}:
            raise KubernetesConfigurationError("k8s_descriptor_platform_unsupported")
        if not isinstance(policy, str) or not _IDENTIFIER.fullmatch(policy):
            raise KubernetesConfigurationError("k8s_status_policy_revision_required")
        return DeploymentDescriptor(
            cluster_id=self.cluster_id,
            namespace=self.namespace,
            platform=platform,
            memory_budget_mb=_positive_int(document, "memory_budget_mb"),
            cpu_budget_millicores=_positive_int(document, "cpu_budget_millicores"),
            status_policy_revision=policy,
            document=document,
        )
