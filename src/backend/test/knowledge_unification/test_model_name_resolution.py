"""T476: a real SQL name catalog freezes one complete lock plan.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-92
SQLite proves rollback and manifest checks, not MySQL/DM8 scheduling.
"""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import (
    ModelFaceCapabilityUndeclaredError,
    ModelFaceCatalogUnavailableError,
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import model_name_resolution as names
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.services.model_catalog import ModelRange
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from test.knowledge_unification.test_ref_repo import tenant

TABLES = [Tenant.__table__, LLMServer.__table__, LLMModel.__table__, TenantSystemModelConfig.__table__]


class Relations:
    allowed = ("2",)
    error = None

    async def list_resource_ids(self, *, subject, relation, resource_type):
        assert (subject.subject_type, subject.subject_id, relation, resource_type) == (
            "tenant",
            "101",
            "shared_with",
            "llm_server",
        )
        if self.error:
            raise self.error
        return self.allowed


@pytest.fixture
async def ctx(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    table_names = {table.name for table in TABLES if "tenant_id" in table.columns}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | table_names)
    tenant_filter.register_tenant_filter_events()
    async with engine.begin() as conn:
        for table in TABLES:
            await conn.run_sync(lambda connection, table=table: table.create(connection))
    async with AsyncSession(engine) as session, session.begin():
        session.add_all(
            [
                Tenant(id=1, tenant_code="root", tenant_name="Root", share_default_to_children=1),
                Tenant(id=101, tenant_code="one", tenant_name="One", parent_tenant_id=1),
                Tenant(id=202, tenant_code="two", tenant_name="Two", parent_tenant_id=1),
                LLMServer(id=1, tenant_id=101, name="own", type="openai"),
                LLMServer(id=2, tenant_id=1, name="root", type="openai"),
                LLMServer(id=3, tenant_id=202, name="foreign", type="openai"),
                LLMModel(id=11, server_id=1, tenant_id=101, model_name="alpha", model_type="llm"),
                LLMModel(id=12, server_id=1, tenant_id=101, model_name="same", model_type="llm"),
                LLMModel(id=13, server_id=1, tenant_id=101, model_name="root/slash", model_type="llm"),
                LLMModel(id=14, server_id=1, tenant_id=101, model_name="offline", model_type="llm", online=False),
                LLMModel(id=15, server_id=1, tenant_id=101, model_name="embed", model_type="embedding"),
                LLMModel(id=21, server_id=2, tenant_id=1, model_name="same", model_type="llm"),
                LLMModel(id=22, server_id=2, tenant_id=1, model_name="slash", model_type="llm"),
                LLMModel(id=31, server_id=3, tenant_id=202, model_name="secret", model_type="llm"),
            ]
        )
    principal = OpenApiPrincipal(
        credential_id=9,
        actor_kind="hosted_app",
        actor_id=7,
        actor_name="app",
        tenant_id=101,
        subject_ref="actual-app",
        resource_owner_user_id=4,
        scopes=frozenset({"model:invoke"}),
        authorization_subject_type="service_account",
        authorization_subject_id=7,
        effective_user_id=None,
    )
    relations = Relations()
    monkeypatch.setattr(names, "get_permission_relation_api", AsyncMock(return_value=relations))
    port = names.ModelNameResolutionPort()
    with tenant(101):
        token = set_current_open_api_principal(principal)
        try:
            yield engine, principal, port, relations
        finally:
            reset_current_open_api_principal(token)
    await engine.dispose()


async def prepare(ctx, session, requested, **kwargs):
    _, identity, port, _ = ctx
    return await port.aprepare_model_names_current(session, 101, requested, identity=identity, **kwargs)


async def resolve(ctx, session, plan, requested, **kwargs):
    _, identity, port, _ = ctx
    return await port.resolve_model_name_current(session, 101, requested, identity=identity, plan=plan, **kwargs)


async def test_complete_batch_has_canonical_names_and_exact_bare_slash_precedence(ctx, monkeypatch):
    from bisheng.llm.domain.services import model_catalog

    monkeypatch.setattr(model_catalog, "resolve_model_name", AsyncMock(side_effect=AssertionError("cached path")))
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("root/same", "alpha", "root/slash", "alpha"))
        assert plan.requested_names == ("alpha", "root/same", "root/slash")
        assert tuple(item.resolved.model_id for item in plan.resolutions) == (11, 21, 13)
        for item in plan.resolutions:
            assert await resolve(ctx, session, plan, item.requested) == item.resolved
        assert not session.sync_session.identity_map
        assert session.in_transaction()


