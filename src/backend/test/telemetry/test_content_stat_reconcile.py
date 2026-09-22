from copy import deepcopy
from types import SimpleNamespace

import pytest

from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentRecord
from test.test_knowledge_space_content_telemetry import _import_worker_mid_table


def record(file_id, **changes):
    return KnowledgeSpaceContentRecord(
        es_id=str(file_id),
        timestamp=100,
        space_id=3,
        space_name="空间",
        file_id=file_id,
        file_name=changes.pop("file_name", f"{file_id}.pdf"),
        file_type=1,
        uploader_user_id=7,
        uploader_user_name="上传人",
        **changes,
    )


class FakeES:
    def __init__(self, records=()):
        self.docs = {r.es_id: r.model_dump(exclude={"es_id"}) for r in records}
        self.reads = []
        self.writes = []
        self.fail_read = False
        self.conflict_ids = set()
        self.fail_write_ids = set()
        self.cleared = []
        self.indices = SimpleNamespace(
            exists=lambda **kw: True, put_mapping=lambda **kw: None, put_settings=lambda **kw: None
        )

    def observation(self, key):
        if key not in self.docs:
            return {"_id": key, "found": False}
        return {"_id": key, "found": True, "_source": deepcopy(self.docs[key]), "_seq_no": 1, "_primary_term": 1}

    def mget(self, *, index, ids, realtime):
        self.reads.append(ids)
        if self.fail_read:
            return {"docs": [{"_id": key, "error": {"type": "unavailable"}} for key in ids]}
        return {"docs": [self.observation(key) for key in ids]}

    def bulk(self, *, operations, refresh):
        self.writes.append(deepcopy(operations))
        items = []
        offset = 0
        while offset < len(operations):
            kind, meta = next(iter(operations[offset].items()))
            key = meta["_id"]
            offset += 1
            body = None
            if kind != "delete":
                body = operations[offset]
                offset += 1
            if key in self.conflict_ids:
                status = 409
            elif key in self.fail_write_ids:
                status = 503
            else:
                if kind == "delete":
                    self.docs.pop(key, None)
                else:
                    self.docs[key] = body
                status = 200
            items.append({kind: {"_id": key, "status": status}})
        return {"items": items}

    def search(self, **kwargs):
        assert kwargs["size"] == 1000
        assert kwargs["query"] == {"term": {"record_type": "file"}}
        self.scan_docs = [self.observation(key) for key, value in self.docs.items() if value["record_type"] == "file"]
        return self.scroll()

    def scroll(self, **kwargs):
        hits, self.scan_docs = self.scan_docs[:1000], self.scan_docs[1000:]
        return {"_scroll_id": "scan", "_shards": {"failed": 0}, "hits": {"hits": hits}}

    def clear_scroll(self, **kwargs):
        self.cleared.append(kwargs)


def setup_job(monkeypatch, expected, es):
    worker = _import_worker_mid_table()
    stat = worker.KnowledgeSpaceContentStat
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: es)
    monkeypatch.setattr(stat, "renew_lock_sync", lambda owner: True)
    monkeypatch.setattr(stat, "dead_file_ids_sync", lambda ids: set())
    monkeypatch.setattr(stat, "queue_status_sync", lambda: {"pending_count": 0, "oldest_pending_age_ms": 0})
    monkeypatch.setattr(stat, "delete_space_records_sync", lambda *a: 0)
    monkeypatch.setattr(stat, "delete_stale_file_records_sync", lambda *a: 0)
    monkeypatch.setattr(worker, "_get_favorite_space_ids", lambda: [])
    rows = [(SimpleNamespace(id=int(r.es_id)), None) for r in expected]
    by_id = {int(r.es_id): r for r in expected}
    monkeypatch.setattr(
        worker, "_get_success_space_file_rows", lambda page, size: rows[(page - 1) * size : page * size]
    )
    monkeypatch.setattr(
        worker, "_get_content_stat_reconcile_scope", lambda: (len(rows), max(by_id, default=0)), raising=False
    )
    monkeypatch.setattr(
        worker,
        "_get_content_stat_reconcile_rows",
        lambda after_id, max_id, limit: [r for r in rows if after_id < r[0].id <= max_id][:limit],
        raising=False,
    )
    monkeypatch.setattr(worker, "_get_content_stat_valid_file_ids", lambda ids: set(ids) & set(by_id), raising=False)
    monkeypatch.setattr(
        worker,
        "_build_knowledge_space_content_records",
        lambda batch, cache, **kw: ([by_id[row[0].id] for row in batch], cache),
    )
    legacy_writes = []
    monkeypatch.setattr(stat, "insert_records_sync", lambda self, records: legacy_writes.extend(records))
    queued = []
    monkeypatch.setattr(stat, "enqueue_file_stat_sync", lambda ids: queued.extend(ids) or True)
    logs = []
    monkeypatch.setattr(worker, "logger", SimpleNamespace(info=lambda msg, *args: logs.append(msg.format(*args))))
    return worker, legacy_writes, queued, logs


