import ast
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext
from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
    ContentStatEventEnvelope,
    KnowledgeSpaceContentStat,
)
from test.telemetry.test_telemetry_retry_budget import redis_connection as redis_connection
from test.test_knowledge_space_content_telemetry import _import_worker_mid_table


def load_raw_bulk_method():
    # 隔离项目全局 telemetry mock; 执行源文件里的原方法, 避免网络和应用启动。
    path = Path(__file__).parents[2] / "bisheng/common/services/telemetry/telemetry_service.py"
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BaseTelemetryService")
    method = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "record_events_sync_strict"
    )
    namespace = {
        "BaseTelemetryEvent": BaseTelemetryEvent,
        "DEFAULT_TENANT_ID": 1,
        "get_current_tenant_id": lambda: 1,
        "logger": SimpleNamespace(exception=lambda *a: None),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[method.name]


class EventES:
    def __init__(self):
        self.raw, self.daily = {}, {}
        self.bulk_calls, self.search_calls, self.refresh_calls = [], [], []
        self.fail_raw = set()
        self.fail_daily = set()
        self.fail_count = set()
        self.indices = SimpleNamespace(
            exists=lambda **kw: True, put_mapping=lambda **kw: {}, put_settings=lambda **kw: {}, refresh=self.refresh
        )

    def refresh(self, **kwargs):
        self.refresh_calls.append(kwargs)
        return {"_shards": {"failed": 0}}

    def bulk(self, *, operations, refresh):
        self.bulk_calls.append(operations)
        items = []
        for offset in range(0, len(operations), 2):
            kind, meta = next(iter(operations[offset].items()))
            key, document = meta["_id"], operations[offset + 1]
            if kind == "create":
                status = 503 if key in self.fail_raw else 409 if key in self.raw else 201
                if status == 201:
                    self.raw[key] = document
            else:
                status = 503 if key in self.fail_daily else 200
                if status == 200:
                    assert "ctx.op = 'noop'" in document["script"]["source"]
                    self.daily[key] = max(self.daily.get(key, 0), document["script"]["params"]["count"])
            items.append({kind: {"_id": key, "status": status}})
        return {"items": items}

    def msearch(self, *, searches):
        self.search_calls.append(searches)
        responses = []
        for offset in range(1, len(searches), 2):
            filters = searches[offset]["query"]["bool"]["filter"]
            field, group = next(iter(filters[-1]["term"].items()))
            if group in self.fail_count:
                responses.append({"error": {"type": "unavailable"}})
                continue
            field = field.removeprefix("event_data.").removesuffix(".keyword")
            count = sum(doc["event_data"].get(field) == group for doc in self.raw.values())
            responses.append({"hits": {"total": {"value": count, "relation": "eq"}}, "_shards": {"failed": 0}})
        return {"responses": responses}


@pytest.mark.parametrize("failure", ["raw", "daily", "count"])
def test_events_batch_group_counts_and_retry_only_failed_items(monkeypatch, redis_connection, failure):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as content

    worker, es = _import_worker_mid_table(), EventES()
    cls = KnowledgeSpaceContentStat
    wrapper = SimpleNamespace(connection=redis_connection, cluster_nodes=lambda key: None, get=lambda key: None)
    monkeypatch.setattr(content, "get_redis_client_sync", lambda: wrapper)
    now = [1000]
    monkeypatch.setattr(cls, "_now_ms", lambda: now[0])
    monkeypatch.setattr(cls, "clear_event_scheduled_sync", lambda: None)
    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: es)
    monkeypatch.setattr(worker, "get_statistics_es_connection_sync", lambda: es)
    users = []
    service = SimpleNamespace(
        _es_client_sync=es,
        _index_initialized=True,
        index_name="raw",
        _init_user_contexts_sync=lambda ids: (
            users.extend(ids) or {uid: UserContext(user_id=uid, user_name="员工") for uid in ids}
        ),
    )
    service.record_events_sync_strict = MethodType(load_raw_bulk_method(), service)
    monkeypatch.setattr(worker, "telemetry_service", service)
    for key, group in [("a", "day1"), ("b", "day1"), ("c", "day2")]:
        envelope = ContentStatEventEnvelope(
            event_id=key,
            event_type="portal_document_read",
            record_type="preview_daily",
            user_id=7,
            occurred_at=100,
            local_date="2026-09-22",
            daily_id=group,
            source_app="portal",
            scene="preview",
            entry_point="direct",
            dimensions={"file_id": 1, "space_id": 1},
        )
        redis_connection.hset(cls.EVENT_PAYLOAD_KEY, key, envelope.model_dump_json())
        redis_connection.zadd(cls.EVENT_PENDING_KEY, {key: 1})
    es.fail_raw = {"c"} if failure == "raw" else set()
    es.fail_daily = {"day2"} if failure == "daily" else set()
    es.fail_count = {"day2"} if failure == "count" else set()
    first = worker.sync_pending_knowledge_space_content_events.run()
    assert first["processed_count"] == 2 and first["failed_count"] == 1
    assert users == [7]
    assert len(es.bulk_calls) == 2 and len(es.search_calls) == 1
    assert len(es.search_calls[0]) == (2 if failure == "raw" else 4)
    assert es.daily == {"day1": 2}
    assert redis_connection.hlen(cls.EVENT_PAYLOAD_KEY) == 1
    es.fail_raw.clear()
    es.fail_daily.clear()
    es.fail_count.clear()
    now[0] = 1000000
    second = worker.sync_pending_knowledge_space_content_events.run()
    assert second["processed_count"] == 1
    assert len(es.raw) == 3 and es.daily == {"day1": 2, "day2": 1}
    assert not redis_connection.hlen(cls.EVENT_PAYLOAD_KEY)


def test_raw_event_replay_keeps_original_snapshot_and_refreshes_before_count():
    es = EventES()
    service = SimpleNamespace(
        _es_client_sync=es,
        _index_initialized=True,
        index_name="raw",
        _init_user_contexts_sync=lambda ids: {uid: UserContext(user_id=uid, user_name="原姓名") for uid in ids},
    )
    event = {
        "event_id": "a",
        "user_id": 7,
        "event_type": "user_login",
        "timestamp": 100,
        "trace_id": None,
        "event_data": None,
    }
    method = load_raw_bulk_method()
    assert method(service, [event]) == {}
    service._init_user_contexts_sync = lambda ids: {uid: UserContext(user_id=uid, user_name="新姓名") for uid in ids}
    assert method(service, [event]) == {}
    assert es.raw["a"]["user_context"]["user_name"] == "原姓名"
    assert len(es.refresh_calls) == 2
