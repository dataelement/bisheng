"""AC-01..07: durable, bounded administrative audit history."""

import base64
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, event
from sqlmodel import Session, SQLModel

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.core.database import tenant_filter
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicyAudit
from bisheng.dsh.domain.repositories.audit import DshAuditRepository
from bisheng.dsh.domain.services.admin import DshManagementService
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.user.domain.models.user import User
from test.e2e.helpers.api import assert_resp_200

AT = datetime(2026, 9, 16, 9, 0)


def operation(number, *, tenant=2, status="SUCCEEDED", at=AT):
    return DshAdminOperation(
        operation_id=str(UUID(int=number)),
        tenant_id=tenant,
        user_id=20,
        actor_user_id=21,
        action="UPDATE_POLICY",
        status=status,
        expected_policy_version=0,
        payload_hash="x" * 64,
        payload={"model_id": 4, "monthly_token_limit": 200, "enabled": True, "access_token": "fixture-private"},
        before_values={"monthly_token_limit": 100, "enabled": False, "secret": "fixture-private"},
        after_values={"monthly_token_limit": 200, "enabled": True} if status == "SUCCEEDED" else None,
        create_time=at,
        update_time=at,
    )


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    engine = create_engine(f"sqlite:///{tmp_path / 'dsh-audit.db'}")
    tables = [
        DshAdminOperation.__table__,
        DshSubjectPolicyAudit.__table__,
        User.__table__,
        UserTenant.__table__,
        Department.__table__,
        Role.__table__,
        LLMModel.__table__,
    ]
    SQLModel.metadata.create_all(engine, tables=tables)
    # Install the real tenant SELECT hook without unrelated application imports.
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._discover_tenant_aware_tables())
    with Session(engine) as session, session.begin(), profile_scope(2):
        session.add_all(
            [
                User(user_id=20, user_name="e2e-audit-member", password="fixture"),
                User(user_id=21, user_name="e2e-audit-admin", password="fixture"),
                UserTenant(id=1, user_id=20, tenant_id=2),
                UserTenant(id=2, user_id=21, tenant_id=2),
                Department(id=10, name="e2e-audit-department", dept_id="e2e-audit-department", tenant_id=2),
                Role(id=10, role_name="e2e-audit-role", tenant_id=2),
                LLMModel(id=4, server_id=1, model_name="e2e-audit-model", name="model 4", tenant_id=2),
                operation(1),
                operation(2, status="FAILED", at=AT + timedelta(seconds=1)),
                DshSubjectPolicyAudit(
                    id=1,
                    tenant_id=2,
                    subject_type="DEPARTMENT",
                    subject_id=10,
                    model_id=4,
                    actor_user_id=21,
                    before_values={"enabled": False},
                    after_values={"enabled": True},
                    create_time=AT,
                ),
                DshSubjectPolicyAudit(
                    id=2,
                    tenant_id=2,
                    subject_type="ROLE",
                    subject_id=10,
                    model_id=4,
                    actor_user_id=21,
                    before_values={},
                    after_values={"enabled": True},
                    create_time=AT,
                ),
            ]
        )
    with Session(engine) as session, session.begin(), profile_scope(3):
        session.add(operation(99, tenant=3, at=AT + timedelta(days=1)))
    yield engine
    engine.dispose()


def test_persisted_sources_refresh_names_and_redaction(audit_db):
    """AC-01,02,03,05: both sources survive a new session and expose safe details."""
    for _ in range(2):
        with Session(audit_db) as session, profile_scope(2):
            page = DshAuditRepository(session).list_records()
        assert len(page["data"]) == 4
        assert page["data"][0]["status"] == "FAILED"
        assert page["data"][0]["requested_values"]["monthly_token_limit"] == 200
        assert page["data"][0]["after_values"] == {}
        assert page["data"][1]["target_name"] == "e2e-audit-role"
        assert page["data"][2]["target_name"] == "e2e-audit-department"
        assert page["data"][3]["actor_name"] == "e2e-audit-admin"
        assert page["data"][3]["model_name"] == "e2e-audit-model"
        assert "fixture-private" not in json.dumps(page)
        assert page["data"][0]["created_at"].endswith("Z")
        assert page["data"][0]["created_at"] == "2026-09-16T01:00:01Z"


