"""Tests for ``scripts/backfill_department_parent_tuples.py``.

DB-integration is skipped (sqlite fixtures lack the full schema); these
cover the dry-run/apply orchestration with the edge collector and the
OpenFGA writer mocked.
"""

import contextlib
from unittest.mock import AsyncMock, patch

import pytest

import scripts.backfill_department_parent_tuples as mod


@pytest.fixture(autouse=True)
def _stub_tenant_filter():
    with patch(
        "bisheng.core.context.tenant.bypass_tenant_filter",
        new=lambda: contextlib.nullcontext(),
    ):
        yield


def _patch_edges(edges):
    return patch.object(
        mod,
        "_collect_parent_edges",
        new_callable=AsyncMock,
        return_value=edges,
    )


def _patch_writer():
    permissions = AsyncMock()
    permissions.apply_changes = AsyncMock()
    return patch(
        "bisheng.permission.application.get_permission_relation_api",
        new=AsyncMock(return_value=permissions),
    )


@pytest.mark.asyncio
class TestRun:
    async def test_empty_tree_is_noop(self):
        with _patch_edges([]), _patch_writer() as writer:
            rc = await mod.run(apply=True)
        assert rc == 0
        writer.assert_not_awaited()

    async def test_dry_run_does_not_write(self):
        with _patch_edges([(5, 1), (9, 5)]), _patch_writer() as writer:
            rc = await mod.run(apply=False)
        assert rc == 0
        writer.assert_not_awaited()

    async def test_apply_writes_one_parent_edge_per_child(self):
        with _patch_edges([(5, 1), (9, 5)]), _patch_writer() as writer:
            rc = await mod.run(apply=True)
        assert rc == 0
        writer.assert_awaited_once()
        permissions = writer.return_value
        permissions.apply_changes.assert_awaited_once()
        changes = permissions.apply_changes.await_args.args[0]
        assert [
            (
                change.action,
                change.relation.subject.subject_id,
                change.relation.relation,
                change.relation.resource.resource_id,
            )
            for change in changes
        ] == [
            ("grant", "1", "parent", "5"),
            ("grant", "5", "parent", "9"),
        ]
