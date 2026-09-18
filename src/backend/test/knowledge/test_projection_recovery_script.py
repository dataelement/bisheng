"""恢复工具只能显式、可审计地重开单条失败投影。"""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from scripts import reconcile_knowledge_document_projection as script
from test.knowledge.test_knowledge_document_projection_service import _seed_entries


async def seed(session, monkeypatch):
    await _seed_entries(session)
    session.add(KnowledgeDocument(id=91, tenant_id=7, knowledge_id=20, primary_version_id=501, content_generation=4))
    session.add(KnowledgeDocumentVersion(id=501, document_id=91, knowledge_file_id=100, version_no=1, is_primary=True))
    repo = KnowledgeFileRepositoryImpl(session)
    entry = await repo.find_by_id(101)
    entry.entry_type = "projection_tombstone"
    entry.entry_status = "deleting"
    entry.projection_status = "failed"
    entry.projection_retry_count = 8
    entry.projection_last_error = "retry_exhausted:old failure"
    await session.commit()

    @asynccontextmanager
    async def db():
        yield session

    monkeypatch.setattr(script, "get_async_db_session", db)
    return repo


async def test_recovery_preview_and_apply_preserve_audit(async_db_session, monkeypatch, tmp_path):
    repo = await seed(async_db_session, monkeypatch)
    preview = await script.inspect_entry(tenant_id=7, entry_id=101)
    assert preview["recovery_blocked_reason"] is None
    assert (await repo.find_by_id(101)).projection_retry_count == 8
    audit = tmp_path / "recovery.jsonl"
    snapshot = await script.recover_entry(
        tenant_id=7, entry_id=101, operator="tester", reason="dependency fixed", audit_file=str(audit)
    )
    recovered = await repo.find_by_id(101)
    assert recovered.projection_status == "pending"
    assert recovered.projection_retry_count == 0
    assert recovered.entry_status == "deleting"
    assert recovered.entry_type == "projection_tombstone"
    assert recovered.applied_content_generation == 0
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [row["phase"] for row in rows] == ["prepared", "committed"]
    assert rows[0]["before"]["last_error"] == "retry_exhausted:old failure"
    assert rows[0]["before"]["retry_count"] == 8
    assert snapshot["recovery_id"] in recovered.projection_last_error


@pytest.mark.parametrize("blocker", ["tenant", "lease", "dependency", "audit"])
async def test_recovery_fails_closed(async_db_session, monkeypatch, tmp_path, blocker):
    repo = await seed(async_db_session, monkeypatch)
    entry = await repo.find_by_id(101)
    audit = tmp_path / "recovery.jsonl"
    tenant_id = 7
    if blocker == "tenant":
        tenant_id = 8
    elif blocker == "lease":
        entry.projection_lease_owner = "live-worker"
        entry.projection_lease_until = datetime.now() + timedelta(minutes=1)
    elif blocker == "dependency":
        (await repo.find_by_id(100)).projection_status = "failed"
    elif blocker == "audit":
        audit = tmp_path / "missing" / "recovery.jsonl"
    await async_db_session.commit()
    with pytest.raises((ValueError, OSError)):
        await script.recover_entry(
            tenant_id=tenant_id, entry_id=101, operator="tester", reason="fixed", audit_file=str(audit)
        )
    await async_db_session.rollback()
    failed = await repo.find_by_id(101)
    assert failed.projection_retry_count == 8
    assert failed.projection_status == "failed"


async def test_execute_dry_run_does_not_write_or_dispatch(async_db_session, monkeypatch, tmp_path):
    from types import SimpleNamespace

    repo = await seed(async_db_session, monkeypatch)
    args = SimpleNamespace(tenant_id=7, entry_id=101, apply=False, recover_failed=True)
    snapshot = await script.execute(args)
    assert snapshot["dispatch_status"] == "dry_run"
    assert (await repo.find_by_id(101)).projection_retry_count == 8
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["committed_audit", "dispatch"])
async def test_post_commit_failure_reports_durable_recovery(async_db_session, monkeypatch, tmp_path, failure):
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    repo = await seed(async_db_session, monkeypatch)
    append = script._append_audit

    def audit(path, record):
        if failure == "committed_audit" and record["phase"] == "committed":
            raise OSError("disk full")
        append(path, record)

    monkeypatch.setattr(script, "_append_audit", audit)
    task = MagicMock()
    task.apply_async.side_effect = RuntimeError("broker unavailable")
    monkeypatch.setitem(
        sys.modules, "bisheng.worker.knowledge.document_projection", SimpleNamespace(process_document_projection=task)
    )
    args = SimpleNamespace(
        tenant_id=7,
        entry_id=101,
        apply=True,
        recover_failed=True,
        operator="tester",
        reason="fixed",
        audit_file=str(tmp_path / "audit.jsonl"),
    )
    with pytest.raises(script.RecoveryCommittedError, match="committed") as error:
        await script.execute(args)
    assert error.value.snapshot["recovery_status"] == "committed"
    assert error.value.snapshot["recovery_id"]
    recovered = await repo.find_by_id(101)
    assert recovered.projection_status == "pending"
    assert recovered.projection_retry_count == 0
    assert "prepared" in (tmp_path / "audit.jsonl").read_text()
    if failure == "committed_audit":
        task.apply_async.assert_not_called()


async def test_recover_manager_before_dependent_cleanup(async_db_session, monkeypatch, tmp_path):
    from test.knowledge.test_knowledge_document_projection_service import _service

    repo = await seed(async_db_session, monkeypatch)
    manager = await repo.find_by_id(100)
    manager.projection_status = "failed"
    manager.projection_retry_count = 8
    manager.applied_content_generation = 3
    await async_db_session.commit()
    args = {
        "tenant_id": 7,
        "operator": "tester",
        "reason": "loader fixed",
        "audit_file": str(tmp_path / "audit.jsonl"),
    }
    with pytest.raises(ValueError, match="manager projection is not ready"):
        await script.recover_entry(entry_id=101, **args)
    await script.recover_entry(entry_id=100, **args)
    assert (await repo.find_by_id(101)).projection_retry_count == 8
    result = await _service(async_db_session).process_entry(tenant_id=7, entry_id=100, lease_owner="manager-recovery")
    assert result.status == "ready"
    await script.recover_entry(entry_id=101, **args)
    result = await _service(async_db_session).process_entry(tenant_id=7, entry_id=101, lease_owner="cleanup-recovery")
    assert result.status == "cleaned"
