"""Audit names follow authorized historical records, never a directory-wide join.

Coverage AC: AC-03, AC-45, AC-49.
"""

import json
from datetime import timedelta

from sqlalchemy import event

from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.user.domain.models.user import User
from test.dsh.model_audit_fixtures import NOW, audit_session
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture
from test.dsh.test_model_audit_groups import row


async def test_names_on_request_detail_pages_and_conversation_groups():
    async with fixture() as (harness, client, _objects):
        # Keep manually inserted fixed-time records inside the relative query window.
        harness.queries.now = lambda: NOW + timedelta(seconds=1)
        with audit_session(harness.engine) as session, session.begin():
            session.add(User(user_id=20, user_name="Audit Alice", password="unused-test-only"))
            session.add(User(user_id=21, user_name="Former User", password="unused-test-only", delete=1))
            session.add(User(user_id=30, user_name="Other Tenant", password="unused-test-only"))
            for index, user in enumerate((20, 20, 21, 22)):
                session.add(row(f"names-{index}", user=user, conversation=f"session-{index}"))
            session.flush()
            repository = DshModelAuditQueryRepository(session)
            for request_id in repository.projection_candidates():
                repository.project_request(request_id, now=NOW)

        statements = []

        def observe(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(harness.engine, "before_cursor_execute", observe)
        try:
            response = await client.get(BASE + "/requests", headers=LOCAL_ADMIN)
        finally:
            event.remove(harness.engine, "before_cursor_execute", observe)
        data = response.json()["data"]
        assert [item["user_name"] for item in data["items"]] == ["Audit Alice", "Audit Alice", "Former User", None]
        assert sum("user_name" in sql and "FROM user" in sql for sql in statements) == 1
        assert "Other Tenant" not in json.dumps(data)
        assert "unused-test-only" not in json.dumps(data)
        detail = (await client.get(BASE + "/requests/names-0", headers=LOCAL_ADMIN)).json()["data"]
        assert detail["user_name"] == "Audit Alice"
        groups = (await client.get(BASE + "/conversation-groups", headers=LOCAL_ADMIN)).json()["data"]
        assert {g["user_name"] for g in groups["items"]} == {"Audit Alice", "Former User", None}
        group = next(g for g in groups["items"] if g["conversation_id"] == "session-0")
        grouped = (
            await client.get(BASE + f"/conversation-groups/{group['conversation_key']}/requests", headers=LOCAL_ADMIN)
        ).json()["data"]
        assert grouped["items"][0]["user_name"] == "Audit Alice"
        assert (await client.get(BASE + "/requests", headers=USER)).status_code == 403
        assert (await client.get(BASE + "/requests", headers=LOCAL_ADMIN, params={"tenant_id": 3})).status_code == 403
        foreign = (await client.get(BASE + "/requests", headers=ADMIN, params={"tenant_id": 3})).json()["data"]
        assert not foreign["items"]
