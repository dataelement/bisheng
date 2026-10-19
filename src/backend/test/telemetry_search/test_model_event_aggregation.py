"""Event metrics must not count the per-minute copies used for concurrency."""

import os
from uuid import uuid4

import pytest
from elasticsearch import Elasticsearch, helpers

from bisheng.telemetry_search.domain.models.dashboard_dataset import MetricConfig
from bisheng.telemetry_search.domain.schemas.component import AggregationType, ComponentDataConfig
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    AggsTypeEnum,
    FilterExpression,
    RangeOp,
    RangeValue,
    TermOp,
)
from bisheng.telemetry_search.domain.services.component import DataQueryService
from bisheng.telemetry_search.domain.services.search_engine_service import (
    QueryBuilder,
    SearchEngineService,
    SearchParameters,
)


def _parameters(field="total_token", agg_type=AggsTypeEnum.SUM, **kwargs):
    return SearchParameters(
        index_name=kwargs.pop("index_name", "mid_model_call_dtl"),
        metrics=[AggregationExpression(name=field, field=field, type=agg_type)],
        dimensions=kwargs.pop("dimensions", []),
        **kwargs,
    )


@pytest.mark.parametrize("field", ["total_token", "first_token_cost_time"])
def test_event_metrics_filter_representative_before_dimension_aggregation(field):
    params = _parameters(
        field,
        dimensions=[AggregationExpression(name="app", field="app_name", type=AggsTypeEnum.TERMS)],
        filters=[FilterExpression(bool_operator="must", filters=[TermOp(field="app_name", value="daily_chat")])],
    )
    dsl = QueryBuilder(params).build_query_dsl()
    assert dsl["query"]["bool"]["must"] == [{"term": {"app_name": "daily_chat"}}]
    assert dsl["query"]["bool"]["filter"][0]["script"]["script"]["lang"] == "painless"
    assert dsl["aggs"]["dimension_0"]["aggs"]["metric_0"] == {"sum": {"field": field}}
    assert "event_id" not in str(dsl)  # No high-cardinality event buckets or in-memory ID map.
    assert params.filters[0].to_dsl() == {"must": [{"term": {"app_name": "daily_chat"}}]}


@pytest.mark.parametrize(
    ("index_name", "field", "agg_type"),
    [
        ("mid_other", "total_token", AggsTypeEnum.SUM),
        ("mid_model_call_dtl", "event_id", AggsTypeEnum.CARDINALITY),
        ("mid_model_call_dtl", "minute_ts", AggsTypeEnum.DATE_HISTOGRAM),
    ],
)
def test_other_indices_call_counts_and_concurrency_keep_all_rows(index_name, field, agg_type):
    params = _parameters(field, agg_type, index_name=index_name)
    if field == "minute_ts":
        params.metrics[0].custom_params = {"fixed_interval": "1m"}
        params.metrics[0].aggs = [AggregationExpression(name="online", field="event_id", type=AggsTypeEnum.CARDINALITY)]
    assert QueryBuilder(params).build_query_dsl()["query"] == {"match_all": {}}


async def test_existing_non_virtual_dataset_metric_automatically_gets_filter(monkeypatch):
    queries = []

    async def capture_search(self):
        queries.append(self.build_search_query())
        return [[2494]]

    monkeypatch.setattr(SearchEngineService, "search", capture_search)
    service = DataQueryService(dataset_code="mid_model_call_dtl", data_config=ComponentDataConfig())
    metric = MetricConfig(field="total_token", name="tokens", is_virtual=False)
    assert await service.query_one_metric(
        metric, AggregationType.SUM, -1, index_name="mid_model_call_dtl", dimensions=[], filters=None
    ) == [[2494]]
    assert "script" in queries[0]["query"]["bool"]["filter"][0]
    assert queries[0]["aggs"] == {"metric_0": {"sum": {"field": "total_token"}}}


@pytest.fixture
def es_event_index():
    """Opt-in middleware test; only creates/deletes a uniquely named test index."""
    url = os.getenv("TELEMETRY_TEST_ES_URL")
    if not url:
        pytest.skip("Set TELEMETRY_TEST_ES_URL to an isolated test Elasticsearch")
    client = Elasticsearch(url)
    name = f"test-model-event-{uuid4().hex}"
    yield client, name
    if client.indices.exists(index=name):
        client.indices.delete(index=name)
    client.close()


