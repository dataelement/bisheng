"""组织四级标签：深度映射、冲突与鉴权。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.points import PointsCompanyRootConflictError, PointsPermissionDeniedError
from bisheng.points.domain.constants.org_levels import (
    org_level_for_relative_depth,
    relative_depth,
)
from bisheng.points.domain.services.department_org_level_service import DepartmentOrgLevelService
from bisheng.points.domain.services.points_auth import require_platform_admin


def test_relative_depth_mapping():
    assert relative_depth("/1/", "/1/") == 0
    assert relative_depth("/1/", "/1/2/") == 1
    assert relative_depth("/1/", "/1/2/3/") == 2
    assert relative_depth("/1/", "/1/2/3/4/") == 3
    assert relative_depth("/1/", "/9/") is None
    assert org_level_for_relative_depth(0) == "company"
    assert org_level_for_relative_depth(1) == "dept"
    assert org_level_for_relative_depth(2) == "office"
    assert org_level_for_relative_depth(3) == "squad"
    assert org_level_for_relative_depth(5) == "squad"


def test_non_admin_denied():
    with pytest.raises(PointsPermissionDeniedError):
        require_platform_admin(SimpleNamespace(is_admin=lambda: False, is_global_super=False))


def test_global_super_allowed():
    require_platform_admin(SimpleNamespace(is_admin=lambda: False, is_global_super=True))


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_set_company_root_rejects_other_company():
    service = DepartmentOrgLevelService()
    company = SimpleNamespace(id=10, path="/10/", dept_id="BS@10", status="active")
    other = SimpleNamespace(id=99, path="/99/", org_level="company", status="active")

    class FakeSession:
        async def exec(self, _stmt):
            return _FakeResult([other])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    with (
        patch.object(service, "_resolve_department", AsyncMock(return_value=company)),
        patch(
            "bisheng.points.domain.services.department_org_level_service.get_async_db_session",
            return_value=FakeSession(),
        ),
    ):
        with pytest.raises(PointsCompanyRootConflictError):
            await service.set_company_root(
                SimpleNamespace(is_admin=lambda: True, is_global_super=False),
                "10",
            )


@pytest.mark.asyncio
async def test_set_company_root_labels_subtree_by_depth():
    service = DepartmentOrgLevelService()
    company = SimpleNamespace(id=1, path="/1/", dept_id="BS@1", status="active", org_level=None)
    dept = SimpleNamespace(id=2, path="/1/2/", status="active", org_level=None)
    office = SimpleNamespace(id=3, path="/1/2/3/", status="active", org_level=None)
    squad = SimpleNamespace(id=4, path="/1/2/3/4/", status="active", org_level=None)
    nodes = [company, dept, office, squad]
    cleared = {"ok": False}

    class ScriptedSession:
        def __init__(self):
            self.queue = [
                _FakeResult([]),  # existing companies
                "update",
                _FakeResult(nodes),  # subtree
            ]
            self._i = 0

        async def exec(self, _stmt):
            item = self.queue[self._i]
            self._i += 1
            if item == "update":
                cleared["ok"] = True
                return _FakeResult([])
            return item

        async def commit(self):
            return None

        def add(self, *_):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    with (
        patch.object(service, "_resolve_department", AsyncMock(return_value=company)),
        patch(
            "bisheng.points.domain.services.department_org_level_service.get_async_db_session",
            return_value=ScriptedSession(),
        ),
    ):
        result = await service.set_company_root(
            SimpleNamespace(is_admin=lambda: True, is_global_super=False),
            "1",
        )

    assert cleared["ok"] is True
    assert company.org_level == "company"
    assert dept.org_level == "dept"
    assert office.org_level == "office"
    assert squad.org_level == "squad"
    assert result.company_id == 1
    assert result.labeled_count == 4
    assert result.levels == {"company": 1, "dept": 1, "office": 1, "squad": 1}
