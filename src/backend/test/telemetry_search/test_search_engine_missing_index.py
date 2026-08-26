"""Regression: dashboard queries must not 500 when the underlying ES index
does not yet exist.

Root cause (gitee IKB8XI — "全新部署点击看板报错"): on a fresh deployment the
preset dashboards query Elasticsearch indices (``mid_user_increment``,
``mid_knowledge_increment``, ``mid_app_increment``, ``mid_user_interact_dtl``, …)
that the telemetry mid-table Celery workers have not yet created. The
underlying ``AsyncElasticsearch.search`` raises ``NotFoundError`` (HTTP 404),
which the dashboard's ``SearchEngineService.search`` wrapped as a generic
``RuntimeError`` — every dashboard component then 500'd with the frontend's
generic "服务器错误" toast.

The fix: ``SearchEngineService.search`` catches ``NotFoundError`` and returns
an empty result (so the dashboard renders zeros/empty charts instead of
failing the whole page), and lets every other error propagate with its
original traceback.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from elasticsearch import NotFoundError

from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    AggsTypeEnum,
)
from bisheng.telemetry_search.domain.services.search_engine_service import (
    SearchEngineService,
    SearchParameters,
)


def _make_params(index_name: str = "mid_user_increment") -> SearchParameters:
    return SearchParameters(
        index_name=index_name,
        metrics=[AggregationExpression(name="total", type=AggsTypeEnum.CARDINALITY, field="user_id")],
        dimensions=[],
    )


def _not_found_error() -> NotFoundError:
    return NotFoundError(
        message="index_not_found_exception",
        meta=MagicMock(),
        body={"error": {"type": "index_not_found_exception"}},
    )


async def test_search_returns_empty_when_index_missing():
    """NotFoundError (index missing) must yield an empty result, not raise."""
    service = SearchEngineService(_make_params())

    mock_es = MagicMock()
    mock_es.search = AsyncMock(side_effect=_not_found_error())

    with patch(
        "bisheng.telemetry_search.domain.services.search_engine_service.get_es_connection",
        new=AsyncMock(return_value=mock_es),
    ):
        result = await service.search()

    assert result == []
    mock_es.search.assert_awaited_once()


async def test_search_propagates_other_errors():
    """Non-NotFoundError exceptions must still surface (no silent swallow)."""
    service = SearchEngineService(_make_params())

    mock_es = MagicMock()
    # ConnectionError / mapping / other genuine failures → still 500
    mock_es.search = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch(
        "bisheng.telemetry_search.domain.services.search_engine_service.get_es_connection",
        new=AsyncMock(return_value=mock_es),
    ):
        with pytest.raises(RuntimeError, match="connection refused"):
            await service.search()


async def test_search_returns_parsed_rows_on_success():
    """Happy path: a normal ES response is parsed into a 2D array as before."""
    service = SearchEngineService(_make_params())

    fake_response = {
        "aggregations": {
            "metric_0": {"value": 42},
        }
    }
    mock_es = MagicMock()
    mock_es.search = AsyncMock(return_value=fake_response)

    with patch(
        "bisheng.telemetry_search.domain.services.search_engine_service.get_es_connection",
        new=AsyncMock(return_value=mock_es),
    ):
        result = await service.search()

    # Single-metric, no-dimension query → one row, one column.
    assert result == [[42]]
