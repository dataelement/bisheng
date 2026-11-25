"""Hint refresh uses old tables and never invents a business binding. 覆盖 AC: AC-08, AC-09, AC-11, AC-14."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.services.saved_bindings import binding_payload, saved_bindings
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceType, TargetKey
from bisheng.resource_reference.application.source_sync import refresh_root
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for model in (Tenant, Flow, FlowVersion, LLMModel, BusinessReferenceSet, BusinessResourceReference):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    with tenant_execution_scope(101):
        async with sessions() as session, session.begin():
            session.add(Tenant(id=101, tenant_code="e2e-reference-tenant", tenant_name="Test"))
            session.add(Flow(id="w", tenant_id=101, name="workflow", flow_type=10))
            session.add(
                FlowVersion(
                    id=1,
                    flow_id="w",
                    tenant_id=101,
                    name="one",
                    data={
                        "nodes": [
                            {
                                "data": {
                                    "id": "llm",
                                    "type": "llm",
                                    "group_params": [{"params": [{"key": "model_id", "value": 11}]}],
                                }
                            }
                        ]
                    },
                )
            )
            session.add(LLMModel(id=11, tenant_id=101, server_id=1, model_name="model", model_type="llm"))
    yield sessions
    await engine.dispose()


async def test_refresh_replaces_current_config_and_cleans_removed_source(database):
    assert (await refresh_root(101, SourceType.WORKFLOW_VERSION, "w", session_factory=database))["references"] == 1
    assert (await refresh_root(101, SourceType.WORKFLOW_VERSION, "w", session_factory=database))["references"] == 1
    with tenant_execution_scope(101):
        async with database() as session, session.begin():
            rows = (await session.execute(select(BusinessResourceReference))).scalars().all()
            assert len(rows) == 1 and rows[0].target_id == "11"
            root = await session.get(Flow, "w")
            root.is_delete = 1
    assert (await refresh_root(101, SourceType.WORKFLOW_VERSION, "w", session_factory=database))["references"] == 0


def test_saved_app_uses_original_id_and_only_unknown_slot_remains_unresolved():
    declaration = {"models": [{"name": "alpha"}, {"name": "beta"}]}
    _, _, missing = saved_bindings(declaration, {})
    assert len(missing) == 2
    from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
    from bisheng.app_publish.domain.services.reference_extractor import extract_app_reference_requests

    requests = extract_app_reference_requests(CapabilityDeclaration.model_validate(declaration))
    alpha = next(item for item in requests if item.requested_name == "alpha")
    old = SimpleNamespace(slot_key=alpha.slot_key, target_type="model", target_id="11")
    _, refs, missing = saved_bindings(declaration, {}, (old,))
    assert refs == (ReferenceSpec(alpha.slot_key, TargetKey("model", "11")),)
    assert len(missing) == 1
    _, refs2, missing2 = saved_bindings(declaration, {"resource_bindings": binding_payload(refs)}, ())
    assert refs2 == refs and missing2 == missing


def test_present_but_corrupt_business_binding_never_falls_back_to_index():
    declaration = {"knowledge_bases": [{"id": "7"}]}
    _, refs, _ = saved_bindings(declaration, {})
    assert refs[0].target.target_id == "7"
    _, refs, missing = saved_bindings(declaration, {"resource_bindings": None})
    assert not refs and missing


def test_notification_broker_failure_does_not_change_business_result(monkeypatch):
    from unittest.mock import Mock

    from bisheng.resource_reference.application.source_sync import notify_reference_sync_sync
    from bisheng.worker.resource_reference import sync_reference_root

    publish = Mock(side_effect=OSError("broker unavailable"))
    monkeypatch.setattr(sync_reference_root, "apply_async", publish)
    notify_reference_sync_sync(101, "assistant", "a")
    assert publish.call_args.kwargs["headers"] == {"tenant_id": 101}
    assert publish.call_args.kwargs["kwargs"]["tenant_id"] == 101


def test_failed_refresh_uses_existing_celery_retry(monkeypatch):
    from unittest.mock import Mock

    from sqlalchemy.exc import SQLAlchemyError

    from bisheng.worker import resource_reference as worker

    class RetryRequested(Exception):
        pass

    monkeypatch.setattr(worker, "run_async_task", Mock(side_effect=SQLAlchemyError("temporary failure")))
    task = SimpleNamespace(
        request=SimpleNamespace(headers={"tenant_id": 101}, retries=2, id="test"),
        retry=Mock(side_effect=RetryRequested()),
    )
    with pytest.raises(RetryRequested):
        worker.sync_reference_root.run(task, tenant_id=101, source_type="assistant", source_id="a")
    assert task.retry.call_args.kwargs["countdown"] == 60


def test_refresh_refuses_mismatched_tenant_header():
    from bisheng.worker.resource_reference import sync_reference_root

    task = SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 202}))
    with pytest.raises(ValueError, match="tenant header mismatch"):
        sync_reference_root.run(task, tenant_id=101, source_type="assistant", source_id="a")


@pytest.mark.parametrize(
    "kind,source,row,targets,complete",
    [
        (
            SourceType.ASSISTANT,
            "a",
            {"model_name": "legacy name", "knowledge_ids": [7]},
            {("knowledge_space", "7")},
            False,
        ),
        (
            SourceType.CHANNEL_SYNC,
            "c",
            {"rows": [{"knowledge_space_id": 7, "folder_id": 9, "enabled": False}]},
            {("knowledge_space", "7"), ("knowledge_file", "9")},
            True,
        ),
        (
            SourceType.KNOWLEDGE,
            "7",
            {"model": "11", "model_transition": None, "metadata_fields": [{"value": "model:99"}]},
            {("model", "11")},
            True,
        ),
        (
            SourceType.KNOWLEDGE,
            "7",
            {"model": "bge-large-zh", "model_transition": None},
            set(),
            False,
        ),
        (
            SourceType.MODEL_DEFAULT,
            "assistant_llm",
            {"value": '{"llm_list":[{"model_id":11,"default":true}]}'},
            {("model", "11")},
            True,
        ),
    ],
)
def test_saved_business_shapes_keep_models_and_disabled_channels_but_ignore_metadata(
    kind, source, row, targets, complete
):
    from bisheng.resource_reference.application.source_sync import extract_snapshot

    _, refs, _, ready = extract_snapshot(kind, source, {"version": "current", **row}, ())
    assert {(ref.target.target_type.value, ref.target.target_id) for ref in refs} == targets
    assert ready is complete


def test_optional_task_module_failure_does_not_turn_committed_business_into_failure(monkeypatch):
    import sys

    from bisheng.resource_reference.application.source_sync import notify_reference_sync_sync

    monkeypatch.setitem(sys.modules, "bisheng.worker.resource_reference", None)
    assert notify_reference_sync_sync(101, "assistant", "a") is None


async def test_queued_refresh_after_tenant_deletion_cleans_hints_even_if_business_root_remains(database):
    await refresh_root(101, SourceType.WORKFLOW_VERSION, "w", session_factory=database)
    with tenant_execution_scope(101):
        async with database() as session, session.begin():
            await session.execute(delete(Tenant).where(Tenant.id == 101))
    result = await refresh_root(101, SourceType.WORKFLOW_VERSION, "w", session_factory=database)
    assert result["references"] == 0
    with tenant_execution_scope(101):
        async with database() as session:
            assert not (await session.execute(select(BusinessResourceReference))).scalars().all()
