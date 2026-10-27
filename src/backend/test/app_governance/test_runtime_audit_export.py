"""Bounded whole-result exports. 覆盖 AC: AC-51, AC-52, AC-53, AC-56, AC-57, AC-58, AC-60."""

import csv
import io

import pytest

from test.app_governance.test_runtime_audit_query import audit_env as audit_env


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    async def put(self, key, value):
        self.objects[key] = value

    async def get(self, key):
        return self.objects.get(key)

    async def remove(self, key):
        self.objects.pop(key, None)


async def test_export_whole_selection_is_immutable_and_csv_safe(audit_env):
    from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import RuntimeAuditExportRepository
    from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService

    service, repo, _, scope = audit_env
    storage = MemoryStorage()

    async def current(job):
        return scope

    export = RuntimeAuditExportService(
        RuntimeAuditExportRepository(repo.factory),
        repo,
        storage,
        scope_resolver=service.scope_resolver,
        worker_scope=current,
    )
    page = await service.list("admin", "model", {"time_range": "all"}, limit=1)
    job = await export.submit("admin", page["snapshot_id"], "request-a")
    assert (await export.submit("admin", page["snapshot_id"], "request-a")).id == job.id
    await export.run(job.id, scope.owner_tenant_id, batch_size=2)
    ready = await export.status("admin", job.id)
    assert ready["status"] == "ready" and ready["final_count"] == 4
    raw = b"".join([part async for part in export.download("admin", job.id)])
    assert await export.download_size("admin", job.id) == len(raw)
    data = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert [int(row["id"]) for row in data] == [4, 3, 2, 1]
    assert data[0]["actor_name"] == "'=unsafe"
    assert "token_hash" not in data[0]
    assert raw == b"".join([part async for part in export.download("admin", job.id)])


@pytest.mark.parametrize("text", ["=1+1", "  +1", "\t@sum(A1)", "\r-3", "\x00 =1"])
def test_formula_prefix_after_whitespace_and_controls(text):
    from bisheng.app_governance.domain.services.runtime_audit_export_service import safe_csv_value

    assert safe_csv_value(text).startswith("'")


async def test_revoked_reader_cannot_download_ready_object(audit_env):
    from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import RuntimeAuditExportRepository
    from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService
    from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError

    service, repo, _, scope = audit_env
    allowed = True

    async def current(job):
        if not allowed:
            raise RuntimeAuditAccessDeniedError()
        return scope

    async def resolve(user, tenant_id=None):
        if not allowed:
            raise RuntimeAuditAccessDeniedError()
        return scope

    export = RuntimeAuditExportService(
        RuntimeAuditExportRepository(repo.factory), repo, MemoryStorage(), scope_resolver=resolve, worker_scope=current
    )
    page = await service.list("admin", "model", {"time_range": "all"})
    job = await export.submit("admin", page["snapshot_id"], "request-b")
    await export.run(job.id, 1, batch_size=2)
    allowed = False
    with pytest.raises(RuntimeAuditAccessDeniedError):
        await anext(export.download("admin", job.id))


def test_celery_wrapper_passes_factory_with_explicit_tenant(monkeypatch):
    """覆盖 AC: AC-56. The actual worker adapter accepts a coroutine factory."""
    import inspect

    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.worker.runtime_audit import tasks

    def runner(factory):
        assert callable(factory)
        assert get_current_tenant_id() == 9
        coroutine = factory()
        assert inspect.iscoroutine(coroutine)
        coroutine.close()
        return "factory accepted"

    monkeypatch.setattr(tasks, "run_async_task", runner)
    assert tasks.runtime_audit_export.run("job", 9) == "factory accepted"


async def test_terminal_artifact_gc_marker_does_not_starve_later_jobs(audit_env):
    """覆盖 AC: AC-57. Completed GC is durable; expired snapshots are independent of copied job filters."""
    from datetime import datetime, timedelta

    from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditQuerySnapshot
    from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import RuntimeAuditExportRepository
    from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService

    service, source, sessions, scope = audit_env
    repo = RuntimeAuditExportRepository(source.factory)
    exports = RuntimeAuditExportService(repo, source, MemoryStorage(), scope_resolver=service.scope_resolver)
    page = await service.list("admin", "model", {"time_range": "all"})
    job = await exports.submit("admin", page["snapshot_id"], "gc-test")
    await repo.terminate(1, job.id, "failed")
    assert [row.id for row in await repo.gc_candidates()] == [job.id]
    await repo.mark_gc_complete(1, job.id)
    assert await repo.gc_candidates() == []
    async with sessions() as session:
        snapshot = await session.get(RuntimeAuditQuerySnapshot, page["snapshot_id"])
        snapshot.expires_at = datetime.utcnow() - timedelta(minutes=1)
        session.add(snapshot)
        await session.commit()
    await repo.clear_snapshots()
    assert await source.snapshot(scope, page["snapshot_id"]) is None
    assert (await repo.get(1, job.id)).normalized_filter["time_range"] == "all"


async def test_expired_attempt_cannot_publish_after_new_owner_claim(audit_env):
    """覆盖 AC: AC-51, AC-56. Recovery restarts one read-view attempt and fences its predecessor."""
    from datetime import datetime, timedelta

    from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditExport
    from bisheng.app_governance.domain.repositories.runtime_audit_export_repository import RuntimeAuditExportRepository
    from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService
    from bisheng.common.errcode.app_governance import RuntimeAuditExportUnavailableError

    service, source, sessions, _ = audit_env
    repo = RuntimeAuditExportRepository(source.factory)
    exports = RuntimeAuditExportService(repo, source, MemoryStorage(), scope_resolver=service.scope_resolver)
    page = await service.list("admin", "model", {"time_range": "all"})
    job = await exports.submit("admin", page["snapshot_id"], "lease-test")
    old = await repo.claim(1, job.id, "old")
    async with sessions() as session:
        row = await session.get(RuntimeAuditExport, job.id)
        row.lease_until = datetime.utcnow() - timedelta(seconds=1)
        row.processed_rows = 3
        session.add(row)
        await session.commit()
    current = await repo.claim(1, job.id, "new")
    assert current.epoch == old.epoch + 1 and current.attempt == old.attempt + 1 and current.processed_rows == 0
    with pytest.raises(RuntimeAuditExportUnavailableError):
        await repo.checkpoint(old, status="ready")
    await repo.checkpoint(current, processed_rows=1)
