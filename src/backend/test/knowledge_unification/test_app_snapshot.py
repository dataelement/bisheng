"""Immutable version plus B2 is one transaction. 覆盖 AC: AC-68, AC-71, AC-87, AC-88, AC-89."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.models.app_deployment import AppDeployment
from bisheng.app_publish.domain.services import version_service as module
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_app_source_owner as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
VERSION = "a1b5fbb9-7496-4ee4-84cb-12340c82c17b"


@pytest.fixture
async def writing(application, monkeypatch):
    engine = application.engine
    metadata = sa.MetaData()
    for model in (KnowledgeFile, ResourceReferenceTombstone):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name,
                    col.type.copy(),
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if col.name in {"create_time", "update_time"}
                    else col.server_default,
                )
                for col in model.__table__.columns
            ],
        )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    model_owner = ModelReferenceTargetOwner()
    knowledge_owner = KnowledgeReferenceTargetOwner()
    verifier = ReferenceTargetVerifier(
        {
            TargetType.MODEL: model_owner,
            TargetType.KNOWLEDGE_SPACE: knowledge_owner,
            TargetType.KNOWLEDGE_FILE: knowledge_owner,
        }
    )
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    user = UserPayload(user_id=4, user_name="publisher", tenant_id=101, user_role=[])

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def original_context(context, app, *, version_id):
        assert context["target"] == {"tenant_id": 101, "app_id": "actual-app", "version_id": VERSION}
        token = set_current_open_api_principal(None)
        actor_token = set_current_permission_actor(PermissionActor(subject_type="user", subject_id=4, tenant_id=101))
        try:
            yield user
        finally:
            reset_current_permission_actor(actor_token)
            reset_current_open_api_principal(token)

    monkeypatch.setattr(module, "get_async_db_session", factory)
    monkeypatch.setattr(module, "get_reference_binding_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(module, "user_authorization_context", original_context, raising=False)
    monkeypatch.setattr(module, "get_model_name_resolution_port", lambda: application.names, raising=False)
    authorization = AsyncMock()
    monkeypatch.setattr(module, "authorize_loaded_app", authorization, raising=False)
    monkeypatch.setattr(module, "require_business_action", AsyncMock(), raising=False)
    return SimpleNamespace(**vars(application), runtime=runtime, user=user, authorization=authorization)


def deployment():
    return AppDeployment(
        id="deployment",
        app_id="actual-app",
        version_id=VERSION,
        owner_user_id=4,
        tenant_id=101,
        manifest={
            "runtime": "python3.11",
            "original": " text ",
            "capabilities": {"models": [{"name": "alpha"}], "knowledge_bases": [{"id": "7"}]},
        },
        code_object_key="snapshot",
        tier_code="light",
        authorization_context={
            "target": {"tenant_id": 101, "app_id": "actual-app", "version_id": VERSION},
            "purpose": "release_submit",
            "required_actions": ["edit", "publish"],
        },
    )


async def snapshot(engine):
    async with engine.connect() as connection:
        result = []
        for model in (App, AppVersion, BusinessReferenceSet, BusinessResourceReference):
            result.append(tuple((await connection.execute(sa.select(model.__table__).order_by(model.id))).all()))
        return tuple(result)


async def test_actual_uuid_insert_retains_manifest_and_historical_source_sets(writing):
    attempted = deployment()
    original = deepcopy(attempted.manifest)
    row = await module.VersionService._insert_version(attempted, image_ref="frozen-image")
    assert row.id == VERSION and row.version_no == 3 and row.manifest == original
    assert row.image_ref == "frozen-image"
    async with AsyncSession(writing.engine) as session, session.begin():
        sets = (
            (await session.execute(sa.select(BusinessReferenceSet).where(BusinessReferenceSet.record_kind == "source")))
            .scalars()
            .all()
        )
        assert {item.source_version for item in sets} == {fixtures.VERSION, fixtures.HISTORY, VERSION}
        assert all(item.ready and item.effective for item in sets)
        rows = (
            (
                await session.execute(
                    sa.select(BusinessResourceReference).where(BusinessResourceReference.source_version == VERSION)
                )
            )
            .scalars()
            .all()
        )
        assert {item.target_id for item in rows} == {"11", "7"}
    assert writing.authorization.await_args.args[0] is writing.user


async def test_reference_apply_failure_rolls_back_business_version_and_all_revisions(writing, monkeypatch):
    before = await snapshot(writing.engine)
    real = ReferenceBindings.areplace_source_bindings

    async def failed(self, *args, **kwargs):
        await real(self, *args, **kwargs)
        raise RuntimeError("reference apply failed")

    monkeypatch.setattr(ReferenceBindings, "areplace_source_bindings", failed)
    with pytest.raises(RuntimeError, match="reference apply failed"):
        await module.VersionService._insert_version(deployment())
    assert await snapshot(writing.engine) == before


async def test_existing_saved_version_missing_coverage_cannot_hide_behind_new_source(writing):
    async with AsyncSession(writing.engine) as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(BusinessReferenceSet.source_version == fixtures.HISTORY)
        )
    before = await snapshot(writing.engine)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await module.VersionService._insert_version(deployment())
    assert await snapshot(writing.engine) == before
