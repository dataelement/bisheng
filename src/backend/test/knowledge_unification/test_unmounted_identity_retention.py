"""Native preservation, original frozen recovery and no phantom Coverage."""

import asyncio

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.knowledge.application import unification_identity_retention as policy
from bisheng.knowledge.application.unification_inventory_codec import record_from_values
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
    ResourcePermissionMode,
)
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from test.knowledge_unification import test_migration_inventory_application as m2
from test.knowledge_unification import test_migration_references_application as fixtures
from test.knowledge_unification.test_migration_references_application import (
    app,
)

TABLES = (
    AuditLog,
    GptsToolsType,
    GptsTools,
    ResourcePermissionMode,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionVisibleSourceProjection,
)
IDENT = 50000
TENANT = 303
complete, native = fixtures.complete, fixtures.native
raw_resource_native, resource_native = fixtures.raw_resource_native, fixtures.resource_native
transport, published_input, no_real_network = fixtures.transport, fixtures.published_input, fixtures.no_real_network


async def seed(database, count=1):
    async with database.engine.begin() as connection:
        for model in (AuditLog, GptsToolsType, GptsTools):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
    for model, rows in (
        (
            AuditLog,
            [
                {
                    "id": f"unmount-{i:08}",
                    "operator_id": 7,
                    "tenant_id": TENANT + i,
                    "action": "tenant.unmount",
                    "target_type": "tenant",
                    "target_id": str(TENANT + i),
                    "metadata": {"migrated_counts": {"assistant": 1}},
                }
                for i in range(count)
            ],
        ),
        (
            GptsToolsType,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "name": "original preset",
                    "is_preset": 1,
                    "extra": "original payload",
                }
                for i in range(count)
            ],
        ),
        (
            GptsTools,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "type": IDENT + i,
                    "name": "preset child",
                    "tool_key": "original",
                    "is_preset": 1,
                }
                for i in range(count)
            ],
        ),
        (
            ResourcePermissionMode,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "resource_type": "tool",
                    "resource_id": str(IDENT + i),
                    "mode": "CUSTOM",
                    "projection_state": "CURRENT",
                    "version": 1,
                }
                for i in range(count)
            ],
        ),
        (
            PermissionGrant,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "resource_type": "tool",
                    "resource_id": str(IDENT + i),
                    "model_key": "owner",
                    "state": "ACTIVE",
                    "projection_state": "CURRENT",
                    "version": 1,
                }
                for i in range(count)
            ],
        ),
        (
            PermissionGrantAssignee,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "grant_id": IDENT + i,
                    "subject_type": "user",
                    "subject_id": "7",
                    "include_children": False,
                    "source_type": "CREATOR",
                    "source_ref": "original",
                    "source_locator": "original",
                    "source_fingerprint": "a" * 64,
                    "projected_subject": "user:7",
                    "protected": True,
                    "state": "ACTIVE",
                    "version": 1,
                }
                for i in range(count)
            ],
        ),
        (
            PermissionVisibleSourceProjection,
            [
                {
                    "id": IDENT + i,
                    "tenant_id": TENANT + i,
                    "resource_type": "tool",
                    "resource_id": str(IDENT + i),
                    "visibility_class": "standard",
                    "projected_subject": "user:7",
                    "source_kind": "GRANT_ASSIGNEE",
                    "source_owner_key": f"grant_assignee:{IDENT + i}",
                    "source_locator": "original",
                    "source_fingerprint": "a" * 64,
                    "contribution_fingerprint": "b" * 64,
                    "source_version": 1,
                    "tuple_fingerprint": "c" * 64,
                    "state": "ACTIVE",
                }
                for i in range(count)
            ],
        ),
    ):
        await database.insert(model, rows)


async def observe(database, **kwargs):
    with tenant_execution_scope(1):
        async with AsyncSession(database.engine) as session, session.begin():
            return await policy.validate(session, **kwargs)


async def snapshot(database):
    async with database.engine.connect() as connection:
        return {
            model.__tablename__: [
                dict(row)
                for row in (
                    await connection.execute(
                        sa.select(model.__table__).where(model.tenant_id >= TENANT).order_by(model.id)
                    )
                ).mappings()
            ]
            for model in TABLES
        }


async def test_native_capture_and_frozen_revalidation_never_write_or_recreate_identity(complete):
    await seed(complete)
    before = await snapshot(complete)
    captured = await observe(complete)
    assert captured.tenant_ids == (TENANT,) and len(policy.protected_objects(captured)) == 2
    assert await observe(complete, expected=captured.metadata()) == captured
    assert await snapshot(complete) == before
    async with complete.engine.connect() as connection:
        assert not (await connection.execute(sa.select(Tenant.id).where(Tenant.id == TENANT))).all()
    with pytest.raises(BaseErrorCode):
        await observe(complete, expected={})  # frozen legacy Run is not reinterpreted