@pytest.mark.parametrize(
    "requested,exception",
    [
        ("same", ModelFaceModelAmbiguousError),
        ("offline", ModelFaceModelOfflineError),
        ("never", ModelFaceModelNotFoundError),
        ("secret", ModelFaceModelNotFoundError),
        ("embed", ModelFaceModelNotFoundError),
    ],
)
async def test_errors_use_complete_real_callable_set(ctx, requested, exception):
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(exception):
            await prepare(ctx, session, (requested,))


async def test_range_is_bound_without_changing_name_resolution_precedence(ctx):
    allowed = ModelRange("declared", frozenset({"own/alpha"}))
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",), range=allowed)
        assert (await resolve(ctx, session, plan, "alpha", range=allowed)).model_id == 11
        with pytest.raises(ResourceReferenceInvalidError):
            await resolve(ctx, session, plan, "alpha", range=ModelRange())
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(ModelFaceCapabilityUndeclaredError):
            await prepare(ctx, session, ("root/slash",), range=allowed)


@pytest.mark.parametrize("case", ["copy", "equal_clone", "identity", "tenant", "transaction", "other_port"])
async def test_plan_cannot_be_forged_reused_or_widened(ctx, case):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",))
        if case == "copy":
            plan = replace(plan)
        elif case == "equal_clone":
            original = plan

            class Clone(type(original)):
                def __hash__(self):
                    return hash(original)

                def __eq__(self, other):
                    return other is original or other is self

            plan = Clone(**{field: getattr(original, field) for field in original.__dataclass_fields__})
        elif case == "transaction":
            await session.rollback()
        elif case == "identity":
            token = set_current_open_api_principal(ctx[1].model_copy())
        elif case == "other_port":
            ctx = (ctx[0], ctx[1], names.ModelNameResolutionPort(), ctx[3])
        try:
            with tenant(202 if case == "tenant" else 101), pytest.raises(ResourceReferenceInvalidError):
                await resolve(ctx, session, plan, "alpha")
        finally:
            if case == "identity":
                reset_current_open_api_principal(token)


@pytest.mark.parametrize("case", ["name", "online", "provider", "new_model", "sharing"])
async def test_after_prepare_manifest_changes_fail_without_rebinding(ctx, case):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",))
        if case == "sharing":
            ctx[3].allowed = ()
        elif case == "new_model":
            session.add(LLMModel(id=16, server_id=1, tenant_id=101, model_name="new", model_type="llm"))
            await session.flush()
        else:
            values = {"name": {"model_name": "renamed"}, "online": {"online": False}, "provider": {"server_id": 2}}[
                case
            ]
            await session.execute(update(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101).values(**values))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await resolve(ctx, session, plan, "alpha")
        await session.rollback()
    async with AsyncSession(ctx[0]) as check:
        assert (await check.execute(select(LLMModel.model_name).where(LLMModel.id == 11))).scalar_one() == "alpha"


async def test_all_servers_lock_before_any_model_and_external_transaction_owns_rollback(ctx):
    locked = []
    async with AsyncSession(ctx[0]) as session:

        def observe(state):
            if state.is_select and state.statement._for_update_arg is not None:
                tables = {table.name for table in state.statement.get_final_froms()}
                if "llm_server" in tables:
                    locked.append("server")
                if "llm_model" in tables:
                    locked.append("model")

        event.listen(session.sync_session, "do_orm_execute", observe)
        plan = await prepare(ctx, session, ("alpha", "root/same"), frozen_models=(names.FrozenModelIdentity(13, 1),))
        assert "server" in locked and "model" in locked
        assert locked.index("server") < locked.index("model")
        assert (await resolve(ctx, session, plan, "root/same")).model_id == 21
        assert session.in_transaction()
        await session.rollback()


