import asyncio
from dataclasses import replace

import pytest
from loguru import logger

from bisheng.common.errcode.permission import PermissionProjectionFailedError
from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationError, GrantChange
from test.workflow.kunlian_workflow_authorization_fixtures import WORKFLOW, PermissionFixture

CHANGE = GrantChange(3, 12, subject_ref="member-b", model_key="viewer")


async def test_finalized_original_receipt_survives_projection_error_and_new_revision():
    fixture = PermissionFixture()

    async def lost_projection_reply(key):
        fixture.operations[key] = ("COMMITTED", fixture.revision)
        raise PermissionProjectionFailedError(msg="private projection error")

    fixture.after_change = lost_projection_reply
    subject = fixture.subject()
    first = await fixture.service().change(subject, WORKFLOW, CHANGE, "request-secret-value")
    assert first == {"operation_ref": first["operation_ref"], "status": "PENDING"}
    (internal_key,) = fixture.operations
    fixture.operations[internal_key] = ("FINALIZED", 4)
    fixture.revision = 5

    logs = []
    sink = logger.add(lambda message: logs.append(str(message)))
    try:
        confirmed = await fixture.service().change(subject, WORKFLOW, CHANGE, "request-secret-value")
    finally:
        logger.remove(sink)
    assert confirmed == {"operation_ref": first["operation_ref"], "status": "APPLIED", "applied_resource_version": 4}
    assert fixture.mutations == 1 and len(internal_key) == 64
    assert any(first["operation_ref"] in entry and WORKFLOW in entry for entry in logs)
    assert all("request-secret-value" not in entry and "private projection error" not in entry for entry in logs)
    fixture.managers.clear()
    with pytest.raises(AuthorizationError, match="NOT_FOUND"):
        await fixture.service().change(subject, WORKFLOW, CHANGE, "request-secret-value")


async def test_concurrent_same_key_and_changed_requests_are_not_dispatched_twice():
    fixture = PermissionFixture()
    entered, release = asyncio.Event(), asyncio.Event()
    original = fixture.mutate_grants

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return await original(**kwargs)

    fixture.mutate_grants = delayed
    service, subject = fixture.service(), fixture.subject()
    operation = asyncio.create_task(service.change(subject, WORKFLOW, CHANGE, "original"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (await service.change(subject, WORKFLOW, CHANGE, "original"))["status"] == "PENDING"
        with pytest.raises(AuthorizationError, match="IDEMPOTENCY_CONFLICT"):
            await service.change(subject, WORKFLOW, replace(CHANGE, model_key="another"), "original")
    finally:
        release.set()
        applied = await asyncio.wait_for(operation, 2)
    assert await service.change(subject, WORKFLOW, CHANGE, "original") == applied
    with pytest.raises(AuthorizationError, match="REVISION_CONFLICT"):
        await service.change(subject, WORKFLOW, CHANGE, "different")
    assert fixture.mutations == 1


async def test_two_different_keys_on_same_revision_only_apply_one_mutation():
    fixture = PermissionFixture()
    gate = asyncio.Barrier(2)
    original = fixture.mutate_grants

    async def delayed(**kwargs):
        await gate.wait()
        return await original(**kwargs)

    fixture.mutate_grants = delayed
    service, subject = fixture.service(), fixture.subject()
    results = await asyncio.wait_for(
        asyncio.gather(
            service.change(subject, WORKFLOW, CHANGE, "first"),
            service.change(subject, WORKFLOW, CHANGE, "second"),
            return_exceptions=True,
        ),
        2,
    )
    assert [result["status"] for result in results if isinstance(result, dict)] == ["APPLIED"]
    assert [str(result) for result in results if isinstance(result, AuthorizationError)] == ["REVISION_CONFLICT"]
    assert fixture.mutations == 1 and fixture.revision == 4
