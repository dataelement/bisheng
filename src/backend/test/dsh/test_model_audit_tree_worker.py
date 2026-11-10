"""AC-H07/H08: independent scheduling, tenant fencing and terminal-history progress."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Repository
from bisheng.dsh.domain.services.model_audit_tree import DshAuditTreeProjectionService
from bisheng.worker.dsh.model_audit_tree import register_audit_tree_tasks
from test.dsh.model_audit_fixtures import audit_database, audit_session
from test.dsh.test_model_audit_tree import add, finish
from test.dsh.test_model_audit_worker import Tasks


@pytest.mark.parametrize(
    "headers,tenant", [({}, 2), ({"tenant_id": "2"}, 2), ({"tenant_id": True}, 1), ({"tenant_id": 3}, 2)]
)
def test_tree_worker_rejects_scope_before_database(headers, tenant):
    """AC-H06/AC-H08: reject untrusted task inputs without acquiring runtime."""
    prepare, _scan = register_audit_tree_tasks(Tasks())
    with pytest.raises(ValueError, match="trusted tenant"):
        prepare(SimpleNamespace(request=SimpleNamespace(headers=headers)), tenant)


def test_terminal_histories_and_dirty_summaries_are_scheduled_without_mode_dependency():
    """AC-H07: all requests can be terminal and mode OFF; no pending call is needed."""
    with audit_database() as engine:
        Tenant.__table__.create(engine, checkfirst=True)
        with audit_session(engine) as session, session.begin():
            session.add(Tenant(id=2, tenant_code="e2e-tree-tenant", tenant_name="e2e-tree-tenant"))
            add(session, "p", "parent")
            repo = Repository(session)
            assert repo.tree_pending_tenants() == [2]
            finish(repo)
            assert repo.tree_pending_tenants() == []
            add(session, "late", "parent", model_result="FAILED")
            assert repo.tree_pending_tenants() == [2]


async def test_projection_service_uses_scoped_committed_steps_and_fenced_failure():
    """AC-H07/AC-H08: run the production background service with isolated SQL."""
    with audit_database() as engine:
        with audit_session(engine) as session, session.begin():
            add(session, "service-p", "parent")
            add(session, "service-c", "child", origin="subagent", parent="parent")

        @contextmanager
        def scope():
            with audit_session(engine) as session, session.begin():
                yield Repository(session)

        service, owner = DshAuditTreeProjectionService(scope), None
        for _ in range(30):
            result = await service.step(2, owner=owner)
            owner = result.get("owner")
            if not result["has_more"]:
                break
        with audit_session(engine) as session, session.begin():
            repo = Repository(session)
            assert repo.tree_page()["items"][0]["branch_summary"]["request_count"] == 2
            state = repo.tree_state(lock=True)
            state.lease_owner = "new-fenced-owner"
            session.add(state)
        await service.failed(2, owner="old-fenced-owner")
        with audit_session(engine) as session:
            state = Repository(session).tree_state()
            assert state.lease_owner == "new-fenced-owner" and not state.failed