async def test_original_root_inheritance_is_real_sql_and_no_context_switch(ctx):
    ctx[3].allowed = ()
    async with AsyncSession(ctx[0]) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":22}'))
    async with AsyncSession(ctx[0]) as session:
        assert (await resolve(ctx, session, await prepare(ctx, session, ("root/same",)), "root/same")).model_id == 21
        from bisheng.core.context.tenant import get_current_tenant_id

        assert get_current_tenant_id() == 101


@pytest.mark.parametrize("case", ["error", "malformed"])
async def test_sharing_failure_never_returns_a_narrower_catalog(ctx, case):
    if case == "error":
        ctx[3].error = RuntimeError("permission unavailable")
    else:
        ctx[3].allowed = ("broken",)
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(ModelFaceCatalogUnavailableError):
            await prepare(ctx, session, ("alpha",))


async def test_frozen_model_hint_must_be_current_real_fact(ctx):
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await prepare(ctx, session, ("alpha",), frozen_models=(names.FrozenModelIdentity(11, 2),))


@pytest.mark.parametrize("requested", [(), ("alpha",)])
async def test_empty_and_nonempty_plans_have_one_explicit_current_assertion(ctx, requested):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, requested)
        assert await ctx[2].assert_plan_current(session, 101, identity=ctx[1], plan=plan) is None
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].assert_plan_current(session, 101, identity=ctx[1], plan=replace(plan))
        await session.rollback()
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].assert_plan_current(session, 101, identity=ctx[1], plan=plan)


async def test_original_plan_public_fields_are_not_the_private_name_binding(ctx):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",))
        other = await prepare(ctx, session, ("root/same",))
        object.__setattr__(plan, "requested_names", other.requested_names)
        object.__setattr__(plan, "resolutions", other.resolutions)
        with pytest.raises(ResourceReferenceInvalidError):
            await resolve(ctx, session, plan, "root/same")


@pytest.mark.parametrize("change", ["subject", "tenant", "super", "admin", "data_scope", "kind"])
async def test_original_ambient_permission_actor_is_part_of_principal_plan(ctx, change):
    from bisheng.permission.application.identity import (
        PermissionActor,
        reset_current_permission_actor,
        set_current_permission_actor,
    )

    actor = PermissionActor(subject_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    try:
        async with AsyncSession(ctx[0]) as session:
            plan = await prepare(ctx, session, ("alpha",))
            changes = {
                "subject": {"subject_id": 8},
                "tenant": {"tenant_id": 202},
                "super": {"super_admin": True},
                "admin": {"tenant_admin_tenant_ids": frozenset({101})},
                "data_scope": {"data_scope": "personal_only"},
                "kind": {"subject_type": "service_account"},
            }[change]
            replacement = PermissionActor(**{"subject_type": "user", "subject_id": 7, "tenant_id": 101, **changes})
            changed_token = set_current_permission_actor(replacement)
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await ctx[2].assert_plan_current(session, 101, identity=ctx[1], plan=plan)
            finally:
                reset_current_permission_actor(changed_token)
    finally:
        reset_current_permission_actor(token)


async def test_range_is_a_private_value_snapshot_not_a_mutable_original_alias(ctx):
    scope = ModelRange("declared", frozenset({"alpha"}))
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",), range=scope)
        object.__setattr__(scope, "declared", frozenset({"alpha", "root/same"}))
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].assert_plan_current(session, 101, identity=ctx[1], plan=plan, range=scope)


