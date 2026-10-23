"""AC-QC-04..12: real HTTP/SQL chain with isolated synthetic identity."""

from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy import event

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.model_audit_maintenance import backfill_audit_presentation
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.schemas.model_audit_status import audit_status_facts, refresh_audit_status
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.model_audit_fixtures import NOW, audit_database, audit_session
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture


def row(request_id, *, conversation="e2e-qc-session", user=20, name="Provider / A", **values):
    result = DshModelAuditRequest(
        request_id=request_id,
        user_id=user,
        conversation_id=conversation,
        conversation_key=conversation_key(2, user, conversation) if conversation else None,
        conversation_id_digest=sha256(conversation.encode()).hexdigest() if conversation else None,
        association_status="ASSOCIATED" if conversation else "UNASSOCIATED",
        model_name=name,
        model_name_digest=sha256(name.encode()).hexdigest(),
        started_at=NOW,
        model_result="SUCCEEDED",
        response_result="COMPLETED",
        usage_settlement="SETTLED",
    )
    for key, value in values.items():
        setattr(result, key, value)
    refresh_audit_status(result)
    return result


@pytest.mark.parametrize(
    "axis,value,abnormal",
    [
        ("model_result", "RUNNING", False),
        ("model_result", "FAILED", True),
        ("model_result", "CANCELLED", True),
        ("model_result", "UNKNOWN", True),
        ("response_result", "RUNNING", False),
        ("response_result", "INTERRUPTED", True),
        ("response_result", "ERROR", True),
        ("response_result", "UNKNOWN", True),
        ("usage_settlement", "PENDING", False),
        ("usage_settlement", "USAGE_UNKNOWN", True),
        ("usage_settlement", "UNCERTAIN", True),
        ("model_result", "FUTURE", True),
    ],
)
def test_status_mapping(axis, value, abnormal):
    """AC-QC-04: pending is not failed; unrecognized facts never imply success."""
    status, reasons, pending = audit_status_facts(row("e2e-qc-state", **{axis: value}))
    assert (status == "ABNORMAL") is abnormal
    assert bool(reasons) is abnormal
    assert pending is (value in {"RUNNING", "PENDING"})


@pytest.mark.parametrize(
    "mode,content,failed,expected",
    [
        ("METADATA", "NOT_CAPTURED", False, "NORMAL"),
        ("METADATA", "COMPLETE", False, "ABNORMAL"),
        ("CONTENT", "PENDING", False, "NORMAL"),
        ("CONTENT", "COMPLETE", False, "NORMAL"),
        ("CONTENT", "PARTIAL", False, "ABNORMAL"),
        ("CONTENT", "NOT_CAPTURED", False, "ABNORMAL"),
        ("CONTENT", "COMPLETE", True, "ABNORMAL"),
    ],
)
def test_content_mode_mapping(mode, content, failed, expected):
    assert (
        audit_status_facts(row("e2e-qc-content", effective_mode=mode, content_status=content, capture_failed=failed))[0]
        == expected
    )


def test_projection_idempotency_recovery_isolation_and_rollback():
    """AC-QC-06/09: request facts survive projection rollback and repeated delivery."""
    with audit_database() as engine:
        with audit_session(engine) as session, session.begin():
            session.add(row("e2e-qc-a", model_result="FAILED"))
            session.add(row("e2e-qc-b"))
            session.add(row("e2e-qc-c", user=21))
        with audit_session(engine) as session:
            repository = DshModelAuditQueryRepository(session)
            assert repository.project_request("e2e-qc-a", now=NOW)
            session.rollback()
        with audit_session(engine) as session, session.begin():
            repository = DshModelAuditQueryRepository(session)
            assert repository.request("e2e-qc-a").model_result == "FAILED"
            for request_id in ("e2e-qc-a", "e2e-qc-b", "e2e-qc-c"):
                assert repository.project_request(request_id, now=NOW)
                assert not repository.project_request(request_id, now=NOW)
            group = repository.group(conversation_key(2, 20, "e2e-qc-session"))
            assert (group.request_count, group.abnormal_count) == (2, 1)
            target = repository.request("e2e-qc-a", lock=True)
            target.model_result = "SUCCEEDED"
            refresh_audit_status(target)
        with audit_session(engine) as session, session.begin():
            repository = DshModelAuditQueryRepository(session)
            assert repository.project_request("e2e-qc-a", now=NOW + timedelta(days=1))
            group = repository.group(conversation_key(2, 20, "e2e-qc-session"))
            assert (group.request_count, group.abnormal_count) == (2, 0)
            assert group.listed_at.replace(tzinfo=NOW.tzinfo) == NOW
        with audit_session(engine, 3) as session:
            assert DshModelAuditQueryRepository(session).group(group.conversation_key) is None