def test_unchanged_business_fields_do_not_write(monkeypatch):
    current = record(11, sync_run_id="old", projection_updated_at=10)
    expected = record(11, sync_run_id="new", projection_updated_at=20)
    es = FakeES([current])
    worker, legacy, _, logs = setup_job(monkeypatch, [expected], es)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert legacy == []
    assert es.writes == []
    assert es.docs["11"] == current.model_dump(exclude={"es_id"})
    assert result["unchanged"] == result["checked"] == 1
    assert result["synced"] == 0
    assert any("progress=100.00%" in log for log in logs)


def test_batches_only_write_missing_or_changed_and_remove_orphans(monkeypatch):
    expected = [record(i) for i in range(1, 1002)]
    es = FakeES([record(i) for i in range(1, 1000)] + [record(1000, file_name="旧名称"), record(2000)])
    es.docs["daily:2000"] = {"record_type": "preview_daily", "file_id": 2000, "preview_count": 7}
    worker, legacy, _, logs = setup_job(monkeypatch, expected, es)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert legacy == []
    assert [len(ids) for ids in es.reads] == [1000, 1]
    assert es.docs["1000"]["file_name"] == "1000.pdf"
    assert "1001" in es.docs and "2000" not in es.docs
    assert es.docs["daily:2000"]["preview_count"] == 7
    assert result["checked"] == 1001 and result["unchanged"] == 999
    assert result["created"] == result["updated"] == result["deleted_stale"] == 1
    assert result["synced"] == 2
    assert es.cleared
    assert any("batch=2" in log and "progress=100.00%" in log for log in logs)
    assert any("file_name" in log for log in logs)


@pytest.mark.parametrize("failure", ["read", "write", "lock"])
def test_incomplete_batch_never_runs_orphan_cleanup(monkeypatch, failure):
    es = FakeES([record(2000)])
    es.fail_read = failure == "read"
    es.fail_write_ids = {"11"} if failure == "write" else set()
    worker, _, _, _ = setup_job(monkeypatch, [record(11)], es)
    if failure == "lock":
        monkeypatch.setattr(worker.KnowledgeSpaceContentStat, "renew_lock_sync", lambda owner: False)
    with pytest.raises(RuntimeError):
        worker.rebuild_knowledge_space_content_file_projection("owner")
    assert "2000" in es.docs
    assert not es.cleared


def test_conflicting_documents_are_not_overwritten_or_deleted(monkeypatch):
    es = FakeES([record(11, file_name="并发版本"), record(2000)])
    es.conflict_ids = {"11", "2000"}
    worker, _, queued, _ = setup_job(monkeypatch, [record(11)], es)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert es.docs["11"]["file_name"] == "并发版本" and "2000" in es.docs
    assert set(queued) == {11, 2000}
    assert result["conflicts"] == 2 and result["degraded"] is True
    for operations in es.writes:
        for operation in operations:
            if "index" in operation or "delete" in operation:
                meta = next(iter(operation.values()))
                assert meta["if_seq_no"] == meta["if_primary_term"] == 1


