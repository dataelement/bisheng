from copy import deepcopy

import pytest

from bisheng.telemetry.domain.mid_table.content_stat_reconcile import ContentStatReconciler
from test.telemetry.test_content_stat_reconcile import FakeES, record, setup_job
from test.telemetry.test_telemetry_retry_budget import redis_connection as redis_connection


def test_partial_bulk_retry_only_writes_failed_documents():
    es = FakeES()
    desired = {"q1": {"question_id": "q1"}, "q2": {"question_id": "q2"}}
    es.fail_write_ids = {"q2"}
    reconcile = ContentStatReconciler(es, "qa", str)
    with pytest.raises(RuntimeError, match="q2"):
        reconcile.reconcile(desired)
    assert es.docs == {"q1": desired["q1"]}
    es.fail_write_ids.clear()
    result = reconcile.reconcile(desired)
    assert result["unchanged"] == result["created"] == 1
    assert es.writes[-1] == [{"create": {"_index": "qa", "_id": "q2"}}, desired["q2"]]


def test_participation_preserves_login_and_event_department_and_skips_unchanged():
    from bisheng.telemetry.domain.mid_table.daily_participation import merge_participation_document

    current = {
        "user_id": 7,
        "logged_in": True,
        "login_count": 3,
        "first_login_at": 1,
        "last_login_at": 9,
        "primary_department_id": 8,
        "department_source": "event_time",
    }
    roster = {
        "user_id": 7,
        "logged_in": False,
        "login_count": 0,
        "first_login_at": None,
        "last_login_at": None,
        "primary_department_id": 99,
        "department_source": "current_roster",
    }
    assert merge_participation_document(current, roster) == current
    history = {**roster, "logged_in": True, "login_count": 4, "department_source": "current_primary_backfill"}
    merged = merge_participation_document(current, history)
    assert merged["login_count"] == 4 and merged["primary_department_id"] == 8
    es = FakeES()
    es.docs["p7"] = deepcopy(current)
    result = ContentStatReconciler(es, "participation", str).reconcile({"p7": roster}, merge_participation_document)
    assert result["unchanged"] == 1 and not es.writes


def test_qa_repair_preserves_event_time_department():
    from bisheng.telemetry.domain.mid_table.realtime_qa_question import merge_qa_document

    es = FakeES()
    es.docs["q1"] = {"question_id": "q1", "department_source": "event_time", "primary_department_id": 8}
    result = ContentStatReconciler(es, "qa", str).reconcile(
        {"q1": {"question_id": "q1", "department_source": "current_primary_backfill", "primary_department_id": 99}},
        merge_qa_document,
    )
    assert not es.writes and result["unchanged"] == 1


def test_history_reuses_roster_and_merges_login_before_one_write(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from test.test_knowledge_space_content_telemetry import _import_worker_mid_table

    worker = _import_worker_mid_table()
    users = [(SimpleNamespace(user_id=i, user_name=str(i)), 1) for i in range(1, 1002)]
    es = FakeES()
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: es)
    reads, department_reads = [], []

    def roster(offset, limit):
        reads.append(offset)
        return users[offset : offset + limit]

    monkeypatch.setattr(worker, "_get_active_participation_users", roster)
    monkeypatch.setattr(
        worker.UserDepartmentDao,
        "get_primary_department_map_by_user_ids",
        lambda ids: department_reads.append(ids) or {},
    )
    monkeypatch.setattr(worker, "_cleanup_participation_records", lambda *args: 0)
    dates = [date(2026, 9, 20), date(2026, 9, 21)]
    login = {
        "tenant_id": 1,
        "local_date": "2026-09-20",
        "user_id": 1,
        "user_name": "1",
        "login_count": 3,
        "first_login_at": 100,
        "last_login_at": 200,
    }
    result = worker._reconcile_participation_days(
        dates, aggregates={(1, "2026-09-20", 1): login}, department_source="current_roster_backfill"
    )
    assert reads == [0, 1000, 1001]
    assert [len(ids) for ids in department_reads] == [1000, 1]
    assert [len(ids) for ids in es.reads] == [1000, 1000, 2]
    assert result["written"] == len(es.docs) == 2002
    assert es.docs["participation_1_2026-09-20_1"]["login_count"] == 3
    es.writes.clear()
    worker._reconcile_participation_days(
        dates, aggregates={(1, "2026-09-20", 1): login}, department_source="current_roster_backfill"
    )
    assert not es.writes


