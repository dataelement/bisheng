# ruff: noqa: RUF002
"""按真实查询条件筛选分页样本，验证库存和调用范围不会相互污染。"""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import AsyncElasticsearch

from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, RangeOp, RangeValue, TermOp
from bisheng.telemetry_search.domain.services import knowledge_document_reader as module


def matches(source, query):
    if "exists" in query:
        return source.get(query["exists"]["field"]) is not None
    if "term" in query:
        return all(source.get(k) == v for k, v in query["term"].items())
    if "terms" in query:
        return all(str(source.get(k)) in {str(value) for value in values} for k, values in query["terms"].items())
    if "range" in query:
        return all(source.get(k, 0) > bounds["gt"] for k, bounds in query["range"].items())
    boolean = query["bool"]
    return not any(matches(source, clause) for clause in boolean.get("must_not", [])) and all(
        matches(source, clause) for clause in boolean.get("filter", []) + boolean.get("must", [])
    ) and (
        not boolean.get("should") or any(matches(source, clause) for clause in boolean["should"])
    )


class ES:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        definition = kwargs["aggs"]["items"]
        keys = sorted({str(row["file_id"]) for row in self.rows if matches(row, kwargs["query"])})
        after = definition["composite"].get("after", {}).get("key", "")
        keys = [key for key in keys if key > after][:1]
        buckets = []
        for key in keys:
            rows = [row for row in self.rows if str(row["file_id"]) == key and matches(row, kwargs["query"])]
            bucket = {"key": {"key": key}, "doc_count": len(rows)}
            if "record" in definition["aggs"]:
                bucket["record"] = {"hits": {"hits": [{"_source": rows[0]}]}}
            else:
                bucket["first"] = {"value": min(row["timestamp"] * 1000 for row in rows)}
            buckets.append(bucket)
        return {
            "aggregations": {
                "items": {
                    "buckets": buckets,
                    **({"after_key": {"key": keys[-1]}} if keys else {}),
                }
            },
        }


async def test_pages_scope_external_calls_and_exact_zero(monkeypatch):
    rows = [
        {
            "file_id": i,
            "record_type": "file",
            "file_type": 1,
            "tenant_id": 1,
            "org": "A",
            "timestamp": 1,
            "knowledge_identity": f"document:{i}",
        }
        for i in (1, 2)
    ] + [
        {
            "file_id": 9,
            "record_type": "preview_daily",
            "preview_count": 3,
            "space_level": "team",
            "org": "B",
            "timestamp": 10,
        },
        {
            "file_id": 10,
            "record_type": "download_daily",
            "download_count": 2,
            "space_level": "personal",
            "timestamp": 9,
        },
        {"file_id": 2, "record_type": "download_daily", "download_count": 0, "space_level": "public", "timestamp": 8},
    ]
    monkeypatch.setattr(
        module.KnowledgeStatisticsRepository,
        "aliases",
        lambda ids: {1: "document:1", 9: "document:1", 2: "document:2", 10: "document:2"},
    )
    client = ES(rows)
    reader = module.DocumentReader(client, "mid_knowledge_space_content_stat")
    result = await reader.load([{"term": {"org": "A"}}, {"term": {"tenant_id": 1}}], include_usage=True)
    assert result.aggregate([], "total_file_count") == [[2]]
    assert result.aggregate([], "called_document_count") == [[1]]
    assert result.aggregate([], "document_usage_ratio") == [[0.5]]
    assert result.called_at == {"document:1": 10000}
    assert len(client.calls) == 5
    assert client.calls[1]["aggs"]["items"]["composite"]["after"] == {"key": "1"}
    assert all(call["index"] == "mid_knowledge_space_content_stat" and "pit" not in call for call in client.calls)


@pytest.mark.parametrize("response", [{"timed_out": True}, {"terminated_early": True}, {"_shards": {"failed": 1}}])
async def test_partial_responses_are_errors(response):
    client = type("ES", (), {"search": AsyncMock(return_value=response)})()
    with pytest.raises(RuntimeError, match="不完整"):
        await module.DocumentReader(client, "pit").load([], include_usage=False)
    assert client.search.await_args.kwargs["allow_partial_search_results"] is False


