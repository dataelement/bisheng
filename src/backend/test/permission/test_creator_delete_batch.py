"""T865: preserve the original creator exception while bounding native SQL."""

from dataclasses import asdict
from math import ceil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import AuthorizationModelMismatchError, PermissionPublishNotReadyError
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee, ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from test.knowledge_unification import test_app_source_disclosure as app

source_tenant = app.source_tenant
source_db = app.source_db
disclosure = app.disclosure
app_disclosure = app.app_disclosure


@pytest.fixture
async def batch_case(app_disclosure, monkeypatch):
    case = app_disclosure
    await app.seed_creator_catalog(case, monkeypatch)

    async def check(*, user, relation, object, **_options):
        return (user, relation, object) in case.allowed

    case.fga.check = AsyncMock(side_effect=check)
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
        yield SimpleNamespace(**(vars(case) | {"actor": actor}))
    finally:
        reset_current_open_api_principal(principal_token)
        reset_current_permission_actor(actor_token)


def target(ident, *, tenant=101, resource_type="app", version=4, parent_type=None, parent_id=None):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant,
        resource_type=resource_type,
        resource_id=ident,
        resource_version=version,
        context_version="original-business-facts",
        parent_type=parent_type,
        parent_id=parent_id,
    )


async def seed(case, count, *, creator=True):
    requested = tuple(app.key(f"bulk-{i}", f"version-{i}") for i in range(count))
    async with case.engine.begin() as conn:
        await conn.execute(sa.insert(App), [app.root(item.source_id) for item in requested])
        await conn.execute(
            sa.insert(AppVersion), [app.version(item.source_version, item.source_id) for item in requested]
        )
        await conn.execute(
            sa.insert(ResourcePermissionMode),
            [
                {
                    "id": 3000 + i,
                    "tenant_id": 101,
                    "resource_type": "app",
                    "resource_id": item.source_id,
                    "mode": "CUSTOM",
                    "version": 4,
                    "projection_state": "CURRENT",
                }
                for i, item in enumerate(requested)
            ],
        )
        if creator:
            await conn.execute(
                sa.insert(PermissionGrant),
                [
                    {
                        "id": i + 1,
                        "tenant_id": 101,
                        "resource_type": "app",
                        "resource_id": item.source_id,
                        "model_key": "manager",
                        "state": "ACTIVE",
                        "version": 7,
                        "projection_state": "CURRENT",
                    }
                    for i, item in enumerate(requested)
                ],
            )
            rows = []
            for i, item in enumerate(requested):
                source = asdict(
                    GrantSourceService().canonicalize_source(
                        source_id=i + 1,
                        subject_type="service_account",
                        subject_id="44",
                        source_type="CREATOR_GRANT",
                        source_ref="app-create:" + item.source_id,
                    )
                )
                source.pop("active")
                source["id"] = source.pop("source_id")
                rows.append(source | {"tenant_id": 101, "grant_id": i + 1, "state": "ACTIVE"})
            await conn.execute(sa.insert(PermissionGrantAssignee), rows)
    return requested


def select_count(case, table=None):
    return sum(
        sql.lstrip().upper().startswith("SELECT") and (table is None or "FROM " + table in sql)
        for sql, _ in case.queries
    )


@pytest.mark.parametrize("creator", [False, True])
@pytest.mark.parametrize("count", [50, 200, 401])
async def test_actual_app_disclosure_creator_semantics_and_bounded_permission_sql(batch_case, creator, count):
    case = batch_case
    requested = await seed(case, count, creator=creator)
    case.queries.clear()
    results = []
    for start in range(0, count, 200):
        results.extend(await app.disclose(case, requested[start : start + 200]))
    assert all((item is not None) == creator for item in results)
    assert sum("FROM app " in sql for sql, _ in case.queries) == ceil(count / 200)
    assert sum("FROM app_version" in sql for sql, _ in case.queries) == ceil(count / 200)
    chunks = ceil(count / 100)
    print(
        {
            "count": count,
            "creator": creator,
            "selects": select_count(case),
            "catalogs": select_count(case, "permission_catalog_release"),
            "modes": select_count(case, "resource_permission_mode"),
            "grants": select_count(case, "permission_grant "),
            "sources": select_count(case, "permission_grant_assignee"),
        }
    )
    assert select_count(case, "permission_catalog_release") <= chunks
    assert select_count(case, "permission_grant ") <= chunks
    assert select_count(case, "permission_grant_assignee") <= chunks
    assert select_count(case) <= chunks * 30 + ceil(count / 200) * 2
    assert all(len(values) <= 100 for values in case.checks)