@pytest.mark.parametrize(
    "end_format", ["epoch_millis", "epoch_second", "strict_date_optional_time||epoch_second||epoch_millis"]
)
def test_real_es_counts_each_invocation_once_with_legacy_and_correct_dates(es_event_index, end_format):
    client, index = es_event_index
    client.indices.create(
        index=index,
        mappings={
            "properties": {
                "event_id": {"type": "keyword"},
                "app_name": {"type": "keyword"},
                "timestamp": {"type": "date", "format": "epoch_second"},
                "minute_ts": {"type": "date", "format": "epoch_millis"},
                "end_time": {"type": "date", "format": end_format},
                "total_token": {"type": "long"},
                "first_token_cost_time": {"type": "long"},
                "user_group_infos": {
                    "type": "nested",
                    "properties": {"user_group_name": {"type": "keyword"}},
                },
            }
        },
    )
    # Two distinct invocations with equal Token values must both count. Only
    # the first crosses a minute boundary; otherwise AVG would weight it twice.
    end = 1791949504
    minute = end // 60 * 60000
    docs = [
        {
            "event_id": "a",
            "end_time": end,
            "minute_ts": minute - 60000,
            "total_token": 100,
            "first_token_cost_time": 100,
        },
        {"event_id": "a", "end_time": end, "minute_ts": minute, "total_token": 100, "first_token_cost_time": 100},
        {"event_id": "b", "end_time": end, "minute_ts": minute, "total_token": 100, "first_token_cost_time": 900},
        # Ending exactly on a minute boundary still has an ending-minute copy.
        {
            "event_id": "c",
            "end_time": end - 4,
            "minute_ts": minute - 60000,
            "total_token": 5,
            "first_token_cost_time": 200,
        },
        {"event_id": "c", "end_time": end - 4, "minute_ts": minute, "total_token": 5, "first_token_cost_time": 200},
        # Old, unexpanded events have no minute_ts and must remain visible.
        {"event_id": "legacy", "total_token": 7, "first_token_cost_time": 400},
    ]
    helpers.bulk(
        client,
        [
            {
                "_index": index,
                "_source": {
                    "app_name": "daily_chat",
                    "timestamp": end,
                    "user_group_infos": [{"user_group_name": "group-a"}, {"user_group_name": "group-b"}],
                    **doc,
                },
            }
            for doc in docs
        ],
        refresh=True,
    )
    assert client.count(index=index)["count"] == 6

    def query(params):
        return client.search(index=index, body=QueryBuilder(params).build_query_dsl())["aggregations"]

    assert query(_parameters())["metric_0"]["value"] == 212
    avg = query(_parameters("first_token_cost_time", AggsTypeEnum.AVG))
    assert avg["metric_0"]["value"] == 400

    grouped = _parameters(
        dimensions=[AggregationExpression(name="app", field="app_name", type=AggsTypeEnum.TERMS)],
        filters=[
            FilterExpression(
                bool_operator="filter",
                # Component TimeFilter converts seconds to milliseconds.
                filters=[RangeOp(field="timestamp", value=RangeValue(gte=end * 1000, lte=end * 1000))],
            )
        ],
    )
    buckets = query(grouped)["dimension_0"]["buckets"]
    assert [(bucket["key"], bucket["metric_0"]["value"]) for bucket in buckets] == [("daily_chat", 212)]

    # A nested user-group dimension returns to the parent document before
    # aggregating Token values; the representative-row filter must still hold.
    nested = _parameters(
        dimensions=[
            AggregationExpression(name="group", field="user_group_infos.user_group_name", type=AggsTypeEnum.TERMS)
        ],
        stack_dimension=AggregationExpression(name="app", field="app_name", type=AggsTypeEnum.TERMS),
    )
    response = client.search(index=index, body=QueryBuilder(nested).build_query_dsl())
    from bisheng.telemetry_search.domain.services.search_engine_service import ResultParser

    assert sorted(ResultParser(nested).parse_to_2d_array(response.body)) == [
        ["group-a", "daily_chat", 212],
        ["group-b", "daily_chat", 212],
    ]

    # The concurrent-call metric must still see both minute buckets.
    concurrent = _parameters("minute_ts", AggsTypeEnum.DATE_HISTOGRAM)
    concurrent.metrics[0].custom_params = {"fixed_interval": "1m"}
    concurrent.metrics[0].aggs = [AggregationExpression(name="online", field="event_id", type=AggsTypeEnum.CARDINALITY)]
    assert [bucket["metric_0_0"]["value"] for bucket in query(concurrent)["metric_0"]["buckets"]] == [2, 3]


def test_real_es_unexpanded_index_without_minute_mapping(es_event_index):
    client, index = es_event_index
    client.index(index=index, document={"total_token": 123}, refresh=True)
    dsl = QueryBuilder(_parameters()).build_query_dsl()
    assert client.search(index=index, body=dsl)["aggregations"]["metric_0"]["value"] == 123


@pytest.mark.slow
def test_real_es_large_event_volume_needs_no_event_id_buckets(es_event_index):
    if os.getenv("TELEMETRY_TEST_ES_LARGE") != "1":
        pytest.skip("Set TELEMETRY_TEST_ES_LARGE=1 to test more than 100,000 invocations")
    client, index = es_event_index
    client.indices.create(
        index=index,
        mappings={
            "properties": {
                "event_id": {"type": "keyword"},
                "minute_ts": {"type": "date", "format": "epoch_millis"},
                "end_time": {"type": "date", "format": "epoch_millis"},
                "total_token": {"type": "long"},
            }
        },
    )
    event_count = 100001

    def actions():
        for event in range(event_count):
            end = 1791949504 - event % 180 * 86400
            minute = end // 60 * 60000
            for minute_ts in (minute - 60000, minute):
                yield {
                    "_index": index,
                    "_source": {"event_id": str(event), "end_time": end, "minute_ts": minute_ts, "total_token": 1},
                }

    helpers.bulk(client, actions(), refresh=True)
    assert client.count(index=index)["count"] == event_count * 2
    dsl = QueryBuilder(_parameters()).build_query_dsl()
    result = client.search(index=index, body=dsl)
    assert result["aggregations"]["metric_0"]["value"] == event_count