def test_concurrent_login_conflict_never_overwrites_current_document():
    from bisheng.telemetry.domain.mid_table.daily_participation import merge_participation_document

    es = FakeES()
    es.docs["p1"] = {"user_name": "旧名字", "logged_in": True, "login_count": 9}
    es.conflict_ids = {"p1"}
    with pytest.raises(RuntimeError, match="409"):
        ContentStatReconciler(es, "participation", str).reconcile(
            {"p1": {"user_name": "新名字", "department_source": "current_roster"}}, merge_participation_document
        )
    assert es.docs["p1"]["login_count"] == 9


@pytest.mark.parametrize("conflict", [False, True])
def test_cleanup_reuses_roster_and_rechecks_only_stale_candidates(monkeypatch, conflict):
    from types import SimpleNamespace

    from test.test_knowledge_space_content_telemetry import _import_worker_mid_table

    worker, es = _import_worker_mid_table(), FakeES()
    for uid in range(1, 5):
        es.docs[f"p{uid}"] = {"tenant_id": 1, "local_date": "2026-09-20", "user_id": uid}

    def scan(*args, **kwargs):
        filters = kwargs["query"]["query"]["bool"]["filter"]
        assert {"term": {"metric_source": "participation"}} in filters
        assert kwargs["seq_no_primary_term"]
        for key in list(es.docs):
            yield es.observation(key)

    queried = []

    def users(offset, limit, ids):
        queried.append(ids)
        return [(SimpleNamespace(user_id=3), 1)] if offset == 0 else []

    monkeypatch.setattr(worker.helpers, "scan", scan)
    monkeypatch.setattr(worker, "_get_active_participation_users", users)
    fact = SimpleNamespace(_es_client_sync=es, _index_name="shared")
    es.conflict_ids = {"p2"} if conflict else set()
    arguments = (fact, ["2026-09-20"], 100, {(1, "2026-09-20", 4)}, {(1, 1)})
    if conflict:
        with pytest.raises(RuntimeError, match="conflicts"):
            worker._cleanup_participation_records(*arguments)
        assert "p2" in es.docs
    else:
        assert worker._cleanup_participation_records(*arguments) == 1
        assert set(es.docs) == {"p1", "p3", "p4"}
    assert queried == [[2, 3], [2, 3]]
    assert es.writes[0][0]["delete"]["if_seq_no"] == 1


def test_file_partial_bulk_acknowledges_success_and_retries_only_failed_item(monkeypatch, redis_connection):
    from types import SimpleNamespace

    from bisheng.telemetry.domain.mid_table import knowledge_space_content as content

    es = FakeES()
    worker, _, _, _ = setup_job(monkeypatch, [record(11), record(12)], es)
    cls = content.KnowledgeSpaceContentStat
    monkeypatch.setattr(
        content,
        "get_redis_client_sync",
        lambda: SimpleNamespace(connection=redis_connection, cluster_nodes=lambda key: None),
    )
    monkeypatch.setattr(cls, "clear_scheduled_sync", lambda: None)
    monkeypatch.setattr(worker.logger, "exception", lambda *args: None, raising=False)
    monkeypatch.setattr(worker, "_is_file_content_stat_visible", lambda *args: True)
    monkeypatch.setattr(
        worker,
        "_get_knowledge_space_content_rows_by_file_ids",
        lambda ids: [(SimpleNamespace(id=key), None) for key in ids],
    )
    now = [1000]
    monkeypatch.setattr(cls, "_now_ms", lambda: now[0])
    redis_connection.zadd(cls.PENDING_KEY, {"file:11": 1, "file:12": 1})
    es.fail_write_ids = {"12"}
    with pytest.raises(RuntimeError, match="12"):
        worker.sync_pending_knowledge_space_content_stat.run()
    assert set(es.docs) == {"11"}
    assert redis_connection.hget(cls.ATTEMPTS_KEY, "file:11") is None
    assert redis_connection.hget(cls.ATTEMPTS_KEY, "file:12") == "1"
    assert redis_connection.zrange(cls.PENDING_KEY, 0, -1) == ["file:12"]
    es.fail_write_ids.clear()
    now[0] = 1000000
    worker.sync_pending_knowledge_space_content_stat.run()
    assert set(es.docs) == {"11", "12"}
    assert not redis_connection.zcard(cls.PENDING_KEY)
    assert len(es.writes[-1]) == 2 and es.writes[-1][0]["create"]["_id"] == "12"


def test_incremental_delete_preserves_concurrent_file_version(monkeypatch):
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

    es = FakeES([record(11)])
    es.conflict_ids = {"11"}
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: es)
    with pytest.raises(RuntimeError, match="conflicts"):
        KnowledgeSpaceContentStat().reconcile_delete_file_records_sync([11, 12])
    assert "11" in es.docs
    assert es.writes[0][0]["delete"]["if_seq_no"] == 1
