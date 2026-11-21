"""Offline review probe against an independently archived pre-fix source tree.

Run from src/backend with an offline config and the fixed checkout on PYTHONPATH:
F118_REVIEW_BASE_BACKEND=/path/to/base/src/backend python -m pytest -c pyproject.toml \
  /absolute/path/to/review_legacy_equivalence.py -q

Only the original script implementations come from the archive. Both versions
use identical native SQLite rows and fixture FGA transport. No production IO.
"""

import json
import os
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

import scripts
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration import f118_plan
from scripts import prepare_f118_history as current
from test.knowledge_unification import test_prepare_history as fixtures

history, native, resource_native = (
    fixtures.history,
    fixtures.native,
    fixtures.resource_native,
)


def old_module(name, filename):
    base = Path(os.environ["F118_REVIEW_BASE_BACKEND"])
    module = ModuleType(name)
    # The old CLI's import bootstrap must keep using the selected fixed checkout;
    # the archived script itself is compiled verbatim, without source rewriting.
    module.__file__ = str(Path(current.__file__).with_name(filename))
    source = base / "scripts" / filename
    exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
    return module


async def legacy_capture(history, monkeypatch):
    old_business = old_module("review_old_business", "f118_history_business.py")
    old_history = old_module("review_old_history", "prepare_f118_history.py")
    with monkeypatch.context() as patch:
        patch.setattr(scripts, "f118_history_business", old_business)
        return await old_history.capture(history.sessions, history.fga)


def semantic_plan(plan):
    """Only ignore independent item ordering; keep every selected fact/hash."""
    plan = json.loads(json.dumps(plan))
    for section in ("levels", "parents", "purges", "blocked", "retained_evidence"):
        for item in plan[section]:
            for key in ("incoming", "tuples"):
                if key in item:
                    item[key].sort(key=lambda value: json.dumps(value, sort_keys=True))
        plan[section].sort(key=lambda value: json.dumps(value, sort_keys=True))
    return plan


@pytest.mark.parametrize("scenario", ["original", "owners", "forest", "retained_chain"])
async def test_native_inventory_preserves_old_selected_facts_and_digests(
    history, monkeypatch, scenario
):
    if scenario == "owners":
        async with current.global_session(history.sessions) as session:
            await session.exec(
                sa.update(KnowledgeFile)
                .where(KnowledgeFile.id == 30)
                .values(tenant_id=202)
            )
            session.add(
                Flow(id="parent", tenant_id=101, name="parent", user_id=7, flow_type=10)
            )
            session.add(
                FlowVersion(
                    id=71, tenant_id=202, flow_id="parent", name="v", flow_type=10
                )
            )
            session.add(
                Knowledge(
                    id=11,
                    tenant_id=101,
                    user_id=7,
                    name="empty",
                    type=0,
                    model="旧模型",
                )
            )
            session.add(
                Tag(
                    id=52,
                    tenant_id=202,
                    user_id=7,
                    name="tag",
                    business_type="knowledge",
                    business_id="10",
                )
            )
            session.add(
                TagLink(
                    id=52,
                    tenant_id=202,
                    user_id=7,
                    tag_id=52,
                    resource_type=8,
                    resource_id="30",
                )
            )
    if scenario in {"forest", "retained_chain"}:
        async with current.global_session(history.sessions) as session:
            for ident, parent in (
                (1001, "10"),
                (1002, "1001"),
                (1003, "10"),
                (1004, "1003"),
            ):
                root = parent == "10"
                session.add(
                    ResourcePermissionMode(
                        id=ident,
                        tenant_id=101,
                        resource_type="folder",
                        resource_id=str(ident),
                        mode="INHERIT",
                        version=1,
                        projection_state="CURRENT",
                        parent_type="knowledge_library" if root else "folder",
                        parent_id=parent,
                    )
                )
                history.fga.present.add(
                    (
                        f"{'knowledge_library' if root else 'folder'}:{parent}",
                        "parent",
                        f"folder:{ident}",
                    )
                )
        if scenario == "retained_chain":
            history.fga.present.add(("folder:1002", "parent", "folder:external-live"))
    expected = await legacy_capture(history, monkeypatch)
    actual = await current.capture(history.sessions, history.fga)
    assert semantic_plan(actual) == semantic_plan(expected)
    if scenario in {"original", "owners"}:
        # No independent cleanup ordering difference in these two fixtures.
        assert current.checksum(actual) == current.checksum(expected)