def test_empty_database_cleans_only_file_snapshots(monkeypatch):
    es = FakeES([record(11)])
    es.docs["daily:11"] = {"record_type": "download_daily", "download_count": 8}
    worker, _, _, logs = setup_job(monkeypatch, [], es)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert set(es.docs) == {"daily:11"}
    assert result["total"] == result["checked"] == result["synced"] == 0
    assert result["deleted_stale"] == 1
    assert any("total=0" in log for log in logs)


def test_full_reconcile_does_not_revive_dead_work_items(monkeypatch):
    es = FakeES([record(11, file_name="待人工修复")])
    worker, _, _, _ = setup_job(monkeypatch, [record(11)], es)
    monkeypatch.setattr(worker.KnowledgeSpaceContentStat, "dead_file_ids_sync", lambda ids: set(ids) & {"11"})
    monkeypatch.setattr(worker.logger, "error", lambda *args: None, raising=False)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert not es.writes
    assert result["blocked"] == 1 and result["degraded"]


def test_removed_optional_field_is_cleared_but_null_and_absent_are_equivalent(monkeypatch):
    es = FakeES([record(11, file_category_name="旧分类"), record(12)])
    es.docs["12"]["file_category_name"] = None
    worker, _, _, _ = setup_job(monkeypatch, [record(11), record(12)], es)
    result = worker.rebuild_knowledge_space_content_file_projection("owner")
    assert "file_category_name" not in es.docs["11"]
    assert result["updated"] == result["unchanged"] == 1


def test_database_count_cursor_and_orphan_check_share_visibility_rules(monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime

    from sqlmodel import Session, create_engine, delete

    from bisheng.core.context.tenant import bypass_tenant_filter

    worker = _import_worker_mid_table()
    knowledge, file, version = worker.Knowledge, worker.KnowledgeFile, worker.KnowledgeDocumentVersion
    engine = create_engine("sqlite://")
    for model in (knowledge, file, version):
        model.__table__.create(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(worker, "get_sync_db_session", session_factory)
    try:
        with bypass_tenant_filter(), session_factory() as session:
            session.add_all(
                [
                    knowledge(id=1, name="空间", tenant_id=1, type=worker.KnowledgeTypeEnum.SPACE.value),
                    knowledge(
                        id=2, name="收藏", tenant_id=1, type=worker.KnowledgeTypeEnum.SPACE.value, is_favorite=True
                    ),
                ]
            )
            for file_id, changes in [
                (1, {}),
                (2, {}),
                (3, {"status": 3}),
                (4, {"deleted_at": datetime.now()}),
                (5, {"knowledge_id": 2}),
                (6, {}),
                (7, {"file_type": 0}),
                (8, {"tenant_id": 2}),
            ]:
                values = {"id": file_id, "knowledge_id": 1, "tenant_id": 1, "file_name": "文件", "status": 2}
                session.add(file(**(values | changes)))
            session.add_all(
                [
                    version(id=1, document_id=1, knowledge_file_id=2, version_no=2, is_primary=True),
                    version(id=2, document_id=1, knowledge_file_id=6, version_no=1, is_primary=False),
                ]
            )
            session.commit()
        assert worker._get_content_stat_reconcile_scope() == (3, 8)
        first = worker._get_content_stat_reconcile_rows(0, 8, 1)
        assert [row[0].id for row in first] == [1]
        with bypass_tenant_filter(), session_factory() as session:
            session.exec(delete(file).where(file.id == 1))
            session.add(file(id=9, knowledge_id=1, tenant_id=1, file_name="新增文件", status=2))
            session.commit()
        assert [row[0].id for row in worker._get_content_stat_reconcile_rows(1, 8, 1000)] == [2, 8]
        assert worker._get_content_stat_valid_file_ids(list(range(1, 10))) == {2, 8, 9}
    finally:
        engine.dispose()
