"""Initial v0 creation joins SQL-backed reference maintenance atomically.

覆盖 AC: AC-68, AC-87, AC-88, AC-89. Only target and FGA transport boundaries
are test adapters; extraction, binding runtime, repositories and SQL are real.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services import flow as flow_service
from bisheng.api.services.f048_application_permission import F048ApplicationPermissionAdapter
from bisheng.api.v1 import workflow as workflow_endpoint
from bisheng.common.errcode.flow import WorkflowNameExistsError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models import flow as flow_model
from bisheng.database.models import flow_version as version_model
from bisheng.database.models.flow import FlowCreate
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.contracts import (
    ReferenceState,
    TargetLockReceipt,
    TransactionIdentity,
    VerifiedReferenceTarget,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_wf_transaction as wf_fixtures
from test.knowledge_unification.test_ref_repo import TABLES
from test.knowledge_unification.test_wf_extract import graph, node

store = wf_fixtures.store
tenant = wf_fixtures.tenant


class SqlTargetOwner:
    """Test Owner resolves a real SQL target row and issues transaction receipts."""

    def __init__(self, table):
        self.table = table

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        receipts = []
        for key in target_keys:
            row = (
                (
                    await session.execute(
                        sa.select(self.table)
                        .where(
                            self.table.c.target_id == key.target_id, self.table.c.target_type == key.target_type.value
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ResourceReferenceInvalidError(reason="test_target_missing")
            target = VerifiedReferenceTarget(
                key,
                row["tenant_id"],
                row["space_id"],
                "1" if key.target_type.value == "model" else None,
                ReferenceState.VALID,
                "r1",
            )
            receipts.append(TargetLockReceipt(source_key, target, TransactionIdentity.capture(session), self))
        return tuple(receipts)

    def lock_and_verify(self, session, target_keys, source_key, operation):
        raise AssertionError("async workflow must use native async Owner I/O")


@pytest.fixture
async def bindings(store, monkeypatch):
    async_engine, sync_engine = store
    for table in TABLES:
        table.create(sync_engine)
    metadata = sa.MetaData()
    targets = sa.Table(
        "wf_test_target",
        metadata,
        sa.Column("target_type", sa.String, primary_key=True),
        sa.Column("target_id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("space_id", sa.String),
    )
    metadata.create_all(sync_engine)
    with sync_engine.begin() as connection:
        connection.execute(targets.insert(), [{"target_type": "model", "target_id": "7", "tenant_id": 101}])
    owner = SqlTargetOwner(targets)
    verifier = ReferenceTargetVerifier({"model": owner, "knowledge_space": owner, "knowledge_file": owner})
    repository = ReferenceRepository(verifier=verifier)
    runtime = ReferenceBindingRuntime(repository, verifier)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(flow_service, "get_async_db_session", session_factory, raising=False)
    monkeypatch.setattr(flow_model, "get_async_db_session", session_factory)
    monkeypatch.setattr(version_model, "get_async_db_session", session_factory)
    monkeypatch.setattr(version_model, "get_sync_db_session", flow_model.get_sync_db_session)
    monkeypatch.setattr(workflow_endpoint, "get_sync_db_session", flow_model.get_sync_db_session)
    monkeypatch.setattr(flow_service, "get_reference_binding_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(flow_service.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(flow_service.telemetry_service, "log_event_sync", Mock())
    permission = SimpleNamespace(authorize_created=AsyncMock())
    loader = SimpleNamespace(load_permission_record=AsyncMock(side_effect=AssertionError("must not reload new root")))
    adapter = F048ApplicationPermissionAdapter(loader=loader, permission=permission)
    monkeypatch.setattr(flow_service, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(
        flow_service, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(tenant_id=101, user_id=11))
    )
    monkeypatch.setattr(flow_service.AuditLogService, "create_build_workflow", Mock())
    monkeypatch.setattr(flow_service.FlowService, "get_logo_share_link", Mock())
    return SimpleNamespace(
        runtime=runtime,
        repository=repository,
        session_factory=session_factory,
        permission=permission,
        loader=loader,
        sync_engine=sync_engine,
        user=SimpleNamespace(user_id=11, tenant_id=101),
        request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}),
    )


async def create(context, name="new-workflow", saved_data=None):
    return await workflow_endpoint.create_flow.__wrapped__(
        request=context.request,
        flow=FlowCreate(name=name, data=saved_data),
        login_user=context.user,
    )


def rows(context, table):
    with context.sync_engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT * FROM {table}")).mappings().all()


async def test_actual_create_endpoint_registers_v0_using_its_database_generated_id(bindings):
    result = await create(bindings, saved_data=graph(node("llm", "llm", model_id=7)))
    assert result.status_code == 200 and result.data.version_id is not None
    sources = [row for row in rows(bindings, "business_reference_set") if row["record_kind"] == "source"]
    assert len(sources) == 1
    assert (sources[0]["source_id"], sources[0]["source_version"], sources[0]["effective"], sources[0]["ready"]) == (
        result.data.id,
        str(result.data.version_id),
        1,
        1,
    )
    references = rows(bindings, "business_resource_reference")
    assert [(row["slot_key"], row["target_id"], row["source_version"]) for row in references] == [
        ("node:llm.model_id", "7", str(result.data.version_id))
    ]
    bindings.permission.authorize_created.assert_awaited_once()
    bindings.loader.load_permission_record.assert_not_awaited()


async def test_empty_initial_draft_is_indexed_as_a_ready_zero_reference_source(bindings):
    result = await create(bindings, saved_data={})
    sources = [row for row in rows(bindings, "business_reference_set") if row["record_kind"] == "source"]
    assert len(sources) == 1 and sources[0]["source_version"] == str(result.data.version_id)
    assert sources[0]["ready"] == 1 and not rows(bindings, "business_resource_reference")


async def test_binding_failure_rolls_back_initial_root_v0_index_and_details(bindings, monkeypatch):
    original = bindings.runtime.aapply_source_bindings

    async def fail_after_binding_write(session, prepared):
        await original(session, prepared)
        raise RuntimeError("binding write failed")

    monkeypatch.setattr(bindings.runtime, "aapply_source_bindings", fail_after_binding_write)
    with pytest.raises(RuntimeError, match="binding write failed"):
        await create(bindings, saved_data=graph(node("llm", "llm", model_id=7)))
    assert all(row["name"] != "new-workflow" for row in rows(bindings, "flow"))
    assert {row["id"] for row in rows(bindings, "flowversion")} == {1, 2, 3}
    assert not rows(bindings, "business_reference_set") and not rows(bindings, "business_resource_reference")
    bindings.permission.authorize_created.assert_not_awaited()


async def test_copy_or_import_new_root_cannot_introduce_a_missing_target(bindings):
    with pytest.raises(ResourceReferenceInvalidError):
        await create(bindings, saved_data=graph(node("llm", "llm", model_id=999)))
    assert all(row["name"] != "new-workflow" for row in rows(bindings, "flow"))
    assert not rows(bindings, "business_reference_set")
    bindings.permission.authorize_created.assert_not_awaited()


async def test_projection_precedes_business_commit_without_reloading_uncommitted_root(bindings):
    async def assert_not_committed(**kwargs):
        target = kwargs["target"]
        assert all(row["id"] != target.resource_id for row in rows(bindings, "flow"))
        assert not rows(bindings, "business_reference_set")

    bindings.permission.authorize_created.side_effect = assert_not_committed
    result = await create(bindings, saved_data=graph(node("llm", "llm", model_id=7)))
    assert any(row["id"] == result.data.id for row in rows(bindings, "flow"))
    bindings.loader.load_permission_record.assert_not_awaited()


async def test_projection_failure_does_not_commit_business_or_reference_rows(bindings):
    bindings.permission.authorize_created.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await create(bindings, saved_data=graph(node("llm", "llm", model_id=7)))
    assert all(row["name"] != "new-workflow" for row in rows(bindings, "flow"))
    assert not rows(bindings, "business_reference_set") and not rows(bindings, "business_resource_reference")


async def test_duplicate_workflow_name_preserves_existing_business_guard(bindings):
    with pytest.raises(type(WorkflowNameExistsError.http_exception())):
        await create(bindings, name="workflow", saved_data={})
    assert not rows(bindings, "business_reference_set")
    bindings.permission.authorize_created.assert_not_awaited()
