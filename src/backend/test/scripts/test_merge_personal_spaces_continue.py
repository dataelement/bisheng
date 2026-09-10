"""单元失败可隔离时继续迁移, 不忽略来源异常或审计失败。"""

import json
from unittest.mock import AsyncMock

import pytest

from test.scripts.test_merge_personal_knowledge_spaces import MemoryOperations, file, m, runtime


@pytest.mark.parametrize("fail_at", ["copy", "permissions", "verify", "delete"])
async def test_recoverable_failure_continues_and_retains_source(monkeypatch, tmp_path, fail_at):
    state, backend, calls, args = runtime(monkeypatch, tmp_path)
    state.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "file_name": "b.pdf"}))
    count = 0

    def operations(tenant_id, spaces):
        nonlocal count
        count += 1
        op = MemoryOperations(tenant_id, spaces, state, fail_at if count == 1 else None)
        op.calls = calls
        return op

    monkeypatch.setattr(m, "GuardedOperations", operations)
    assert await m.run(args, backend=backend) == 3
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "completed_with_errors"
    assert report["pending"] == report["pending_sources"] == 0
    assert report["result_counts"] == {"failed": 1, "success": 1}
    assert {f.id for f in state.files} == {201, 1202}
    assert backend.deleted == []


async def test_inconsistent_source_is_skipped_before_copy(monkeypatch, tmp_path):
    state, backend, calls, args = runtime(monkeypatch, tmp_path)
    state.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "file_name": "b.pdf"}))

    class CheckedOperations(MemoryOperations):
        async def snapshot_unit(self, unit):
            await super().snapshot_unit(unit)
            for source in unit.source_files:
                if source.id == 201:
                    self.snapshots[source.id] = m.SourceSnapshot(m.TagSnapshot(), (), m.IndexSnapshot(0, 58), {})
            await m.BishengMoveOperations.snapshot_unit(self, unit)

    def operations(tenant_id, spaces):
        op = CheckedOperations(tenant_id, spaces, state)
        op.calls = calls
        return op

    monkeypatch.setattr(m, "GuardedOperations", operations)
    monkeypatch.setattr(m, "_index_snapshot", lambda *args: m.IndexSnapshot(0, 58))
    monkeypatch.setattr(m.asyncio, "sleep", AsyncMock())
    assert await m.run(args, backend=backend) == 0
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "completed_with_skips"
    assert report["results"][0]["status"] == "skipped"
    assert "source_index_count_mismatch" in report["results"][0]["reason"]
    assert "es_count=58" in report["results"][0]["reason"]
    assert report["results"][1]["status"] == "success"
    assert calls.count("copy") == 1
    assert {f.id for f in state.files} == {201, 1202}
    assert backend.deleted == []


async def test_audit_failure_never_continues(monkeypatch, tmp_path):
    state, backend, calls, args = runtime(monkeypatch, tmp_path)
    state.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "file_name": "b.pdf"}))
    original = m.record_event

    def record(journal, kind, payload):
        if kind == "before_source_delete":
            raise OSError("disk full")
        original(journal, kind, payload)

    monkeypatch.setattr(m, "record_event", record)
    assert await m.run(args, backend=backend) == 3
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "failed" and report["pending"] == 1
    assert calls.count("copy") == 1
    assert {f.id for f in state.files} == {201, 202}


async def test_incomplete_cleanup_never_continues(monkeypatch, tmp_path):
    state, backend, calls, args = runtime(monkeypatch, tmp_path)
    state.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "file_name": "b.pdf"}))

    def operations(tenant_id, spaces):
        op = MemoryOperations(tenant_id, spaces, state, "verify")
        op.calls = calls
        op.cleanup_target = AsyncMock(return_value=["storage unavailable; target preserved"])
        return op

    monkeypatch.setattr(m, "GuardedOperations", operations)
    assert await m.run(args, backend=backend) == 3
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "failed" and report["pending"] == 1
    assert calls.count("copy") == 1
    assert {f.id for f in state.files} == {201, 202, 1201}
