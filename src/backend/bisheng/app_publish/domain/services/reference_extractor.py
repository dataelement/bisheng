"""Pure APP declaration slots; SQL resolution belongs to its application Owner."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    canonical_target_id,
    normalize_references,
)

APP_REFERENCE_EXTRACTOR_VERSION = "hosted-app-v1"


@dataclass(frozen=True, slots=True)
class AppReferenceRequest:
    slot_key: str
    target_type: TargetType
    requested_name: str | None = None
    target_id: str | None = None


def _slot(kind: str, value: str) -> str:
    return f"capabilities.{kind}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def extract_app_reference_requests(declaration: CapabilityDeclaration) -> tuple[AppReferenceRequest, ...]:
    """Keep exact model names and legacy numeric-ID-first knowledge semantics.

    Neither this function nor the resolver writes the immutable declaration.
    Reordered or duplicate declarations retain the same semantic source slot.
    An unreadable selection is an error, never an empty ready reference set.
    """
    if not isinstance(declaration, CapabilityDeclaration):
        raise TypeError("APP references require a validated CapabilityDeclaration")
    requests = set()
    for model in declaration.models:
        requests.add(AppReferenceRequest(_slot("model", model.name), TargetType.MODEL, requested_name=model.name))
    for knowledge in declaration.knowledge_bases:
        selected_id = (knowledge.id or "").strip()
        if selected_id.isascii() and selected_id.isdecimal():
            target_id = canonical_target_id(selected_id)
            requests.add(
                AppReferenceRequest(_slot("knowledge.id", target_id), TargetType.KNOWLEDGE_SPACE, target_id=target_id)
            )
        else:
            name = (knowledge.name or "").strip()
            if not name:
                raise ValueError("knowledge declaration has no resolvable ID or name")
            requests.add(
                AppReferenceRequest(_slot("knowledge.name", name), TargetType.KNOWLEDGE_SPACE, requested_name=name)
            )
    return tuple(sorted(requests, key=lambda request: request.slot_key))


def extract_app_references(
    declaration: CapabilityDeclaration, *, resolved_targets: Mapping[str, TargetKey]
) -> tuple[ReferenceSpec, ...]:
    """Consume one complete Owner-resolved map, never infer a replacement ID."""
    requests = extract_app_reference_requests(declaration)
    if set(resolved_targets) != {request.slot_key for request in requests}:
        raise ValueError("APP reference resolution must be complete")
    references = []
    for request in requests:
        target = resolved_targets[request.slot_key]
        if not isinstance(target, TargetKey) or target.target_type != request.target_type:
            raise ValueError("APP resolved resource type differs from its declaration")
        if request.target_id is not None and target.target_id != request.target_id:
            raise ValueError("APP resolved identity differs from its explicit ID")
        references.append(ReferenceSpec(request.slot_key, target))
    return normalize_references(tuple(references))
