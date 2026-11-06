"""Channel semantic slots survive replacement, reordering and disabled sync.

覆盖 AC: AC-71, AC-87, AC-88, AC-91, AC-92.
"""

import hashlib

import pytest

from bisheng.channel.domain.services.reference_extractor import (
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    extract_channel_sync_references,
)
from bisheng.resource_reference.application.source_contracts import canonical_payload_json


def row(space="10", folder=None, name=None, enabled=True, **extra):
    return {"knowledge_space_id": space, "folder_id": folder, "sub_channel_name": name, "is_enabled": enabled, **extra}


def refs(rows):
    return {
        (ref.slot_key, ref.target.target_type.value, ref.target.target_id)
        for ref in extract_channel_sync_references(rows)
    }


def test_disabled_main_and_sub_keep_space_and_folder_and_ignore_recreated_row_ids():
    source = [row(folder="20", enabled=False, id="old"), row("11", name="日报", enabled=False)]
    digest = hashlib.sha256(canonical_payload_json({"name": "日报"}).encode()).hexdigest()
    assert refs(source) == {
        ("main.space", "knowledge_space", "10"),
        ("main.folder", "knowledge_file", "20"),
        (f"sub.{digest}.space", "knowledge_space", "11"),
    }
    assert refs([{**value, "id": "new", "user_id": 99} for value in reversed(source)]) == refs(source)
    assert CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION == "channel-sync-v1"


def test_multiselect_deduplicates_same_slot_target_without_collapsing_different_scopes():
    values = [row(), row("010"), row("11"), row(name="sub"), row(folder="20")]
    assert len(refs(values)) == 4
    assert refs([]) == set()


def test_rule_names_use_exact_runtime_matching_without_trim_or_casefold():
    values = refs([row(name="news"), row(name=" news"), row(name="NEWS"), row(name="news ")])
    assert len(values) == 4
    assert all(slot.startswith("sub.") and len(slot) < 192 for slot, _, _ in values)


@pytest.mark.parametrize("space", [None, "", "missing", "0", "-1", True, "١٠", [], 1.5])
def test_invalid_space_ids_are_not_silently_dropped(space):
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(space)])


@pytest.mark.parametrize("folder", ["", "missing", "0", "-1", True, "١٠", [], 1.5])
def test_populated_invalid_folder_cannot_fall_back_to_root(folder):
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(folder=folder)])


def test_invalid_rule_shape_is_not_reinterpreted_as_main():
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(name=123)])
