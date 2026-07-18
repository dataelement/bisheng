from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from bisheng.api.v1 import mark_task as mark_task_api
from bisheng.api.v1.schema.mark_schema import MarkTaskCreate
from bisheng.database.models import mark_task as mark_task_model
from bisheng.database.models.mark_task import MarkTask, MarkTaskDao


def test_mark_task_create_rejects_non_numeric_user_ids():
    with pytest.raises(ValidationError):
        MarkTaskCreate(app_list=['api-contract'], user_list=['api-contract'])


def test_mark_task_create_accepts_numeric_user_ids():
    payload = MarkTaskCreate(app_list=['flow-id'], user_list=['686', 687])

    assert payload.user_list == [686, 687]


def test_parse_process_user_ids_skips_legacy_invalid_values():
    assert mark_task_api._parse_process_user_ids('api-contract,686,,invalid,687', task_id=111) == [686, 687]


def test_list_mark_tasks_keeps_rows_with_legacy_invalid_user_ids(monkeypatch):
    task = MarkTask(
        id=111,
        create_id=1,
        create_user='contract-probe',
        app_id='api-contract',
        process_users='api-contract',
    )
    login_user = Mock(user_id=3)
    login_user.is_admin.return_value = True
    monkeypatch.setattr(mark_task_api.UserGroupDao, 'get_user_admin_group', Mock(return_value=[]))
    monkeypatch.setattr(MarkTaskDao, 'get_task_list', Mock(return_value=([task], 1)))
    monkeypatch.setattr(mark_task_api.MarkRecordDao, 'get_count', Mock(return_value=[]))
    get_user = Mock()
    monkeypatch.setattr(mark_task_api.UserDao, 'get_user', get_user)

    response = mark_task_api.list(request=Mock(), login_user=login_user)

    assert response.status_code == 200
    assert response.data['total'] == 1
    assert response.data['list'][0].id == 111
    assert response.data['list'][0].mark_process == []
    get_user.assert_not_called()


@pytest.mark.asyncio
async def test_create_mark_task_uses_atomic_assignment_write(monkeypatch):
    create_task = Mock()
    monkeypatch.setattr(MarkTaskDao, 'create_task_with_assignments', create_task)
    login_user = Mock(user_id=3, user_name='admin')
    payload = MarkTaskCreate(app_list=['flow-id'], user_list=[686])

    response = await mark_task_api.create(payload, login_user)

    task, app_ids, user_ids = create_task.call_args.args
    assert task.process_users == '686'
    assert app_ids == ['flow-id']
    assert user_ids == [686]
    assert response.status_code == 200


def test_task_and_assignments_share_one_transaction(monkeypatch):
    events = []
    assignments = []

    class FakeSession:
        def add(self, task):
            events.append('add_task')
            self.task = task

        def flush(self):
            events.append('flush_task')
            self.task.id = 42

        def add_all(self, values):
            events.append('add_assignments')
            assignments.extend(values)

        def commit(self):
            events.append('commit')

        def refresh(self, _task):
            events.append('refresh_task')

    @contextmanager
    def fake_session():
        yield FakeSession()

    monkeypatch.setattr(mark_task_model, 'get_sync_db_session', fake_session)
    task = MarkTask(create_id=3, create_user='admin', app_id='flow-a,flow-b', process_users='686')

    MarkTaskDao.create_task_with_assignments(task, ['flow-a', 'flow-b'], [686])

    assert events == ['add_task', 'flush_task', 'add_assignments', 'commit', 'refresh_task']
    assert [(item.task_id, item.app_id, item.user_id) for item in assignments] == [
        (42, 'flow-a', 686),
        (42, 'flow-b', 686),
    ]