@pytest.mark.parametrize("changed", [None, "source_revoked", "grant_revoked", "editor", "other_subject", "direct"])
async def test_original_custom_creator_roster_policy_stays_identical(batch_case, changed):
    case = batch_case
    await seed(case, 1)
    async with case.engine.begin() as conn:
        if changed == "source_revoked":
            await conn.execute(sa.update(PermissionGrantAssignee).values(state="REVOKED"))
        elif changed == "grant_revoked":
            await conn.execute(sa.update(PermissionGrant).values(state="REVOKED"))
        elif changed == "editor":
            await conn.execute(sa.update(PermissionGrant).values(model_key="editor"))
        elif changed == "other_subject":
            await conn.execute(sa.update(PermissionGrantAssignee).values(subject_id="45"))
        elif changed == "direct":
            await conn.execute(sa.update(PermissionGrantAssignee).values(source_type="DIRECT"))
    original = await case.runtime.check_action(case.actor, target("bulk-0"), "delete")
    assert original is (changed is None)
    assert await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),) * 30, "delete") == (original,) * 30


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 5},
        {"parent_type": "knowledge_space", "parent_id": "7"},
        {"projection_state": "PROJECTING"},
        {"projection_state": "FAILED"},
    ],
)
async def test_original_strict_current_version_parent_exception_does_not_follow_decidable_states(batch_case, changes):
    case = batch_case
    await seed(case, 1)
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.update(ResourcePermissionMode).where(ResourcePermissionMode.resource_id == "bulk-0").values(**changes)
        )
    assert await case.runtime._creator_grant_allows_delete(case.actor, target("bulk-0"), "delete") is False
    assert await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),), "delete") == (False,)


async def test_empty_foreign_non_service_non_delete_and_prior_allow_do_not_read_creator_roster(batch_case):
    case = batch_case
    await seed(case, 1)
    for actor, targets, action, expected in (
        (case.actor, (), "delete", ()),
        (case.actor, (target("foreign", tenant=202),), "delete", (False,)),
        (PermissionActor(user_id=44, tenant_id=101), (target("bulk-0"),), "delete", (False,)),
        (case.actor, (target("bulk-0"),), "edit", (False,)),
    ):
        case.queries.clear()
        assert await case.runtime.batch_check_actions(actor, targets, action) == expected
        assert select_count(case, "permission_catalog_release") == select_count(case, "permission_grant ") == 0
    case.allowed.add((case.actor.fga_subject, "can_delete", "app:bulk-0"))
    case.queries.clear()
    assert await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),), "delete") == (True,)
    assert select_count(case, "permission_catalog_release") == select_count(case, "permission_grant ") == 0


async def test_catalog_pin_and_roster_operational_errors_never_allow(batch_case, monkeypatch):
    case = batch_case
    await seed(case, 1)
    case.runtime._client.model_id = "wrong-pin"
    with pytest.raises(AuthorizationModelMismatchError):
        await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),), "delete")
    case.runtime._client.model_id = "model"
    monkeypatch.setattr(case.runtime._state, "load_grants_batch", AsyncMock(side_effect=ConnectionError("unavailable")))
    with pytest.raises(ConnectionError):
        await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),), "delete")
    monkeypatch.setattr(
        case.runtime._state, "load_grants_batch", AsyncMock(side_effect=PermissionPublishNotReadyError())
    )
    assert await case.runtime.batch_check_actions(case.actor, (target("bulk-0"),), "delete") == (False,)


async def test_inherit_keeps_original_nearest_custom_fallback(batch_case):
    case = batch_case
    await seed(case, 1)
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.insert(ResourcePermissionMode).values(
                id=6000,
                tenant_id=101,
                resource_type="knowledge_file",
                resource_id="file-1",
                mode="INHERIT",
                parent_type="app",
                parent_id="bulk-0",
                version=4,
                projection_state="CURRENT",
            )
        )
    # Preserve the established fallback itself without creating a new inheritance policy.
    original = AsyncMock(side_effect=case.runtime._creator_grant_allows_delete)
    case.runtime._creator_grant_allows_delete = original
    item = target("file-1", resource_type="knowledge_file", parent_type="app", parent_id="bulk-0")
    expected = await case.runtime.check_action(case.actor, item, "delete")
    original.reset_mock()
    assert await case.runtime.batch_check_actions(case.actor, (item,), "delete") == (expected,)
    original.assert_awaited_once_with(case.actor, item, "delete")


