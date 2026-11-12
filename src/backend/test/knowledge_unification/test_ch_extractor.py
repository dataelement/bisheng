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


@pytest.mark.parametrize("space", [None, "", "missing", "0", "-1", True, "\u0661\u0660", [], 1.5])
def test_invalid_space_ids_are_not_silently_dropped(space):
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(space)])


@pytest.mark.parametrize("folder", ["", "missing", "0", "-1", True, "\u0661\u0660", [], 1.5])
def test_populated_invalid_folder_cannot_fall_back_to_root(folder):
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(folder=folder)])


def test_invalid_rule_shape_is_not_reinterpreted_as_main():
    with pytest.raises((TypeError, ValueError)):
        extract_channel_sync_references([row(name=123)])


def test_legacy_picker_placeholder_is_read_only_and_keeps_other_references():
    legacy = row(folder="new-folder-1730000000000", enabled=False)
    values = [legacy, row("11", folder="20")]
    references = extract_channel_sync_references(values, skip_legacy_folders=True)
    assert {(ref.slot_key, ref.target.target_id) for ref in references} == {
        ("main.space", "10"),
        ("main.space", "11"),
        ("main.folder", "20"),
    }
    assert legacy["folder_id"] == "new-folder-1730000000000"
    with pytest.raises(ValueError):
        extract_channel_sync_references(values)


@pytest.mark.parametrize("folder", ["missing", "new-folder-", "new-folder-x", "new-folder-123/4", "0", "-1", ""])
def test_legacy_skip_does_not_accept_other_malformed_bindings(folder):
    with pytest.raises(ValueError):
        extract_channel_sync_references([row(folder=folder)], skip_legacy_folders=True)


def test_legacy_folder_does_not_skip_invalid_parent_space():
    with pytest.raises(ValueError):
        extract_channel_sync_references([row("missing", folder="new-folder-123")], skip_legacy_folders=True)