async def test_group_http_filters_scope_paging_and_no_body_reads():
    """AC-QC-06/07/08/12: all predicates refer to the same request; pages do not read bodies."""
    async with fixture() as (harness, client, objects):
        with audit_session(harness.engine) as session, session.begin():
            for request in (
                row("e2e-qc-http-a"),
                row("e2e-qc-http-b", name="Provider / B", model_result="FAILED"),
                row("e2e-qc-http-c", conversation="e2e-qc-second", model_result="FAILED"),
                row("e2e-qc-http-d", conversation=None),
            ):
                session.add(request)
            session.flush()
            repository = DshModelAuditQueryRepository(session)
            for request_id in repository.projection_candidates():
                repository.project_request(request_id, now=NOW)
        assert not objects.data
        query = {"model_name": "Provider / A", "audit_status": "ABNORMAL", "limit": 1}
        response = await client.get(BASE + "/conversation-groups", headers=LOCAL_ADMIN, params=query)
        assert response.json()["status_code"] == 200 and response.headers["cache-control"] == "no-store"
        page = response.json()["data"]
        assert len(page["items"]) == 1 and page["items"][0]["conversation_id"] == "e2e-qc-second"
        key = page["items"][0]["conversation_key"]
        detail = (
            await client.get(BASE + f"/conversation-groups/{key}/requests", headers=LOCAL_ADMIN, params=query)
        ).json()["data"]
        assert [r["request_id"] for r in detail["items"]] == ["e2e-qc-http-c"]
        assert detail["items"][0]["audit_status"] == "ABNORMAL"
        assert detail["items"][0]["status_reasons"] == ["model_result:FAILED"]
        assert not objects.data
        for path in ("/conversation-groups", f"/conversation-groups/{key}/requests", "/query-readiness"):
            assert (await client.get(BASE + path, headers=USER)).status_code == 403
            assert (await client.get(BASE + path, headers=LOCAL_ADMIN, params={"tenant_id": 3})).status_code == 403
        other = await client.get(BASE + f"/conversation-groups/{key}/requests", headers=ADMIN, params={"tenant_id": 3})
        assert other.json()["status_code"] != 200
        for params in (
            {"model_id": 1},
            {"content_status": "COMPLETE"},
            {"surprise": "x"},
            {"limit": 0},
            {"user_id": 0},
        ):
            assert (await client.get(BASE + "/conversation-groups", headers=LOCAL_ADMIN, params=params)).json()[
                "status_code"
            ] == 26131
        assert (
            await client.get(BASE + f"/conversation-groups/{key}/requests", headers=LOCAL_ADMIN, params={"user_id": 21})
        ).json()["status_code"] == 26131
        first = (await client.get(BASE + "/conversation-groups", headers=LOCAL_ADMIN, params={"limit": 1})).json()[
            "data"
        ]
        second = (
            await client.get(
                BASE + "/conversation-groups", headers=LOCAL_ADMIN, params={"limit": 1, "cursor": first["next_cursor"]}
            )
        ).json()["data"]
        assert first["items"][0]["conversation_key"] != second["items"][0]["conversation_key"]
        assert (
            await client.get(
                BASE + "/conversation-groups",
                headers=LOCAL_ADMIN,
                params={"limit": 1, "cursor": first["next_cursor"], "audit_status": "ABNORMAL"},
            )
        ).json()["status_code"] == 26131


def test_backfill_is_bounded_preview_and_directory_requires_readiness():
    """AC-QC-10: legacy NULL states cannot disappear behind an apparently complete page."""
    with audit_database() as engine:
        with audit_session(engine) as session, session.begin():
            session.add(DshModelAuditRequest(request_id="e2e-qc-legacy", started_at=NOW))
        with audit_session(engine) as session, session.begin():
            repository = DshModelAuditQueryRepository(session)
            assert not repository.readiness()["status_ready"]
            assert repository.group_page()["progress"]["status_ready"] is False
            assert backfill_audit_presentation(session)["updated"] == 0
            assert repository.request("e2e-qc-legacy").audit_status is None
            assert backfill_audit_presentation(session, apply=True, limit=1)["updated"] == 1
        with audit_session(engine) as session, session.begin():
            assert backfill_audit_presentation(session, apply=True)["updated"] == 0
            assert DshModelAuditQueryRepository(session).readiness()["status_ready"]


def test_sparse_directory_scan_returns_continuation_without_grouping_the_audit_table():
    """AC-QC-10/11: bounded empty batches continue; no online DISTINCT/GROUP BY."""
    with audit_database() as engine:
        with audit_session(engine) as session, session.begin():
            for index in range(1005):
                conversation = f"e2e-qc-sparse-{index:04}"
                session.add(
                    DshModelAuditConversation(
                        conversation_key=conversation_key(2, 20, conversation),
                        user_id=20,
                        conversation_id=conversation,
                        listed_at=NOW + timedelta(seconds=index),
                        first_request_at=NOW,
                        last_request_at=NOW,
                        updated_at=NOW,
                        request_count=1,
                        abnormal_count=0,
                    )
                )
            session.add(row("e2e-qc-sparse-request", conversation="e2e-qc-sparse-0000", group_index_pending=False))
        sql = []

        def observed(_connection, _cursor, statement, _parameters, _context, _many):
            sql.append(statement.upper())

        event.listen(engine, "before_cursor_execute", observed)
        try:
            with audit_session(engine) as session:
                repository = DshModelAuditQueryRepository(session)
                first = repository.group_page(model_name="Provider / A")
                assert not first["items"] and first["next_cursor"] and first["scan_limited"]
                second = repository.group_page(model_name="Provider / A", cursor=first["next_cursor"])
                assert [g["conversation_id"] for g in second["items"]] == ["e2e-qc-sparse-0000"]
                assert second["next_cursor"] is None
            assert not any(
                token in statement for statement in sql for token in (" LIKE ", "GROUP BY", "DISTINCT", "COUNT(")
            )
            assert len(sql) < 35
        finally:
            event.remove(engine, "before_cursor_execute", observed)
