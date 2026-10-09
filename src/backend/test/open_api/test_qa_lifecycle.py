"""Behaviour of the v2 QA endpoints: query, delete, update and add."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from bisheng.open_api.api import dependencies as open_api_dependencies
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.schemas.filelib import QueryQAParam

USER = SimpleNamespace(user_id=7)


# --- query_qa -------------------------------------------------------------


def test_query_qa_includes_api_written_rows(monkeypatch):
    query = Mock(return_value=[])
    monkeypatch.setattr(filelib, "get_open_api_operator", Mock(return_value=USER))
    monkeypatch.setattr(filelib.QAKnoweldgeDao, "query_by_condition_v1", query)

    filelib.query_qa(QueryQAParam(timeRange=["2026-01-01", "2026-12-31"]))

    sources = query.call_args.kwargs["source"]
    # 1 manual, 2 audit, 3 written by add_qa / add_relative_qa of this API.
    assert set(sources) == {1, 2, 3}


@pytest.mark.parametrize("time_range", [[], ["2026-01-01"]])
def test_query_qa_rejects_short_time_range(time_range):
    with pytest.raises(ValidationError):
        QueryQAParam(timeRange=time_range)


async def test_query_qa_short_time_range_is_http_400(monkeypatch):
    @asynccontextmanager
    async def authenticated(request, inspect_body=False):
        yield

    # The validation handler re-runs authentication first; treat the caller as authenticated.
    monkeypatch.setattr(open_api_dependencies, "open_api_access_context", authenticated)
    app = FastAPI()
    register_open_api_exception_handlers(app)

    @app.post("/api/v2/filelib/query_qa")
    def endpoint(param: QueryQAParam):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v2/filelib/query_qa", json={"timeRange": ["2026-01-01"]})

    assert response.status_code == 400
    assert response.json()["status_code"] == 400
