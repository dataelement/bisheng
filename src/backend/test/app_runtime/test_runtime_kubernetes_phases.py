"""覆盖 AC: AC-08、AC-15、AC-33、AC-35、AC-48、AC-49、AC-50. Sequential writer evidence."""

import pytest

from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_kubernetes_repository import (
    NOW,
    UID,
    bind,
    evidence,
    leased,
    repo,  # noqa: F401 -- share the real SQL transaction fixture
    resource,
    setup_operation,
)


async def stopped(repository, row):
    await bind(repository, row)
    await repository.request_resource_stop(
        row.id, operation_id=row.operation_id, holder_id="controller-a", controller_epoch=1, now=NOW
    )
    await repository.confirm_resource_stop(row.id, evidence(), holder_id="controller-a", controller_epoch=1, now=NOW)


async def create(repository, row):
    return await repository.create_resource_intent(row, holder_id="controller-a", controller_epoch=1, now=NOW)


async def test_fixed_name_can_advance_after_stop_and_cleanup(repo):  # noqa: F811
    op = await setup_operation(repo)
    await leased(repo)
    first = await create(repo, resource(op, purpose="migrate"))
    await stopped(repo, first)
    await repo.complete_resource_cleanup(first.id, uid=UID, holder_id="controller-a", controller_epoch=1, now=NOW)
    second = await create(repo, resource(op, purpose="serve"))
    assert second.id != first.id and second.uid is None
    history = await repo.find(RuntimeExecutionResource, operation_id=op.id, kind="Pod")
    assert len(history) == 2
    assert (await repo.get(RuntimeExecutionResource, first.id)).uid == UID
    again = await create(repo, RuntimeExecutionResource(**second.model_dump()))
    assert again.id == second.id


@pytest.mark.parametrize("stop", [False, True])
async def test_fixed_name_refuses_unfinished_previous_writer(repo, stop):  # noqa: F811
    op = await setup_operation(repo)
    await leased(repo)
    first = await create(repo, resource(op, purpose="migrate"))
    if stop:
        await stopped(repo, first)
    with pytest.raises(RuntimeConflict, match="production_writer"):
        await create(repo, resource(op, purpose="serve"))


async def test_original_ref_cannot_change_frozen_phase(repo):  # noqa: F811
    op = await setup_operation(repo)
    await leased(repo)
    first = await create(repo, resource(op, purpose="migrate"))
    other = RuntimeExecutionResource(**{**first.model_dump(), "purpose": "serve"})
    with pytest.raises(RuntimeConflict, match="intent_conflict"):
        await create(repo, other)
