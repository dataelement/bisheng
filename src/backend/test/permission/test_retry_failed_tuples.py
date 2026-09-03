import asyncio
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import CeleryConf
from bisheng.database.models.failed_tuple import FailedTupleDao


def _load_retry_module():
    fake_celery = SimpleNamespace(task=lambda *args, **kwargs: lambda fn: fn)
    sys.modules["bisheng.worker.main"] = SimpleNamespace(bisheng_celery=fake_celery)
    path = Path(__file__).resolve().parents[2] / "bisheng/worker/permission/retry_failed_tuples.py"
    spec = importlib.util.spec_from_file_location("retry_failed_tuples_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_retry_module = _load_retry_module()
_cleanup_succeeded_failed_tuples = _retry_module._cleanup_succeeded_failed_tuples
_retry_single = _retry_module._retry_single


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
        fga_user="user:1",
        relation="viewer",
        object="workflow:1",
        retry_count=0,
        max_retries=3,
    )


def test_retry_single_treats_duplicate_write_as_success():
    _FakeDao.reset()

    async def duplicate(_relations):
        raise RuntimeError("cannot write a tuple which already exists")

    permissions = SimpleNamespace(grant=duplicate)
    _retry_single(permissions, _item("write"), "write", _FakeDao, lambda factory: asyncio.run(factory()))

    assert _FakeDao.succeeded == [7]
    assert _FakeDao.retries == []
    assert _FakeDao.dead == []


def test_retry_single_treats_missing_delete_as_success():
    _FakeDao.reset()

    async def missing(_relations):
        raise RuntimeError("cannot delete a tuple which does not exist")

    permissions = SimpleNamespace(revoke=missing)
    _retry_single(permissions, _item("delete"), "delete", _FakeDao, lambda factory: asyncio.run(factory()))

    assert _FakeDao.succeeded == [7]
    assert _FakeDao.retries == []
    assert _FakeDao.dead == []


async def test_cleanup_deletes_only_succeeded_records_before_retention_cutoff(monkeypatch):
    delete_old_succeeded = AsyncMock(return_value=4)
    monkeypatch.setattr(FailedTupleDao, "adelete_old_succeeded", delete_old_succeeded)
    monkeypatch.setattr(settings.openfga, "failed_tuple_succeeded_retention_days", 30)

    deleted = await _cleanup_succeeded_failed_tuples(now=datetime(2026, 8, 6, 3, 30))

    assert deleted == 4
    delete_old_succeeded.assert_awaited_once_with(datetime(2026, 7, 7, 3, 30))


def test_cleanup_is_scheduled_on_the_default_queue():
    schedule = CeleryConf().beat_schedule["cleanup_succeeded_failed_tuples"]

    assert schedule["task"] == ("bisheng.worker.permission.retry_failed_tuples.cleanup_succeeded_failed_tuples")
    assert schedule["schedule"] is not None
    assert "options" not in schedule
