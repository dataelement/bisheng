"""T530: an override cannot use its disappearing inheritance as new eligibility.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-92
Actual model/config/reference SQL; only the permission transport is replaced.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.application import reference_target_owner as module
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_model_reference_owner as models
from test.knowledge_unification.test_ref_repo import tenant

model_owner_tenant = models.model_owner_tenant
SOURCE = SourceKey(101, "model_default", "evaluation_llm", "current")
TARGETS = (TargetKey("model", "22"),)


@pytest.fixture
async def db(model_owner_tenant, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for table in models.TABLES:
            await conn.run_sync(lambda connection, table=table: table.create(connection))
    async with AsyncSession(engine) as session, session.begin():
        await session.run_sync(models.setup)
        session.add(TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":22}'))
    permissions = AsyncMock(list_resource_ids=AsyncMock(return_value=()))
    monkeypatch.setattr(module, "get_permission_relation_api", AsyncMock(return_value=permissions))
    yield engine, permissions
    await engine.dispose()


async def test_new_override_cannot_consume_the_inheritance_it_replaces(db):
    async with AsyncSession(db[0]) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await ModelReferenceTargetOwner().alock_and_verify(session, TARGETS, SOURCE, "bind")


@pytest.mark.parametrize("proof", ["fga", "other_key"])
async def test_explicit_share_or_another_still_inherited_key_is_eligible(db, proof):
    async with AsyncSession(db[0]) as session, session.begin():
        if proof == "fga":
            db[1].list_resource_ids.return_value = ("2",)
        else:
            session.add(TenantSystemModelConfig(tenant_id=1, key="workflow_llm", value='{"model_id":22}'))
            await session.flush()
        receipt = (await ModelReferenceTargetOwner().alock_and_verify(session, TARGETS, SOURCE, "bind"))[0]
        assert receipt.target.new_binding_allowed and receipt.target.target_tenant_id == 1


async def test_knowledge_binding_does_not_remove_default_inheritance(db):
    async with AsyncSession(db[0]) as session, session.begin():
        receipt = (
            await ModelReferenceTargetOwner().alock_and_verify(
                session, TARGETS, SourceKey(101, "knowledge", "1", "current"), "bind"
            )
        )[0]
        assert receipt.target.new_binding_allowed


async def test_existing_exact_override_reference_can_still_be_retained_or_removed(db):
    async with AsyncSession(db[0]) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value='{"model_id":22}'))
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="model_default",
                source_id="evaluation_llm",
                source_version="current",
                slot_key="model_id",
                target_type="model",
                target_id="22",
                target_tenant_id=1,
                source_revision=1,
            )
        )
    async with AsyncSession(db[0]) as session, session.begin():
        receipt = (await ModelReferenceTargetOwner().alock_and_verify(session, TARGETS, SOURCE, "bind"))[0]
        assert receipt.target.state == "valid" and not receipt.target.new_binding_allowed


def native_store(f118_engine):
    for table in models.TABLES:
        table.create(f118_engine)
    with Session(f118_engine) as session, session.begin():
        models.setup(session)
        session.add(TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":22}'))
    return f118_engine


@pytest.mark.parametrize("source,allow", [("knowledge", False), ("model_default", True)])
def test_sync_uses_native_permission_port_and_actual_inherited_server_sql(
    f118_engine, model_owner_tenant, monkeypatch, source, allow
):
    engine = native_store(f118_engine)
    api = Mock(list_resource_ids_sync=Mock(return_value=("2",) if allow else ()))
    monkeypatch.setattr(module, "get_permission_relation_api_sync", Mock(return_value=api), raising=False)
    with Session(engine) as session, session.begin():
        key = SOURCE if source == "model_default" else SourceKey(101, "knowledge", "1", "current")
        receipt = ModelReferenceTargetOwner().lock_and_verify(session, TARGETS, key, "bind")[0]
        assert receipt.target.state == "valid" and receipt.target.new_binding_allowed
        api.list_resource_ids_sync.assert_called_once()


def test_sync_native_permission_error_is_not_an_inherited_or_own_only_fallback(
    f118_engine, model_owner_tenant, monkeypatch
):
    engine = native_store(f118_engine)
    api = Mock(list_resource_ids_sync=Mock(side_effect=RuntimeError("permission unavailable")))
    monkeypatch.setattr(module, "get_permission_relation_api_sync", Mock(return_value=api), raising=False)
    with Session(engine) as session, session.begin(), pytest.raises(RuntimeError):
        ModelReferenceTargetOwner().lock_and_verify(
            session, TARGETS, SourceKey(101, "knowledge", "1", "current"), "bind"
        )


def test_root_original_default_remains_own_and_never_queries_child_sharing(
    f118_engine, model_owner_tenant, monkeypatch
):
    engine = native_store(f118_engine)
    api = Mock(side_effect=AssertionError("Root own is not a sharing query"))
    monkeypatch.setattr(module, "get_permission_relation_api_sync", api, raising=False)
    with tenant(1), Session(engine) as session, session.begin():
        receipt = ModelReferenceTargetOwner().lock_and_verify(
            session, TARGETS, SourceKey(1, "model_default", "evaluation_llm", "current"), "bind"
        )[0]
        assert receipt.target.new_binding_allowed
    api.assert_not_called()


def test_native_accessor_only_unready_reason_maps_to_reference_coverage(f118_engine, model_owner_tenant, monkeypatch):
    from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    engine = native_store(f118_engine)
    unavailable = PermissionServiceUnavailableError(reason="permission_runtime_not_ready")
    monkeypatch.setattr(module, "get_permission_relation_api_sync", Mock(side_effect=unavailable))
    with Session(engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError) as observed:
            ModelReferenceTargetOwner().lock_and_verify(
                session, TARGETS, SourceKey(101, "knowledge", "1", "current"), "bind"
            )
        assert observed.value.__cause__ is unavailable
    broken_ready = PermissionServiceUnavailableError(msg="READY component is malformed")
    monkeypatch.setattr(module, "get_permission_relation_api_sync", Mock(side_effect=broken_ready))
    with Session(engine) as session, session.begin():
        with pytest.raises(PermissionServiceUnavailableError) as observed:
            ModelReferenceTargetOwner().lock_and_verify(
                session, TARGETS, SourceKey(101, "knowledge", "1", "current"), "bind"
            )
        assert observed.value is broken_ready


async def test_malformed_backend_membership_cannot_be_ignored_in_favor_of_inheritance(db):
    db[1].list_resource_ids.return_value = ("not-a-server-id",)
    async with AsyncSession(db[0]) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await ModelReferenceTargetOwner().alock_and_verify(
                session, TARGETS, SourceKey(101, "knowledge", "1", "current"), "bind"
            )