def test_keyset_same_timestamp_merge_and_new_insert(audit_db):
    """AC-04: sources tied at one second have stable, unique page boundaries."""
    with Session(audit_db) as session, profile_scope(2):
        repo = DshAuditRepository(session)
        expected = [row["id"] for row in repo.list_records()["data"]]
        found, cursor = [], None
        while True:
            page = repo.list_records(limit=1, cursor=cursor)
            found.extend(row["id"] for row in page["data"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        assert found == expected
        first = repo.list_records(limit=2)
        session.add(operation(3, at=AT + timedelta(days=2)))
        session.commit()
        second = repo.list_records(limit=2, cursor=first["next_cursor"])
        assert [row["id"] for row in first["data"] + second["data"]] == expected


@pytest.mark.parametrize(
    "action,status",
    [("REVOKE", "SUCCEEDED"), ("REASSIGN", "PROCESSING"), ("SYNC_PROFILE", "PENDING"), ("RECONCILE_USAGE", "FAILED")],
)
def test_seat_and_background_operations(audit_db, action, status):
    """AC-02,03: every persisted action retains its actual state and actor."""
    with Session(audit_db) as session, profile_scope(2):
        row = operation(5, status=status)
        row.action = action
        row.actor_user_id = None if action == "SYNC_PROFILE" else 21
        row.expected_grant_version = 1
        row.expected_event_version = 1
        row.before_values = {"state": "ASSIGNED", "grant_version": 1}
        row.after_values = {"state": "REVOKED", "grant_version": 2} if status == "SUCCEEDED" else None
        session.add(row)
        session.commit()
        data = DshAuditRepository(session).list_records(action=action, status=status)["data"]
        assert len(data) == 1
        assert data[0]["action"] == action and data[0]["status"] == status
        assert data[0]["actor_id"] == row.actor_user_id
        assert data[0]["after_values"] == (row.after_values or {})


@pytest.mark.parametrize(
    "action,status,count",
    [
        ("UPDATE_POLICY", None, 2),
        ("UPDATE_DEPARTMENT_POLICY", None, 1),
        ("UPDATE_ROLE_POLICY", None, 1),
        (None, "FAILED", 1),
        (None, "SUCCEEDED", 3),
        ("UPDATE_ROLE_POLICY", "FAILED", 0),
        ("REVOKE", None, 0),
    ],
)
def test_filters(audit_db, action, status, count):
    """AC-04,06: exact type/result filters, including genuine empty results."""
    with Session(audit_db) as session, profile_scope(2):
        assert len(DshAuditRepository(session).list_records(action=action, status=status)["data"]) == count


def test_cross_tenant_cursor_and_missing_objects(audit_db):
    """AC-05: tenant binding and ID fallback preserve historical evidence."""
    with Session(audit_db) as session, profile_scope(2):
        repo = DshAuditRepository(session)
        cursor = repo.list_records(limit=1)["next_cursor"]
        for query in ({"limit": 2}, {"limit": 1, "status": "FAILED"}):
            with pytest.raises(DshInvalidRequestError):
                repo.list_records(cursor=cursor, **query)
        row = session.get(DshSubjectPolicyAudit, 1)
        row.subject_id = 999
        session.commit()
        missing = repo.list_records(action="UPDATE_DEPARTMENT_POLICY")["data"][0]
        assert missing["target_id"] == 999 and missing["target_name"] is None
    with Session(audit_db) as session, profile_scope(3):
        repo = DshAuditRepository(session)
        assert len(repo.list_records()["data"]) == 1
        with pytest.raises(DshInvalidRequestError):
            repo.list_records(limit=1, cursor=cursor)


@pytest.mark.parametrize(
    "cursor",
    ["!", "W10=", base64.b64encode(json.dumps([[2, None, None, 20], "x", "operation", None]).encode()).decode()],
)
def test_invalid_cursors(audit_db, cursor):
    with Session(audit_db) as session, profile_scope(2), pytest.raises(DshInvalidRequestError):
        DshAuditRepository(session).list_records(cursor=cursor)


async def test_api_service_repository_chain_and_denials(audit_db):
    """AC-01,04,05,07: real read chain, validated inputs and original authorizer."""
    from bisheng.dsh.api.endpoints import admin

    async def read(**query):
        with Session(audit_db) as session:
            return DshAuditRepository(session).list_records(**query)

    authorize = AsyncMock(return_value=({}, 2))
    service = DshManagementService(
        repository_scope=None,
        gateway=None,
        profiles=None,
        policy=None,
        policy_view=None,
        now=None,
        authorize=authorize,
        audit_view=read,
    )
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1")
    app.dependency_overrides[admin.admin_user] = lambda: SimpleNamespace(user_id=21)
    app.dependency_overrides[admin.get_management] = lambda: service
    statements = []
    event.listen(audit_db, "before_cursor_execute", lambda conn, cur, sql, params, ctx, many: statements.append(sql))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dsh/admin/audit-records?limit=2")
        assert response.json()["status_message"] == "SUCCESS"
        assert len(assert_resp_200(response)["data"]) == 2
        authorize.assert_awaited_once_with(21, None)
        for params in ("limit=0", "limit=101", "action=UNKNOWN", "status=UNKNOWN", "tenant_id=0"):
            assert (await client.get(f"/api/v1/dsh/admin/audit-records?{params}")).status_code == 422
        authorize.side_effect = HTTPException(403, "Forbidden")
        assert (await client.get("/api/v1/dsh/admin/audit-records?tenant_id=3")).status_code == 403

        def denied():
            raise HTTPException(401, "Unauthenticated")

        app.dependency_overrides[admin.admin_user] = denied
        assert (await client.get("/api/v1/dsh/admin/audit-records")).status_code == 401
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
