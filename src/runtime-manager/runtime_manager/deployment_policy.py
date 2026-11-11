"""F008 deployment-owned inputs. No probe report grants execution authority."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path

from runtime_manager.k8s_config import validate_namespace

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
TIMEOUTS = {"image_check": 120, "init_phase": 90, "health": 90}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_ACTOR = re.compile(r"system:[A-Za-z0-9_.:-]{1,240}")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")


class PolicyError(ValueError):
    """Fixed reason, never the supplied document or Secret contents."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("deployment_policy_duplicate_field")
        result[key] = value
    return result


def _positive(value, maximum=2**31 - 1):
    return type(value) is int and 0 < value <= maximum


def canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class DeploymentPolicy:
    document: dict
    raw: str

    @classmethod
    def read(cls, path):
        try:
            with Path(path).open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise PolicyError("deployment_policy_too_large")
            return cls.parse(raw.decode("utf-8"))
        except (OSError, UnicodeError):
            raise PolicyError("deployment_policy_unavailable") from None

    @classmethod
    def parse(cls, raw):
        try:
            document = json.loads(
                raw,
                object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(PolicyError("deployment_policy_nonfinite")),
            )
            result = cls.from_document(document)
            return cls(result.document, raw)
        except (TypeError, json.JSONDecodeError, RecursionError):
            raise PolicyError("deployment_policy_invalid") from None

    @classmethod
    def from_document(cls, document):
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 2
            or type(document.get("schema_version")) is not int
        ):
            raise PolicyError("deployment_policy_version_invalid")
        if document.get("configuration_source") != "operator-configured" or "probe_report" in document:
            raise PolicyError("deployment_policy_source_invalid")
        try:
            validate_namespace(document.get("namespace", ""))
        except (ValueError, TypeError):
            raise PolicyError("deployment_policy_namespace_invalid") from None
        for key in ("installation_id", "node_id", "cluster_id", "status_policy_revision"):
            if not isinstance(document.get(key), str) or not _ID.fullmatch(document[key]):
                raise PolicyError("deployment_policy_scope_invalid")
        if document.get("platform") not in {"linux/amd64", "linux/arm64"}:
            raise PolicyError("deployment_policy_platform_invalid")
        for key in ("memory_budget_mb", "cpu_budget_millicores"):
            if not _positive(document.get(key)):
                raise PolicyError("deployment_policy_budget_invalid")
        if not _IMAGE.fullmatch(str(document.get("helper_image", ""))):
            raise PolicyError("deployment_policy_image_invalid")
        if not _ACTOR.fullmatch(str(document.get("manager_username", ""))):
            raise PolicyError("deployment_policy_actor_invalid")
        actors = document.get("storage_controller_usernames")
        if (
            not isinstance(actors, list)
            or not actors
            or any(not isinstance(x, str) or not _ACTOR.fullmatch(x) for x in actors)
            or len(set(actors)) != len(actors)
        ):
            raise PolicyError("deployment_policy_actor_invalid")
        if document.get("cni_username") and not _ACTOR.fullmatch(str(document["cni_username"])):
            raise PolicyError("deployment_policy_actor_invalid")
        try:
            if not document.get("service_cidrs"):
                raise ValueError()
            for value in document["service_cidrs"]:
                if not isinstance(value, str):
                    raise ValueError()
                net = ipaddress.ip_network(value)
                if net.is_multicast or net.is_loopback or net.is_link_local or net.prefixlen == 0:
                    raise ValueError()
        except (TypeError, ValueError):
            raise PolicyError("deployment_policy_network_invalid") from None
        storage = document.get("storage", {})
        if (
            not isinstance(storage, dict)
            or storage.get("filesystem") not in {"ext4", "xfs"}
            or storage.get("sqlite_compatible") is not True
        ):
            raise PolicyError("deployment_policy_storage_invalid")
        resources = document.get("helper_resources", {})
        if not isinstance(resources, dict) or set(resources) - HELPERS.keys():
            raise PolicyError("deployment_policy_helper_invalid")
        for value in {**HELPERS, **resources}.values():
            if (
                not isinstance(value, dict)
                or set(value) != {"memory_mb", "cpu_millicores"}
                or any(not _positive(v) for v in value.values())
            ):
                raise PolicyError("deployment_policy_helper_invalid")
            if (
                value["memory_mb"] > document["memory_budget_mb"]
                or value["cpu_millicores"] > document["cpu_budget_millicores"]
            ):
                raise PolicyError("deployment_policy_helper_over_budget")
        timeouts = document.get("timeouts", {})
        if (
            not isinstance(timeouts, dict)
            or set(timeouts) - TIMEOUTS.keys()
            or any(not _positive(v, 1800) for v in timeouts.values())
        ):
            raise PolicyError("deployment_policy_timeout_invalid")
        if "operation_timeout_seconds" in document and not _positive(document["operation_timeout_seconds"], 1800):
            raise PolicyError("deployment_policy_timeout_invalid")
        placement = document.get("placement", {})
        if not isinstance(placement, dict) or set(placement) - {"nodeSelector", "affinity", "tolerations"}:
            raise PolicyError("deployment_policy_placement_invalid")
        if (
            not isinstance(placement.get("affinity", {}), dict)
            or not isinstance(placement.get("tolerations", []), list)
            or any(not isinstance(x, dict) for x in placement.get("tolerations", []))
        ):
            raise PolicyError("deployment_policy_placement_invalid")
        selector = placement.get("nodeSelector", {})
        if not isinstance(selector, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in selector.items()
        ):
            raise PolicyError("deployment_policy_selector_invalid")
        for key, required in {
            "kubernetes.io/os": "linux",
            "kubernetes.io/arch": document["platform"].split("/")[1],
        }.items():
            if key in selector and selector[key] != required:
                raise PolicyError("deployment_policy_selector_conflict")
        try:
            raw = canonical(document)
        except (TypeError, ValueError, RecursionError):
            raise PolicyError("deployment_policy_invalid") from None
        return cls(copy.deepcopy(document), raw)

    @property
    def digest(self):
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()

    @property
    def protection_digest(self):
        keys = (
            "installation_id",
            "node_id",
            "cluster_id",
            "namespace",
            "status_policy_revision",
            "manager_username",
            "cni_username",
        )
        subset = {key: self.document.get(key, "") for key in keys}
        subset["guard_contract_version"] = 1
        subset["storage_controller_usernames"] = sorted(self.document["storage_controller_usernames"])
        return hashlib.sha256(canonical(subset).encode()).hexdigest()

    def helper(self, purpose):
        return dict(self.document.get("helper_resources", {}).get(purpose, HELPERS[purpose]))

    def timeout(self, stage):
        return self.document.get("timeouts", {}).get(stage, TIMEOUTS[stage])
