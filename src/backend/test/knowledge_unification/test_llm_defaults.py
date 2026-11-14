"""T055: defaults and complete R2 bindings have one real SQL transaction.

覆盖 AC: AC-71, AC-74, AC-87, AC-88, AC-89
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeProcessingConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
from bisheng.llm.application import model_default as application
from bisheng.llm.application.model_default import ModelDefaultApplication
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant


@pytest.fixture
async def business(model_owner_tenant, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        for table in [*models.TABLES, BusinessReferenceSet.__table__]:
            await connection.run_sync(lambda conn, table=table: table.create(conn))
    async with AsyncSession(engine) as session, session.begin():
        await session.run_sync(models.setup)
        session.add(LLMModel(id=12, tenant_id=101, server_id=1, model_name="other", model_type="llm"))
    verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    monkeypatch.setattr(application, "get_reference_binding_runtime", AsyncMock(return_value=runtime))

    async def actor(user):
        return PermissionActor(
            subject_id=user.user_id,
            tenant_id=101,
            super_admin=user.user_id == 99,
            tenant_admin_tenant_ids=frozenset({101}) if user.user_id == 7 else frozenset(),
        )

    monkeypatch.setattr(application, "resolve_permission_actor", actor)
    user = UserPayload(user_id=7, user_name="admin", tenant_id=101, user_role=[])
    yield SimpleNamespace(engine=engine, runtime=runtime, user=user)
    await engine.dispose()


@pytest.mark.parametrize(
    "key,payload,count",
    [
        ("knowledge_llm", {"source_model_id": 11}, 1),
        ("assistant_llm", {"auto_llm": {"model_id": 11}, "llm_list": [{"model_id": 12}]}, 2),
        ("evaluation_llm", {"model_id": 11}, 1),
        ("workflow_llm", {"model_id": 12}, 1),
        ("linsight_llm", {"models": [{"id": "11", "name": "one"}], "chat_default_model_id": "11"}, 2),
    ],
)
async def test_five_original_defaults_write_business_and_index_in_same_session(business, key, payload, count):
    async with AsyncSession(business.engine) as session:
        await ModelDefaultApplication.asave(session, key, payload, login_user=business.user)
        own = await ModelDefaultRepository().aget_own(session, key)
        refs = (
            (await session.execute(select(BusinessResourceReference).where(BusinessResourceReference.source_id == key)))
            .scalars()
            .all()
        )
        assert own.tenant_id == 101 and len(refs) == count
        assert all(ref.source_type == "model_default" and ref.source_version == "current" for ref in refs)
        assert session.in_transaction()
        await session.rollback()
    async with AsyncSession(business.engine) as check:
        assert await ModelDefaultRepository().aget_own(check, key) is None
        assert not (await check.execute(select(BusinessReferenceSet))).all()


async def test_bind_failure_never_saves_a_default_or_zero_ready_placeholder(business):
    async with AsyncSession(business.engine) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 999}, login_user=business.user)
        await session.rollback()
    async with AsyncSession(business.engine) as check:
        assert await ModelDefaultRepository().aget_own(check, "evaluation_llm") is None
        assert not (await check.execute(select(BusinessReferenceSet))).all()


async def test_existing_raw_default_missing_index_is_not_treated_as_new(business):
    async with AsyncSession(business.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value='{"model_id":11}'))
    async with AsyncSession(business.engine) as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 12}, login_user=business.user)
        await session.rollback()
    async with AsyncSession(business.engine) as check:
        assert (await ModelDefaultRepository().aget_own(check, "evaluation_llm")).value == '{"model_id":11}'


async def test_actual_config_index_drift_is_rejected_before_replacement(business):
    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 11}, login_user=business.user)
        await session.execute(
            update(TenantSystemModelConfig)
            .where(TenantSystemModelConfig.tenant_id == 101, TenantSystemModelConfig.key == "evaluation_llm")
            .values(value='{"model_id":12}')
        )
    async with AsyncSession(business.engine) as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 12}, login_user=business.user)
        await session.rollback()


@pytest.mark.parametrize("stage", ["deleted", "deleting"])
async def test_original_tombstone_can_be_repaired_but_deleting_fences_all_writes(business, stage):
    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(session, "knowledge_llm", {"source_model_id": 11}, login_user=business.user)
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_tenant_id=101,
                target_type="model",
                target_id="11",
                operation_id="delete-old",
                operation_type="force_delete_model",
                actor_type="user",
                actor_id="7",
                stage=stage,
            )
        )
        if stage == "deleted":
            await session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
    async with AsyncSession(business.engine) as session:
        if stage == "deleting":
            with pytest.raises(KnowledgeProcessingConflictError):
                await ModelDefaultApplication.asave(
                    session,
                    "knowledge_llm",
                    {"source_model_id": 11, "extract_title_model_id": 12},
                    login_user=business.user,
                )
            await session.rollback()
        else:
            await ModelDefaultApplication.asave(
                session,
                "knowledge_llm",
                {"source_model_id": 11, "extract_title_model_id": 12},
                login_user=business.user,
            )
            assert (
                len(
                    await business.runtime.repository.alist_source_references(
                        session, SourceKey(101, "model_default", "knowledge_llm", "current")
                    )
                )
                == 2
            )
            await session.rollback()


async def test_r2_failure_after_rows_changed_rolls_back_config_and_revisions(business, monkeypatch):
    original = business.runtime.aapply_source_bindings

    async def fail(session, prepared):
        await original(session, prepared)
        raise RuntimeError("reference write failed after SQL")

    monkeypatch.setattr(business.runtime, "aapply_source_bindings", fail)
    with pytest.raises(RuntimeError):
        async with AsyncSession(business.engine) as session, session.begin():
            await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 11}, login_user=business.user)
    async with AsyncSession(business.engine) as check:
        assert await ModelDefaultRepository().aget_own(check, "evaluation_llm") is None
        assert not (await check.execute(select(BusinessReferenceSet))).all()


@pytest.mark.parametrize("case", ["ordinary", "no_identity"])
async def test_only_original_super_or_tenant_admin_can_write(business, case):
    user = UserPayload(user_id=8, user_name="ordinary", tenant_id=101, user_role=[]) if case == "ordinary" else None
    async with AsyncSession(business.engine) as session:
        with pytest.raises(LLMSystemConfigForbiddenError):
            await ModelDefaultApplication.asave(session, "evaluation_llm", {"model_id": 11}, login_user=user)
        assert not session.new and not session.dirty


async def test_passive_model_creation_does_not_materialize_inherited_root_defaults(business, monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.llm.domain.const import LLMModelType
    from bisheng.llm.domain.services import llm as service

    async with AsyncSession(business.engine) as session, session.begin():
        session.add_all(
            [
                TenantSystemModelConfig(tenant_id=1, key=key, value=value)
                for key, value in [
                    ("knowledge_llm", '{"source_model_id":22,"extract_title_model_id":22,"qa_similar_model_id":22}'),
                    ("evaluation_llm", '{"model_id":22}'),
                    ("workflow_llm", '{"model_id":22}'),
                    ("assistant_llm", '{"auto_llm":{"model_id":22},"llm_list":[{"model_id":22}]}'),
                    (
                        "linsight_llm",
                        '{"chat_title_llm":{"id":"22","name":"root"},"models":[{"id":"22","name":"root"}]}',
                    ),
                ]
            ]
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(business.engine) as session:
            yield session

    monkeypatch.setattr(service, "get_async_db_session", sessions)
    await service.LLMService.set_default_model(
        SimpleNamespace(id=12, model_type=LLMModelType.LLM.value, model_name="other"), login_user=business.user
    )
    async with AsyncSession(business.engine) as check:
        rows = [
            await ModelDefaultRepository().aget_own(check, key)
            for key in ("knowledge_llm", "evaluation_llm", "workflow_llm", "assistant_llm", "linsight_llm")
        ]
        assert all(row is None for row in rows)
        assert not (await check.execute(select(BusinessReferenceSet))).all()


async def test_first_llm_fills_settings_added_after_the_first_model_logic(business, monkeypatch):
    """Workflow default, workbench list and both workbench defaults are filled too."""
    import json
    from contextlib import asynccontextmanager

    from bisheng.llm.domain.const import LLMModelType
    from bisheng.llm.domain.services import llm as service

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(business.engine) as session:
            yield session

    monkeypatch.setattr(service, "get_async_db_session", sessions)
    await service.LLMService.set_default_model(
        SimpleNamespace(id=12, model_type=LLMModelType.LLM.value, model_name="other"), login_user=business.user
    )
    async with AsyncSession(business.engine) as check:
        workflow = await ModelDefaultRepository().aget_own(check, "workflow_llm")
        workbench = await ModelDefaultRepository().aget_own(check, "linsight_llm")
    assert json.loads(workflow.value)["model_id"] == 12
    saved = json.loads(workbench.value)
    assert [one["id"] for one in saved["models"]] == ["12"]
    assert saved["linsight_default_model_id"] == "12"
    assert saved["chat_default_model_id"] == "12"


async def test_workbench_partial_post_keeps_saved_models_in_same_atomic_writer(business, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import BackgroundTasks

    from bisheng.llm.domain.schemas import WorkbenchModelConfig
    from bisheng.llm.domain.services import llm as service

    async with AsyncSession(business.engine) as session, session.begin():
        await ModelDefaultApplication.asave(
            session,
            "linsight_llm",
            {"models": [{"id": "11", "name": "one"}, {"id": "12", "name": "two"}]},
            login_user=business.user,
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(business.engine) as session:
            yield session

    monkeypatch.setattr(service, "get_async_db_session", sessions)
    result = await service.LLMService.update_workbench_llm(
        7, WorkbenchModelConfig(), BackgroundTasks(), login_user=business.user
    )
    assert [one.id for one in result.models] == ["11", "12"]
    async with AsyncSession(business.engine) as check:
        saved = await ModelDefaultRepository().aget_own(check, "linsight_llm")
        assert '"id":"11"' in saved.value and '"id":"12"' in saved.value
        assert (
            len(
                await business.runtime.repository.alist_source_references(
                    check, SourceKey(101, "model_default", "linsight_llm", "current")
                )
            )
            == 2
        )


async def test_writer_missing_tenant_maps_10996_before_opening_transaction(business, monkeypatch):
    from bisheng.common.errcode.tenant import NoTenantContextError
    from bisheng.common.services.config_service import settings
    from test.knowledge_unification.test_ref_repo import tenant

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    with tenant(None):
        async with AsyncSession(business.engine) as session:
            with pytest.raises(ResourceReferenceInvalidError) as raised:
                await ModelDefaultApplication.asave(
                    session, "evaluation_llm", {"model_id": 11}, login_user=business.user
                )
            assert isinstance(raised.value.__cause__, NoTenantContextError)
            assert not session.in_transaction()


def test_writer_single_tenant_keeps_core_default_without_explicit_root_fallback(monkeypatch):
    from bisheng.common.services.config_service import settings
    from test.knowledge_unification.test_ref_repo import tenant

    monkeypatch.setattr(settings.multi_tenant, "enabled", False)
    with tenant(None):
        assert application.current_model_default_tenant() == 1
        with pytest.raises(ResourceReferenceInvalidError):
            application.current_model_default_tenant(101)
