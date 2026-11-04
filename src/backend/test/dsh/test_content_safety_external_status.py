"""Coverage AC: AC-32, AC-34, AC-36, AC-38, AC-44, AC-48, AC-52.

Exercise the existing status, worker and query boundaries with durable synthetic
facts. No external source can manufacture model execution or zero token usage.
"""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, call

import pytest
from sqlmodel import Session, SQLModel, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories import content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.schemas.model_audit_status import audit_status_facts, refresh_audit_status
from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
from bisheng.dsh.domain.services.model_audit_states import DshModelAuditStateService, derive_audit_states
from test.dsh.model_audit_fixtures import AUDIT_MODELS
from test.dsh.test_content_safety_merge import append_and_merge, committed_merge, output_event
from test.dsh.test_content_safety_native_writer import capture_events, safety_first
from test.dsh.test_content_safety_native_writer import native_environment as native_environment
from test.dsh.test_content_safety_repository import tenant_session


@pytest.fixture
def status_tables(content_safety_engine):
    models = (*AUDIT_MODELS, DshModelCall)
    SQLModel.metadata.create_all(content_safety_engine, tables=[model.__table__ for model in models])
    tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in models)


def queries(engine):
    @contextmanager
    def scope():
        with strict_tenant_filter(), Session(engine, expire_on_commit=False) as session, session.begin():
            yield DshModelAuditQueryRepository(session)

    return DshModelAuditQueryService(None, scope)


def external(engine, factory, *, input_block=False, state="BLOCKED"):
    if input_block:
        raw = factory(conversation=None, session_id=None)
    else:
        raw = output_event(
            factory,
            conversation=None,
            session_id=None,
            stage_results={"input": "DISABLED" if state == "DISABLED" else "PASSED", "output": state},
            stage_versions={"input": 1, "output": 0 if state == "UNREPORTED" else 1},
            hit_count=1 if state == "BLOCKED" else 0,
            rule_refs=["synthetic-rule-1"] if state == "BLOCKED" else [],
        )
    _, row, _ = committed_merge(engine, content_safety_projection, raw)
    return raw, row


@pytest.mark.parametrize("input_block", [True, False])
def test_external_input_and_output_have_non_model_audit_status_without_invalid_axes(
    content_safety_engine, content_safety_event, input_block
):
    _, row = external(content_safety_engine, content_safety_event, input_block=input_block)
    before = row.model_dump()
    assert audit_status_facts(row) == ("NOT_APPLICABLE", [], False)
    assert row.model_dump() == before
    assert row.model_entered is (False if input_block else None)
    assert row.effective_mode is None and row.model_result is None
    assert row.response_result is None and row.usage_settlement is None
    assert row.content_status == "NOT_CAPTURED" and row.content_safety_state == "BLOCKED"


@pytest.mark.parametrize("state", ["BLOCKED", "ERROR", "PASSED", "DISABLED", "UNREPORTED"])
def test_external_safety_result_does_not_become_model_normal_or_abnormal(
    content_safety_engine, content_safety_event, state
):
    _, row = external(content_safety_engine, content_safety_event, state=state)
    safety_state = row.content_safety_state
    assert audit_status_facts(row) == ("NOT_APPLICABLE", [], False)
    refresh_audit_status(row)
    assert row.audit_status == "NOT_APPLICABLE" and row.content_safety_state == safety_state
    assert row.has_sensitive_hit is (state == "BLOCKED")


def test_refresh_does_not_make_an_unassociated_external_row_permanently_dirty(
    content_safety_engine, content_safety_event
):
    raw, _ = external(content_safety_engine, content_safety_event)
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.conversation_key is None and not row.group_index_pending
        refresh_audit_status(row)
        session.add(row)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.audit_status == "NOT_APPLICABLE" and not row.group_index_pending
        assert row.has_sensitive_hit


@pytest.mark.parametrize("active", [True, False, None])
def test_normal_external_never_acquires_stale_model_states_even_long_after_receipt(
    content_safety_engine, content_safety_event, content_safety_clock, active
):
    _, row = external(content_safety_engine, content_safety_event)
    before = row.model_dump()
    assert (
        derive_audit_states(
            row,
            now=content_safety_clock.now() + timedelta(days=90),
            window=300,
            activity=active,
            has_fragments=False,
        )
        == {}
    )
    assert row.model_dump() == before


