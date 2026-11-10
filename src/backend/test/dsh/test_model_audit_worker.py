"""AC-24/AC-37: trusted tenant headers precede runtime/database acquisition."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bisheng.worker.dsh.model_audit import register_model_audit_tasks


class Tasks:
    def __init__(self):
        self.tasks = {}

    def task(self, **options):
        def register(callback):
            self.tasks[options["name"]] = callback
            return callback

        return register


@pytest.mark.parametrize(
    "headers,tenant",
    [({}, 2), ({"tenant_id": "2"}, 2), ({"tenant_id": True}, 1), ({"tenant_id": 3}, 2), ({"tenant_id": 0}, 0)],
)
def test_inspection_rejects_untrusted_scope_before_runtime(headers, tenant):
    app = Tasks()
    inspect, _scan = register_model_audit_tasks(app)
    with pytest.raises(ValueError, match="trusted tenant"):
        inspect(SimpleNamespace(request=SimpleNamespace(headers=headers)), tenant)
    assert set(app.tasks) == {"dsh.inspect_model_audit", "dsh.scan_model_audit"}


async def test_scanner_limits_dispatch_and_passes_trusted_headers_with_continuation(monkeypatch):
    import bisheng.dsh.operations_runtime as composition
    import bisheng.worker._asyncio_utils as bridge

    @contextmanager
    def scope(_repository):
        yield SimpleNamespace(
            session=None,
            pending_tenants=lambda _session, cursor=None: list(range((cursor or 0) + 1, (cursor or 0) + 101)),
        )

    monkeypatch.setattr(bridge, "run_async_task", lambda function: function())
    monkeypatch.setattr(composition, "repository_scope", scope)
    app = Tasks()
    inspect, scan = register_model_audit_tasks(app)
    dispatched, continuations = [], []
    inspect.apply_async = lambda **kwargs: dispatched.append(kwargs)
    scan.apply_async = lambda **kwargs: continuations.append(kwargs)
    assert await scan(100) == 100
    assert all(item["headers"] == {"tenant_id": item["args"][0]} for item in dispatched)
    assert dispatched[0]["args"] == [101] and dispatched[-1]["args"] == [200]
    assert continuations == [{"args": [200]}]
