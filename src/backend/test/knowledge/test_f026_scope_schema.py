"""F026 T041: the task-version scope contract.

A task version freezes the material scope the user actually chose: the selected
knowledge ids *and* the per-space fixed tag references. Two states the wire
format used to conflate must stay apart after a round trip through the request
and the task record:

* ``None``  — the scope was never recorded (a task/round created before the
  field existed, or a legacy client). It must never be read as "the whole
  space"; the caller has to ask for a new range.
* ``{}``    — the user explicitly pinned no tag, so the selected spaces are
  searched without a tag condition.

The fixed references travel as ``{space_id: tag_ref_id}`` and are validated
against the selected spaces so a stale/foreign reference cannot widen a scope.
"""

import pytest
from pydantic import ValidationError

from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.workstation.domain.schemas.chat import UseKnowledgeBaseParam


def _submit(**kwargs) -> LinsightQuestionSubmitSchema:
    return LinsightQuestionSubmitSchema(question="q", **kwargs)


def test_round_trip_keeps_fixed_tag_refs():
    submit = _submit(knowledge_space_ids=[7], knowledge_space_tag_filters={"7": 11})
    assert submit.knowledge_space_tag_filters == {7: 11}

    dumped = submit.model_dump(mode="json")
    assert dumped["knowledge_space_tag_filters"] == {"7": 11}
    rehydrated = LinsightQuestionSubmitSchema.model_validate(dumped)
    assert rehydrated.knowledge_space_tag_filters == submit.knowledge_space_tag_filters
    assert rehydrated.fixed_tag_refs == {7: 11}


def test_unrecorded_and_unspecified_scopes_stay_distinct():
    unrecorded = _submit(knowledge_space_ids=[7])
    unspecified = _submit(knowledge_space_ids=[7], knowledge_space_tag_filters={})
    pinned = _submit(knowledge_space_ids=[7], knowledge_space_tag_filters={7: 11})

    assert unrecorded.knowledge_space_tag_filters is None
    assert unrecorded.scope_state == "unrecorded"
    assert unrecorded.tag_scope_recorded is False

    assert unspecified.knowledge_space_tag_filters == {}
    assert unspecified.scope_state == "unspecified"
    assert unspecified.tag_scope_recorded is True

    assert pinned.scope_state == "fixed"
    assert pinned.tag_scope_recorded is True


def test_fixed_refs_are_looked_up_per_space_and_never_widened():
    pinned = _submit(knowledge_space_ids=[7, 8], knowledge_space_tag_filters={7: 11})
    assert pinned.tag_ref_for(7) == 11
    assert pinned.tag_ref_for(8) is None
    assert pinned.fixed_tag_refs == {7: 11}

    # A missing record exposes no reference at all — an empty mapping here is
    # "no tag condition", never "search everything".
    unrecorded = _submit(knowledge_space_ids=[7])
    assert unrecorded.fixed_tag_refs == {}
    assert unrecorded.tag_ref_for(7) is None


@pytest.mark.parametrize(
    "filters",
    [
        {8: 11},  # space not selected
        {7: 0},
        {7: -1},
        {7: True},
        {0: 11},
        {7: 1.5},
        {7.0: 11},
        {"7.0": 11},
        "not-a-mapping",
    ],
)
def test_rejects_tag_refs_outside_the_selected_spaces(filters):
    with pytest.raises(ValidationError):
        _submit(knowledge_space_ids=[7], knowledge_space_tag_filters=filters)


def test_rejects_tag_refs_without_any_selected_space():
    with pytest.raises(ValidationError):
        _submit(knowledge_space_tag_filters={7: 11})


def test_daily_request_reports_whether_it_declared_tags():
    declared = UseKnowledgeBaseParam.model_validate({"knowledge_space_ids": [7], "knowledge_space_tag_filters": {}})
    legacy = UseKnowledgeBaseParam.model_validate({"knowledge_space_ids": [7]})

    assert declared.tag_scope_recorded is True
    assert legacy.tag_scope_recorded is False
    # Old readers keep the historical dict shape, so the marker never changes
    # what a legacy client (or an older call site) receives.
    assert legacy.knowledge_space_tag_filters == {}
    assert UseKnowledgeBaseParam().knowledge_space_tag_filters == {}