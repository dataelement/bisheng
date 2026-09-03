import pytest

from bisheng.telemetry_search.domain.schemas.query_builder import AggregationExpression, AggsTypeEnum
from bisheng.telemetry_search.domain.services import search_engine_service
from bisheng.telemetry_search.domain.services.search_engine_service import SearchEngineService, SearchParameters


class FakeIndexNotFoundError(Exception):
    body = {"error": {"type": "index_not_found_exception"}}


class FakeNotFoundError(Exception):
    body = {"error": {"type": "document_missing_exception"}}


class MissingIndexClient:
    async def search(self, **kwargs):
        raise FakeIndexNotFoundError("index_not_found_exception")


class MissingDocumentClient:
    async def search(self, **kwargs):
        raise FakeNotFoundError("document_missing_exception")


def _metric() -> AggregationExpression:
    return AggregationExpression(name="like_count", type=AggsTypeEnum.VALUE_COUNT, field="event_id")


@pytest.mark.asyncio
async def test_missing_index_returns_zero_metric_result(monkeypatch):
    async def fake_get_es_connection():
        return MissingIndexClient()

    monkeypatch.setattr(search_engine_service.es_exceptions, "NotFoundError", FakeIndexNotFoundError)
    monkeypatch.setattr(search_engine_service, "get_es_connection", fake_get_es_connection)

    params = SearchParameters(index_name="mid_user_interact_dtl", metrics=[_metric()], dimensions=[])

    assert await SearchEngineService(params).search() == [[0]]


@pytest.mark.asyncio
async def test_missing_index_returns_empty_dimension_result(monkeypatch):
    async def fake_get_es_connection():
        return MissingIndexClient()

    monkeypatch.setattr(search_engine_service.es_exceptions, "NotFoundError", FakeIndexNotFoundError)
    monkeypatch.setattr(search_engine_service, "get_es_connection", fake_get_es_connection)

    params = SearchParameters(
        index_name="mid_user_interact_dtl",
        metrics=[_metric()],
        dimensions=[AggregationExpression(name="app_name", type=AggsTypeEnum.TERMS, field="app_name")],
    )

    assert await SearchEngineService(params).search() == []


@pytest.mark.asyncio
async def test_non_index_not_found_still_fails(monkeypatch):
    async def fake_get_es_connection():
        return MissingDocumentClient()

    monkeypatch.setattr(search_engine_service.es_exceptions, "NotFoundError", FakeNotFoundError)
    monkeypatch.setattr(search_engine_service, "get_es_connection", fake_get_es_connection)

    params = SearchParameters(index_name="mid_user_interact_dtl", metrics=[_metric()], dimensions=[])

    with pytest.raises(RuntimeError, match="Search execution failed"):
        await SearchEngineService(params).search()