async def test_batch_repository_exact_keys_models_empty_missing_and_deduplicated_sources(batch_case):
    case = batch_case
    await seed(case, 1)
    catalog = await case.runtime.current_catalog()
    manager = tuple(row.snapshot for row in catalog.models if row.snapshot.model_key == "manager")
    case.queries.clear()
    assert await case.runtime._state.load_grants_batch(targets=(), models=manager) == {}
    assert not case.queries
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.insert(PermissionGrant),
            [
                {
                    "id": 10,
                    "tenant_id": 101,
                    "resource_type": "workflow",
                    "resource_id": "other",
                    "model_key": "manager",
                    "state": "ACTIVE",
                    "version": 3,
                },
                {
                    "id": 11,
                    "tenant_id": 101,
                    "resource_type": "workflow",
                    "resource_id": "bulk-0",
                    "model_key": "manager",
                    "state": "ACTIVE",
                    "version": 3,
                },
                {
                    "id": 12,
                    "tenant_id": 101,
                    "resource_type": "app",
                    "resource_id": "other",
                    "model_key": "manager",
                    "state": "ACTIVE",
                    "version": 3,
                },
                {
                    "id": 13,
                    "tenant_id": 101,
                    "resource_type": "app",
                    "resource_id": "bulk-0",
                    "model_key": "editor",
                    "state": "ACTIVE",
                    "version": 3,
                },
                {
                    "id": 14,
                    "tenant_id": 202,
                    "resource_type": "app",
                    "resource_id": "bulk-0",
                    "model_key": "manager",
                    "state": "ACTIVE",
                    "version": 3,
                },
            ],
        )
    observed = []

    @sa.event.listens_for(case.engine.sync_engine, "after_cursor_execute")
    def after(_conn, cursor, sql, _params, _context, _many):
        if "FROM permission_grant " in sql:
            observed.append(cursor)

    requested = (target("bulk-0"), target("other", resource_type="workflow"), target("missing"), target("bulk-0"))
    case.queries.clear()
    try:
        found = await case.runtime._state.load_grants_batch(targets=requested, models=manager)
    finally:
        sa.event.remove(case.engine.sync_engine, "after_cursor_execute", after)
    assert set(found) == {(101, "app", "bulk-0"), (101, "workflow", "other"), (101, "app", "missing")}
    assert found[(101, "app", "missing")] == ()
    assert found[(101, "app", "bulk-0")][0].version == 7
    assert found[(101, "app", "bulk-0")][0].sources[0].subject_id == "44"
    assert all(grant.model.model_key == "manager" for values in found.values() for grant in values)
    sql = next(sql for sql, _ in case.queries if "FROM permission_grant " in sql)
    assert " OR " in sql.upper() and select_count(case, "permission_grant ") == 1
    assert select_count(case, "permission_grant_assignee") == 1
    assert observed


async def test_batch_repository_rejects_oversized_input_before_sql(batch_case):
    case = batch_case
    case.queries.clear()
    with pytest.raises(ValueError):
        await case.runtime._state.load_grants_batch(targets=tuple(target(str(i)) for i in range(201)), models=())
    assert not case.queries


async def test_custom_file_with_a_parent_is_still_batched_by_its_real_mode(batch_case):
    case = batch_case
    await seed(case, 50)
    async with case.engine.begin() as conn:
        await conn.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.resource_id.like("bulk-%"))
            .values(resource_type="knowledge_file", parent_type="knowledge_space", parent_id="7")
        )
        await conn.execute(sa.update(PermissionGrant).values(resource_type="knowledge_file"))
        await conn.execute(
            sa.insert(ResourcePermissionMode).values(
                id=7000,
                tenant_id=101,
                resource_type="knowledge_space",
                resource_id="7",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
    targets = tuple(
        target(f"bulk-{i}", resource_type="knowledge_file", parent_type="knowledge_space", parent_id="7")
        for i in range(50)
    )
    assert await case.runtime._creator_grant_allows_delete(case.actor, targets[0], "delete") is True
    case.queries.clear()
    assert await case.runtime.batch_check_actions(case.actor, targets, "delete") == (True,) * 50
    assert select_count(case, "permission_catalog_release") == 1
    assert select_count(case, "permission_grant ") == 1


async def test_many_sources_of_one_grant_are_complete_and_sql_result_pages_are_bounded(batch_case):
    case = batch_case
    await seed(case, 1)
    rows = []
    for source_id in range(2, 402):
        source = asdict(
            GrantSourceService().canonicalize_source(
                source_id=source_id,
                subject_type="service_account",
                subject_id="44",
                source_type="CREATOR_GRANT",
                source_ref=f"app-create:bulk-0:{source_id}",
            )
        )
        source.pop("active")
        source["id"] = source.pop("source_id")
        rows.append(source | {"tenant_id": 101, "grant_id": 1, "state": "ACTIVE"})
    async with case.engine.begin() as conn:
        await conn.execute(sa.insert(PermissionGrantAssignee), rows)
    catalog = await case.runtime.current_catalog()
    manager = tuple(row.snapshot for row in catalog.models if row.snapshot.model_key == "manager")
    case.queries.clear()
    found = await case.runtime._state.load_grants_batch(targets=(target("bulk-0"),), models=manager)
    sources = found[(101, "app", "bulk-0")][0].sources
    assert tuple(item.source_id for item in sources) == tuple(range(1, 402))
    assert select_count(case, "permission_grant ") == 1
    assert select_count(case, "permission_grant_assignee") == 3
    assert all("LIMIT" in sql.upper() for sql, _ in case.queries if "FROM permission_grant_assignee" in sql)
