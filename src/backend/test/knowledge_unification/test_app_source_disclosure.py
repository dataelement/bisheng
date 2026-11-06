"""T849: APP disclosure keeps management-read OR and immutable version parents."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.application.reference_source_owner import HostedAppReferenceSourceOwner
from bisheng.app_runtime.domain.services.f048_app_permission import F048AppPermissionAdapter
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.database import tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application import access
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.application.migration_read import target_authorization_model_checksum
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    ResourcePermissionMode,
)
from bisheng.permission.domain.services.catalog_service import _checksum
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.model_policy import derive_permission_models
from bisheng.permission.migration.f048_model_mapper import build_initial_action_release
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime
from test.knowledge_unification import test_assistant_source_disclosure as assistants

source_tenant = assistants.source_tenant
source_db = assistants.source_db
disclosure = assistants.disclosure


def key(app_id="owned-app", version="v1", tenant=101, kind=SourceType.HOSTED_APP_VERSION):
    return SourceKey(tenant, kind, app_id, version)


def root(ident="owned-app", tenant=101):
    return {
        "id": ident,
        "tenant_id": tenant,
        "slug": ident,
        "name": "Application " + ident,
        "owner_user_id": 99,
        "state": "online",
        "current_version_id": ident + "-current",
    }


def version(ident="v1", app_id="owned-app", number=1):
    return {
        "id": ident,
        "app_id": app_id,
        "version_no": number,
        "kind": "iteration",
        "code_object_key": "private-source-key",
        "manifest": {"private": "do not disclose"},
        "capabilities": {},
        "injections": {"private": "credential"},
        "runtime": "python3.11",
        "tier_id": "light",
    }


@pytest.fixture
async def app_disclosure(disclosure, monkeypatch):
    case = disclosure
    async with case.engine.begin() as conn:
        await conn.run_sync(lambda sync: App.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: AppVersion.__table__.create(sync, checkfirst=True))
        await conn.execute(sa.insert(App), [root(), root("outside-app", 202)])
        await conn.execute(
            sa.insert(AppVersion),
            [version(), version("owned-app-current", number=2), version("outside-version", "outside-app")],
        )
        await conn.execute(
            sa.insert(ResourcePermissionMode).values(
                id=1000,
                tenant_id=101,
                resource_type="app",
                resource_id="owned-app",
                mode="CUSTOM",
                version=4,
                projection_state="CURRENT",
            )
        )
    adapter = F048AppPermissionAdapter(loader=None, permission=case.runtime)
    monkeypatch.setattr(access, "_resource_adapters", {"app": adapter})
    return SimpleNamespace(**(vars(case) | {"owner": HostedAppReferenceSourceOwner()}))


async def disclose(case, keys):
    async with AsyncSession(case.engine) as session, session.begin():
        result = await case.owner.adisclose_sources(session, identity=case.user, source_keys=keys)
        assert not session.new and not session.dirty and not session.identity_map
        return result


async def test_current_and_historical_version_metadata_need_management_not_root_visible(app_disclosure):
    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "visible", "app:owned-app"))
    assert await disclose(case, (key(), key(version="owned-app-current"))) == (None, None)
    assert all(row["relation"] != "visible" for batch in case.checks for row in batch)
    case.allowed.add((case.actor.fga_subject, "can_edit", "app:owned-app"))
    result = await disclose(case, (key(), key(version="owned-app-current"), key()))
    assert result == (
        SourceDisclosure(key(), "Application owned-app", "v1", "/build/apps/owned-app"),
        SourceDisclosure(key(version="owned-app-current"), "Application owned-app", "v2", "/build/apps/owned-app"),
        result[0],
    )
    assert all(
        item.source == requested
        for item, requested in zip(result, (key(), key(version="owned-app-current"), key()), strict=True)
    )


@pytest.mark.parametrize("action", ["edit", "manage_permission", "delete", "publish", "unpublish"])
async def test_every_original_management_read_or_action_remains_sufficient(app_disclosure, action):
    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "can_" + action, "app:owned-app"))
    assert (await disclose(case, (key(),)))[0].source == key()
    seen = [row["relation"] for batch in case.checks for row in batch]
    assert (
        seen[-1] == "can_" + action
        and len(seen) == ["edit", "manage_permission", "delete", "publish", "unpublish"].index(action) + 1
    )


async def test_empty_and_foreign_owner_direct_calls_have_no_sql_or_permission_io(app_disclosure):
    case = app_disclosure
    case.queries.clear()
    assert await disclose(case, ()) == ()
    assert await disclose(
        case, (key("outside-app", "outside-version", 202), key("outside-app", "outside-version", 202))
    ) == (None, None)
    assert not case.queries and not case.checks


@pytest.mark.parametrize(
    "keys", [[key()], (key(kind=SourceType.ASSISTANT),), tuple(key() for _ in range(201)), (object(),)]
)
async def test_invalid_owner_direct_batch_never_reads_metadata(app_disclosure, keys):
    case = app_disclosure
    case.queries.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, keys)
    assert not case.queries and not case.checks


@pytest.mark.parametrize(
    "keys", [(key(version="missing"),), (key(version="outside-version"),), (key("missing"),), (key(version="current"),)]
)
async def test_missing_or_bad_immutable_version_parent_cannot_be_hidden(app_disclosure, keys):
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(app_disclosure, keys)


async def test_raw_manifest_and_injections_are_never_loaded_even_if_original_json_is_corrupt(app_disclosure):
    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "can_edit", "app:owned-app"))
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE app_version SET manifest='private-not-json', capabilities='private-not-json', injections='private-not-json' WHERE id='v1'"
            )
        )
    case.queries.clear()
    result = await disclose(case, (key(),))
    assert result[0].version_label == "v1"
    sql = " ".join(statement for statement, _ in case.queries).lower()
    assert all(
        field not in sql for field in ("manifest", "capabilities", "injections", "code_object_key", "release_notes")
    )
    assert "private" not in repr(result)


@pytest.mark.parametrize("changes", [{"state": "deleted"}, {"state": "unknown"}, {"owner_user_id": 0}])
async def test_invalid_current_root_facts_are_fail_closed_not_visibility_denials(app_disclosure, changes):
    case = app_disclosure
    async with case.engine.begin() as conn:
        await conn.execute(sa.update(App).where(App.id == "owned-app").values(**changes))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key(),))


async def test_stopped_or_draft_root_and_explicit_history_keep_original_management_read(app_disclosure):
    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "can_publish", "app:owned-app"))
    for state in ("stopped", "draft", "pending_capacity"):
        async with case.engine.begin() as conn:
            await conn.execute(sa.update(App).where(App.id == "owned-app").values(state=state, current_version_id=None))
        assert (await disclose(case, (key(),)))[0].version_label == "v1"


async def test_permission_metadata_and_transport_failures_cannot_be_converted_to_hidden_sources(app_disclosure):
    case = app_disclosure
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.resource_type == "app")
            .values(parent_type="knowledge_space", parent_id="8")
        )
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key(),))
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.resource_type == "app")
            .values(parent_type=None, parent_id=None)
        )
    case.fga.batch_check.side_effect = ConnectionError("transport unavailable")
    with pytest.raises(ReferenceCoverageNotReadyError):
        await disclose(case, (key(),))


async def test_401_app_versions_and_repeated_slots_have_bounded_projection_and_original_or_short_circuit(
    app_disclosure,
):
    case = app_disclosure
    async with case.engine.begin() as conn:
        await conn.execute(sa.insert(App), [root(f"app-{i}") for i in range(401)])
        await conn.execute(sa.insert(AppVersion), [version(f"version-{i}", f"app-{i}") for i in range(401)])
        await conn.execute(
            sa.insert(ResourcePermissionMode),
            [
                {
                    "id": 2000 + i,
                    "tenant_id": 101,
                    "resource_type": "app",
                    "resource_id": f"app-{i}",
                    "mode": "CUSTOM",
                    "version": 4,
                    "projection_state": "CURRENT",
                }
                for i in range(401)
            ],
        )
    case.allowed.update((case.actor.fga_subject, "can_edit", f"app:app-{i}") for i in range(401))
    requested = tuple(key(f"app-{i}", f"version-{i}") for i in range(401))
    runtime = SourceDisclosureRuntime({SourceType.HOSTED_APP_VERSION: case.owner})
    case.queries.clear()
    found = []
    async with AsyncSession(case.engine) as session, session.begin():
        for start in range(0, len(requested), 200):
            found.extend(
                await runtime.adisclose_sources(session, identity=case.user, source_keys=requested[start : start + 200])
            )
        repeated = await runtime.adisclose_sources(session, identity=case.user, source_keys=(requested[0],) * 200)
    assert tuple(item.source for item in found) == requested and all(item == found[0] for item in repeated)
    assert sum("FROM app " in sql for sql, _ in case.queries) <= 4
    assert sum("FROM app_version" in sql for sql, _ in case.queries) <= 4
    assert sum("FROM resource_permission_mode" in sql for sql, _ in case.queries) <= 10
    assert sum(len(batch) for batch in case.checks) == 402 and all(len(batch) <= 100 for batch in case.checks)
    assert all(row["relation"] == "can_edit" for batch in case.checks for row in batch)


async def test_current_read_does_not_flush_or_commit_callers_pending_app(app_disclosure):
    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "can_edit", "app:owned-app"))
    async with AsyncSession(case.engine, autoflush=True) as session, session.begin():
        pending = App(**root("pending-app"))
        session.add(pending)
        found = await case.owner.adisclose_sources(session, identity=case.user, source_keys=(key(),))
        assert found[0].source == key() and pending in session.new and not session.identity_map
        await session.rollback()
    async with case.engine.connect() as conn:
        assert (
            await conn.execute(sa.select(sa.func.count()).select_from(App).where(App.id == "pending-app"))
        ).scalar_one() == 0


async def seed_creator_catalog(case, monkeypatch):
    """A canonical CURRENT SQL catalog, not a mocked creator-delete answer."""
    actions = build_initial_action_release()
    models = derive_permission_models(actions)
    tables = (
        AuthorizationModelRelease,
        PermissionCatalogRelease,
        PermissionAction,
        PermissionActionResourceScope,
        PermissionModel,
        PermissionModelAction,
        PermissionGrant,
        PermissionGrantAssignee,
    )
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables | {"permission_grant", "permission_grant_assignee"},
    )
    async with case.engine.begin() as conn:
        for model in tables:
            await conn.run_sync(lambda sync, model=model: model.__table__.create(sync, checkfirst=True))
        await conn.execute(
            sa.insert(AuthorizationModelRelease).values(
                id=1,
                environment="test",
                store_id="store",
                model_version="v1",
                model_id="model",
                model_checksum=target_authorization_model_checksum(),
                required_relations_checksum="a" * 64,
                openfga_version="1.15.1",
                status="ACTIVE",
            )
        )
        await conn.execute(
            sa.insert(PermissionCatalogRelease).values(
                id=1,
                release_key="current",
                version=1,
                status="CURRENT",
                required_authorization_model_release_id=1,
                draft_owner_id=9,
                idempotency_key="seed",
                checksum=_checksum({"actions": actions.checksum, "models": models.checksum}),
            )
        )
        action_ids, scope_id = {}, 1
        for number, action in enumerate(actions.actions, 1):
            action_ids[action.code] = number
            await conn.execute(
                sa.insert(PermissionAction).values(
                    id=number,
                    catalog_release_id=1,
                    code=action.code,
                    name=action.name,
                    level=action.level,
                    active=action.active,
                    sort_order=action.sort_order,
                )
            )
            for resource_type in action.resource_types:
                await conn.execute(
                    sa.insert(PermissionActionResourceScope).values(
                        id=scope_id,
                        action_id=number,
                        resource_type=resource_type,
                    )
                )
                scope_id += 1
        selected_id = 1
        for number, model in enumerate(models.models, 1):
            fields = {
                name: getattr(model, name)
                for name in (
                    "model_key",
                    "name",
                    "kind",
                    "config_scope",
                    "derived_level",
                    "visibility_level",
                    "active",
                    "allow_same_level",
                )
            }
            await conn.execute(
                sa.insert(PermissionModel).values(
                    id=number,
                    catalog_release_id=1,
                    normalized_name=model.name.casefold(),
                    visibility_only_resource_types=list(model.visibility_only_resource_types),
                    **fields,
                )
            )
            for action in model.selected_action_codes:
                await conn.execute(
                    sa.insert(PermissionModelAction).values(
                        id=selected_id,
                        model_id=number,
                        action_id=action_ids[action],
                    )
                )
                selected_id += 1
    case.runtime._client = SimpleNamespace(store_id="store", model_id="model")
    await case.runtime.current_catalog()


@pytest.mark.parametrize(
    "changed", [None, "source_revoked", "grant_revoked", "other_subject", "manual_source", "editor_model"]
)
async def test_service_account_creator_delete_keeps_exact_original_revocable_sql_source(
    app_disclosure, monkeypatch, changed
):
    case = app_disclosure
    await seed_creator_catalog(case, monkeypatch)
    source = asdict(
        GrantSourceService().canonicalize_source(
            source_id=1,
            subject_type="service_account",
            subject_id="43" if changed == "other_subject" else "44",
            source_type="DIRECT" if changed == "manual_source" else "CREATOR_GRANT",
            source_ref="app-create:owned-app",
        )
    )
    source.pop("active")
    source["id"] = source.pop("source_id")
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.insert(PermissionGrant).values(
                id=1,
                tenant_id=101,
                resource_type="app",
                resource_id="owned-app",
                model_key="editor" if changed == "editor_model" else "manager",
                state="REVOKED" if changed == "grant_revoked" else "ACTIVE",
                version=1,
                projection_state="CURRENT",
            )
        )
        await conn.execute(
            sa.insert(PermissionGrantAssignee).values(
                **source,
                tenant_id=101,
                grant_id=1,
                state="REVOKED" if changed == "source_revoked" else "ACTIVE",
            )
        )
    actor = PermissionActor(subject_type="service_account", subject_id=44, tenant_id=101)
    principal = OpenApiPrincipal(
        credential_id=10,
        actor_kind="service_account",
        actor_id=44,
        actor_name="SA44",
        tenant_id=101,
        resource_owner_user_id=9,
        scopes=frozenset({"app:read"}),
        authorization_subject_type="service_account",
        authorization_subject_id=44,
        effective_user_id=None,
    )
    actor_token, principal_token = set_current_permission_actor(actor), set_current_open_api_principal(principal)
    try:
        result = await disclose(case, (key(), key()))
        assert all((item is not None) == (changed is None) for item in result)
        if changed is None:
            assert result[0].source == key() and result[0] == result[1]
            assert [row["relation"] for batch in case.checks for row in batch] == [
                "can_edit",
                "can_manage_permission",
                "can_delete",
            ]
        assert case.user.user_id == 9 and actor.subject_type == "service_account" and actor.subject_id == 44
    finally:
        reset_current_open_api_principal(principal_token)
        reset_current_permission_actor(actor_token)


async def test_original_home_and_trusted_selected_management_tenant_are_preserved(app_disclosure):
    from bisheng.core.context import tenant as context

    case = app_disclosure
    home = case.user.model_copy(update={"tenant_id": 1, "is_global_super": True})
    actor = PermissionActor(user_id=9, tenant_id=1, super_admin=True)
    tokens = (
        (context.current_tenant_id, context.set_current_tenant_id(1)),
        (context._is_management_api, context.set_is_management_api(True)),
        (context._admin_scope_tenant_id, context.set_admin_scope_tenant_id(101)),
    )
    actor_token = set_current_permission_actor(actor)
    try:
        async with AsyncSession(case.engine) as session, session.begin():
            result = await case.owner.adisclose_sources(session, identity=home, source_keys=(key(), key(tenant=1)))
        assert result[0].source == key() and result[1] is None
        assert home.tenant_id == actor.current_tenant_id == 1 and not case.checks
    finally:
        reset_current_permission_actor(actor_token)
        for variable, token in reversed(tokens):
            variable.reset(token)


async def test_actor_change_during_original_permission_check_is_fail_closed(app_disclosure):
    case = app_disclosure
    original = case.fga.batch_check.side_effect

    async def changed(values, **options):
        result = await original(values, **options)
        set_current_permission_actor(PermissionActor(user_id=77, tenant_id=101))
        return result

    case.fga.batch_check.side_effect = changed
    token = set_current_permission_actor(case.actor)
    try:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await disclose(case, (key(),))
    finally:
        reset_current_permission_actor(token)


async def test_native_sqlalchemy_session_reads_only_safe_metadata(app_disclosure):
    from sqlalchemy.ext.asyncio import AsyncSession as NativeSession

    case = app_disclosure
    case.allowed.add((case.actor.fga_subject, "can_edit", "app:owned-app"))
    async with NativeSession(case.engine) as session, session.begin():
        result = await case.owner.adisclose_sources(session, identity=case.user, source_keys=(key(),))
        assert result[0].source == key() and not session.identity_map and not session.new


async def test_existing_admin_shortcuts_keep_original_app_data_scope_boundary(app_disclosure):
    case = app_disclosure
    for actor, allowed in (
        (PermissionActor(user_id=9, tenant_id=101, super_admin=True), True),
        (PermissionActor(user_id=9, tenant_id=101, tenant_admin_tenant_ids=frozenset({101})), True),
        # F066 narrows knowledge ownership; App is outside that governed set.
        (PermissionActor(user_id=9, tenant_id=101, super_admin=True, data_scope="personal_only"), True),
        (PermissionActor(user_id=9, tenant_id=101, data_scope="personal_only"), False),
    ):
        token = set_current_permission_actor(actor)
        try:
            assert ((await disclose(case, (key(),)))[0] is not None) is allowed
        finally:
            reset_current_permission_actor(token)
