"""Native FGA stream order never changes a new frozen inventory identity."""

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_tuple_sort import stable_original_tuples
from bisheng.permission.application.migration_read import OriginalTupleFact


async def stream(values):
    for value in values:
        yield value


async def test_stable_disk_order_across_batches_and_source_order():
    values = [OriginalTupleFact(f"user:{index:04d}", "viewer", f"knowledge_file:{index}") for index in range(601)]
    shuffled = values[200:400][::-1] + values[400:][::-1] + values[:200][::-1]
    result = [value async for value in stable_original_tuples(stream(shuffled), current=lambda: None)]
    assert result == values


async def test_duplicate_in_different_batch_is_rejected():
    values = [OriginalTupleFact(f"user:{index}", "viewer", "knowledge_file:1") for index in range(201)]
    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        _ = [value async for value in stable_original_tuples(stream([*values, values[0]]), current=lambda: None)]
    assert error.value.kwargs["reason"] == "migration_inventory_duplicate_original_tuple"
