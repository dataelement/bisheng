"""F133 retention uses real file SQLite and independent committed reads."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun as Run
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest, RunSubject
from test.workflow.test_kunlian_runtime import formal_store
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE


def identity(tenant=7):
    return asdict(RunSubject(tenant, SCOPE.connection_id, 12, 1, "sso", "tenant", "subject", 1))


def read_committed(tmp_path, session_id):
    # Separate engine/connection, not the repository's ORM identity map.
    engine = create_engine(f"sqlite:///{tmp_path / 'invocation.sqlite3'}")
    try:
        with Session(engine) as session:
            return Run.model_validate(session.get(Run, session_id))
    finally:
        engine.dispose()


def insert(registration, ident, *, tenant=7, status="FAILED", expires=1000, material=None):
    row = Run(
        session_id=f"{ident:032x}",
        tenant_id=tenant,
        connection_id=SCOPE.connection_id,
        user_id=12,
        workflow_id=FLOW_ID,
        workflow_version_id=1,
        key_digest=f"{ident:064x}",
        request_digest="d" * 64,
        status=status,
        accepted_at=900,
        deadline_at=950,
        finished_at=950,
        expires_at=expires,
        material=material
        if material is not None
        else {
            "runtime_contract": "published-workflow",
            "kunlian_identity": identity(tenant),
            "graph": {"secret": "node-password"},
            "input": {"secret": "input-value"},
            "answer": {"secret": "answer-value"},
            "snapshot": {"secret": "snapshot-value"},
        },
        output={"text": "private-result"},
    )
    with registration.transaction() as session:
        session.add(row)
    return row


async def test_cleanup_keyset_only_scrubs_trusted_expired_terminal(invocation_registration_store, tmp_path):
    from bisheng.worker.workflow.kunlian_runtime import cleanup_batch

    runs = formal_store(invocation_registration_store)
    runs.clock = lambda: 1000
    # Invalid rows occupy pages too; they must not stop forward progress.
    rows = [
        insert(invocation_registration_store, 1, material={"graph": {"secret": "candidate"}}),
        insert(invocation_registration_store, 2),
        insert(invocation_registration_store, 3, tenant=8, status="CANCELLED"),
        insert(invocation_registration_store, 4, status="SUCCEEDED"),
        insert(invocation_registration_store, 5, expires=1001),
        insert(invocation_registration_store, 6, status="RUNNING"),
        insert(
            invocation_registration_store,
            7,
            material={
                "runtime_contract": "published-workflow",
                "kunlian_identity": identity(8),
                "input": {"secret": "bad"},
            },
        ),
    ]
    cursor = None
    with tenant_execution_scope(99):
        for _ in range(6):
            cursor = await cleanup_batch(SimpleNamespace(repository=runs), cursor, limit=1)
            assert get_current_tenant_id() == 99
            if cursor is None:
                break
        assert cursor is None
    for index in (1, 2, 3):
        original = rows[index]
        saved = read_committed(tmp_path, original.session_id)
        assert saved.output is None
        assert saved.material == {
            "runtime_contract": "published-workflow",
            "kunlian_identity": identity(saved.tenant_id),
        }
        for key in (
            "tenant_id",
            "connection_id",
            "user_id",
            "workflow_id",
            "workflow_version_id",
            "key_digest",
            "request_digest",
            "status",
            "expires_at",
        ):
            assert getattr(saved, key) == getattr(original, key)
    for index in (0, 4, 5, 6):
        saved = read_committed(tmp_path, rows[index].session_id)
        assert saved.material == rows[index].material and saved.output == rows[index].output


def test_real_terminal_retains_formal_identity_and_expired_key_cannot_restart(invocation_registration_store, tmp_path):
    runs = formal_store(invocation_registration_store)
    now = [1000]
    runs.clock = lambda: now[0]
    body = RunRequest(workflow_id=FLOW_ID, input={"question": "private"})
    row, _ = runs.admit(SCOPE, 12, "never-restart", body, run_control=True, identity=identity())
    claim = runs.claim(7, row.session_id)
    assert runs.finish(7, row.session_id, claim, output={"text": "private-result"})
    now[0] += runs.retain_seconds
    references, cursor = runs.formal_cleanup_page(limit=1)
    assert references == [(7, SCOPE.connection_id, row.session_id)] and cursor is None
    assert runs.cleanup_formal_expired(7, SCOPE.connection_id, row.session_id)
    saved = read_committed(tmp_path, row.session_id)
    assert saved.output is None and saved.material == {
        "runtime_contract": "published-workflow",
        "kunlian_identity": identity(),
    }
    assert runs.load(7, row.session_id) is None
    with pytest.raises(RunError, match="IDEMPOTENCY_EXPIRED"):
        runs.admit(SCOPE, 12, "never-restart", body)
    with pytest.raises(RunError, match="IDEMPOTENCY_CONFLICT"):
        runs.admit(SCOPE, 12, "never-restart", RunRequest(workflow_id=FLOW_ID))
    assert read_committed(tmp_path, row.session_id).status == "SUCCEEDED"


@pytest.mark.parametrize("mutation", ["identity", "status", "expiry", "connection"])
def test_cleanup_revalidates_discovered_row(invocation_registration_store, tmp_path, mutation):
    runs = formal_store(invocation_registration_store)
    runs.clock = lambda: 1000
    row = insert(invocation_registration_store, 1)
    references, _ = runs.formal_cleanup_page()
    assert references == [(7, SCOPE.connection_id, row.session_id)]
    with invocation_registration_store.transaction() as session:
        stored = session.get(Run, row.session_id)
        if mutation == "identity":
            stored.material = {**stored.material, "kunlian_identity": identity(8)}
        elif mutation == "status":
            stored.status = "RUNNING"
        elif mutation == "expiry":
            stored.expires_at = 1001
        else:
            stored.connection_id = "different-integration"
    assert not runs.cleanup_formal_expired(*references[0])
    assert read_committed(tmp_path, row.session_id).output == row.output


@pytest.mark.parametrize(
    "field,value",
    [
        ("credential_id", True),
        ("user_id", True),
        ("external_user_id", ""),
        ("policy_revision", {"secret": "unexpected-material"}),
    ],
)
def test_cleanup_skips_malformed_identity(invocation_registration_store, tmp_path, field, value):
    runs = formal_store(invocation_registration_store)
    runs.clock = lambda: 1000
    row = insert(
        invocation_registration_store,
        1,
        material={"runtime_contract": "published-workflow", "kunlian_identity": {**identity(), field: value}},
    )
    assert runs.formal_cleanup_page() == ([], None)
    assert not runs.cleanup_formal_expired(7, SCOPE.connection_id, row.session_id)
    assert read_committed(tmp_path, row.session_id).output == row.output


@pytest.mark.parametrize("limit", [0, 101, True, -1])
def test_cleanup_rejects_unbounded_pages(invocation_registration_store, limit):
    runs = formal_store(invocation_registration_store)
    with pytest.raises(ValueError):
        runs.formal_cleanup_page(limit=limit)
