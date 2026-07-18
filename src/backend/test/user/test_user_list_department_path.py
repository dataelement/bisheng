"""F038: ``/user/list?with_department_path=true`` returns each user's primary
department FULL path, so the user picker resolves labels server-side instead of
firing one path-tree call per distinct department in the result page."""

import types
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.department import DepartmentDao


class TestDepartmentPathLabelMap:
    @pytest.mark.asyncio
    async def test_full_path_with_batched_ancestor_load(self):
        from bisheng.user.api.user import _department_path_label_map

        catalog = {
            1: types.SimpleNamespace(id=1, name="总公司", path="/1/"),
            21: types.SimpleNamespace(id=21, name="研发部", path="/1/21/"),
            106: types.SimpleNamespace(id=106, name="平台组", path="/1/21/106/"),
        }
        calls: list[list[int]] = []

        async def fake_aget_by_ids(ids):
            calls.append(sorted(ids))
            return [catalog[i] for i in ids if i in catalog]

        with patch.object(DepartmentDao, "aget_by_ids", new=AsyncMock(side_effect=fake_aget_by_ids)):
            labels = await _department_path_label_map([106, 106, None])

        assert labels == {106: "总公司/研发部/平台组"}
        # one query for the requested depts, one batched query for missing ancestors
        assert len(calls) == 2
        assert calls[0] == [106]
        assert calls[1] == [1, 21]

    @pytest.mark.asyncio
    async def test_empty_returns_empty(self):
        from bisheng.user.api.user import _department_path_label_map

        assert await _department_path_label_map([]) == {}

    @pytest.mark.asyncio
    async def test_no_extra_query_when_all_ancestors_granted(self):
        from bisheng.user.api.user import _department_path_label_map

        catalog = {
            1: types.SimpleNamespace(id=1, name="总公司", path="/1/"),
            21: types.SimpleNamespace(id=21, name="研发部", path="/1/21/"),
        }
        calls: list[list[int]] = []

        async def fake_aget_by_ids(ids):
            calls.append(sorted(ids))
            return [catalog[i] for i in ids if i in catalog]

        with patch.object(DepartmentDao, "aget_by_ids", new=AsyncMock(side_effect=fake_aget_by_ids)):
            labels = await _department_path_label_map([1, 21])

        assert labels == {1: "总公司", 21: "总公司/研发部"}
        assert len(calls) == 1  # every ancestor already in the requested set
