"""Five actual saved default keys are metadata, never copied inherited bindings."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.llm.application.model_default_read_identity import ModelDefaultReadIdentityPort
from bisheng.llm.application.model_default_source_owner import ModelDefaultSourceOwner
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.services.default_reference_extractor import MODEL_DEFAULT_SCHEMAS
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure
from test.knowledge_unification import test_llm_default_repository as original

astore = original.astore
model_owner_tenant = original.model_owner_tenant
KEYS = tuple(MODEL_DEFAULT_SCHEMAS)
TABS = dict(zip(KEYS, ("knowledge", "assis", "evaluation", "workflow", "workbench"), strict=True))


def key(name="evaluation_llm", *, tenant_id=101, version="current", source_type=SourceType.MODEL_DEFAULT):
    return SourceKey(tenant_id, source_type, name, version)


@pytest.fixture
async def metadata(astore):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    actor = PermissionActor(user_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    async with AsyncSession(astore) as session, session.begin():
        session.add_all(
            TenantSystemModelConfig(tenant_id=101, key=name, value='{"private-secret":"never read"}') for name in KEYS
        )
    queries = []

    @sa.event.listens_for(astore.sync_engine, "before_cursor_execute")
    def seen(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))

    owner = ModelDefaultSourceOwner(identity_port=ModelDefaultReadIdentityPort())
    try:
        yield SimpleNamespace(engine=astore, user=user, actor=actor, queries=queries, owner=owner)
    finally:
        reset_current_permission_actor(token)


async def test_all_five_original_authenticated_gets_allow_names_without_management_entries(metadata):
    keys = tuple(key(name) for name in KEYS)
    async with AsyncSession(metadata.engine) as session, session.begin():
        result = await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=keys)
        assert not session.new and not session.dirty and not session.deleted
    assert result == tuple(SourceDisclosure(source, name, None, None) for source, name in zip(keys, KEYS, strict=True))
    assert len(metadata.queries) == 1
    selected = metadata.queries[0][0].split("FROM")[0].lower()
    assert ".value" not in selected and "tenant." not in selected


async def test_existing_admin_qualification_only_decorates_real_setting_entries(metadata):
    actor = replace(metadata.actor, tenant_admin_tenant_ids=frozenset({101}))
    token = set_current_permission_actor(actor)
    try:
        keys = tuple(key(name) for name in KEYS)
        async with AsyncSession(metadata.engine) as session, session.begin():
            result = await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=keys)
        assert [item.entry for item in result] == [f"/model/management?systemModel={TABS[name]}" for name in KEYS]
    finally:
        reset_current_permission_actor(token)


async def test_foreign_root_sources_and_empty_input_have_zero_business_io(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        assert await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=()) == ()
        assert await metadata.owner.adisclose_sources(
            session, identity=metadata.user, source_keys=(key(tenant_id=1), key(tenant_id=202))
        ) == (None, None)
        assert await ModelDefaultRepository().alist_disclosure_rows(session, keys=()) == ()
    assert metadata.queries == []


async def test_actual_root_view_exposes_only_original_root_row_without_a_child_copy(metadata):
    user = metadata.user.model_copy(update={"tenant_id": 1, "is_global_super": True})
    token = set_current_permission_actor(PermissionActor(user_id=7, tenant_id=1, super_admin=True))
    try:
        with tenant_execution_scope(1):
            async with AsyncSession(metadata.engine) as session, session.begin():
                source = key(tenant_id=1)
                result = await metadata.owner.adisclose_sources(session, identity=user, source_keys=(source,))
        assert result == (SourceDisclosure(source, "evaluation_llm", None, "/model/management?systemModel=evaluation"),)
        assert len(metadata.queries) == 1
    finally:
        reset_current_permission_actor(token)


async def test_missing_own_source_is_failure_even_when_original_root_fallback_exists(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        await session.execute(
            sa.delete(TenantSystemModelConfig).where(
                TenantSystemModelConfig.tenant_id == 101, TenantSystemModelConfig.key == "evaluation_llm"
            )
        )
    metadata.queries.clear()
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(),))
    assert len(metadata.queries) == 1


@pytest.mark.parametrize(
    "keys",
    [
        [key()],
        (key(),) * 201,
        (key("unregistered"),),
        (key(version="old"),),
        (key(source_type=SourceType.ASSISTANT),),
        ("invalid",),
    ],
)
async def test_invalid_shape_version_or_key_rejects_before_io(metadata, keys):
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=keys)
    assert metadata.queries == []


async def test_duplicate_binding_slots_keep_positions_with_three_queries_for_401_occurrences(metadata):
    keys = tuple(key(KEYS[i % len(KEYS)]) for i in range(401))
    result = []
    async with AsyncSession(metadata.engine) as session, session.begin():
        for offset in range(0, len(keys), 200):
            result.extend(
                await metadata.owner.adisclose_sources(
                    session, identity=metadata.user, source_keys=keys[offset : offset + 200]
                )
            )
    assert tuple(item.source for item in result) == keys
    assert len(metadata.queries) == 3
    assert all(".value" not in statement.split("FROM")[0].lower() for statement, _ in metadata.queries)


async def test_scalar_metadata_reads_preserve_pending_config_changes_without_autoflush(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        stored = (
            await session.execute(
                sa.select(TenantSystemModelConfig).where(
                    TenantSystemModelConfig.tenant_id == 101, TenantSystemModelConfig.key == "evaluation_llm"
                )
            )
        ).scalar_one()
        stored.value = "pending private config"
        before = sa.inspect(stored).attrs.value.history
        await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(),))
        assert stored in session.dirty and stored.value == "pending private config"
        assert sa.inspect(stored).attrs.value.history == before
        await session.rollback()


async def test_current_identity_mutation_during_real_sql_is_rejected(metadata, monkeypatch):
    original_method = metadata.owner.repository.alist_disclosure_rows
    changed = []

    async def mutate(session, **kwargs):
        rows = await original_method(session, **kwargs)
        changed.append(set_current_permission_actor(PermissionActor(user_id=99, tenant_id=101)))
        return rows

    monkeypatch.setattr(metadata.owner.repository, "alist_disclosure_rows", mutate)
    try:
        async with AsyncSession(metadata.engine) as session, session.begin():
            with pytest.raises(ReferenceCoverageNotReadyError):
                await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(),))
    finally:
        for token in reversed(changed):
            reset_current_permission_actor(token)
