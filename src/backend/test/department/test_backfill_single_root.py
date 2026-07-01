"""Tests for the single-root backfill script
``scripts/backfill_departments_under_single_root.py``.

DB-integration is skipped (sqlite fixtures don't carry the full schema);
these cover the pure path-rebasing helper and the apply/dry-run
orchestration with the DAO layer mocked.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import scripts.backfill_departments_under_single_root as mod


def _dept(id, *, path, name="D", source="wecom"):
    return SimpleNamespace(id=id, path=path, name=name, source=source)


@pytest.fixture(autouse=True)
def _stub_tenant_filter():
    """``run`` opens ``bypass_tenant_filter()`` (imported locally). Stub the
    real symbol with a no-op context so the orchestration runs DB-free.
    """
    with patch(
        "bisheng.core.context.tenant.bypass_tenant_filter",
        new=lambda: contextlib.nullcontext(),
    ):
        yield


def _patch_root(root):
    return patch(
        "bisheng.database.models.department.DepartmentDao.aget_tenant_root_via_pointer",
        new_callable=AsyncMock,
        return_value=root,
    )


def _patch_reparent():
    return patch(
        "bisheng.database.models.department.DepartmentDao.areparent_root_under",
        new_callable=AsyncMock,
        return_value=3,
    )


class TestRebasedPath:
    def test_top_level_gets_root_prefix(self):
        assert mod._rebased_path("/1/", "/5/") == "/1/5/"

    def test_root_path_without_trailing_slash(self):
        assert mod._rebased_path("/1", "/5/") == "/1/5/"

    def test_multi_digit_ids(self):
        assert mod._rebased_path("/1/", "/237/") == "/1/237/"


@pytest.mark.asyncio
class TestRun:
    async def test_no_root_pointer_aborts(self):
        with _patch_root(None):
            rc = await mod.run(apply=True)
        assert rc == 2

    async def test_dry_run_does_not_mutate(self):
        root = _dept(1, path="/1/", name="默认组织", source="local")
        extra = _dept(5, path="/5/")
        with (
            _patch_root(root),
            patch.object(
                mod,
                "_collect_extra_roots",
                new_callable=AsyncMock,
                return_value=[extra],
            ),
            _patch_reparent() as reparent,
        ):
            rc = await mod.run(apply=False)
        assert rc == 0
        reparent.assert_not_awaited()

    async def test_apply_collapses_each_extra_root(self):
        root = _dept(1, path="/1/", name="默认组织", source="local")
        extras = [_dept(5, path="/5/"), _dept(8, path="/8/")]
        with (
            _patch_root(root),
            patch.object(
                mod,
                "_collect_extra_roots",
                new_callable=AsyncMock,
                return_value=extras,
            ),
            _patch_reparent() as reparent,
        ):
            rc = await mod.run(apply=True)
        assert rc == 0
        assert reparent.await_count == 2
        first = reparent.await_args_list[0].kwargs
        assert first["dept_id"] == 5
        assert first["old_path"] == "/5/"
        assert first["new_path"] == "/1/5/"
        assert first["new_parent_id"] == 1

    async def test_malformed_path_is_skipped(self):
        root = _dept(1, path="/1/", name="默认组织", source="local")
        # path doesn't match the expected '/<id>/' shape → skip, don't corrupt.
        broken = _dept(5, path="/9/5/")
        with (
            _patch_root(root),
            patch.object(
                mod,
                "_collect_extra_roots",
                new_callable=AsyncMock,
                return_value=[broken],
            ),
            _patch_reparent() as reparent,
        ):
            rc = await mod.run(apply=True)
        assert rc == 0
        reparent.assert_not_awaited()