@pytest.mark.parametrize(
    "change",
    [
        "no_audit",
        "wrong_audit",
        "bound_user",
        "mounted",
        "custom_tool",
        "missing_tool",
        "tool_child",
        "live_mode",
        "mode_pending",
        "grant_pending",
        "foreign_assignee",
        "unknown_permission",
    ],
)
async def test_unknown_or_still_active_originals_stay_blocked(complete, change):
    await seed(complete)
    async with complete.engine.begin() as connection:
        if change == "no_audit":
            await connection.execute(sa.delete(AuditLog))
        elif change == "wrong_audit":
            await connection.execute(sa.update(AuditLog).values(target_id="different"))
        elif change == "bound_user":
            await connection.execute(
                sa.insert(UserTenant).values(
                    id=IDENT, tenant_id=TENANT, user_id=7, is_default=0, status="inactive", is_active=None
                )
            )
        elif change == "mounted":
            await connection.execute(
                sa.insert(Department).values(
                    id=IDENT,
                    dept_id="original-department",
                    name="mounted",
                    tenant_id=1,
                    mounted_tenant_id=TENANT,
                    is_tenant_root=1,
                )
            )
        elif change == "custom_tool":
            await connection.execute(sa.update(GptsToolsType).values(is_preset=0))
        elif change == "missing_tool":
            await connection.execute(sa.delete(GptsToolsType))
        elif change == "tool_child":
            await connection.execute(sa.update(GptsTools).values(type=999999))
        elif change == "live_mode":
            await connection.execute(
                sa.insert(ResourcePermissionMode).values(
                    id=IDENT + 1,
                    tenant_id=1,
                    resource_type="tool",
                    resource_id=str(IDENT),
                    mode="CUSTOM",
                    projection_state="CURRENT",
                    version=1,
                )
            )
        elif change == "mode_pending":
            await connection.execute(
                sa.update(ResourcePermissionMode)
                .where(ResourcePermissionMode.id == IDENT)
                .values(projection_state="PROJECTING")
            )
        elif change == "grant_pending":
            await connection.execute(sa.update(PermissionGrant).values(projection_state="PROJECTING"))
        elif change == "foreign_assignee":
            await connection.execute(sa.update(PermissionGrantAssignee).values(tenant_id=TENANT + 1))
        else:
            await connection.execute(sa.update(PermissionGrant).values(resource_id="unknown"))
    with pytest.raises(BaseErrorCode):
        await observe(complete)


@pytest.mark.parametrize("change", ["tool", "child", "permission", "audit", "restored"])
async def test_frozen_retention_detects_changed_or_removed_originals(complete, change):
    await seed(complete)
    expected = (await observe(complete)).metadata()
    async with complete.engine.begin() as connection:
        if change == "tool":
            await connection.execute(sa.update(GptsToolsType).values(extra="changed"))
        elif change == "child":
            await connection.execute(sa.update(GptsTools).values(api_params=[{"changed": True}]))
        elif change == "permission":
            await connection.execute(sa.update(PermissionGrant).values(version=2))
        elif change == "audit":
            await connection.execute(sa.update(AuditLog).values(reason="changed"))
        else:
            await connection.execute(
                sa.insert(Tenant).values(id=TENANT, tenant_name="restored", tenant_code="restored")
            )
    with pytest.raises(BaseErrorCode):
        await observe(complete, expected=expected)


async def test_206_identities_are_paged_without_a_tenant_cap(complete):
    await seed(complete, 206)
    before = len(complete.queries)
    result = await observe(complete)
    queries = complete.queries[before:]
    assert len(result.tenant_ids) == 206 and dict(result.counts)["t_gpts_tools_type"] == 206
    assert len(queries) < 60
    assert result == await observe(complete, expected=result.metadata())


async def test_transferred_assistant_keeps_original_old_scope_without_root_mode(complete):
    await seed(complete)
    async with complete.engine.begin() as connection:
        await connection.execute(sa.insert(Assistant).values(id="moved", name="moved", tenant_id=1, user_id=7))
        await connection.execute(
            sa.insert(ResourcePermissionMode).values(
                id=IDENT + 1,
                tenant_id=TENANT,
                resource_type="assistant",
                resource_id="moved",
                mode="CUSTOM",
                projection_state="CURRENT",
                version=1,
            )
        )
    result = await observe(complete)
    assert "assistant:moved" in result.objects
    async with complete.engine.connect() as connection:
        assert not (
            await connection.execute(
                sa.select(ResourcePermissionMode.id).where(
                    ResourcePermissionMode.tenant_id == 1, ResourcePermissionMode.resource_id == "moved"
                )
            )
        ).all()


def test_retained_graph_changes_cannot_be_hidden_by_full_store_conversion():
    from types import SimpleNamespace

    before = frozenset({("user:7", "visible", "tool:original")})
    policy.verify_tuple_plan(SimpleNamespace(before=before, staged=before, after=before), {"tool:original"})
    with pytest.raises(BaseErrorCode):
        policy.verify_tuple_plan(SimpleNamespace(before=before, staged=frozenset(), after=before), {"tool:original"})


