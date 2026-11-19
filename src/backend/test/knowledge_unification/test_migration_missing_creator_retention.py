"""Missing historical owners preserve identities without creating membership."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.user.domain.models.user import User
from test.knowledge_unification import test_migration_structural_retention as original

resource_native, native, complete = original.resource_native, original.native, original.complete
raw_resource_native = original.raw_resource_native
transport, module, published_input = original.transport, original.module, original.published_input
resources = original.resources


async def missing_owner(database):
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(resources.Knowledge).where(resources.Knowledge.id == 9000).values(user_id=999)
        )
        await connection.execute(
            sa.update(resources.KnowledgeFile).where(resources.KnowledgeFile.id == 1).values(user_id=999)
        )


async def legacy_locator(database):
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(resources.KnowledgeFile)
            .where(resources.KnowledgeFile.id == 1)
            .values(object_name="https://legacy.invalid/original")
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": legacy_locator}], indirect=True)
async def test_original_url_locator_full_migration_preserves_value_without_fetch(published_input):
    value = published_input
    result = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    async with value.sessions() as session, session.begin():
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids
        assert (await session.get(resources.KnowledgeFile, 1)).object_name == "https://legacy.invalid/original"


@pytest.mark.parametrize("published_input", [{"reference_seed": missing_owner}], indirect=True)
async def test_missing_original_creator_full_migration_and_completed_resume(published_input):
    value = published_input
    app = original.reference_tests.app(value)
    result = await app.arun_references(**value.input, operator_id=7)
    assert result.complete
    assert await app.arun_references(**value.input, operator_id=7) == result
    async with value.sessions() as session, session.begin():
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids
        root = await session.get(resources.Knowledge, 9000)
        assert (root.type, root.user_id) == (3, 999)
        members = (await session.exec(sa.select(original.original.SpaceChannelMember))).all()
        assert not any(member.user_id == 999 for member in members)
        assert await session.get(User, 999) is None
        assert (await session.get(resources.KnowledgeFile, 1)).user_id == 999


@pytest.mark.parametrize("count", [200, 400])
async def test_missing_creator_pages_and_resume_have_bounded_identity_reads(module, complete, transport, count):
    await complete.insert(
        resources.Knowledge,
        [resources.resource(10000 + ident, user_id=999, type=3, model=None) for ident in range(count)],
    )
    inventory = original.original.application(module, transport)
    complete.queries.clear()
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.arun(session, **transport.inputs)
    creator_reads = sum("m2_exact_creator.user_id IN" in sql for sql, _ in complete.queries)
    assert creator_reads <= 5  # Original+source acquisition, never per resource.

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    app = UnificationSQLConversionApplication(
        artifact_store=transport.store, session_factory=sessions, structural_reader_factory=transport.reader_factory
    )
    with tenant_execution_scope(1):
        assert (await app.arun(**transport.inputs)).sql_complete
        assert (await app.arun(**transport.inputs)).sql_complete


async def test_creator_reappearing_after_freeze_blocks_before_conversion(module, complete, transport):
    await missing_owner(complete)
    inventory = original.original.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        await inventory.arun(session, **transport.inputs)
    await complete.insert(User, [{"user_id": 999, "user_name": "reappeared", "password": "test"}])

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    app = UnificationSQLConversionApplication(
        artifact_store=transport.store, session_factory=sessions, structural_reader_factory=transport.reader_factory
    )
    with tenant_execution_scope(1), pytest.raises(BaseErrorCode):
        await app.arun(**transport.inputs)
    async with complete.engine.connect() as connection:
        assert (
            await connection.execute(sa.select(resources.Knowledge.type).where(resources.Knowledge.id == 9000))
        ).scalar_one() == 0
