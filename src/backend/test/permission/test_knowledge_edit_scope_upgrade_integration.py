"""Version HTTP writes use native Catalog decisions before/after the upgrade."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.knowledge.application import knowledge_version_mutation as mutations
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_version_service
from test.knowledge_unification.test_kn_version_mutation_authorization import request
from test.knowledge_unification.test_kn_version_mutation_repository import database as database
from test.knowledge_unification.test_kn_version_mutation_repository import native as native
from test.knowledge_unification.test_kn_version_mutation_repository import snapshot
from test.knowledge_unification.test_kn_version_mutation_wiring import wired as wired
from test.permission.test_f048_catalog_runtime import TABLE_NAMES
from test.permission.test_knowledge_edit_scope_upgrade import apply, decisions, resource, setup_catalog


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
@pytest.mark.parametrize("model", ["editor", "manager", "viewer"])
async def test_original_http_with_space_viewer_and_inherited_folder_grant(wired, monkeypatch, operation, model):
    metadata = sa.MetaData()
    for name in TABLE_NAMES:
        table = SQLModel.metadata.tables[name].to_metadata(metadata)
        table.c.id.type = sa.Integer()
    async with wired.database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            sa.update(KnowledgeFile).where(KnowledgeFile.id.in_([101, 201, 202])).values(file_level_path="/99")
        )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(wired.database.engine, expire_on_commit=False) as session:
            yield session

    catalog = await setup_catalog(factory, monkeypatch)
    targets = {ident: await resource(catalog, ident=str(ident), model=model) for ident in (101, 201, 202)}
    runtime = decisions(catalog)
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    actor = PermissionActor(user_id=7, tenant_id=101)

    async def require(user, *, resource_type, resource_id, action):
        assert user is wired.user and not user.is_global_super
        assert resource_type == "knowledge_file" and action == "edit"
        async with factory() as session:
            actual = await session.get(KnowledgeFile, resource_id)
        assert actual and actual.tenant_id == actor.tenant_id and actual.file_level_path == "/99"
        if not await runtime.check_action(actor, targets[resource_id], action):
            raise UnAuthorizedError()

    # Replace only the external composition: decisions are the real F048
    # service + SQL Catalog/fence + the schema evaluator, never an ALLOW mock.
    monkeypatch.setattr(knowledge_version_service, "require_business_action", require)
    monkeypatch.setattr(mutations, "require_business_action", require)
    before = await snapshot(wired.database)
    response = await request(wired, operation)
    assert response.json()["status_code"] == 25001
    assert await snapshot(wired.database) == before
    await apply(catalog)
    response = await request(wired, operation)
    assert response.json()["status_code"] == (UnAuthorizedError.Code if model == "viewer" else 200)
    if model == "viewer":
        assert await snapshot(wired.database) == before
    else:
        assert response.json()["data"]["document_id"] == 20