def test_normal_graph_path_does_not_rescan_when_retention_is_empty():
    policy.verify_tuple_plan(object(), frozenset())


RAW_EDGES = tuple(
    (subject, relation, f"tool:{IDENT}")
    for subject, relation in [
        ("user:*", "permission_enabled"),
        ("service_account:*", "permission_enabled"),
        ("user:*", "custom_mode"),
        ("service_account:*", "custom_mode"),
        ("user:7", "visible"),
    ]
)
ORIGINAL_GRANT = "permission_grant:" + stable_grant_key(
    tenant_id=TENANT, resource_type="tool", resource_id=str(IDENT), model_key="owner"
)
RAW_EDGES += (
    (ORIGINAL_GRANT, "grant", f"tool:{IDENT}"),
    ("permission_model:owner", "model", ORIGINAL_GRANT),
    ("user:7", "protected_assignee", ORIGINAL_GRANT),
)
OPTIONS = {"reference_seed": seed, "raw_edges": RAW_EDGES}


@pytest.mark.parametrize("published_input", [OPTIONS], indirect=True)
async def test_original_full_entry_preserves_orphans_and_same_run_replays_to_coverage(published_input):
    value = published_input
    before = await snapshot(value.database)
    retained = await policy.load_metadata(value.artifacts.store, value.frozen)
    assert retained["unmounted_identity_count"] == 1
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete and TENANT not in result.tenant_ids
    assert await snapshot(value.database) == before
    assert set(RAW_EDGES) <= value.store.tuples
    writes = value.store.writes
    assert await app(value).arun_references(**value.input, operator_id=7) == result
    assert value.store.writes == writes


@pytest.mark.parametrize("published_input", [OPTIONS], indirect=True)
async def test_retention_drift_rejected_before_first_business_conversion(published_input):
    value = published_input
    async with value.database.engine.begin() as connection:
        await connection.execute(sa.update(GptsToolsType).values(extra="after freeze"))
    with pytest.raises(BaseErrorCode):
        await app(value).arun_references(**value.input, operator_id=7)
    assert value.store.writes == 0
    async with value.database.engine.connect() as connection:
        assert (await connection.execute(sa.select(m2.resources.Knowledge.type))).scalar_one() == 0


@pytest.mark.parametrize("published_input", [OPTIONS], indirect=True)
@pytest.mark.parametrize("phase", ["sql", "fga", "finalize"])
async def test_original_run_resumes_after_sql_fga_and_final_pointer_interruptions(published_input, monkeypatch, phase):
    from bisheng.permission.domain.repositories.f118_catalog_write_repository import F118CatalogWriteRepository

    value = published_input
    original = await snapshot(value.database)
    if phase == "sql":
        value.sessions.fail_at, value.sessions.after, value.sessions.cancel = 1, True, True
    elif phase == "fga":
        value.store.fail_write, value.store.after, value.store.cancel = 1, True, True
    else:
        actual = F118CatalogWriteRepository.afinalize_catalog
        once = False

        async def interrupted(*args, **kwargs):
            nonlocal once
            result = await actual(*args, **kwargs)
            if not once:
                once = True
                raise asyncio.CancelledError()
            return result

        monkeypatch.setattr(F118CatalogWriteRepository, "afinalize_catalog", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await app(value).arun_references(**value.input, operator_id=7)
    value.sessions.fail_at, value.store.fail_write = None, None
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete
    assert await snapshot(value.database) == original
    assert set(RAW_EDGES) <= value.store.tuples


@pytest.mark.parametrize("bad", ["missing_digest", "zero", "bool", "unknown_policy"])
def test_retention_metadata_is_closed_and_cannot_reclassify_old_runs(bad):
    descriptor = {"object_key": "original", "sha256": "a" * 64}
    value = {
        "writer_contract_version": "f118-v1",
        "environment": "test",
        "tenant_count": 1,
        "tenant_inventory_digest": "a" * 64,
        "backup_ref": descriptor,
        "schema_ref": descriptor,
        "catalog_digest": "a" * 64,
        "authorization_model_checksum": "a" * 64,
        "baseline_ref": None,
        "unmounted_identity_policy": "preserve_unmounted_v1",
        "unmounted_identity_count": 1,
        "unmounted_identity_digest": "b" * 64,
    }
    record_from_values("run", **value)
    if bad == "missing_digest":
        del value["unmounted_identity_digest"]
    elif bad == "zero":
        value["unmounted_identity_count"] = 0
    elif bad == "bool":
        value["unmounted_identity_count"] = True
    else:
        value["unmounted_identity_policy"] = "ignore_orphans"
    with pytest.raises(BaseErrorCode):
        record_from_values("run", **value)
