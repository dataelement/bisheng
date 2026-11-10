"""AC-H01/H02/H04/H06: real HTTP/service/SQL with isolated synthetic identity.

The shared audit harness replaces external identity only; this is not proof of
production JWT/OpenFGA. It creates a disposable database and object store.
"""

from datetime import timedelta

from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_content import DshModelAuditBodyAccess
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from test.dsh.model_audit_fixtures import NOW, audit_session
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture
from test.dsh.test_model_audit_tree import add, finish
from test.e2e.helpers.api import assert_resp_200


async def test_tree_http_permissions_filters_and_no_original_prefetch():
    """AC-H01/AC-H04/AC-H06: tenant-scoped tree, same-request filter and zero body reads."""
    async with fixture() as (harness, client, objects):
        harness.queries.now = lambda: NOW + timedelta(seconds=1)
        with audit_session(harness.engine) as session, session.begin():
            add(session, "parent", "parent")
            add(session, "child", "child", origin="subagent", parent="parent", model_result="FAILED")
            finish(Repository(session))
        readiness = assert_resp_200(await client.get(BASE + "/query-readiness", headers=LOCAL_ADMIN))
        assert readiness["hierarchy_available"] and readiness["hierarchy_ready"]
        roots = assert_resp_200(
            await client.get(BASE + "/conversation-tree", headers=ADMIN, params={"audit_status": "ABNORMAL"})
        )
        assert len(roots["items"]) == 1
        parent = roots["items"][0]
        assert parent["conversation_id"] == "parent" and parent["match_scope"] == "DESCENDANT"
        response = await client.get(
            BASE + "/conversation-tree/" + parent["conversation_key"] + "/children",
            headers=LOCAL_ADMIN,
            params={"generation": parent["generation"], "audit_status": "ABNORMAL"},
        )
        assert response.headers["cache-control"] == "no-store"
        child = assert_resp_200(response)["items"][0]
        location = assert_resp_200(
            await client.get(BASE + "/conversation-tree/" + child["conversation_key"] + "/location", headers=ADMIN)
        )
        assert [n["conversation_id"] for n in location["items"]] == ["parent", "child"]
        assert (await client.get(BASE + "/conversation-tree", headers=USER)).status_code == 403
        assert (await client.get(BASE + "/conversation-tree?tenant_id=3", headers=LOCAL_ADMIN)).status_code == 403
        foreign = assert_resp_200(await client.get(BASE + "/conversation-tree?tenant_id=3", headers=ADMIN))
        assert not foreign["items"]
        with audit_session(harness.engine) as session:
            assert not session.exec(select(DshModelAuditBodyAccess)).all()
        assert not objects.data and harness.calls == 0


async def test_tree_strict_query_and_unavailable_identity():
    """AC-H06/AC-H08: reject unknown/duplicate filters and foreign node keys."""
    async with fixture() as (harness, client, _objects):
        with audit_session(harness.engine) as session, session.begin():
            add(session, "p", "parent")
            finish(Repository(session))
        for suffix in ("?model_id=1", "?limit=1&limit=2", "?generation=bad", "?start_at=2026-01-02&end_at=2026-01-01"):
            body = (await client.get(BASE + "/conversation-tree" + suffix, headers=ADMIN)).json()
            assert body["status_code"] == 26131
        missing = (await client.get(BASE + "/conversation-tree/" + "f" * 64 + "/children", headers=ADMIN)).json()
        assert missing["status_code"] == 26132
