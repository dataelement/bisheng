"""Frozen registry targets for the operation-owned read-only image checker."""

import re
from urllib.parse import urlsplit

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict

_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")


def frozen_targets(operation, node):
    payload = operation.payload
    preparing = operation.kind == "prepare"
    delivery = payload.get("delivery", {}) if preparing else payload.get("resolved_delivery", {})
    profile = (payload.get("profile") if preparing else delivery.get("profile")) or {}
    capabilities = node.capabilities or {}
    mode = delivery.get("mode", "bundle")
    targets = [{"role": "helper", "reference": capabilities.get("helper_image", ""), "image_id": ""}]
    if preparing and mode in {"bundle", "source-image"}:
        targets.append(
            {
                "role": "preparer",
                "reference": profile.get("preparer_image", ""),
                "image_id": profile.get("preparer_image_id", ""),
            }
        )
    if mode in {"image", "source-image"} and not preparing:
        targets.append(
            {"role": "image", "reference": delivery.get("image_ref", ""), "image_id": delivery.get("image_id", "")}
        )
    elif mode == "image":
        targets.append({"role": "image", "reference": delivery.get("image", ""), "image_id": ""})
    else:
        targets.append(
            {
                "role": "runtime",
                "reference": profile.get("runtime_image", ""),
                "image_id": profile.get("runtime_image_id", ""),
            }
        )
    if preparing and mode == "source-image":
        targets.append({"role": "assembler", "reference": capabilities.get("assembler_image", ""), "image_id": ""})
    if any(not isinstance(t["reference"], str) or not _IMAGE.fullmatch(t["reference"]) for t in targets):
        raise RuntimeConflict("image_check_frozen_reference_invalid")
    return targets


def check_document(operation, node):
    targets = frozen_targets(operation, node)
    document = {"platform": node.platform, "targets": targets}
    capabilities = node.capabilities or {}
    if capabilities.get("insecure_registry") is True:
        repository = capabilities.get("image_repository", "")
        first = repository.split("/", 1)[0]
        authority = (
            first if "/" in repository and ("." in first or ":" in first or first == "localhost") else "index.docker.io"
        )
        document["insecure_registries"] = (
            [authority] if any(t["reference"].split("/", 1)[0] == authority for t in targets) else []
        )
    return document


def registry_sources(operation, node):
    sources = set()
    document = check_document(operation, node)
    for target in document["targets"]:
        repository = target["reference"].split("@", 1)[0]
        first = repository.split("/", 1)[0]
        authority = (
            first if "/" in repository and ("." in first or ":" in first or first == "localhost") else "index.docker.io"
        )
        if authority in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
            sources.update({"https://registry-1.docker.io:443", "https://auth.docker.io:443"})
        else:
            parsed = urlsplit("https://" + authority)
            scheme = "http" if authority in document.get("insecure_registries", []) else "https"
            sources.add(f"{scheme}://{parsed.hostname}:{parsed.port or (80 if scheme == 'http' else 443)}")
    endpoints = (node.capabilities or {}).get("image_registry_endpoints", [])
    if not isinstance(endpoints, list) or len(endpoints) > 32:
        raise RuntimeConflict("image_check_registry_endpoints_invalid")
    for endpoint in endpoints:
        try:
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError()
            sources.add(
                f"{parsed.scheme}://{parsed.hostname.lower()}:{parsed.port or (80 if parsed.scheme == 'http' else 443)}"
            )
        except (ValueError, TypeError):
            raise RuntimeConflict("image_check_registry_endpoints_invalid") from None
    return sorted(sources)
