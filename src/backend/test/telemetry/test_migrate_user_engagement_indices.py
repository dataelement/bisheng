"""Pure-logic tests for scripts/migrate_user_engagement_indices.py's per-document
transform (id-prefixing + metric_source tagging). No ES connection needed."""

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "migrate_user_engagement_indices.py"
_spec = importlib.util.spec_from_file_location("migrate_user_engagement_indices", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)


def test_increment_id_gets_prefixed():
    assert _module._new_doc_id("increment", "user_42") == "increment_user_42"


def test_active_user_id_gets_prefixed():
    assert _module._new_doc_id("active_user", "42_2026-08-31") == "active_42_2026-08-31"


def test_participation_id_kept_unchanged():
    """Already source-scoped by the live writer (participation_{tenant}_{date}_{user})."""
    old_id = "participation_1_2026-08-31_42"
    assert _module._new_doc_id("participation", old_id) == old_id


def test_transform_hit_tags_metric_source_and_targets_shared_index():
    hit = {"_id": "user_42", "_source": {"user_id": 42, "user_name": "张三"}}

    action = _module._transform_hit(hit, "increment")

    assert action["_index"] == _module.USER_ENGAGEMENT_ES_INDEX
    assert action["_id"] == "increment_user_42"
    assert action["_source"]["metric_source"] == "increment"
    assert action["_source"]["user_id"] == 42


def test_transform_hit_does_not_mutate_the_original_hit():
    hit = {"_id": "user_42", "_source": {"user_id": 42}}

    _module._transform_hit(hit, "increment")

    assert "metric_source" not in hit["_source"]
