# ruff: noqa: RUF002
"""按真实查询条件筛选分页样本，验证库存和调用范围不会相互污染。"""

from unittest.mock import AsyncMock

import pytest

from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, RangeOp, RangeValue, TermOp
from bisheng.telemetry_search.domain.services import knowledge_document_reader as module


def matches(source, query):
    if "term" in query:
        return all(source.get(k) == v for k, v in query["term"].items())
    if "terms" in query:
        return all(str(source.get(k)) in {str(value) for value in values} for k, values in query["terms"].items())
    if "range" in query:
        return all(source.get(k, 0) > bounds["gt"] for k, bounds in query["range"].items())
    boolean = query["bool"]
    return all(matches(source, clause) for clause in boolean.get("filter", []) + boolean.get("must", [])) and (
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
            "pit_id": "updated",
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
    reader = module.DocumentReader(client, "initial")
    result = await reader.load([{"term": {"org": "A"}}, {"term": {"tenant_id": 1}}], include_usage=True)
    assert result.aggregate([], "total_file_count") == [[2]]
    assert result.aggregate([], "called_document_count") == [[1]]
    assert result.aggregate([], "document_usage_ratio") == [[0.5]]
    assert result.called_at == {"document:1": 10000}
    assert len(client.calls) == 5
    assert client.calls[1]["pit"]["id"] == "updated"


@pytest.mark.parametrize("response", [{"timed_out": True}, {"_shards": {"failed": 1}}])
async def test_partial_responses_are_errors(response):
    client = type("ES", (), {"search": AsyncMock(return_value=response)})()
    with pytest.raises(RuntimeError, match="不完整"):
        await module.DocumentReader(client, "pit").load([], include_usage=False)


async def test_readiness_gate_and_pit_close_on_failure(monkeypatch):
    client = type("ES", (), {})()
    client.indices = type("Indices", (), {"get_mapping": AsyncMock(return_value={"i": {"mappings": {}}})})()
    client.open_point_in_time = AsyncMock(return_value={"id": "pit"})
    client.close_point_in_time = AsyncMock()
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=client))
    with pytest.raises(module.DocumentStatisticsNotReadyError):
        async with module.document_reader("index"):
            pytest.fail("不应读取未迁移索引")
    client.open_point_in_time.assert_not_awaited()
    client.indices.get_mapping.return_value = {"i": {"mappings": {"_meta": {"document_statistics_version": 1}}}}
    with pytest.raises(RuntimeError):
        async with module.document_reader("index") as reader:
            reader.pit_id = "latest"
            raise RuntimeError("query failed")
    client.close_point_in_time.assert_awaited_once_with(id="latest")


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
