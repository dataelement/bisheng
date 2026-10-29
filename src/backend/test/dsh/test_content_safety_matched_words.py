"""Coverage AC: AC-66. Frozen rule-word snapshots, legacy facts and bounded metadata."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from bisheng.common.errcode.dsh import DshContentSafetyConflictError
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.repositories import content_safety_projection
from bisheng.dsh.domain.repositories.content_safety_queries import event_metadata
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent
from test.dsh.test_content_safety_merge import committed_merge
from test.dsh.test_content_safety_repository import tenant_session


def test_legacy_event_has_unknown_words(content_safety_event):
    assert ContentSafetyEvent.model_validate(content_safety_event()).matched_words is None


@pytest.mark.parametrize("word", ["synthetic-rule", "<img src=x onerror=synthetic>", "😀" * 256])
def test_rule_word_snapshot_round_trips_without_original_context(content_safety_event, content_safety_engine, word):
    raw = content_safety_event(matched_words={"input": [word], "output": []})
    event = ContentSafetyEvent.model_validate(raw)
    assert event.matched_words.input == (word,)
    fact, audit, _ = committed_merge(content_safety_engine, content_safety_projection, raw)
    assert audit.has_sensitive_hit
    with tenant_session(content_safety_engine) as session:
        stored = session.scalars(select(DshContentSafetyEvent)).one()
        assert event_metadata(stored)["matched_words"] == {"input": [word], "output": []}
        assert stored.matched_words == raw["matched_words"]
    repeated, _, duplicate = committed_merge(content_safety_engine, content_safety_projection, raw)
    assert duplicate and repeated.id == fact.id


@pytest.mark.parametrize(
    "words",
    [
        {"input": [""], "output": []},
        {"input": [" "], "output": []},
        {"input": ["x" * 257], "output": []},
        {"input": [chr(0xD800)], "output": []},
        {"input": ["x", "x"], "output": []},
        {"input": [str(i) for i in range(21)], "output": []},
        {"input": [123], "output": []},
        {"input": ["x"], "output": [], "raw_text": "forged"},
        {"input": ["x"]},
        {"input": [], "output": ["x"]},
    ],
)
def test_invalid_or_wrong_direction_snapshots_are_rejected(content_safety_event, words):
    with pytest.raises(ValidationError):
        ContentSafetyEvent.model_validate(content_safety_event(matched_words=words))


def test_word_budget_is_shared_across_directions(content_safety_event):
    raw = content_safety_event(
        matched_words={"input": [str(i) for i in range(11)], "output": [str(i) for i in range(10)]},
        stage_results={"input": "BLOCKED", "output": "BLOCKED"},
    )
    with pytest.raises(ValidationError):
        ContentSafetyEvent.model_validate(raw)


def test_legacy_and_new_facts_remain_distinct_and_legacy_metadata_is_null(content_safety_event, content_safety_engine):
    raw = content_safety_event()
    fact, _, _ = committed_merge(content_safety_engine, content_safety_projection, raw)
    assert event_metadata(fact)["matched_words"] is None
    changed = deepcopy(raw)
    changed["matched_words"] = {"input": ["synthetic-rule"], "output": []}
    with pytest.raises(DshContentSafetyConflictError):
        committed_merge(content_safety_engine, content_safety_projection, changed)
