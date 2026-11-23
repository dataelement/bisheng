"""Public response projection must never mutate server-side execution records."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from bisheng.common.schemas.api import resp_200
from bisheng.public_endpoints.api.endpoints import assistant, flow

CANARY = "synthetic-sql-password-DO-NOT-EXPOSE"


def graph():
    return {
        "nodes": [
            {
                "id": "agent_1",
                "data": {
                    "id": "agent_1",
                    "type": "agent",
                    "name": "SQL agent",
                    "group_params": [{"params": [{"key": "sql_agent", "value": {"db_password": CANARY}}]}],
                    "custom_secret": CANARY,
                },
            },
            {
                "id": "input_1",
                "data": {
                    "id": "input_1",
                    "type": "input",
                    "tab": {"value": "dialog_input"},
                    "group_params": [{"params": [{"key": "user_input", "tab": "dialog_input", "value": CANARY}]}],
                },
            },
            {"id": "code_1", "data": {"type": "code", "code": CANARY}},
        ],
        "edges": [{"source": "agent_1", "target": "input_1", "data": {"password": CANARY}}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "unknown_config": CANARY,
    }


class AssistantData(BaseModel):
    id: str
    name: str
    can_share: bool = True
    flow_list: list[dict]
    tool_list: list[dict]


@asynccontextmanager
async def allowed_public(*_args):
    yield SimpleNamespace(operator=SimpleNamespace(user_id=1))


@pytest.mark.parametrize("kind", ["workflow", "assistant"])
def test_public_detail_does_not_serialize_configuration_or_mutate_execution(monkeypatch, kind):
    saved_graph = graph()
    before = deepcopy(saved_graph)
    app = FastAPI()
    if kind == "workflow":
        response = resp_200(data={"id": UUID(int=41).hex, "name": "Published", "data": saved_graph})
        source_before = deepcopy(response.model_dump())
        monkeypatch.setattr(flow, "public_execution", allowed_public)
        monkeypatch.setattr(flow.FlowService, "get_one_flow", AsyncMock(return_value=response))
        app.include_router(flow.router)
        path = f"/flows/{UUID(int=41).hex}"
    else:
        response = AssistantData(
            id=UUID(int=42).hex,
            name="Published assistant",
            flow_list=[{"id": "offline-linked-flow", "name": "Private flow", "status": 1, "data": saved_graph}],
            tool_list=[{"id": 3, "name": "SQL tool", "api_key": CANARY, "extra": {"password": CANARY}}],
        )
        source_before = deepcopy(response.model_dump())
        monkeypatch.setattr(assistant, "public_execution", allowed_public)
        monkeypatch.setattr(assistant.PublishedAssistantService, "get_info", AsyncMock(return_value=response))
        app.include_router(assistant.router)
        path = f"/assistant/info/{UUID(int=42).hex}"
    with TestClient(app) as client:
        result = client.get(path)
    assert result.status_code == 200
    assert CANARY not in result.text
    assert saved_graph == before
    assert response.model_dump() == source_before
    payload = result.json()["data"]
    assert payload["can_share"] is False
    if kind == "workflow":
        node = payload["data"]["nodes"][1]
        assert node["id"] == "input_1"
        assert node["data"]["tab"]["value"] == "dialog_input"
        assert node["data"]["group_params"][0]["params"][0]["key"] == "user_input"
        assert node["data"]["group_params"][0]["params"][0]["tab"] == "dialog_input"
    else:
        assert payload["flow_list"][0]["name"] == "Private flow"
        assert "data" not in payload["flow_list"][0]
        assert payload["tool_list"][0]["name"] == "SQL tool"
