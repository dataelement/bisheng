import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_retry_module():
    fake_celery = SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn))
    sys.modules['bisheng.worker.main'] = SimpleNamespace(bisheng_celery=fake_celery)
    path = Path(__file__).resolve().parents[1] / 'bisheng/worker/permission/retry_failed_tuples.py'
    spec = importlib.util.spec_from_file_location('retry_failed_tuples_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_retry_single = _load_retry_module()._retry_single


class _FakeDao:
    succeeded = []
    retries = []
    dead = []

    @classmethod
    def reset(cls):
        cls.succeeded = []
        cls.retries = []
        cls.dead = []

    @classmethod
    def update_succeeded(cls, item_id: int) -> None:
        cls.succeeded.append(item_id)

    @classmethod
    def update_retry(cls, item_id: int, error: str) -> None:
        cls.retries.append((item_id, error))

    @classmethod
    def mark_dead(cls, item_id: int, error: str) -> None:
        cls.dead.append((item_id, error))


def _item(action: str):
    return SimpleNamespace(
        id=7,
        action=action,
        fga_user='user:1',
        relation='viewer',
        object='workflow:1',
        retry_count=0,
        max_retries=3,
    )


def test_retry_single_treats_duplicate_write_as_success():
    _FakeDao.reset()

    fga = SimpleNamespace(
        write_tuples_sync=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError('cannot write a tuple which already exists')
        )
    )

    _retry_single(fga, _item('write'), 'write', _FakeDao)

    assert _FakeDao.succeeded == [7]
    assert _FakeDao.retries == []
    assert _FakeDao.dead == []


def test_retry_single_treats_missing_delete_as_success():
    _FakeDao.reset()

    fga = SimpleNamespace(
        write_tuples_sync=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError('cannot delete a tuple which does not exist')
        )
    )

    _retry_single(fga, _item('delete'), 'delete', _FakeDao)

    assert _FakeDao.succeeded == [7]
    assert _FakeDao.retries == []
    assert _FakeDao.dead == []
