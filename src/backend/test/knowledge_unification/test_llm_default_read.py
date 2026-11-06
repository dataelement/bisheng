"""T472: raw repair metadata and strict whole-key default execution stay separate.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-89, AC-91, AC-92
"""

import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
from bisheng.llm.application import model_default_read as defaults
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.application.source_read_target_owner import ModelSourceReadTargetOwner
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_model_default_native_target as native
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant


@pytest.fixture
async def reads(tmp_path, model_owner_tenant, monkeypatch):
    path = tmp_path / "defaults.db"
    engine = create_engine(f"sqlite:///{path}")
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    for table in native.TABLES:
        table.create(engine)
    with Session(engine) as session, session.begin():
        models.setup(session)
    identity = ModelDefaultReadIdentityPort()
    owner = ModelDefaultSourceOwner(identity_port=identity)
    verifier = SourceReadVerifier({"model_default": owner}, identity)
    target = ModelSourceReadTargetOwner(
        verifier, legacy_evidence=KnowledgeReferenceReadLegacyEvidence(verifier), sharing=models.FrozenSharing()
    )
    core = ReferenceSourceReadRuntime(verifier, SourceReadRepository(verifier), {"model": target})
    facade = defaults.ModelDefaultReadRuntime(core, identity)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    @asynccontextmanager
    async def asession_factory():
        async with AsyncSession(async_engine) as session:
            yield session

    monkeypatch.setattr(defaults, "get_sync_db_session", session_factory)
    monkeypatch.setattr(defaults, "get_async_db_session", asession_factory)
    yield SimpleNamespace(engine=engine, async_engine=async_engine, facade=facade, core=core, identity=identity)
    await async_engine.dispose()
    engine.dispose()


@pytest.mark.parametrize("native_sync", [False, True])
async def test_raw_management_preserves_unindexed_original_id_while_execute_refuses(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value='{"model_id":777}'))
    raw = (
        reads.facade.get_default("evaluation_llm") if native_sync else await reads.facade.aget_default("evaluation_llm")
    )
    assert json.loads(raw.payload_json)["model_id"] == 777 and raw.source.tenant_id == 101
    with pytest.raises(ReferenceCoverageNotReadyError):
        if native_sync:
            reads.facade.require_default("evaluation_llm")
        else:
            await reads.facade.arequire_default("evaluation_llm")


@pytest.mark.parametrize("native_sync", [False, True])
async def test_valid_inherited_source_returns_original_root_without_child_copy(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, tenant_id=1, payload={"model_id": 22})
    value = (
        reads.facade.require_default("evaluation_llm")
        if native_sync
        else await reads.facade.arequire_default("evaluation_llm")
    )
    assert json.loads(value.payload_json)["model_id"] == 22 and value.source_key.tenant_id == 1
    assert get_current_tenant_id() == 101
    with pytest.raises(FrozenInstanceError):
        value.payload_json = "{}"
    with Session(reads.engine) as session:
        assert not session.execute(
            delete(TenantSystemModelConfig).where(TenantSystemModelConfig.tenant_id == 101)
        ).rowcount
        session.rollback()


@pytest.mark.parametrize("native_sync", [False, True])
async def test_invalid_optional_model_blocks_entire_key_and_all_slots(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(
            session,
            key="linsight_llm",
            payload={"chat_title_llm": {"id": "11", "name": "ok"}, "models": [{"id": "99", "name": "invalid"}]},
        )
        native.seed_default(session, key="evaluation_llm", payload={"model_id": 11})
    raw = reads.facade.get_default("linsight_llm") if native_sync else await reads.facade.aget_default("linsight_llm")
    assert json.loads(raw.payload_json)["models"][0]["id"] == "99"
    with pytest.raises(ResourceReferenceInvalidError):
        if native_sync:
            reads.facade.require_default_slot("linsight_llm", "chat_title_llm.id")
        else:
            await reads.facade.arequire_default_slot("linsight_llm", "chat_title_llm.id")
    other = (
        reads.facade.require_default("evaluation_llm")
        if native_sync
        else await reads.facade.arequire_default("evaluation_llm")
    )
    assert json.loads(other.payload_json)["model_id"] == 11


@pytest.mark.parametrize("native_sync", [False, True])
async def test_unconfigured_has_explicit_empty_value_but_own_empty_requires_zero_index(reads, native_sync):
    value = (
        reads.facade.require_default("evaluation_llm")
        if native_sync
        else await reads.facade.arequire_default("evaluation_llm")
    )
    assert value.payload_json == "{}" and value.source_key is None
    with Session(reads.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value="{}"))
    with pytest.raises(ReferenceCoverageNotReadyError):
        if native_sync:
            reads.facade.require_default("evaluation_llm")
        else:
            await reads.facade.arequire_default("evaluation_llm")


@pytest.mark.parametrize("native_sync", [False, True])
async def test_ready_zero_set_is_a_real_admitted_source(reads, native_sync):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, payload={})
    value = (
        reads.facade.require_default("evaluation_llm")
        if native_sync
        else await reads.facade.arequire_default("evaluation_llm")
    )
    assert value.payload_json == "{}" and value.source_key.tenant_id == 101


async def test_return_value_comes_from_admitted_snapshot_not_earlier_raw_candidate(reads, monkeypatch):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session, tenant_id=1, payload={"model_id": 22})
    actual = reads.facade.repository.aresolve

    async def stale_candidate(session, key):
        result = await actual(session, key)
        return replace(result, source=replace(result.source, value='{"model_id":11}'))

    monkeypatch.setattr(reads.facade.repository, "aresolve", stale_candidate)
    value = await reads.facade.arequire_default("evaluation_llm")
    assert json.loads(value.payload_json)["model_id"] == 22


async def test_external_session_is_retained_without_commit_or_autoflush(reads):
    with Session(reads.engine) as session, session.begin():
        native.seed_default(session)
    async with AsyncSession(reads.async_engine) as session:
        pending = TenantSystemModelConfig(tenant_id=101, key="workflow_llm", value='{"model_id":11}')
        session.add(pending)
        value = await reads.facade.arequire_default("evaluation_llm", session=session)
        assert json.loads(value.payload_json)["model_id"] == 11 and pending.id is None and session.in_transaction()
        await session.rollback()
    with Session(reads.engine) as session:
        assert not session.execute(
            delete(TenantSystemModelConfig).where(TenantSystemModelConfig.key == "workflow_llm")
        ).rowcount
        session.rollback()


def test_default_factory_requires_actual_explicit_composition(monkeypatch):
    monkeypatch.setattr(defaults, "_runtime", None)
    with pytest.raises(ReferenceCoverageNotReadyError):
        defaults.get_model_default_read_runtime()
