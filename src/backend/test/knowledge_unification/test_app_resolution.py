"""APP resolver consumes real complete name plans. 覆盖 AC: AC-37, AC-68, AC-87, AC-89, AC-92."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.application import reference_resolution as module
from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, TargetType
from test.knowledge_unification import test_model_name_resolution as name_fixtures

ctx = name_fixtures.ctx


@pytest.fixture
async def resolving(ctx, monkeypatch):
    engine, identity, names, _ = ctx
    async with engine.begin() as connection:
        await connection.run_sync(Knowledge.__table__.create)
        await connection.execute(
            sa.insert(Knowledge),
            [
                {"id": key, "tenant_id": tenant, "name": name, "type": kind, "user_id": 4}
                for key, tenant, name, kind in ((7, 101, "ById", 0), (8, 101, "Documents", 3), (9, 202, "Foreign", 0))
            ],
        )
    monkeypatch.setattr(module, "get_model_name_resolution_port", lambda: names)
    return engine, identity, names


async def resolve(resolving, session, declaration, **kwargs):
    _, identity, names = resolving
    requested = tuple(ref.name for ref in declaration.models)
    plan = await names.aprepare_model_names_current(session, 101, requested, identity=identity)
    refs = await module.resolve_app_references(
        session, declaration, identity=identity, source_tenant_id=101, model_name_plan=plan, **kwargs
    )
    return refs, plan


async def test_real_bare_slash_model_and_numeric_id_first_keep_original_manifest(resolving):
    declaration = CapabilityDeclaration(
        models=[{"name": "root/slash"}], knowledge_bases=[{"id": "007", "name": "Documents"}, {"name": "Documents"}]
    )
    original = deepcopy(declaration.model_dump())
    async with AsyncSession(resolving[0]) as session, session.begin():
        refs, _ = await resolve(resolving, session, declaration)
        assert {(ref.target.target_type, ref.target.target_id) for ref in refs} == {
            (TargetType.MODEL, "13"),
            (TargetType.KNOWLEDGE_SPACE, "7"),
            (TargetType.KNOWLEDGE_SPACE, "8"),
        }
        assert not session.identity_map and not session.dirty
    assert declaration.model_dump() == original


@pytest.mark.parametrize("name", ["Missing", "Foreign"])
async def test_unknown_or_foreign_knowledge_cannot_freeze_fake_ids(resolving, name):
    async with AsyncSession(resolving[0]) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await resolve(resolving, session, CapabilityDeclaration(knowledge_bases=[{"name": name}]))


async def test_same_name_knowledge_ambiguity_is_not_first_match(resolving):
    async with AsyncSession(resolving[0]) as session, session.begin():
        session.add(Knowledge(id=10, tenant_id=101, name="Documents", type=0, user_id=4))
        await session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            await resolve(resolving, session, CapabilityDeclaration(knowledge_bases=[{"name": "Documents"}]))


async def test_whole_model_plan_is_required_not_subset_or_other_identity(resolving):
    engine, identity, names = resolving
    async with AsyncSession(engine) as session, session.begin():
        plan = await names.aprepare_model_names_current(session, 101, ("alpha", "root/slash"), identity=identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await module.resolve_app_references(
                session,
                CapabilityDeclaration(models=[{"name": "alpha"}]),
                identity=identity,
                source_tenant_id=101,
                model_name_plan=plan,
            )
        with pytest.raises(ResourceReferenceInvalidError):
            await module.resolve_app_references(
                session,
                CapabilityDeclaration(models=[{"name": "alpha"}, {"name": "root/slash"}]),
                identity=identity.model_copy(),
                source_tenant_id=101,
                model_name_plan=plan,
            )


async def test_frozen_model_id_cannot_follow_name_to_another_target(resolving):
    declaration = CapabilityDeclaration(models=[{"name": "alpha"}])
    async with AsyncSession(resolving[0]) as session, session.begin():
        refs, plan = await resolve(resolving, session, declaration)
        wrong = (ReferenceSpec(refs[0].slot_key, TargetKey(TargetType.MODEL, "13")),)
        with pytest.raises(ResourceReferenceInvalidError):
            await module.resolve_app_references(
                session,
                declaration,
                identity=resolving[1],
                source_tenant_id=101,
                model_name_plan=plan,
                frozen_references=wrong,
            )


async def test_knowledge_current_type_and_name_are_revalidated_from_original_plan(resolving):
    declaration = CapabilityDeclaration(knowledge_bases=[{"name": "Documents"}])
    engine, identity, _ = resolving
    async with AsyncSession(engine) as session, session.begin():
        _, plan = await resolve(resolving, session, declaration)
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 8).values(name="Renamed"))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await module.resolve_app_references(
                session, declaration, identity=identity, source_tenant_id=101, model_name_plan=plan
            )


async def test_empty_plan_still_requires_original_authority(resolving):
    engine, identity, names = resolving
    from dataclasses import replace

    async with AsyncSession(engine) as session, session.begin():
        plan = await names.aprepare_model_names_current(session, 101, (), identity=identity)
        assert (
            await module.resolve_app_references(
                session, CapabilityDeclaration(), identity=identity, source_tenant_id=101, model_name_plan=plan
            )
            == ()
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await module.resolve_app_references(
                session, CapabilityDeclaration(), identity=identity, source_tenant_id=101, model_name_plan=replace(plan)
            )
