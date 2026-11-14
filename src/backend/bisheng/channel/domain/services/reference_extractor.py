"""Extract all saved channel selections, including disabled automation."""

import hashlib
import re
from collections.abc import Iterable, Mapping

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    normalize_references,
)
from bisheng.resource_reference.application.source_contracts import canonical_payload_json

CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION = "channel-sync-v1"


def is_legacy_channel_folder_id(value: object) -> bool:
    """Recognize only the old picker placeholder, never an actual folder ID."""
    return isinstance(value, str) and re.fullmatch(r"new-folder-[0-9]{1,20}", value) is not None


def channel_sync_scope(name: str | None) -> str:
    """Match the actual router's exact name semantics, never display ordering."""
    if name is not None and not isinstance(name, str):
        raise TypeError("channel sync rule name must be text")
    if not name:
        return "main"
    digest = hashlib.sha256(canonical_payload_json({"name": name}).encode("utf-8")).hexdigest()
    return f"sub.{digest}"


def extract_channel_sync_references(
    rows: Iterable[Mapping[str, object]], *, skip_legacy_folders: bool = False
) -> tuple[ReferenceSpec, ...]:
    """Row UUIDs, enable flags and user IDs are not reference identities.

    The configuration contains separate space and optional folder targets.
    Existing snapshots may retain the old picker's placeholder without a folder
    reference. The original payload remains unchanged; new selections stay strict.
    """
    references = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("channel sync extraction requires complete row facts")
        scope = channel_sync_scope(row.get("sub_channel_name"))
        references.append(
            ReferenceSpec(f"{scope}.space", TargetKey(TargetType.KNOWLEDGE_SPACE, row["knowledge_space_id"]))
        )
        folder_id = row.get("folder_id")
        if folder_id is not None and not (skip_legacy_folders and is_legacy_channel_folder_id(folder_id)):
            references.append(ReferenceSpec(f"{scope}.folder", TargetKey(TargetType.KNOWLEDGE_FILE, folder_id)))
    return normalize_references(tuple(references))