async def test_index_query_uses_real_client_without_pit(monkeypatch):
    client = AsyncElasticsearch("http://localhost:9200")
    requests = []

    async def perform_request(method, target, **kwargs):
        requests.append((method, target, kwargs.get("body")))
        path = urlsplit(target)
        params = parse_qs(path.query)
        status = 200
        if path.path == "/mid_knowledge_space_content_stat/_search" and method == "POST":
            assert params["allow_partial_search_results"] == ["false"]
            assert "pit" not in kwargs["body"]
            body = {"aggregations": {"items": {"buckets": []}}}
        else:
            status = 400
            body = {"error": {"type": "illegal_argument_exception", "reason": "PIT must not be used"}}
        return ApiResponseMeta(
            status=status,
            http_version="1.1",
            headers=HttpHeaders({"x-elastic-product": "Elasticsearch"}),
            duration=0,
            node=NodeConfig("http", "localhost", 9200),
        ), body

    monkeypatch.setattr(client.transport, "perform_request", AsyncMock(side_effect=perform_request))
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=client))
    try:
        async with module.document_reader("mid_knowledge_space_content_stat") as reader:
            result = await reader.load([], include_usage=False)
        assert result.aggregate([], "total_file_count") == [[0]]
        assert requests[0][:2] == (
            "POST",
            "/mid_knowledge_space_content_stat/_search?allow_partial_search_results=false",
        )
        assert len(requests) == 1
    finally:
        await client.close()


async def test_fixed_index_without_snapshot_propagates_query_failure(monkeypatch):
    client = type("ES", (), {})()
    client.indices = type("Indices", (), {"get_mapping": AsyncMock(return_value={"i": {"mappings": {}}})})()
    client.open_point_in_time = AsyncMock(return_value={"id": "pit"})
    client.close_point_in_time = AsyncMock()
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=client))
    with pytest.raises(RuntimeError, match="query failed"):
        async with module.document_reader("mid_knowledge_space_content_stat"):
            raise RuntimeError("query failed")
    client.indices.get_mapping.assert_not_awaited()
    client.open_point_in_time.assert_not_awaited()
    client.close_point_in_time.assert_not_awaited()


@pytest.mark.parametrize("include_usage", [False, True])
async def test_legacy_records_resolve_identity_without_reindex(monkeypatch, include_usage):
    rows = [
        {"file_id": 1, "record_type": "file", "file_type": 1, "timestamp": 1},
        {"file_id": 2, "record_type": "file", "file_type": 1, "timestamp": 2, "knowledge_identity": None},
        {"file_id": 3, "record_type": "file", "file_type": 1, "timestamp": 3, "knowledge_identity": "file:3"},
        {"file_id": 9, "record_type": "preview_daily", "space_level": "team", "preview_count": 1, "timestamp": 4},
    ]
    identity_calls = []

    def identities(ids):
        identity_calls.append(ids)
        return {1: "document:10", 2: "document:10"}

    monkeypatch.setattr(module.KnowledgeStatisticsRepository, "identities", identities)
    monkeypatch.setattr(module.KnowledgeStatisticsRepository, "aliases", lambda ids: {9: "document:10"})
    stats = await module.DocumentReader(ES(rows), "pit").load([], include_usage=include_usage)
    assert identity_calls == [[1, 2]]
    assert stats.aggregate([], "total_file_count") == [[2]]
    assert len(stats.detail("total_file_count", start=None, end=None)) == 2
    assert stats.aggregate([], "called_document_count") == [[int(include_usage)]]
    assert "knowledge_identity" not in rows[0]
    assert rows[1]["knowledge_identity"] is None


async def test_unresolvable_legacy_record_fails_without_guessing_identity(monkeypatch):
    monkeypatch.setattr(module.KnowledgeStatisticsRepository, "identities", lambda ids: {})
    rows = [{"file_id": 1, "record_type": "file", "file_type": 1, "timestamp": 1}]
    with pytest.raises(ValueError, match="无法关联文档身份"):
        await module.DocumentReader(ES(rows), "pit").load([], include_usage=False)


def test_time_range_removed_from_candidates_and_intersected():
    clauses, start, end = module.split_time_filters(
        [
            FilterExpression(
                bool_operator="must",
                filters=[
                    TermOp(field="org", value="A"),
                    RangeOp(field="timestamp", value=RangeValue(gte=100, lte=300)),
                ],
            ),
            FilterExpression(
                bool_operator="must", filters=[RangeOp(field="timestamp", value=RangeValue(gt=150, lt=250))]
            ),
        ]
    )
    assert (start, end) == (151, 249)
    assert clauses == [{"bool": {"must": [{"term": {"org": "A"}}]}}]