async def test_frozen_identity_resolution_uses_real_ids_without_name_or_sharing_grants(ctx):
    ctx[3].allowed = ()
    locked = []
    async with AsyncSession(ctx[0]) as session:
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: (
                locked.append(state.statement)
                if state.is_select and state.statement._for_update_arg is not None
                else None
            ),
        )
        facts = await ctx[2].aresolve_frozen_model_identities(session, 101, (22, 11, 22), identity=ctx[1])
        assert facts == (names.FrozenModelIdentity(11, 1), names.FrozenModelIdentity(22, 2))
        assert locked == [] and not session.sync_session.identity_map
        # These are physical candidates, not permission to bind or call Root.
        with pytest.raises(ModelFaceModelNotFoundError):
            await prepare(ctx, session, ("root/same",), frozen_models=facts)


@pytest.mark.parametrize("ids", [(999,), (31,), (True,), (0,)])
async def test_frozen_identity_resolution_never_guesses_deleted_or_foreign_providers(ctx, ids):
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].aresolve_frozen_model_identities(session, 101, ids, identity=ctx[1])


@pytest.mark.parametrize(
    "declared,alias,expected",
    [
        (("alpha",), "own/alpha", 11),
        (("own/alpha",), "alpha", 11),
        (("root/slash",), "own/root/slash", 13),
        (("root/same",), "root/same", 21),
    ],
)
async def test_alias_consumes_only_same_planned_current_model(ctx, monkeypatch, declared, alias, expected):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, declared)
        monkeypatch.setattr(ctx[2].repository, "aprepare_catalog", AsyncMock(side_effect=AssertionError("new plan")))
        value = await ctx[2].resolve_model_alias_current(session, 101, alias, identity=ctx[1], plan=plan)
        assert value.model_id == expected
        assert plan.requested_names == tuple(sorted(declared))


@pytest.mark.parametrize("declared,alias", [((), "alpha"), (("alpha",), "offline"), (("alpha",), "root/slash")])
async def test_alias_cannot_widen_empty_or_unrelated_plan(ctx, declared, alias):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, declared)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].resolve_model_alias_current(session, 101, alias, identity=ctx[1], plan=plan)


async def test_alias_retains_bare_ambiguity_and_original_object_proof(ctx):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("root/same",))
        with pytest.raises(ModelFaceModelAmbiguousError):
            await ctx[2].resolve_model_alias_current(session, 101, "same", identity=ctx[1], plan=plan)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].resolve_model_alias_current(session, 101, "root/same", identity=ctx[1], plan=replace(plan))


async def test_alias_catalog_rename_cannot_accept_different_planned_model(ctx):
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha", "root/same"))
        await session.execute(
            update(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11).values(model_name="changed")
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx[2].resolve_model_alias_current(session, 101, "root/same", identity=ctx[1], plan=plan)
        await session.rollback()


async def test_alias_rejects_changed_transaction_and_range(ctx):
    allowed = ModelRange("declared", frozenset({"own/alpha"}))
    async with AsyncSession(ctx[0]) as session:
        plan = await prepare(ctx, session, ("alpha",), range=allowed)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].resolve_model_alias_current(session, 101, "own/alpha", identity=ctx[1], plan=plan)
        await session.rollback()
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].resolve_model_alias_current(
                session, 101, "own/alpha", identity=ctx[1], plan=plan, range=allowed
            )


async def test_read_inspection_preserves_every_requested_name_and_precise_status(ctx):
    async with AsyncSession(ctx[0]) as session:
        findings = await ctx[2].ainspect_model_names_current(
            session, 101, ("alpha", "gone", "same", "offline", "root/slash", "root/same"), identity=ctx[1]
        )
        assert [(row.requested, row.status) for row in findings] == [
            ("alpha", "valid"),
            ("gone", "unresolvable"),
            ("same", "ambiguous"),
            ("offline", "offline"),
            ("root/slash", "valid"),
            ("root/same", "valid"),
        ]
        assert [row.resolved.model_id if row.resolved is not None else None for row in findings] == [
            11,
            None,
            None,
            None,
            13,
            21,
        ]
        assert session.in_transaction() and not session.sync_session.identity_map
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].resolve_model_name_current(session, 101, "alpha", identity=ctx[1], plan=findings)


