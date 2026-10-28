"""Coverage AC: AC-03, AC-32, AC-38, AC-39, AC-41, AC-51, AC-52, AC-53.

Real SQL usage projection, native audit writer and safety ingestion coexist.
The shared opt-in fixture proves database ownership and migrates real archives;
this file does not claim live model, Redis admission or Gateway E2E evidence.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.unified_policy import CreditRule, ModelVisibility, PersonalLedgerState
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent
from bisheng.dsh.domain.schemas.unified_policy import ModelVisibilityInput
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from test.dsh.test_content_safety_database_integration import (
    Maintenance,
    Request,
    Writer,
    ingest,
    stored,
    transaction,
)
from test.dsh.test_content_safety_database_integration import db as db
from test.dsh.test_content_safety_database_integration import pair as pair


@pytest.fixture
def credit_db(db):
    for tenant, user, model in ((101, 11, 7), (202, 22, 8)):
        with transaction(db, tenant) as session:
            session.add(Tenant(id=tenant, tenant_code=f"safety-credit-{tenant}", tenant_name="Synthetic credit tenant"))
            session.add(UserTenant(tenant_id=tenant, user_id=user, status="active", is_active=1))
            session.add(
                ModelVisibility(
                    tenant_id=tenant,
                    model_id=model,
                    credit_rate=125,
                    everyone=True,
                    subjects=[],
                    updated_by=user,
                )
            )
            session.add(
                CreditRule(
                    tenant_id=tenant,
                    subject_type="USER",
                    subject_id=user,
                    monthly_token_limit=1000,
                    updated_by=user,
                )
            )
            session.add(PersonalLedgerState(tenant_id=tenant, user_id=user))
    return db


def output(factory, *, identity=None, **changes):
    raw = factory(
        identity=identity,
        backend_request_id=str(uuid4()),
        forwarded=True,
        event_kind="DECISION",
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        stage_versions={"input": 1, "output": 1},
        drain_status="RUNNING",
    )
    return {**raw, **changes}


def usage(raw, *, status="RUNNING", version=1, tokens=None):
    started = datetime.fromisoformat(raw["request_started_at"].replace("Z", "+00:00"))
    return UsageEvent(
        request_id=raw["backend_request_id"],
        tenant_id=int(raw["tenant_id"]),
        user_id=int(raw["user_id"]),
        model_id=int(raw["model_id"]),
        session_id=raw["session_id"],
        credit_rate=125,
        usage_month=started.strftime("%Y-%m"),
        billing_timezone="UTC",
        policy_version=1,
        quota_epoch=1,
        event_version=version,
        status=status,
        started_at=started,
        ended_at=started + timedelta(seconds=1) if status != "RUNNING" else None,
        settled_at=started + timedelta(seconds=1) if tokens is not None else None,
        input_tokens=30 if tokens is not None else None,
        output_tokens=50 if tokens is not None else None,
        total_tokens=tokens,
        usage_source="PROVIDER" if tokens is not None else None,
    )


def project(engine, event):
    with transaction(engine, event.tenant_id) as session:
        return DshUsageRepository(session).project_batch([event])


def billing(engine, tenant=101):
    with transaction(engine, tenant) as session:
        return {
            model.__tablename__: sorted((row.model_dump() for row in session.exec(select(model))), key=repr)
            for model in (DshModelCall, DshMonthlyUsage, ModelVisibility, CreditRule, PersonalLedgerState)
        }


def audit(engine, raw, *, finish=False):
    tenant = int(raw["tenant_id"])

    @contextmanager
    def scope():
        with transaction(engine, tenant) as session:
            yield Writer(session)

    def no_objects():
        raise AssertionError("Metadata-only audit must not access body objects")

    writer = DshModelAuditWriter(scope, no_objects, attempts=1)
    metadata = {
        "user_id": int(raw["user_id"]),
        "model_id": int(raw["model_id"]),
        "session_id": raw["session_id"],
        "conversation_id": raw["conversation"]["conversation_id"],
        "request_kind": "chat",
        "session_origin": "main",
        "parent_conversation_id": None,
        "effective_mode": "METADATA",
        "started_at": datetime.fromisoformat(raw["request_started_at"].replace("Z", "+00:00")),
    }

    async def persist():
        events = (
            [("entered", {})]
            if not finish
            else [
                (
                    "terminal",
                    {
                        "model_result": "SUCCEEDED",
                        "input_complete": True,
                        "capture_failed": False,
                        "channels": {},
                        "input_units": 1,
                    },
                ),
                ("response", {"response_result": "COMPLETED"}),
                ("usage", {"usage_settlement": "SETTLED"}),
            ]
        )
        for kind, facts in events:
            assert await writer.write(
                AuditEvent(
                    request_id=raw["backend_request_id"],
                    tenant_id=tenant,
                    kind=kind,
                    observed_at=metadata["started_at"] + timedelta(seconds=2),
                    metadata={**metadata, **facts},
                )
            )

    asyncio.run(persist())


def final(raw):
    return {**raw, "event_id": str(uuid4()), "event_version": 2, "event_kind": "FINAL", "drain_status": "FINISHED"}


def assert_settled(snapshot):
    call = snapshot["dsh_model_call"][0]
    assert (
        call["credit_rate"],
        call["input_tokens"],
        call["output_tokens"],
        call["total_tokens"],
        call["billed_tokens"],
    ) == (125, 30, 50, 80, 100)
    assert snapshot["dsh_monthly_usage"][0]["used_tokens"] == 100


def test_input_block_has_no_native_call_or_credit_debit(credit_db, content_safety_event):
    raw = content_safety_event()
    before = billing(credit_db)
    receipt = ingest(credit_db, raw)
    assert not receipt.duplicate and ingest(credit_db, raw).duplicate
    assert billing(credit_db) == before
    assert before["dsh_model_call"] == before["dsh_monthly_usage"] == []
    with transaction(credit_db) as session:
        row = session.get(Request, receipt.audit_request_id)
        assert row.record_origin == "EXTERNAL_SAFETY" and row.model_entered is False
        assert row.model_result is row.response_result is row.usage_settlement is None


@pytest.mark.parametrize("settled_first", [False, True])
def test_output_hit_and_late_final_never_change_credit_projection(credit_db, content_safety_event, settled_first):
    raw = output(content_safety_event)
    audit(credit_db, raw)
    running, terminal = usage(raw), usage(raw, status="SUCCEEDED", version=2, tokens=80)
    assert project(credit_db, running) == 1
    if settled_first:
        assert project(credit_db, terminal) == 1
    before = billing(credit_db)
    receipt = ingest(credit_db, raw)
    assert receipt.association_status == "ASSOCIATED" and billing(credit_db) == before
    if not settled_first:
        assert project(credit_db, terminal) == 1
    snapshot = billing(credit_db)
    assert_settled(snapshot)
    assert project(credit_db, terminal) == 0
    assert ingest(credit_db, raw).duplicate
    completed = final(raw)
    assert not ingest(credit_db, completed).duplicate
    assert ingest(credit_db, completed).duplicate
    assert billing(credit_db) == snapshot
    with transaction(credit_db) as session:
        row = session.get(Request, raw["backend_request_id"])
        assert row.record_origin == "MODEL" and row.model_entered is True and row.output_sensitive_hit


def test_unknown_usage_remains_null_until_actual_late_settlement(credit_db, content_safety_event):
    raw = output(content_safety_event)
    audit(credit_db, raw)
    assert project(credit_db, usage(raw, status="USAGE_UNKNOWN", version=2)) == 1
    before = billing(credit_db)
    assert before["dsh_model_call"][0]["billed_tokens"] is before["dsh_model_call"][0]["total_tokens"] is None
    assert before["dsh_monthly_usage"] == []
    ingest(credit_db, raw)
    ingest(credit_db, final(raw))
    assert billing(credit_db) == before
    terminal = usage(raw, status="SUCCEEDED", version=3, tokens=80)
    assert project(credit_db, terminal) == 1 and project(credit_db, terminal) == 0
    assert_settled(billing(credit_db))


def test_current_credit_rate_edit_does_not_reprice_inflight_or_safety_retry(credit_db, content_safety_event):
    raw = output(content_safety_event)
    audit(credit_db, raw)
    assert project(credit_db, usage(raw)) == 1
    with transaction(credit_db) as session:
        saved = UnifiedPolicyRepository(session).save_visibility(
            7,
            11,
            ModelVisibilityInput(version=1, everyone=True, credit_multiplier="2"),
        )
        assert saved["credit_multiplier"] == "2"
    ingest(credit_db, raw)
    terminal = usage(raw, status="SUCCEEDED", version=2, tokens=80)
    before = billing(credit_db)
    with pytest.raises(ValueError, match="immutable"):
        project(credit_db, terminal.model_copy(update={"credit_rate": 200}))
    assert billing(credit_db) == before
    assert project(credit_db, terminal) == 1
    snapshot = billing(credit_db)
    assert_settled(snapshot)
    assert snapshot["dsh_model_visibility"][0]["credit_rate"] == 200
    ingest(credit_db, final(raw))
    assert billing(credit_db) == snapshot


def test_cross_tenant_safety_keeps_foreign_credit_and_native_audit_ownership(
    credit_db,
    content_safety_event,
    content_safety_identities,
):
    foreign = output(content_safety_event, identity=content_safety_identities[1])
    audit(credit_db, foreign)
    assert project(credit_db, usage(foreign, status="SUCCEEDED", version=2, tokens=80)) == 1
    before = {tenant: billing(credit_db, tenant) for tenant in (101, 202)}
    wrong_owner = output(content_safety_event, backend_request_id=foreign["backend_request_id"])
    receipt = ingest(credit_db, wrong_owner)
    assert receipt.association_status == "UNASSOCIATED"
    assert {tenant: billing(credit_db, tenant) for tenant in (101, 202)} == before
    with transaction(credit_db, 202) as session:
        row = session.get(Request, foreign["backend_request_id"])
        assert (row.tenant_id, row.user_id, row.model_id) == (202, 22, 8) and not row.has_sensitive_hit
    assert stored(credit_db, 101)[0][0].association_status == "UNASSOCIATED"


def test_main_audit_retention_preserves_weighted_billing_and_allowance(credit_db, content_safety_event):
    raw = output(content_safety_event)
    audit(credit_db, raw)
    assert project(credit_db, usage(raw, status="SUCCEEDED", version=2, tokens=80)) == 1
    ingest(credit_db, raw)
    ingest(credit_db, final(raw))
    audit(credit_db, raw, finish=True)
    before = billing(credit_db)
    with transaction(credit_db) as session:
        DshModelAuditSettingRepository(session).begin_cleanup(
            before=datetime.fromisoformat(raw["request_started_at"].replace("Z", "+00:00")) + timedelta(seconds=1),
        )
    with transaction(credit_db) as session:
        assert Maintenance(session).purge_batch()["audits_deleted"] == 1
    assert stored(credit_db) == ([], [])
    assert billing(credit_db) == before
