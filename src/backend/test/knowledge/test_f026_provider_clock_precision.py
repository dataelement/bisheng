"""Scheduling clocks and the "pending means provably unsent" contract.

These two facts are coupled, and getting them wrong silently swallowed uploads:
`knowledge_provider_operation` / `knowledge_space_delete_job` deadlines live in
`DATETIME(0)` columns, and MySQL **rounds** fractional seconds on insert. A
timestamp taken at `.7s` therefore lands one second in the future, so an
operation created and claimed inside the same request looked "not due yet": the
claim returned None, the API answered `unknown`, and no byte ever reached
WeKnora. Nothing retries a `pending` upload (only provisioning kinds have a
sweeper), so the file stayed missing on the remote side forever.

`deletion_now()` already truncated microseconds for exactly this reason; the
provider-operation clocks had not. These tests pin the rule and the recovery
contract that follows from it.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.application import provider_upload_v1 as uploads
from bisheng.knowledge.application.provider_upload_item import _now as item_now
from bisheng.knowledge.domain.models.knowledge_space_delete_job import deletion_now
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op
from bisheng.knowledge.domain.models.provider_control import _now as control_now
from bisheng.worker.knowledge.provider_operations import utcnow

CLOCKS = {
    "provider_control._now": control_now,
    "provider_upload_item._now": item_now,
    "provider_operations.utcnow": utcnow,
    "deletion_now": deletion_now,
}


@pytest.mark.parametrize("name", sorted(CLOCKS))
def test_scheduling_clocks_have_no_sub_second_part(name):
    """A fractional value would be rounded up by the DATETIME(0) column."""
    for _ in range(20):
        assert CLOCKS[name]().microsecond == 0


@pytest.mark.parametrize("name", sorted(CLOCKS))
def test_clocks_are_naive_utc(name):
    value = CLOCKS[name]()
    assert value.tzinfo is None
    assert abs((datetime.now(UTC).replace(tzinfo=None) - value).total_seconds()) < 2


def test_a_freshly_written_deadline_is_never_ahead_of_the_writer():
    """`next_attempt_at` defaults are written before the claim reads the clock."""
    factory = Op.model_fields["next_attempt_at"].default_factory
    written = factory()
    assert written.microsecond == 0
    assert written <= item_now()
    assert written <= utcnow()


def test_operation_timestamps_are_second_precise():
    assert Op.model_fields["create_time"].default_factory().microsecond == 0


@asynccontextmanager
async def _session():
    yield None


def _service(owner=7):
    return SimpleNamespace(
        login_user=SimpleNamespace(user_id=owner, tenant_id=3),
        _permission_actor=AsyncMock(
            return_value=SimpleNamespace(current_tenant_id=3, subject_type="user", subject_id=owner)
        ),
        require_upload_container=AsyncMock(return_value=SimpleNamespace(tenant_id=3)),
    )


def _row(state, *, last_error_code=None):
    return SimpleNamespace(
        state=state,
        last_error_code=last_error_code,
        operation_id="op-1",
        target_manifest=[{"file_id": 12, "document_id": 5, "version_id": 9, "parent_id": None}],
    )


def _patch(monkeypatch, row):
    monkeypatch.setattr(uploads, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(uploads, "get_async_db_session", _session)
    monkeypatch.setattr(
        uploads.ProviderOperationRepository,
        "read_owned_upload",
        AsyncMock(return_value=row),
    )


@pytest.mark.parametrize(
    "state,last_error,expected",
    [
        # Never claimed: no byte was sent, so it is re-sendable, not "unknown".
        ("pending", None, "reupload_required"),
        ("sending", None, "unknown"),
        ("reconciling", None, "unknown"),
        ("succeeded", None, "accepted"),
        ("failed", "not_received", "reupload_required"),
        ("failed", "timeout", "conflict"),
        ("manual_review", None, "conflict"),
    ],
)
async def test_read_upload_reports_a_recoverable_state(monkeypatch, state, last_error, expected):
    _patch(monkeypatch, _row(state, last_error_code=last_error))
    result = await uploads.read_upload(_service(), 14, "key")
    assert result["state"] == expected
    assert (result["operation_id"], result["file_id"], result["version_id"]) == ("op-1", 12, 9)


async def test_read_upload_keeps_an_absent_request_absent(monkeypatch):
    _patch(monkeypatch, None)
    assert (await uploads.read_upload(_service(), 14, "key"))["state"] == "not_found"
