"""Extract all saved channel selections, including disabled automation."""

import hashlib
from collections.abc import Iterable, Mapping

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    normalize_references,
)
from bisheng.resource_reference.application.source_contracts import canonical_payload_json

CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION = "channel-sync-v1"


def channel_sync_scope(name: str | None) -> str:
    """Match the actual router's exact name semantics, never display ordering."""
    if name is not None and not isinstance(name, str):
        raise TypeError("channel sync rule name must be text")
    if not name:
        return "main"
    digest = hashlib.sha256(canonical_payload_json({"name": name}).encode("utf-8")).hexdigest()
    return f"sub.{digest}"


def extract_channel_sync_references(rows: Iterable[Mapping[str, object]]) -> tuple[ReferenceSpec, ...]:
    """Row UUIDs, enable flags and user IDs are not reference identities.

    The configuration contains separate space and optional folder targets.
    A populated malformed folder is an error, not the space root sentinel.
    """
    references = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("channel sync extraction requires complete row facts")
        scope = channel_sync_scope(row.get("sub_channel_name"))
        references.append(
            ReferenceSpec(f"{scope}.space", TargetKey(TargetType.KNOWLEDGE_SPACE, row["knowledge_space_id"]))
        )
        if row.get("folder_id") is not None:
            references.append(ReferenceSpec(f"{scope}.folder", TargetKey(TargetType.KNOWLEDGE_FILE, row["folder_id"])))
    return normalize_references(tuple(references))