@pytest.mark.parametrize("active", [False, None])
def test_external_origin_wins_over_accidental_native_pending_defaults(
    content_safety_engine, content_safety_event, content_safety_clock, active
):
    _, row = external(content_safety_engine, content_safety_event)
    row.model_result = row.response_result = "RUNNING"
    row.usage_settlement = "PENDING"
    row.content_status = row.message_sources_status = "PENDING"
    before = row.model_dump()
    assert audit_status_facts(row) == ("NOT_APPLICABLE", [], False)
    assert (
        derive_audit_states(
            row,
            now=content_safety_clock.now() + timedelta(hours=1),
            window=300,
            activity=active,
            has_fragments=True,
        )
        == {}
    )
    assert row.model_dump() == before


async def test_external_only_readiness_needs_no_key_manifest_or_model_terminal(
    content_safety_engine, content_safety_event, content_safety_clock, monkeypatch
):
    monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", "invalid-synthetic-key-format")
    for input_block in (True, False):
        external(content_safety_engine, content_safety_event, input_block=input_block)
    service = queries(content_safety_engine)
    ready = await service.execute(101, lambda repository: repository.readiness())
    assert ready == {"status_ready": True, "name_ready": True, "indexing_pending": False}
    activity = AsyncMock()
    activity.confirmed.return_value = False
    worker = DshModelAuditStateService(
        service, activity, window=300, now=lambda: content_safety_clock.now() + timedelta(days=90)
    )
    assert await worker.inspect(101) == (None, 0)
    activity.confirmed.assert_not_awaited()
    with tenant_session(content_safety_engine) as session:
        rows = session.exec(select(DshModelAuditRequest)).all()
        assert len(rows) == 2
        assert all(row.audit_status == "NOT_APPLICABLE" and row.effective_mode is None for row in rows)
        assert all(row.model_result is None and row.usage_settlement is None for row in rows)


async def test_state_worker_skips_external_before_activity_and_fact_reads_but_keeps_native_scan(
    content_safety_engine,
    content_safety_event,
    content_safety_clock,
    content_safety_native_audit,
    status_tables,
    monkeypatch,
):
    raw, _ = external(content_safety_engine, content_safety_event)
    native = content_safety_native_audit(last_write_at=content_safety_clock.now())
    with tenant_session(content_safety_engine) as session, session.begin():
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        row.model_result = row.response_result = "RUNNING"
        row.usage_settlement = "PENDING"
        session.add(row)
        session.add(native)
    activity = AsyncMock()
    activity.confirmed.return_value = False
    fact_reads = []
    original = DshModelAuditQueryRepository.facts

    def record_facts(repository, request_id):
        fact_reads.append(request_id)
        return original(repository, request_id)

    monkeypatch.setattr(DshModelAuditQueryRepository, "facts", record_facts)
    worker = DshModelAuditStateService(
        queries(content_safety_engine),
        activity,
        window=300,
        now=lambda: content_safety_clock.now() + timedelta(hours=1),
    )
    assert await worker.inspect(101) == (None, 1)
    assert activity.confirmed.await_args_list == [call(native.request_id)]
    assert fact_reads == [native.request_id]
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "EXTERNAL_SAFETY" and row.audit_status == "NOT_APPLICABLE"
        assert row.model_result == row.response_result == "RUNNING" and row.usage_settlement == "PENDING"
        assert row.state_version == 0
        model = session.get(DshModelAuditRequest, native.request_id)
        assert model.model_result == model.response_result == "UNKNOWN" and model.usage_settlement == "UNCERTAIN"
        assert model.audit_status == "ABNORMAL" and model.has_sensitive_hit is False


async def test_full_page_of_skipped_external_rows_still_advances_the_existing_cursor(
    content_safety_engine, content_safety_event, content_safety_clock, status_tables
):
    request_ids = []
    with tenant_session(content_safety_engine) as session, session.begin():
        for _ in range(100):
            raw = output_event(content_safety_event, conversation=None, session_id=None)
            _, row, _ = append_and_merge(session, content_safety_projection, raw)
            row.model_result = "RUNNING"
            session.add(row)
            request_ids.append(row.request_id)
    activity = AsyncMock()
    activity.confirmed.return_value = False
    worker = DshModelAuditStateService(
        queries(content_safety_engine),
        activity,
        window=300,
        now=lambda: content_safety_clock.now() + timedelta(hours=1),
    )
    cursor, changed = await worker.inspect(101)
    assert cursor == max(request_ids) and changed == 0
    assert await worker.inspect(101, cursor) == (None, 0)
    activity.confirmed.assert_not_awaited()
    with tenant_session(content_safety_engine) as session:
        rows = session.exec(select(DshModelAuditRequest)).all()
        assert len(rows) == 100 and all(row.state_version == 0 for row in rows)
        assert all(row.audit_status == "NOT_APPLICABLE" and row.model_result == "RUNNING" for row in rows)