async def test_original_saved_plan_resumes_after_parent_commit_without_refreezing(
    history, monkeypatch, tmp_path
):
    plan = await legacy_capture(history, monkeypatch)
    path = tmp_path / "original-schema-1.json"
    current.save_plan(path, plan)
    saved = path.read_bytes()
    original = history.runtime.project_delete
    monkeypatch.setattr(
        history.runtime,
        "project_delete",
        AsyncMock(side_effect=RuntimeError("stop after parent commit")),
    )
    with pytest.raises(RuntimeError, match="stop after parent commit"):
        await current.apply(
            current.load_plan(path),
            sessions=history.sessions,
            client=history.fga,
            runtime=history.runtime,
            operator_id=7,
        )
    assert history.fga.writes > 0
    monkeypatch.setattr(history.runtime, "project_delete", original)
    await current.apply(
        current.load_plan(path),
        sessions=history.sessions,
        client=history.fga,
        runtime=history.runtime,
        operator_id=7,
    )
    writes = history.fga.writes
    await current.apply(
        current.load_plan(path),
        sessions=history.sessions,
        client=history.fga,
        runtime=history.runtime,
        operator_id=7,
    )
    assert history.fga.writes == writes
    assert path.read_bytes() == saved


async def test_batch_reader_preserves_original_inactive_and_paged_source_buckets(
    history,
):
    from test.knowledge_unification.test_perm_migration import source
    from test.knowledge_unification.test_perm_migration_snapshot import seed_rows

    base = Path(os.environ["F118_REVIEW_BASE_BACKEND"])
    filename = (
        "bisheng/permission/domain/repositories/f118_migration_snapshot_repository.py"
    )
    legacy = ModuleType("review_old_permission_snapshot")
    exec(
        compile((base / filename).read_text(), str(base / filename), "exec"),
        legacy.__dict__,
    )
    async with current.global_session(history.sessions) as session:
        original = await seed_rows(session)
        for ident in range(10000, 10401):
            session.add(
                PermissionGrant(
                    id=ident,
                    tenant_id=101,
                    resource_type="knowledge_library"
                    if ident % 2
                    else "knowledge_space",
                    resource_id="40",
                    model_key=f"review-{ident}",
                    state="ACTIVE" if ident % 2 else "INACTIVE",
                    projection_state="CURRENT",
                )
            )
        await session.flush()
        for ident in range(10000, 10401):
            session.add(
                PermissionGrantAssignee(
                    **asdict(
                        source(
                            f118_plan,
                            ident,
                            ident,
                            state="ACTIVE" if ident % 2 else "INACTIVE",
                        )
                    )
                )
            )
    requests = (
        (original.mode.id, (("knowledge_library", "40"), ("knowledge_space", "40"))),
        (20, (("folder", "20"),)),
        (30, (("knowledge_file", "30"),)),
    )
    old, new = (
        legacy.PermissionMigrationSnapshotRepository(),
        PermissionMigrationSnapshotRepository(),
    )
    with tenant_execution_scope(101):
        async with history.sessions() as session, session.begin():
            expected = tuple(
                [
                    await old.aload_resource(session, mode_id=ident, resource_keys=keys)
                    for ident, keys in requests
                ]
            )
            actual = await new.aload_resources(session, requests=requests)
            assert actual == expected
            assert len(actual[0].grants) == len(original.grants) + 401
            assert len(actual[0].assignees) == len(original.assignees) + 401
    async with current.global_session(history.sessions) as session:
        await session.exec(
            sa.update(PermissionGrantAssignee)
            .where(PermissionGrantAssignee.id == 10000)
            .values(tenant_id=202)
        )
    with tenant_execution_scope(101):
        async with history.sessions() as session, session.begin():
            with pytest.raises(PermissionMigrationBlockedError):
                await old.aload_resource(
                    session, mode_id=requests[0][0], resource_keys=requests[0][1]
                )
            with pytest.raises(PermissionMigrationBlockedError):
                await new.aload_resources(session, requests=requests)
