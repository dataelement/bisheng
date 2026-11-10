from dataclasses import replace
from secrets import token_bytes

import pytest

from bisheng.common.errcode.flow import WorkflowRegistrationCursorExpired
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.application.kunlian_registration_sync import RegistrationSync
from bisheng.workflow.domain.models.kunlian_registration import KunlianWorkflowChange, KunlianWorkflowStream
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationReceipt
from bisheng.workflow.domain.services.kunlian_registration_cursor import RegistrationCursor
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, publish, seed


def test_cursor_rejects_tampering_and_different_scope():
    codec = RegistrationCursor(token_bytes(32))
    cursor = codec.issue(SCOPE, "checkpoint", position=4)
    assert codec.read(SCOPE, "checkpoint", cursor)["position"] == 4
    for scope, token in (
        (SCOPE, cursor + "a"),
        (replace(SCOPE, tenant_id=8), cursor),
        (replace(SCOPE, generation=2), cursor),
    ):
        with pytest.raises(WorkflowRegistrationCursorExpired):
            codec.read(scope, "checkpoint", token)


def test_window_resume_and_stale_receipts(registration_store):
    repo = registration_store
    seed(repo)
    sync = RegistrationSync(repo, SCOPE, RegistrationCursor(token_bytes(32)), lambda _: True)
    snapshot = sync.snapshot()
    publish(repo, 1)
    publish(repo, 2)
    page = sync.changes(cursor=snapshot["base_cursor"], limit=1)
    assert page["items"][0]["sequence"] == 1 and page["page_token"]
    repo.unpublish(SCOPE, FLOW_ID, 2)
    last = sync.changes(page_token=page["page_token"])
    assert [row["sequence"] for row in last["items"]] == [2]
    assert [row["sequence"] for row in sync.changes(cursor=last["next_cursor"])["items"]] == [3]
    assert (
        sync.receipt(RegistrationReceipt(workflow_id=FLOW_ID, workflow_version_id="2", sequence=2, status="REGISTERED"))
        is False
    )
    receipt = RegistrationReceipt(workflow_id=FLOW_ID, workflow_version_id="2", sequence=3, status="REMOVED")
    assert sync.receipt(receipt) is True
    assert sync.receipt(receipt) is True
    assert sync.receipt(receipt.model_copy(update={"status": "FAILED"})) is False
    assert repo.status(SCOPE, FLOW_ID)["status"] == "REMOVED"


def test_snapshot_recovers_a_concurrent_withdrawal_and_expired_checkpoint(registration_store):
    repo = registration_store
    other = "g" * 32
    seed(repo, versions=(1,))
    seed(repo, workflow_id=other, versions=(2,))
    publish(repo, 1)
    publish(repo, 2, workflow_id=other)
    sync = RegistrationSync(repo, SCOPE, RegistrationCursor(token_bytes(32)), lambda _: True)
    first = sync.snapshot(limit=1)
    assert first["base"] == 2 and first["page_token"]
    repo.unpublish(SCOPE, other, 2)
    last = sync.snapshot(page_token=first["page_token"], limit=1)
    assert last["base"] == first["base"] and not last["items"]
    assert sync.changes(cursor=last["base_cursor"])["items"][0]["workflow_id"] == other
    with repo.transaction() as session:
        session.get(KunlianWorkflowStream, (SCOPE.tenant_id, SCOPE.connection_id)).retained_after = 3
    with pytest.raises(WorkflowRegistrationCursorExpired):
        sync.changes(cursor=last["base_cursor"])


@pytest.mark.parametrize("kind", ["snapshot", "changes"])
def test_paging_cannot_extend_the_original_scan_or_window(registration_store, kind):
    repo = registration_store
    now = 1000
    codec = RegistrationCursor(token_bytes(32), clock=lambda: now)
    sync = RegistrationSync(repo, SCOPE, codec, lambda _: True)
    checkpoint = sync.snapshot()["base_cursor"]
    for version, workflow_id in enumerate((FLOW_ID, "g" * 32, "h" * 32), start=1):
        seed(repo, workflow_id=workflow_id, versions=(version,))
        publish(repo, version, workflow_id=workflow_id)

    read = getattr(sync, kind)
    initial_args = {"cursor": checkpoint} if kind == "changes" else {}
    first = read(limit=1, **initial_args)
    now += 299
    second = read(page_token=first["page_token"], limit=1)
    assert second["page_token"]
    now += 1
    with pytest.raises(WorkflowRegistrationCursorExpired):
        read(page_token=second["page_token"], limit=1)

    if kind == "changes":
        assert [row["sequence"] for row in read(cursor=second["next_cursor"])["items"]] == [3]


def test_change_window_refuses_to_advance_over_missing_event(registration_store):
    repo = registration_store
    seed(repo)
    sync = RegistrationSync(repo, SCOPE, RegistrationCursor(token_bytes(32)), lambda _: True)
    checkpoint = sync.snapshot()["base_cursor"]
    publish(repo, 1)
    publish(repo, 2)
    with repo.transaction() as session:
        session.delete(session.get(KunlianWorkflowChange, (SCOPE.tenant_id, SCOPE.connection_id, 1)))

    with pytest.raises(WorkflowRegistrationCursorExpired):
        sync.changes(cursor=checkpoint)


@pytest.mark.parametrize("drift", [{"is_current": 0}, {"is_delete": 1}])
def test_catalog_and_receipt_require_the_same_live_published_version(registration_store, drift):
    repo = registration_store
    seed(repo)
    published = publish(repo, 1)
    sync = RegistrationSync(repo, SCOPE, RegistrationCursor(token_bytes(32)), lambda _: True)
    receipt = RegistrationReceipt(
        workflow_id=FLOW_ID, workflow_version_id="1", sequence=published["sequence"], status="REGISTERED"
    )
    assert sync.receipt(receipt.model_copy(update={"status": "FAILED"})) is True
    with repo.transaction() as session:
        version = session.get(FlowVersion, 1)
        for key, value in drift.items():
            setattr(version, key, value)

    assert sync.version(FLOW_ID, 1)["descriptor"] is None
    assert not sync.snapshot()["items"]
    assert sync.receipt(receipt) is False
    assert repo.status(SCOPE, FLOW_ID)["availability"] == "OFFLINE"

    with repo.transaction() as session:
        version = session.get(FlowVersion, 1)
        version.is_current, version.is_delete = 1, 0
    assert sync.receipt(receipt) is True
    assert repo.status(SCOPE, FLOW_ID)["status"] == "REGISTERED"
