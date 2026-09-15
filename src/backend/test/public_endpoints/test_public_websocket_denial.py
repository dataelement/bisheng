"""How a guest WebSocket denial reaches the browser.

NOTE: this is the only synchronous test file in this directory. Starlette's
``TestClient`` is required because ``httpx.AsyncClient`` cannot open a
WebSocket, and ``TestClient`` drives its own event loop.

The behaviour under test is the fix for a real defect: closing before the
handshake completes makes the server answer the upgrade with an HTTP error,
which browsers surface as a bare 1006 with an empty reason. The denial reason
never arrived. Accepting first turns it into a readable frame.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bisheng.database.models.assistant import AssistantStatus
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.public_endpoints.api.exception_handlers import register_public_exception_handlers
from bisheng.public_endpoints.api.router import router_public
from bisheng.public_endpoints.domain.services import guest_policy

WORKFLOW_ID = UUID(int=201).hex


@pytest.fixture
def publication(monkeypatch):
    state = SimpleNamespace(
        flow=SimpleNamespace(
            tenant_id=3, flow_type=FlowType.WORKFLOW.value, status=FlowStatus.OFFLINE.value
        ),
        assistant=None,
    )
    monkeypatch.setattr(
        guest_policy.FlowDao, "aget_flow_by_id", AsyncMock(side_effect=lambda _id: state.flow)
    )
    monkeypatch.setattr(
        guest_policy.AssistantDao,
        "aget_one_assistant",
        AsyncMock(side_effect=lambda _id: state.assistant),
    )
    return state


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router_public)
    register_public_exception_handlers(app)
    with TestClient(app) as value:
        yield value


def _connect_and_read(client, state_setup=None):
    """Open the guest socket and return the first frame plus the close code."""

    if state_setup is not None:
        state_setup()
    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect(
            f"/api/v3/workflow/chat/{UUID(WORKFLOW_ID)}"
        ) as websocket:
            frame = websocket.receive_json()
            websocket.receive_json()  # drives the close
    return frame, disconnect.value.code


def test_offline_application_reports_a_readable_close(client, publication) -> None:
    frame, close_code = _connect_and_read(client)

    # Connecting at all is the point: a pre-accept close would have surfaced as
    # a handshake rejection here, never as a frame.
    assert frame["category"] == "error"
    assert frame["type"] == "end"
    assert frame["message"]["status_code"] == 26102
    assert frame["message"]["data"] == {}
    assert close_code == 1008


def test_unknown_application_reports_the_invalid_link_code(client, publication) -> None:
    def take_it_away():
        publication.flow = None

    frame, close_code = _connect_and_read(client, take_it_away)

    assert frame["message"]["status_code"] == 26101
    assert close_code == 1008


def test_deleted_assistant_reads_as_an_invalid_link(client, publication) -> None:
    def swap():
        publication.flow = None
        publication.assistant = SimpleNamespace(
            tenant_id=3, is_delete=True, status=AssistantStatus.ONLINE.value
        )

    frame, _ = _connect_and_read(client, swap)

    assert frame["message"]["status_code"] == 26101
