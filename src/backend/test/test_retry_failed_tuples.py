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


def test_retry_idempotency_keeps_write_and_delete_semantics_separate():
    check = _load_retry_module()._is_idempotent_tuple_error
    assert check('write', 'cannot write a tuple which already exists')
    assert check('delete', 'cannot delete a tuple which does not exist')
    assert not check('write', 'connection timeout')
    assert not check('delete', 'already exists')
