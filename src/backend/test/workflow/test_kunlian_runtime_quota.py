"""Formal quota semantics on SQLite, not proof of MySQL/DM8 row locks."""

from dataclasses import asdict

import pytest
from pydantic import ValidationError
from sqlmodel import select

from bisheng.common.errcode.open_api import OpenApiKunlianRateLimitedError
from bisheng.core.config.settings import KunlianApiConf
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User
from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun as Run
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest, RunSubject
from test.workflow.test_kunlian_runtime import formal_store
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE
from test.workflow.test_kunlian_workflow_registration_e2e import example_graph


@pytest.fixture
def quota_store(invocation_registration_store):
    registration = invocation_registration_store
    runs = formal_store(registration)
    with registration.sessions() as session:
        User.__table__.create(session.get_bind())
        UserTenant.__table__.create(session.get_bind())
        session.add(User(user_id=12, user_name="quota", password="unused"))
        session.add(UserTenant(user_id=12, tenant_id=7))
        other_flow = "e" * 32
        session.add(Flow(id=other_flow, tenant_id=7, user_id=11, name="other", status=2))
        session.add(FlowVersion(id=3, flow_id=other_flow, tenant_id=7, name="v3", data=example_graph(), is_current=1))
        session.commit()
    # The pre-change repository accepts this attribute but never enforces it.
    runs.max_active_per_user = 1
    return runs


def admit(runs, key, *, scope=SCOPE, user=12, flow=FLOW_ID, formal=True):
    identity = asdict(RunSubject(scope.tenant_id, scope.connection_id, user, credential_id=1)) if formal else None
    return runs.admit(scope, user, key, RunRequest(workflow_id=flow), identity=identity)


def test_formal_admission_requests_user_lock_before_flow_and_current_quota_read(quota_store, monkeypatch):
    from sqlalchemy.dialects.mysql import dialect
    from sqlmodel import Session

    statements = []
    original = Session.exec

    def capture(session, statement, *args, **kwargs):
        statements.append(str(statement.compile(dialect=dialect())))
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "exec", capture)
    admit(quota_store, "locked")
    locks = [sql for sql in statements if "FOR UPDATE" in sql]
    assert "FROM user " in locks[0]
    flow_index = next(i for i, sql in enumerate(locks) if "FROM flow " in sql)
    quota_index = next(i for i, sql in enumerate(locks) if "FROM workflow_kl_run " in sql)
    assert flow_index > 0 and quota_index > flow_index
    # SQL shape only: SQLite ignores these locks; live dual-DB racing is NOT_RUN.


def test_formal_quota_crosses_workflows_and_replay_precedes_limit(quota_store):
    row, _ = admit(quota_store, "first")
    replay, created = admit(quota_store, "first")
    assert not created and replay.session_id == row.session_id
    with pytest.raises(OpenApiKunlianRateLimitedError):
        admit(quota_store, "second", flow="e" * 32)
    with quota_store.registration.transaction() as session:
        assert len(session.exec(select(Run)).all()) == 1


@pytest.mark.parametrize(
    "status", ["QUEUED", "RUNNING", "WAITING_INPUT", "RESUME_QUEUED", "RESUMING", "CANCEL_REQUESTED"]
)
def test_all_formal_nonterminal_states_hold_slot(quota_store, status):
    row, _ = admit(quota_store, "first")
    with quota_store.registration.transaction() as session:
        session.get(Run, row.session_id).status = status
    with pytest.raises(OpenApiKunlianRateLimitedError):
        admit(quota_store, "next")


def test_candidate_and_other_integration_do_not_consume_formal_slot(quota_store):
    admit(quota_store, "candidate", formal=False)
    admit(quota_store, "other-integration", scope=RegistrationScope(7, "other", 0))
    row, created = admit(quota_store, "formal")
    assert created
    # Candidate compatibility: still admitted even while the formal slot is full.
    assert admit(quota_store, "candidate-next", formal=False)[1]
    with quota_store.registration.transaction() as session:
        session.get(Run, row.session_id).status = "FAILED"
    assert admit(quota_store, "released")[1]


def test_formal_quota_requires_matching_active_membership(quota_store):
    with quota_store.registration.transaction() as session:
        membership = session.exec(select(UserTenant)).one()
        membership.tenant_id = 8
    with pytest.raises(RunError, match="FORBIDDEN"):
        admit(quota_store, "wrong-tenant")


@pytest.mark.parametrize("value", [0, -1, True, "5", 1001])
def test_formal_quota_configuration_is_strictly_bounded(value):
    with pytest.raises(ValidationError):
        KunlianApiConf(max_active_per_user=value)


def test_formal_quota_default_and_factory_wiring(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.config.settings import WorkflowConf
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service

    assert KunlianApiConf().max_active_per_user == 5
    monkeypatch.setattr(
        type(settings), "get_workflow_conf", lambda self: WorkflowConf(kunlian_api={"max_active_per_user": 3})
    )
    service = create_kunlian_runtime_service(resolve_user=None, dispatch=None)
    assert service.repository.max_active_per_user == 3