async def test_read_inspection_uses_no_cache_no_locks_no_autoflush_and_cannot_issue_plan(ctx, monkeypatch):
    from bisheng.llm.domain.services import model_catalog

    monkeypatch.setattr(model_catalog, "resolve_model_name", AsyncMock(side_effect=AssertionError("cached inspection")))
    monkeypatch.setattr(
        ctx[2].repository, "aprepare_catalog", AsyncMock(side_effect=AssertionError("lock plan inspection"))
    )
    async with AsyncSession(ctx[0]) as session:
        pending = LLMModel(id=99, server_id=1, tenant_id=101, model_name="pending", model_type="llm")
        session.add(pending)
        statements = []

        def record(state):
            statements.append(state.statement)

        event.listen(session.sync_session, "do_orm_execute", record)
        rows = await ctx[2].ainspect_model_names_current(session, 101, ("alpha", "pending"), identity=ctx[1])
        assert [row.status for row in rows] == ["valid", "unresolvable"]
        assert all(statement._for_update_arg is None for statement in statements if statement.is_select)
        assert pending in session.new and not session.sync_session.identity_map
        await session.rollback()


@pytest.mark.parametrize("failure", ["sharing", "catalog"])
async def test_read_inspection_backend_failure_cannot_be_reported_as_healthy_rows(ctx, monkeypatch, failure):
    error = RuntimeError("catalog backend failed")
    if failure == "sharing":
        ctx[3].error = error
    else:
        monkeypatch.setattr(ctx[2].repository, "ainspect_catalog", AsyncMock(side_effect=error), raising=False)
    async with AsyncSession(ctx[0]) as session:
        with pytest.raises(ModelFaceCatalogUnavailableError) as raised:
            await ctx[2].ainspect_model_names_current(session, 101, ("alpha", "gone"), identity=ctx[1])
        assert raised.value.__cause__ is error


async def test_read_inspection_keeps_original_identity_tenant_and_transaction(ctx, monkeypatch):
    async with AsyncSession(ctx[0]) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].ainspect_model_names_current(session, 202, ("alpha",), identity=ctx[1])
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].ainspect_model_names_current(session, 101, ("alpha",), identity=ctx[1].model_copy())
        original = ctx[2].repository.ainspect_catalog

        async def change_transaction(*args, **kwargs):
            value = await original(*args, **kwargs)
            await session.commit()
            return value

        monkeypatch.setattr(ctx[2].repository, "ainspect_catalog", change_transaction)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx[2].ainspect_model_names_current(session, 101, ("alpha",), identity=ctx[1])


async def test_read_inspection_rejects_non_name_input_and_preserves_explicit_empty_batch(ctx):
    async with AsyncSession(ctx[0]) as session:
        for requested in [(True,), ("",), ["alpha"]]:
            with pytest.raises(ResourceReferenceInvalidError):
                await ctx[2].ainspect_model_names_current(session, 101, requested, identity=ctx[1])
        assert await ctx[2].ainspect_model_names_current(session, 101, (), identity=ctx[1]) == ()


@pytest.mark.parametrize("operation", ["prepare", "frozen", "inspect"])
async def test_public_name_ports_map_missing_multitenant_context_to_10996(ctx, monkeypatch, operation):
    from bisheng.common.errcode.tenant import NoTenantContextError
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    with tenant(None):
        async with AsyncSession(ctx[0]) as session:
            with pytest.raises(ResourceReferenceInvalidError) as raised:
                if operation == "prepare":
                    await ctx[2].aprepare_model_names_current(session, 101, ("alpha",), identity=ctx[1])
                elif operation == "frozen":
                    await ctx[2].aresolve_frozen_model_identities(session, 101, (11,), identity=ctx[1])
                else:
                    await ctx[2].ainspect_model_names_current(session, 101, ("alpha",), identity=ctx[1])
            assert isinstance(raised.value.__cause__, NoTenantContextError)
            assert not session.in_transaction()
