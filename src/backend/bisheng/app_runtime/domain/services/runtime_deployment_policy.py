"""Server-owned Kubernetes deployment policy and immutable operation snapshots.

This module performs no cluster calls. Expected files are mounted by deployment,
not accepted from Manager or application uploads.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

HELPERS = {
    "image-check": {"memory_mb": 256, "cpu_millicores": 1000},
    "prepare-download": {"memory_mb": 128, "cpu_millicores": 100},
    "prepare-install": {"memory_mb": 1024, "cpu_millicores": 1000},
    "prepare-upload": {"memory_mb": 128, "cpu_millicores": 100},
    "assemble": {"memory_mb": 1024, "cpu_millicores": 1000},
    "data": {"memory_mb": 128, "cpu_millicores": 100},
    "sidecar": {"memory_mb": 128, "cpu_millicores": 25},
    "init": {"memory_mb": 128, "cpu_millicores": 25},
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def parse_policy(raw, *, node_id):
    try:
        if not isinstance(raw, str) or len(raw.encode()) > 1024 * 1024:
            raise ValueError()
        document = json.loads(raw, object_pairs_hook=_pairs)
        json.dumps(document, allow_nan=False)
        if (
            document.get("schema_version") != 2
            or document.get("configuration_source") != "operator-configured"
            or document.get("node_id") != node_id
            or "probe_report" in document
            or not document.get("installation_id")
            or not document.get("cluster_id")
            or not document.get("namespace")
            or not document.get("status_policy_revision")
            or not document.get("manager_username")
            or not document.get("storage_controller_usernames")
        ):
            raise ValueError()
        if type(document["schema_version"]) is not int or document.get("platform") not in {
            "linux/amd64",
            "linux/arm64",
        }:
            raise ValueError()
        identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
        for key in ("installation_id", "node_id", "cluster_id", "status_policy_revision"):
            if not isinstance(document[key], str) or not identifier.fullmatch(document[key]):
                raise ValueError()
        namespace = document["namespace"]
        if (
            not isinstance(namespace, str)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", namespace)
            or namespace in {"default", "kubekey-system"}
            or namespace.startswith("kube-")
        ):
            raise ValueError()
        actor = re.compile(r"system:[A-Za-z0-9_.:-]{1,240}")
        actors = [document["manager_username"], *document["storage_controller_usernames"]]
        if document.get("cni_username"):
            actors.append(document["cni_username"])
        if any(not isinstance(value, str) or not actor.fullmatch(value) for value in actors):
            raise ValueError()
        if not isinstance(document["storage_controller_usernames"], list) or len(
            set(document["storage_controller_usernames"])
        ) != len(document["storage_controller_usernames"]):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}", str(document.get("helper_image", ""))):
            raise ValueError()
        cidrs = document.get("service_cidrs")
        if not isinstance(cidrs, list) or not cidrs:
            raise ValueError()
        for value in cidrs:
            if not isinstance(value, str):
                raise ValueError()
            network = ipaddress.ip_network(value)
            if network.is_loopback or network.is_link_local or network.is_multicast or network.prefixlen == 0:
                raise ValueError()
        storage = document.get("storage", {})
        if (
            not isinstance(storage, dict)
            or storage.get("filesystem") not in {"ext4", "xfs"}
            or storage.get("sqlite_compatible") is not True
        ):
            raise ValueError()
        for key in ("memory_budget_mb", "cpu_budget_millicores"):
            if type(document.get(key)) is not int or not 0 < document[key] <= 2**31 - 1:
                raise ValueError()
        resources = document.get("helper_resources", {})
        if not isinstance(resources, dict) or set(resources) - HELPERS.keys():
            raise ValueError()
        for budget in {**HELPERS, **resources}.values():
            if (
                not isinstance(budget, dict)
                or set(budget) != {"memory_mb", "cpu_millicores"}
                or any(type(value) is not int or value <= 0 for value in budget.values())
            ):
                raise ValueError()
            if (
                budget["memory_mb"] > document["memory_budget_mb"]
                or budget["cpu_millicores"] > document["cpu_budget_millicores"]
            ):
                raise ValueError()
        timeouts = document.get("timeouts", {})
        if (
            not isinstance(timeouts, dict)
            or set(timeouts) - {"image_check", "init_phase", "health"}
            or any(type(value) is not int or not 0 < value <= 1800 for value in timeouts.values())
        ):
            raise ValueError()
        if "operation_timeout_seconds" in document and (
            type(document["operation_timeout_seconds"]) is not int
            or not 0 < document["operation_timeout_seconds"] <= 1800
        ):
            raise ValueError()
        placement = document.get("placement", {})
        if (
            not isinstance(placement, dict)
            or set(placement) - {"nodeSelector", "affinity", "tolerations"}
            or not isinstance(placement.get("affinity", {}), dict)
            or not isinstance(placement.get("tolerations", []), list)
        ):
            raise ValueError()
        selector = placement.get("nodeSelector", {})
        if (
            not isinstance(selector, dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in selector.items())
            or any(not isinstance(value, dict) for value in placement.get("tolerations", []))
        ):
            raise ValueError()
        for key, value in {
            "kubernetes.io/os": "linux",
            "kubernetes.io/arch": document["platform"].split("/")[1],
        }.items():
            if key in selector and selector[key] != value:
                raise ValueError()
        return document
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise RuntimeConflict("deployment_policy_invalid") from None


def expected_policy(node_id):
    from bisheng.common.services.config_service import settings

    path = settings.app_runtime.runtime_kubernetes_nodes.get(node_id)
    if not isinstance(path, str) or not path:
        raise RuntimeConflict("deployment_policy_missing")
    try:
        with Path(path).open("rb") as source:
            raw = source.read(1024 * 1024 + 1).decode("utf-8")
    except (OSError, UnicodeError):
        raise RuntimeConflict("deployment_policy_unavailable") from None
    return raw, parse_policy(raw, node_id=node_id)


def policy_digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def protection_digest(document):
    keys = (
        "installation_id",
        "node_id",
        "cluster_id",
        "namespace",
        "status_policy_revision",
        "manager_username",
        "cni_username",
    )
    subset = {key: document.get(key, "") for key in keys}
    subset["guard_contract_version"] = 1
    subset["storage_controller_usernames"] = sorted(document["storage_controller_usernames"])
    return hashlib.sha256(
        json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def operation_policy(operation):
    payload = operation.payload if hasattr(operation, "payload") else operation["payload"]
    raw = payload.get("execution_policy_json")
    if raw is None:
        return None
    node_id = operation.node_id if hasattr(operation, "node_id") else operation["node_id"]
    if policy_digest(raw) != payload.get("execution_policy_digest"):
        raise RuntimeConflict("operation_policy_digest_mismatch")
    return parse_policy(raw, node_id=node_id)


def helper_resources(document, purpose):
    value = (document or {}).get("helper_resources", {}).get(purpose, HELPERS[purpose])
    if (
        not isinstance(value, dict)
        or set(value) != {"memory_mb", "cpu_millicores"}
        or any(type(v) is not int or v <= 0 for v in value.values())
    ):
        raise RuntimeConflict("helper_resource_policy_invalid")
    return value


def matches_heartbeat(body, node_id):
    try:
        raw, policy = expected_policy(node_id)
    except RuntimeConflict:
        return False
    capabilities = body.capabilities
    configuration = capabilities.get("configuration") or {}
    return bool(
        configuration.get("version") == 2
        and configuration.get("source") == "operator-configured"
        and configuration.get("state") == "configured"
        and configuration.get("policy_digest") == policy_digest(raw)
        and configuration.get("protection_baseline_digest") == protection_digest(policy)
        and body.engine_id == policy["cluster_id"] + "/" + policy["namespace"]
        and body.platform == policy["platform"]
        and body.memory_budget_mb == policy["memory_budget_mb"]
        and body.cpu_budget_millicores == policy["cpu_budget_millicores"]
        and capabilities.get("node_id") == node_id
        and capabilities.get("status_policy_revision") == policy["status_policy_revision"]
        and capabilities.get("helper_image") == policy["helper_image"]
        and capabilities.get("service_cidrs") == policy["service_cidrs"]
        and all(
            capabilities.get(key) is True
            for key in ("status_protection", "binding_protection", "mandatory_isolation", "orchestration_available")
        )
    )


def quantity(value):
    text = str(value)
    if len(text) > 64:
        raise RuntimeConflict("resource_quantity_invalid")
    factors = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "m": Decimal("0.001")}
    try:
        result = next((Decimal(text[: -len(k)]) * v for k, v in factors.items() if text.endswith(k)), None)
        result = Decimal(text) if result is None else result
        if not result.is_finite() or not 0 < result <= 2**63 - 1:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise RuntimeConflict("resource_quantity_invalid") from None


def validate_container_resources(spec, operation, document, purpose):
    init = spec.get("initContainers", [])
    for container in [*spec.get("containers", []), *init]:
        name = container.get("name")
        role = None
        if name == "maintenance" or (name == "data-helper" and purpose == "data"):
            role = "data"
        elif name == "data-helper":
            role = "sidecar"
        elif container in init and name != "environment":
            role = "init"
        elif purpose in HELPERS:
            role = purpose
        expected = helper_resources(document, role) if role else operation.payload.get("tier", {})
        if not expected or not expected.get("memory_mb") or not expected.get("cpu_millicores"):
            raise RuntimeConflict("resource_frozen_tier_required")
        resources = container.get("resources", {})
        for side in ("requests", "limits"):
            actual = resources.get(side, {})
            if (
                quantity(actual.get("memory", "0")) != Decimal(expected["memory_mb"]) * 1024**2
                or quantity(actual.get("cpu", "0")) != Decimal(expected["cpu_millicores"]) / 1000
            ):
                raise RuntimeConflict("resource_frozen_budget_mismatch")
