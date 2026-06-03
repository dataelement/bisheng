from types import SimpleNamespace

import pytest

from bisheng.approval.domain.services.approver_resolver import (
    resolve_approvers_from_sources,
    resolve_department_admins_for_user_ids,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao


@pytest.mark.asyncio
async def test_department_admin_keeps_current_department_admins(monkeypatch):
    async def fake_get_department(department_id: int):
        assert department_id == 30
        return SimpleNamespace(id=30, path='/10/20/30/')

    async def fake_get_admins(department_id: int):
        return {
            30: [3001],
            20: [2001],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentDao, 'aget_by_id', fake_get_department)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_department', fake_get_admins)

    approvers = await resolve_approvers_from_sources(
        [{'type': 'department_admin'}],
        SimpleNamespace(applicant_department_id=30),
    )

    assert approvers == [3001]


@pytest.mark.asyncio
async def test_department_admin_resolves_nearest_parent_admin_when_leaf_has_none(monkeypatch):
    async def fake_get_department(department_id: int):
        assert department_id == 30
        return SimpleNamespace(id=30, path='/10/20/30/')

    async def fake_get_admins(department_id: int):
        return {
            30: [],
            20: [2001, 2002],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentDao, 'aget_by_id', fake_get_department)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_department', fake_get_admins)

    approvers = await resolve_approvers_from_sources(
        [{'type': 'department_admin'}],
        SimpleNamespace(applicant_department_id=30),
    )

    assert approvers == [2001, 2002]


@pytest.mark.asyncio
async def test_department_admin_returns_empty_when_department_chain_has_no_admins(monkeypatch):
    async def fake_get_department(department_id: int):
        assert department_id == 30
        return SimpleNamespace(id=30, path='/10/20/30/')

    async def fake_get_admins(department_id: int):
        return []

    monkeypatch.setattr(DepartmentDao, 'aget_by_id', fake_get_department)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_department', fake_get_admins)

    approvers = await resolve_approvers_from_sources(
        [{'type': 'department_admin'}],
        SimpleNamespace(applicant_department_id=30),
    )

    assert approvers == []


@pytest.mark.asyncio
async def test_department_admin_does_not_trust_malformed_department_path(monkeypatch):
    queried_department_ids: list[int] = []

    async def fake_get_department(department_id: int):
        assert department_id == 30
        return SimpleNamespace(id=30, path='/10/bad/30/')

    async def fake_get_admins(department_id: int):
        queried_department_ids.append(department_id)
        return {
            30: [],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentDao, 'aget_by_id', fake_get_department)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_department', fake_get_admins)

    approvers = await resolve_approvers_from_sources(
        [{'type': 'department_admin'}],
        SimpleNamespace(applicant_department_id=30),
    )

    assert approvers == []
    assert queried_department_ids == [30]


@pytest.mark.asyncio
async def test_department_admins_for_user_ids_batches_queries_and_keeps_order(monkeypatch):
    calls: list[tuple[str, tuple[int, ...]]] = []

    async def fake_get_user_departments(user_ids: list[int]):
        calls.append(('user_departments', tuple(user_ids)))
        return [
            SimpleNamespace(user_id=41, department_id=300, is_primary=1),
            SimpleNamespace(user_id=42, department_id=400, is_primary=1),
            SimpleNamespace(user_id=43, department_id=500, is_primary=0),
            SimpleNamespace(user_id=43, department_id=600, is_primary=1),
        ]

    async def fake_get_departments(department_ids: list[int]):
        calls.append(('departments', tuple(department_ids)))
        return [
            SimpleNamespace(id=300, path='/100/200/300/'),
            SimpleNamespace(id=400, path='/100/400/'),
            SimpleNamespace(id=600, path='/100/600/'),
        ]

    async def fake_get_admins_by_departments(department_ids: list[int]):
        calls.append(('admins', tuple(department_ids)))
        return {
            300: [],
            200: [2001, 2002],
            400: [4001, 2001],
            600: [],
            100: [1001],
        }

    async def fail_get_primary_department(user_id: int):
        raise AssertionError('per-user primary department lookup should not be used')

    async def fail_get_department(department_id: int):
        raise AssertionError('per-department lookup should not be used')

    async def fail_get_admins(department_id: int):
        raise AssertionError('per-department admin lookup should not be used')

    monkeypatch.setattr(UserDepartmentDao, 'aget_by_user_ids', fake_get_user_departments)
    monkeypatch.setattr(UserDepartmentDao, 'aget_user_primary_department', fail_get_primary_department)
    monkeypatch.setattr(DepartmentDao, 'aget_by_ids', fake_get_departments)
    monkeypatch.setattr(DepartmentDao, 'aget_by_id', fail_get_department)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_departments', fake_get_admins_by_departments)
    monkeypatch.setattr(DepartmentAdminGrantDao, 'aget_user_ids_by_department', fail_get_admins)

    approvers = await resolve_department_admins_for_user_ids([41, 42, 41, 43])

    assert approvers == [2001, 2002, 4001, 1001]
    assert calls == [
        ('user_departments', (41, 42, 43)),
        ('departments', (300, 400, 600)),
        ('admins', (100, 200, 300, 400, 600)),
    ]
