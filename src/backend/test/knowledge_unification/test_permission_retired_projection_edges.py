"""Frozen inactive SQL sources retire stale graph edges through the original publisher."""

import json
from dataclasses import asdict
from functools import partial

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.models import PermissionGrant as Grant
from bisheng.permission.domain.models import PermissionGrantAssignee as Assignee
from bisheng.permission.domain.models import PermissionVisibleSourceProjection as Visible
from bisheng.permission.domain.models import ResourcePermissionMode as Mode
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.resource_lifecycle_policy import compile_existing_mode_tuples
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


def source(ident, grant, *, department=False, active=False):
    value = GrantSourceService().canonicalize_source(
        source_id=ident,
        subject_type="department" if department else "user",
        subject_id="42" if department else "7",
        userset_relation="member" if department else None,
        source_type="DEPARTMENT" if department else "DIRECT",
        source_ref="42#member" if department else f"original-retirement:{ident}",
    )
    raw = asdict(value)
    raw.pop("active")
    return plans.PermissionAssigneeBaseline(
        id=raw.pop("source_id"), grant_id=grant, tenant_id=101, state="ACTIVE" if active else "INACTIVE", **raw
    )


def grant_key(kind, ident, model):
    return "permission_grant:" + stable_grant_key(tenant_id=101, resource_type=kind, resource_id=ident, model_key=model)


async def original_edges(database, store, *, file=False, fault=None):
    kind, ident = ("knowledge_file", "1") if file else ("knowledge_library", "9000")
    resource = kind + ":" + ident
    active_id, retired_id = (201, 202) if file else (101, 102)
    active_model = "viewer" if file else "owner"
    active_key, retired_key = grant_key(kind, ident, active_model), grant_key(kind, ident, "inactive-model")
    department = source(203, active_id, department=True)
    retired = source(204, retired_id)
    async with AsyncSession(database.engine) as session, session.begin():
        if file:
            await session.execute(sa.update(Mode).where(Mode.id == 1).values(mode="CUSTOM"))
            modes = await PermissionMigrationSnapshotRepository().alist_resource_modes(session)
            mode = next(row for row in modes if row.resource_type == kind and row.resource_id == ident)
            grants = (
                plans.PermissionGrantBaseline(active_id, 101, kind, ident, active_model, "ACTIVE"),
                plans.PermissionGrantBaseline(retired_id, 101, kind, ident, "inactive-model", "INACTIVE"),
            )
            active = source(205, active_id, active=True)
            sources = (active, department, retired)
            if fault == "active_duplicate":
                current = GrantSourceService().canonicalize_source(
                    source_id=206,
                    subject_type="department",
                    subject_id="42",
                    userset_relation="member",
                    source_type="OTHER",
                    source_ref="independent-current-contribution",
                )
                raw = asdict(current)
                raw.pop("active")
                sources += (
                    plans.PermissionAssigneeBaseline(
                        id=raw.pop("source_id"), grant_id=active_id, tenant_id=101, state="ACTIVE", **raw
                    ),
                )
            session.add_all(Grant(**asdict(row)) for row in grants)
            session.add_all(Assignee(**asdict(row)) for row in sources)
            catalog = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
            baseline = plans.PermissionResourceBaseline(101, kind, ident, mode, grants, sources, ())
            snapshots = plans._grants(
                baseline,
                {row.model_key: row for row in catalog.models},
                {row.code: row.resource_types for row in catalog.actions},
                {row.id: tuple(s.to_source_record() for s in sources if s.grant_id == row.id) for row in grants},
            )
            visible = (
                VisibilityProjectionCompiler()
                .compile(tenant_id=101, grants=snapshots, existing_sources=())
                .active_sources
            )
            session.add_all(Visible(id=500 + i, **row.model_dump()) for i, row in enumerate(visible))
            store.tuples.difference_update(key for key in tuple(store.tuples) if key[2] == resource)
            store.tuples.update(delta.key for delta in compile_existing_mode_tuples(mode))
            store.tuples.update((row.projected_subject, "visible", resource) for row in visible)
            store.tuples.update(
                {
                    ("permission_model:viewer", "model", active_key),
                    (active_key, "grant", resource),
                    ("user:7", "ordinary_assignee", active_key),
                    ("user:7", "visible", resource),
                }
            )
        else:
            await session.execute(sa.update(Grant).where(Grant.id == 102).values(state="INACTIVE"))
            await session.execute(sa.update(Assignee).where(Assignee.id == 102).values(state="INACTIVE"))
            await session.execute(
                sa.update(Visible).where(Visible.model_key == "inactive-model").values(state="RETIRED")
            )
            session.add(Assignee(**asdict(department)))
        if fault == "missing_source":
            await session.execute(sa.delete(Assignee).where(Assignee.grant_id == retired_id))
    stale = {
        ("department:42#member", "ordinary_assignee", active_key),
        ("permission_model:inactive-model", "model", retired_key),
        (retired_key, "grant", resource),
        ("user:7", "ordinary_assignee", retired_key),
    }
    store.tuples.update(stale)
    if fault == "foreign":
        store.tuples.add((retired_key, "grant", "workflow:unowned"))
    elif fault == "unproven":
        store.tuples.add(("user:999", "ordinary_assignee", active_key))
    elif fault == "protected":
        store.tuples.add(("user:999", "protected_assignee", active_key))
    store.retired_projection_edges = stale


