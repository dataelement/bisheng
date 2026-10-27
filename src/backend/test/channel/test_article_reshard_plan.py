"""AC-18, AC-19, AC-20, AC-22, AC-23, AC-24: migration policy and full-content basis."""

import pytest

from scripts.article_reshard_plan import MigrationError, copy_settings, document_fingerprint, safe_index_name


def test_copy_preserves_business_policy_but_not_index_generated_fields():
    source = {
        "uuid": "old",
        "number_of_shards": "1",
        "number_of_replicas": "2",
        "number_of_routing_shards": "1024",
        "analysis": {"analyzer": {"mine": {"type": "standard"}}},
        "default_pipeline": "transform",
        "blocks": {"write": "true"},
    }
    target = copy_settings(source, 3)
    assert target["number_of_shards"] == 3 and target["number_of_replicas"] == "2"
    assert target["analysis"] == source["analysis"] and target["default_pipeline"] == "_none"
    assert "uuid" not in target and "blocks" not in target and "number_of_routing_shards" not in target
    assert source["uuid"] == "old"
    with pytest.raises(MigrationError):
        copy_settings({"routing_partition_size": "3"}, 3)


def test_fingerprint_is_order_independent_and_includes_identity_routing_and_all_source():
    hits = [{"_id": "1", "_routing": "x", "_source": {"text": "first"}}, {"_id": "2", "_source": {"text": "second"}}]
    basis = document_fingerprint(hits)
    assert basis == document_fingerprint(reversed(hits))
    assert basis != document_fingerprint([hits[0]])
    assert basis != document_fingerprint([hits[0] | {"_routing": "y"}, hits[1]])
    assert basis != document_fingerprint([hits[0] | {"_source": {"text": "changed"}}, hits[1]])


def test_index_names_are_deterministic_and_safe():
    assert safe_index_name("backup", "ABC_uuid+X") == safe_index_name("backup", "ABC_uuid+X")
    assert "ABC" not in safe_index_name("backup", "ABC_uuid+X")
