"""T667 / AC-51: a loaded authorized space has one processing-state gate."""

from copy import deepcopy

import pytest

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle


@pytest.mark.parametrize(
    "state,transition",
    [
        (KnowledgeState.REBUILDING.value, None),
        (KnowledgeState.UNPUBLISHED.value, {"operation_id": "pending"}),
        (KnowledgeState.PUBLISHED.value, {"operation_id": "pending"}),
        (KnowledgeState.FAILED.value, {"operation_id": "pending"}),
        # A present, malformed pending slot cannot masquerade as no transition.
        (KnowledgeState.PUBLISHED.value, {}),
    ],
)
def test_rebuilding_or_present_transition_is_explicit_conflict_without_mutation(state, transition):
    space = Knowledge(id=19, tenant_id=101, user_id=7, name="space", type=3, state=state, model_transition=transition)
    before = deepcopy(space.model_dump())
    with pytest.raises(KnowledgeProcessingConflictError) as failure:
        require_space_processing_idle(space, operation="upload_file")
    assert failure.value.Code == 10999
    assert space.model_dump() == before


@pytest.mark.parametrize(
    "state",
    [
        KnowledgeState.UNPUBLISHED.value,
        KnowledgeState.PUBLISHED.value,
        KnowledgeState.COPYING.value,
        KnowledgeState.FAILED.value,
        -1,
    ],
)
def test_other_lifecycle_decisions_remain_with_the_existing_business_use_case(state):
    space = Knowledge(id=19, tenant_id=101, user_id=7, name="space", type=3, state=state)
    before = deepcopy(space.model_dump())
    assert require_space_processing_idle(space, operation="move_items") is None
    assert space.model_dump() == before