@pytest.mark.parametrize(
    "published_input",
    [
        {"original_graph_seed": original_edges},
        {"parent": True, "original_graph_seed": partial(original_edges, file=True)},
    ],
    indirect=True,
    ids=["moving-root", "unchanged-file"],
)
async def test_explicit_retired_sql_sources_are_deleted_by_native_publication_and_resume(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        before = (await session.execute(sa.select(Assignee).order_by(Assignee.id))).scalars().all()
        before = [row.model_dump() for row in before]
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    assert not value.store.retired_projection_edges & value.store.tuples
    assert not any(key[0] == "department:42#member" and key[1] == "ordinary_assignee" for key in value.store.tuples)
    requests = tuple(value.store.requests)
    for request in requests:
        if request.method == "POST" and request.url.path.endswith("/write"):
            writes = json.loads(request.content).get("writes", {}).get("tuple_keys", [])
            assert not any(
                (row["user"], row["relation"], row["object"]) in value.store.retired_projection_edges for row in writes
            )
    assert await app(value).arun_references(**value.input, operator_id=7) == result
    async with value.sessions() as session, session.begin():
        after = (await session.execute(sa.select(Assignee).order_by(Assignee.id))).scalars().all()
        assert [row.model_dump() for row in after] == before
        assert (
            await production_coverage_factory(session).arequire_global_ready()
        ).verified_tenant_ids == value.frozen.tenant_ids
    value.sessions.assert_closed()


@pytest.mark.parametrize(
    "published_input",
    [
        {"parent": True, "original_graph_seed": partial(original_edges, file=True, fault=fault)}
        for fault in ("foreign", "unproven", "protected", "missing_source")
    ],
    indirect=True,
    ids=["foreign-context", "unproven-subject", "unproven-protected", "missing-retired-source"],
)
async def test_unexplained_grant_context_still_blocks_before_publication(published_input):
    value = published_input
    original = set(value.store.tuples)
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.tuples == original
    assert not any(
        request.method == "POST" and request.url.path.endswith(("/write", "/authorization-models"))
        for request in value.store.requests
    )


@pytest.mark.parametrize(
    "published_input",
    [
        {
            "parent": True,
            "legacy_frozen_policy": True,
            "original_graph_seed": partial(original_edges, file=True),
        }
    ],
    indirect=True,
)
async def test_old_frozen_policy_preserves_its_original_extra_edge_contract(published_input):
    value = published_input
    result = await app(value).arun_permissions(**value.input, operator_id=7)
    assert result.complete and value.store.retired_projection_edges <= value.store.tuples
    assert await app(value).arun_permissions(**value.input, operator_id=7) == result


@pytest.mark.parametrize(
    "published_input",
    [
        {
            "parent": True,
            "original_graph_seed": partial(original_edges, file=True, fault="active_duplicate"),
        }
    ],
    indirect=True,
)
async def test_another_current_source_keeps_the_same_aggregate_assignee(published_input):
    value = published_input
    key = ("department:42#member", "ordinary_assignee", grant_key("knowledge_file", "1", "viewer"))
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete
    assert key in value.store.tuples
    assert not (value.store.retired_projection_edges - {key}) & value.store.tuples


@pytest.mark.parametrize(
    "published_input",
    [
        {
            "parent": True,
            "original_graph_seed": partial(original_edges, file=True),
        }
    ],
    indirect=True,
)
async def test_native_delete_ack_loss_resumes_the_original_frozen_run(published_input, monkeypatch):
    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher

    value = published_input
    apply = F118PermissionPublisher.aapply
    lost = False

    async def lose_ack(self, operation, *, draft):
        nonlocal lost
        result = await apply(self, operation, draft=draft)
        if not lost and operation[0] == "DELETE" and set(operation[1]) & value.store.retired_projection_edges:
            lost = True
            raise OSError("native deletion ACK lost")
        return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(F118PermissionPublisher, "aapply", lose_ack)
        with pytest.raises(BaseErrorCode):
            await app(value).arun_references(**value.input, operator_id=7)
    assert lost
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete and result.run_id == value.frozen.run_id
    assert not value.store.retired_projection_edges & value.store.tuples
