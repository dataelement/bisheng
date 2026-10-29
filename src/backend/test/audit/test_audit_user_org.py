"""Current primary-department names on the audit lists."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import langchain.docstore.document  # noqa: F401
except ModuleNotFoundError:
    from langchain_core.documents import Document

    docstore = types.ModuleType("langchain.docstore")
    document_mod = types.ModuleType("langchain.docstore.document")
    document_mod.Document = Document
    sys.modules["langchain.docstore"] = docstore
    sys.modules["langchain.docstore.document"] = document_mod

import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.audit_user_org import (
    list_user_org_options,
    org_names_for_users,
    org_names_from_department,
    user_ids_for_org_filters,
)


def _node(node_id: int, name: str, path: str, level: str, status: str = "active"):
    return SimpleNamespace(id=node_id, name=name, path=path, org_level=level, status=status)


def _tree():
    company = _node(1, "首钢", "/1/", "company")
    department = _node(2, "炼铁部", "/1/2/", "dept")
    office = _node(3, "一科室", "/1/2/3/", "office")
    squad = _node(4, "甲班", "/1/2/3/4/", "squad")
    return {1: company, 2: department, 3: office, 4: squad}, squad


def _admin():
    return SimpleNamespace(user_id=1, is_admin=lambda: True, is_global_super=True)


def test_squad_member_resolves_company_department_and_office():
    by_id, squad = _tree()
    assert org_names_from_department(squad, by_id) == {
        "department_name": "炼铁部",
        "company_name": "首钢",
        "office_name": "一科室",
    }


def test_inactive_office_is_left_blank():
    by_id, squad = _tree()
    by_id[3] = _node(3, "一科室", "/1/2/3/", "office", status="archived")
    names = org_names_from_department(squad, by_id)
    assert names["office_name"] == ""
    assert names["department_name"] == "炼铁部"
    assert names["company_name"] == "首钢"


def test_missing_department_is_blank():
    assert org_names_from_department(None, {}) == {
        "department_name": "",
        "company_name": "",
        "office_name": "",
    }


def test_untagged_node_uses_depth_under_its_company():
    company = _node(1, "首钢", "/1/", "company")
    department = _node(2, "炼铁部", "/1/2/", "")
    by_id = {1: company, 2: department}
    assert org_names_from_department(department, by_id)["department_name"] == "炼铁部"


@pytest.mark.asyncio
async def test_org_filter_absent_does_not_read_departments():
    with patch(
        "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_name",
        new=AsyncMock(side_effect=AssertionError("should not query")),
    ):
        assert await user_ids_for_org_filters(None, "  ", "") is None


@pytest.mark.asyncio
async def test_office_filter_includes_primary_users_under_that_node():
    office = _node(3, "一科室", "/1/2/3/", "office")
    with (
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_name",
            new=AsyncMock(return_value=[office]),
        ),
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(return_value=[3, 4]),
        ) as subtree,
        patch(
            "bisheng.api.services.audit_user_org.UserDepartmentDao.aget_primary_user_ids_by_department_ids",
            new=AsyncMock(return_value=[8, 9]),
        ) as members,
    ):
        assert await user_ids_for_org_filters(user_office="一科室") == {8, 9}
    subtree.assert_awaited_once_with("/1/2/3/")
    members.assert_awaited_once_with([3, 4])


@pytest.mark.asyncio
async def test_empty_department_path_does_not_match_every_department():
    isolated = _node(7, "孤立科室", "", "office")
    with (
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_name",
            new=AsyncMock(return_value=[isolated]),
        ),
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(side_effect=AssertionError("empty path must not scan")),
        ),
        patch(
            "bisheng.api.services.audit_user_org.UserDepartmentDao.aget_primary_user_ids_by_department_ids",
            new=AsyncMock(return_value=[3]),
        ) as members,
    ):
        assert await user_ids_for_org_filters(user_office="孤立科室") == {3}
    members.assert_awaited_once_with([7])


@pytest.mark.asyncio
async def test_three_org_filters_intersect_user_ids():
    async def by_name(name):
        if name == "一科室":
            return [_node(3, "一科室", "/1/2/3/", "office")]
        return [_node(1, "首钢", "/1/", "company")]

    async def subtree(path):
        if path == "/1/2/3/":
            return [3, 4]
        return [1, 2, 3, 4]

    async def members(department_ids):
        if department_ids == [3, 4]:
            return [8]
        return [8, 9]

    with (
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_name",
            new=AsyncMock(side_effect=by_name),
        ),
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(side_effect=subtree),
        ),
        patch(
            "bisheng.api.services.audit_user_org.UserDepartmentDao.aget_primary_user_ids_by_department_ids",
            new=AsyncMock(side_effect=members),
        ),
    ):
        assert await user_ids_for_org_filters(user_company="首钢", user_office="一科室") == {8}


@pytest.mark.asyncio
async def test_unknown_org_name_matches_nobody():
    with patch(
        "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_name",
        new=AsyncMock(return_value=[]),
    ):
        assert await user_ids_for_org_filters(user_department="不存在") == set()


@pytest.mark.asyncio
async def test_options_come_from_active_org_levels_only():
    rows = list(_tree()[0].values())
    with patch(
        "bisheng.api.services.audit_user_org.DepartmentDao.aget_all_active",
        new=AsyncMock(return_value=rows),
    ):
        options = await list_user_org_options()
    assert options == {
        "companies": ["首钢"],
        "departments": ["炼铁部"],
        "offices": ["一科室"],
    }


@pytest.mark.asyncio
async def test_page_names_use_the_smaller_primary_department_id():
    memberships = [
        SimpleNamespace(user_id=8, department_id=9, is_primary=1),
        SimpleNamespace(user_id=8, department_id=2, is_primary=1),
        SimpleNamespace(user_id=8, department_id=1, is_primary=0),
    ]
    department = _node(2, "炼铁部", "/1/2/", "dept")
    company = _node(1, "首钢", "/1/", "company")
    with (
        patch(
            "bisheng.api.services.audit_user_org.UserDepartmentDao.aget_by_user_ids",
            new=AsyncMock(return_value=memberships),
        ),
        patch(
            "bisheng.api.services.audit_user_org.DepartmentDao.aget_by_ids",
            new=AsyncMock(side_effect=[[department], [company]]),
        ) as loaded,
    ):
        names = await org_names_for_users([8, 0])
    assert loaded.await_args_list[0].args[0] == [2]
    assert names[8]["department_name"] == "炼铁部"
    assert names[8]["company_name"] == "首钢"


class _Log:
    def __init__(self, operator_id: int):
        self.operator_id = operator_id

    def model_dump(self):
        return {"operator_id": self.operator_id, "action": "create_chat"}


@pytest.mark.asyncio
async def test_audit_list_skips_log_query_when_org_filter_matches_nobody():
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch(
            "bisheng.api.services.audit_log.user_ids_for_org_filters",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "bisheng.api.services.audit_log.AuditLogDao.get_audit_logs",
            new=AsyncMock(),
        ) as logs,
    ):
        resp = await AuditLogService.get_audit_log(
            _admin(),
            [],
            [],
            None,
            None,
            None,
            None,
            1,
            20,
            user_department="炼铁部",
        )
    logs.assert_not_called()
    assert resp.status_code == 200
    assert resp.data["total"] == 0
    assert resp.data["data"] == []


@pytest.mark.asyncio
async def test_audit_list_filters_operator_ids_and_attaches_page_names():
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch(
            "bisheng.api.services.audit_log.user_ids_for_org_filters",
            new=AsyncMock(return_value={8, 9}),
        ),
        patch(
            "bisheng.api.services.audit_log.AuditLogDao.get_audit_logs",
            new=AsyncMock(return_value=([_Log(9)], 1)),
        ) as logs,
        patch(
            "bisheng.api.services.audit_log.UserDao.aget_user_by_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.api.services.audit_log.org_names_for_users",
            new=AsyncMock(
                return_value={
                    9: {"department_name": "炼铁部", "company_name": "首钢", "office_name": "一科室"},
                }
            ),
        ) as names,
    ):
        resp = await AuditLogService.get_audit_log(
            _admin(),
            [],
            [9, 10],
            None,
            None,
            None,
            None,
            1,
            20,
            user_office="一科室",
        )
    assert logs.await_args.args[1] == [9]
    names.assert_awaited_once_with([9])
    row = resp.data["data"][0]
    assert row["department_name"] == "炼铁部"
    assert row["company_name"] == "首钢"
    assert row["office_name"] == "一科室"


@pytest.mark.asyncio
async def test_session_list_returns_empty_without_query_when_org_matches_nobody():
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch(
            "bisheng.api.services.audit_log.user_ids_for_org_filters",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "bisheng.api.services.audit_log.MessageSessionDao.get_statement_results",
            new=AsyncMock(),
        ) as results,
    ):
        rows, total = await AuditLogService.get_session_list(
            _admin(),
            [],
            [],
            [],
            None,
            None,
            None,
            None,
            1,
            20,
            user_company="首钢",
        )
    results.assert_not_called()
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_session_export_forwards_org_filters():
    with patch.object(
        AuditLogService,
        "get_session_list",
        new=AsyncMock(return_value=([], 0)),
    ) as listed:
        await AuditLogService.get_session_messages(
            _admin(),
            [],
            [],
            [],
            None,
            None,
            None,
            None,
            None,
            "炼铁部",
            "首钢",
            "一科室",
        )
    assert listed.await_args.args[-3:] == ("炼铁部", "首钢", "一科室")
