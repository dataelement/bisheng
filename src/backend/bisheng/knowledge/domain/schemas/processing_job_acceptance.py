"""Shared processing acceptance values and the original pure canonical projections."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget


@dataclass(frozen=True)
class ProcessingConfiguration:
    model_config_revision: int
    index_generation: str | None
    metadata_schema_revision: int | None = None
    metadata_schema_digest: str | None = None

    def __post_init__(self):
        if type(self.model_config_revision) is not int or self.model_config_revision < 0:
            raise ValueError("model_config_revision must be a non-negative integer")
        if self.index_generation is not None and (
            not isinstance(self.index_generation, str) or not self.index_generation or len(self.index_generation) > 64
        ):
            raise ValueError("index_generation must be a nonempty stable identifier")
        if self.metadata_schema_revision is None and self.metadata_schema_digest is None:
            return
        if (
            type(self.metadata_schema_revision) is not int
            or self.metadata_schema_revision < 0
            or not isinstance(self.metadata_schema_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.metadata_schema_digest) is None
        ):
            raise ValueError("metadata schema evidence requires a non-negative revision and canonical digest")


@dataclass(frozen=True)
class NewProcessingItem:
    target: ResourceVersionTarget
    expected_space_id: int
    expected_parent_id: int | None = None
    processing_snapshot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobRequestResult:
    job: KnowledgeProcessingJob
    reused: bool


@dataclass(frozen=True)
class JobLease:
    job_id: str
    lease_token: str
    claim_generation: int
    lease_until: datetime


@dataclass(frozen=True)
class ItemLease:
    job: JobLease
    item_id: str
    lease_token: str
    claim_generation: int
    lease_until: datetime


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def processing_manifest(space_id: int, items: Sequence[NewProcessingItem]) -> list[dict]:
    """Validate, freeze and order the original complete item acceptance scope."""
    manifest = []
    for value in items:
        target = ResourceVersionTarget.model_validate(value.target.model_dump(mode="json"))
        if value.expected_space_id != space_id:
            raise ValueError("item scope does not match the owning space")
        manifest.append(
            {
                **target.model_dump(mode="json"),
                "expected_space_id": value.expected_space_id,
                "expected_parent_id": value.expected_parent_id,
                "processing_snapshot": deepcopy(dict(value.processing_snapshot)),
            }
        )
    manifest.sort(key=lambda value: (value["file_id"], value["version_id"], value["document_id"]))
    if len({(value["file_id"], value["version_id"]) for value in manifest}) != len(manifest):
        raise ValueError("duplicate file/version scope")
    return manifest


def processing_request_facts(
    *,
    tenant_id: int,
    space_id: int,
    kind: str,
    actor_user_id: int,
    actor_reference: Mapping[str, Any],
    parameters: Mapping[str, Any],
    manifest: list[dict],
    configuration: ProcessingConfiguration,
    space_config_version: int,
) -> dict:
    """Project prepared acceptance values without copying their large payloads."""
    request_facts = {
        "tenant_id": tenant_id,
        "space_id": space_id,
        "kind": kind,
        "actor_user_id": actor_user_id,
        "actor_reference": actor_reference,
        "parameters": parameters,
        "scope_manifest": manifest,
        "model_config_revision": configuration.model_config_revision,
        "index_generation": configuration.index_generation,
        "space_config_version": space_config_version,
    }
    if kind == "metadata_schema_change":
        request_facts.update(
            metadata_schema_revision=configuration.metadata_schema_revision,
            metadata_schema_digest=configuration.metadata_schema_digest,
        )
    return request_facts