@pytest.mark.parametrize("mode", ["METADATA", "CONTENT"])
async def test_native_promotion_restores_standard_pending_and_stale_state_rules(
    content_safety_engine, content_safety_event, content_safety_clock, native_environment, mode
):
    raw, _ = safety_first(content_safety_engine, content_safety_event)
    writer, _, _ = native_environment
    entered = capture_events(raw, content_safety_clock, mode=mode)[0]
    assert await writer.write(entered)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.record_origin == "MODEL" and row.model_entered is True
        assert audit_status_facts(row) == ("NORMAL", [], True)
        assert row.has_sensitive_hit and row.output_sensitive_hit
    activity = AsyncMock()
    activity.confirmed.return_value = False
    worker = DshModelAuditStateService(
        queries(content_safety_engine),
        activity,
        window=300,
        now=lambda: content_safety_clock.now() + timedelta(hours=1),
    )
    assert await worker.inspect(101) == (None, 1)
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, raw["backend_request_id"])
        assert row.audit_status == "ABNORMAL"
        assert row.model_result == row.response_result == "UNKNOWN" and row.usage_settlement == "UNCERTAIN"
        assert row.has_sensitive_hit and row.output_safety_state == "BLOCKED"
        assert row.content_status == "NOT_CAPTURED"
        assert "INVALID_STATE" not in audit_status_facts(row)[1]


def test_model_invalid_native_axes_still_report_invalid_state(content_safety_native_audit):
    row = content_safety_native_audit(model_result=None, response_result=None, usage_settlement=None)
    status, reasons, pending = audit_status_facts(row)
    assert status == "ABNORMAL" and "INVALID_STATE" in reasons and not pending
    assert row.content_safety_state == "UNREPORTED" and not row.has_sensitive_hit


def test_real_unknown_usage_remains_null_and_not_zero_in_metadata(
    content_safety_engine, content_safety_native_audit, status_tables
):
    native = content_safety_native_audit(
        model_result="UNKNOWN", response_result="UNKNOWN", usage_settlement="UNCERTAIN"
    )
    refresh_audit_status(native)
    with tenant_session(content_safety_engine) as session, session.begin():
        session.add(native)
        session.add(
            DshModelCall(
                request_id=native.request_id,
                tenant_id=101,
                user_id=11,
                model_id=7,
                session_id=native.session_id,
                usage_month="2026-10",
                policy_version=1,
                event_version=1,
                quota_epoch=1,
                status="USAGE_UNKNOWN",
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
            )
        )
    with tenant_session(content_safety_engine) as session:
        row = session.get(DshModelAuditRequest, native.request_id)
        metadata = DshModelAuditQueryRepository(session).metadata(row, user_names={11: "synthetic-user"})
        assert metadata["model_result"] == metadata["response_result"] == "UNKNOWN"
        assert metadata["usage_settlement"] == "UNCERTAIN" and metadata["audit_status"] == "ABNORMAL"
        assert not metadata["status_pending"] and metadata["content_safety_state"] == "UNREPORTED"
        assert metadata["usage"]["status"] == "USAGE_UNKNOWN"
        assert all(metadata["usage"][key] is None for key in ("input_tokens", "output_tokens", "total_tokens"))


@pytest.mark.parametrize("input_block", [True, False])
def test_external_metadata_without_actual_call_keeps_usage_unknown(
    content_safety_engine, content_safety_event, status_tables, input_block
):
    _, row = external(content_safety_engine, content_safety_event, input_block=input_block)
    with tenant_session(content_safety_engine) as session:
        stored = session.get(DshModelAuditRequest, row.request_id)
        metadata = DshModelAuditQueryRepository(session).metadata(stored, user_names={11: "synthetic-user"})
        assert metadata["usage"] is None
        assert metadata["model_result"] is None and metadata["response_result"] is None
        assert metadata["usage_settlement"] is None and not metadata["status_pending"]
        assert metadata["audit_status"] == "NOT_APPLICABLE"
        assert metadata["model_entered"] is (False if input_block else None)
