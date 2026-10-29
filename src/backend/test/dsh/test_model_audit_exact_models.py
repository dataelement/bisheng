"""AC-21: ID and historical names are exclusive exact filters with indexed pagination.

Coverage AC: AC-03, AC-45, AC-49.
"""

from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy import event, text

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.model_audit_maintenance import backfill_name_digests
from test.dsh.model_audit_fixtures import NOW, audit_database, audit_session
from test.dsh.test_model_audit_flow import BASE, LOCAL_ADMIN, call, fixture


async def test_exact_model_filters_match_ids_and_complete_names_without_like_or_distinct():
    async with fixture() as (harness, client, _objects):
        # Keep manually inserted fixed-time records inside the relative query window.
        harness.queries.now = lambda: NOW + timedelta(seconds=1)
        names = ["Provider / Old%_name", "Provider / Old%_name extra", "Provider / Renamed", "Provider / Old%_name"]
        for tenant in (2, 3):
            with audit_session(harness.engine, tenant) as session, session.begin():
                for index, name in enumerate(names):
                    session.add(
                        DshModelAuditRequest(
                            request_id=f"e2e-audit-model-{tenant}-{index}",
                            user_id=20,
                            model_id=42 if index < 3 else 43,
                            model_name=name,
                            model_name_digest=sha256(name.encode()).hexdigest(),
                            started_at=NOW,
                        )
                    )
                # Even an incorrect/colliding digest must not match another original name.
                session.add(
                    DshModelAuditRequest(
                        request_id=f"e2e-audit-collision-{tenant}",
                        user_id=20,
                        model_id=44,
                        model_name="unrelated",
                        model_name_digest=sha256(names[0].encode()).hexdigest(),
                        started_at=NOW,
                    )
                )
        sql = []

        def observed(_connection, _cursor, statement, _params, _context, _many):
            sql.append(statement.upper())

        event.listen(harness.engine, "before_cursor_execute", observed)
        try:
            response = await client.get(
                BASE + "/requests", headers=LOCAL_ADMIN, params={"model_name": names[0], "limit": 1}
            )
            page = response.json()["data"]
            first = page["items"]
            assert len(first) == 1 and first[0]["model_name"] == names[0]
            page2 = (
                await client.get(
                    BASE + "/requests",
                    headers=LOCAL_ADMIN,
                    params={"model_name": names[0], "limit": 1, "cursor": page["next_cursor"]},
                )
            ).json()["data"]
            assert len(page2["items"]) == 1 and page2["next_cursor"] is None
            assert {first[0]["request_id"], page2["items"][0]["request_id"]} == {
                "e2e-audit-model-2-0",
                "e2e-audit-model-2-3",
            }
            by_id = (await client.get(BASE + "/requests", headers=LOCAL_ADMIN, params={"model_id": 42})).json()["data"][
                "items"
            ]
            assert len(by_id) == 3 and all(row["model_id"] == 42 for row in by_id)
            for name in ("Old", "provider / Old%_name", names[0] + " "):
                empty = await client.get(BASE + "/requests", headers=LOCAL_ADMIN, params={"model_name": name})
                assert empty.json()["data"]["items"] == []
            conflict = await client.get(
                BASE + "/requests", headers=LOCAL_ADMIN, params={"model_id": 42, "model_name": names[0]}
            )
            assert conflict.json()["status_code"] == 26131
        finally:
            event.remove(harness.engine, "before_cursor_execute", observed)
        audit_sql = [s for s in sql if "FROM DSH_MODEL_AUDIT_REQUEST" in s]
        assert audit_sql and all(" LIKE " not in s and "DISTINCT" not in s and "COUNT(" not in s for s in audit_sql)


async def test_new_audit_writes_include_exact_name_digest():
    async with fixture() as (harness, client, _objects):
        response = await call(client)
        await harness.drain()
        with audit_session(harness.engine) as session:
            row = session.get(DshModelAuditRequest, response.headers["x-request-id"])
            assert row.model_name_digest == sha256(row.model_name.encode("utf8")).hexdigest()


def test_backfill_is_bounded_dry_run_by_default_idempotent_and_tenant_scoped():
    with audit_database() as engine:
        for tenant in (2, 3):
            with audit_session(engine, tenant) as session, session.begin():
                for index in range(3):
                    session.add(
                        DshModelAuditRequest(
                            request_id=f"e2e-backfill-{tenant}-{index}", model_name="Provider / Old", started_at=NOW
                        )
                    )
        with audit_session(engine) as session, session.begin():
            dry = backfill_name_digests(session, limit=1)
            assert dry["updated"] == 0 and dry["examined"] == 1 and dry["has_more"]
            assert session.get(DshModelAuditRequest, "e2e-backfill-2-0").model_name_digest is None
        with audit_session(engine) as session, session.begin():
            first = backfill_name_digests(session, limit=1, apply=True)
            assert first["updated"] == 1 and first["has_more"]
        with audit_session(engine) as session, session.begin():
            rest = backfill_name_digests(session, after=first["after_request_id"], limit=10, apply=True)
            assert rest["updated"] == 2 and not rest["has_more"]
            assert backfill_name_digests(session, apply=True)["examined"] == 0
        with audit_session(engine, 3) as session:
            assert session.get(DshModelAuditRequest, "e2e-backfill-3-0").model_name_digest is None
        with audit_session(engine) as session:
            for column, value, index in (
                ("model_id", 42, "ix_dma_request_model"),
                ("model_name_digest", "a" * 64, "ix_dma_request_name"),
            ):
                plan = session.execute(
                    text(
                        f"EXPLAIN QUERY PLAN SELECT request_id FROM dsh_model_audit_request WHERE tenant_id=:tenant AND {column}=:value ORDER BY started_at DESC, request_id DESC LIMIT 20"
                    ),
                    {"tenant": 2, "value": value},
                ).all()
                assert index in str(plan)


@pytest.mark.parametrize("value", [0, -1, "not-id", 9223372036854775808])
async def test_model_id_bounds(value):
    async with fixture() as (_harness, client, _objects):
        assert (
            await client.get(BASE + "/requests", headers=LOCAL_ADMIN, params={"model_id": value})
        ).status_code == 422
