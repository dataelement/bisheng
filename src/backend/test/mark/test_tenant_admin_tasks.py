"""Tenant administrators manage tasks created by other people in their tenant."""

from contextlib import contextmanager
from inspect import isawaitable
from unittest.mock import AsyncMock, Mock

from sqlmodel import select

from bisheng.api.v1 import mark_task as api
from bisheng.api.v1.schema.mark_schema import MarkTaskCreate
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope, visible_tenant_ids
from bisheng.database.models import mark_task as models
from bisheng.database.models.mark_app_user import MarkAppUser
from bisheng.database.models.mark_task import MarkTask, MarkTaskDao
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@contextmanager
def shared_visibility():
    token = visible_tenant_ids.set(frozenset({1, 2}))
    try:
        yield
    finally:
        visible_tenant_ids.reset(token)


async def task_list(user):
    result = api.list(request=Mock(), login_user=user)
    return await result if isawaitable(result) else result


async def test_selected_tenant_creation_and_child_admin_list_are_isolated(managed_db, monkeypatch):
    await managed_db.create(MarkTask, MarkAppUser)
    monkeypatch.setattr(models, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(api.UserGroupDao, "get_user_admin_group", Mock(return_value=[]))
    monkeypatch.setattr(api.MarkRecordDao, "get_count", Mock(return_value=[]))
    monkeypatch.setattr(api.UserDao, "get_user", Mock(return_value=None))
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=True))
    root = UserPayload(user_id=3, user_name="root", tenant_id=1, user_role=[1], is_global_super=True)
    child = UserPayload(user_id=7, user_name="child", tenant_id=2, user_role=[])
    payload = MarkTaskCreate(app_list=["flow"], user_list=[99])
    with tenant_execution_scope(1):
        await api.create(payload, root)
    with management_scope(home=1, target=2):
        await api.create(payload, root)
        assert root.tenant_id == 1
    with tenant_execution_scope(3):
        await api.create(payload, root)
    with tenant_execution_scope(2), shared_visibility():
        result = await task_list(child)
        assert result.data["total"] == 1
        assert [(row.tenant_id, row.create_id) for row in result.data["list"]] == [(2, 3)]
        await api.create(payload, child)
        result = await task_list(child)
        assert result.data["total"] == 2
        assert {row.create_id for row in result.data["list"]} == {3, 7}
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            assignments = (await session.exec(select(MarkAppUser))).all()
            assert sorted(row.tenant_id for row in assignments) == [1, 2, 2, 3]


async def test_ordinary_task_list_keeps_participant_filter(monkeypatch):
    monkeypatch.setattr(api, "is_current_tenant_administrator", AsyncMock(return_value=False), raising=False)
    monkeypatch.setattr(api.UserGroupDao, "get_user_admin_group", Mock(return_value=[]))
    query = Mock(return_value=([], 0))
    monkeypatch.setattr(MarkTaskDao, "get_task_list", query)
    await task_list(UserPayload(user_id=8, tenant_id=2, user_role=[]))
    assert query.call_args.kwargs["user_id"] == 8
    assert query.call_args.kwargs["create_id"] is None


async def test_child_admin_has_annotation_entry_without_an_assigned_task(monkeypatch):
    from bisheng.user.api import user as user_api

    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=True))
    task = Mock(return_value=None)
    monkeypatch.setattr(MarkTaskDao, "get_task", task)
    monkeypatch.setattr(user_api.UserGroupDao, "get_user_admin_group", Mock(return_value=[]))
    user = UserPayload(user_id=7, tenant_id=2, user_role=[])
    with tenant_execution_scope(2):
        result = await user_api.has_mark_access(request=Mock(), login_user=user)
    assert result.data is True
    task.assert_not_called()
