"""File deletion crosses actual F048 journals and native history cutover."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import knowledge_deletion as module
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteSelection
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_service import ProjectionService
from test.knowledge_unification import test_kn_delete_plan as native
from test.knowledge_unification.test_model_share_projection_deferred import Marker, Transport

application, context, db, deletion_tenant, service = (
    native.application,
    native.context,
    native.db,
    native.deletion_tenant,
    native.service,
)


async def test_historical_file_delete_requires_real_projection_and_preserves_primary(application, context, monkeypatch):
    models = (
        PermissionProjectionOperation,
        PermissionProjectionTuple,
        ResourcePermissionMode,
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
    )
    metadata = sa.MetaData()
    pending = [model.__table__ for model in models]
    while pending:
        original = pending.pop()
        if original.name in metadata.tables:
            continue
        table = original.to_metadata(metadata)
        table.c.id.type = sa.Integer()
        pending.extend(foreign.column.table for foreign in original.foreign_keys)
    async with context.db.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with context.db.sessions() as session, session.begin():
        session.add(
            ResourcePermissionMode(
                id=1,
                tenant_id=101,
                resource_type="knowledge_file",
                resource_id="31",
                mode="INHERIT",
                parent_type="folder",
                parent_id="20",
                version=1,
                projection_state="CURRENT",
            )
        )
    monkeypatch.setattr(sql_runtime, "get_async_db_session", context.db.sessions)
    monkeypatch.setattr(control_state, "get_async_db_session", context.db.sessions)
    state = control_state.SqlPermissionControlState()
    catalog = await application.permission_runtime.current_catalog()
    monkeypatch.setattr(state, "current_catalog", AsyncMock(return_value=catalog))
    transport = Transport()
    projections = ProjectionService(
        repository=ProjectionRepository(context.db.sessions),
        marker=Marker(),
        scope_guard=sql_runtime.SqlProjectionScopeGuard(),
        fga=transport,
        finalizer=sql_runtime.SqlProjectionFinalizer(),
    )
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=state,
        marker=Marker(),
        decision=None,
        projection=projections,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime))
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id="31",
        resource_version=1,
        context_version="native-history-31",
        parent_type="folder",
        parent_id="20",
    )
    # The existing business adapter's transport is isolated here; every actual
    # permission reservation/journal/finalize and physical version fact is SQL.
    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(
            return_value=SimpleNamespace(tenant_id=101, resource_type="knowledge_file", resource_id="31")
        ),
        _lifecycle_target=lambda *args: target,
    )
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await application.aprecheck(
            identity=application.user,
            space_id=1,
            selections=(DeleteSelection("knowledge_file", 30),),
            historical_version_id=300,
        )
    review = await application.aprecheck(
        identity=application.user,
        space_id=1,
        selections=(DeleteSelection("knowledge_file", 31),),
        historical_version_id=301,
    )
    request = ProcessingCreateRequest(
        confirmation_id=review.confirmation_id, plan_digest=review.plan_digest, idempotency_key="historical-delete"
    )
    result = await application.aconfirm(identity=application.user, space_id=1, request=request)
    assert result["state"] == "succeeded" and transport.writes == 1
    async with context.db.sessions() as session:
        assert await session.get(KnowledgeFile, 31) is None
        assert await session.get(KnowledgeFile, 30) is not None
        assert await session.get(KnowledgeDocument, 100) is not None
        versions = (
            (
                await session.execute(
                    sa.select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == 100)
                )
            )
            .scalars()
            .all()
        )
        assert [row.knowledge_file_id for row in versions] == [30]
        journal = (await session.execute(sa.select(PermissionProjectionOperation))).scalar_one()
        assert journal.status == "FINALIZED" and journal.operation_type == "RESOURCE_DELETE"
    assert (await application.aconfirm(identity=application.user, space_id=1, request=request))["state"] == "succeeded"
    assert transport.writes == 1
