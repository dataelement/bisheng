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
    return patch(
        "bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples",
        new_callable=AsyncMock,
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
        ops = writer.await_args.args[0]
        assert [(o.action, o.user, o.relation, o.object) for o in ops] == [
            ("write", "department:1", "parent", "department:5"),
            ("write", "department:5", "parent", "department:9"),
        ]
