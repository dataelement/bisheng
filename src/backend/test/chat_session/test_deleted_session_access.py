"""Exercise production service/route bodies with isolated external dependencies.

AST loading keeps this lifecycle regression independent of LLM providers and
middleware startup. The compiled methods and endpoint bodies come from source;
only their database, storage, telemetry and schema collaborators are replaced.
"""

import ast
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Union
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel

BACKEND = Path(__file__).resolve().parents[2]


def _load_nodes(path, names, namespace):
    tree = ast.parse((BACKEND / path).read_text())
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(BACKEND / path), "exec"), namespace)


@pytest.fixture
def lifecycle(monkeypatch):
    row = SimpleNamespace(chat_id="chat-1", flow_id="app-1", flow_type=5, user_id=7, is_delete=False, flow_logo="logo", tenant_id=1, api_subject_type=None)
    state = SimpleNamespace(session=row, share=None)
    dao = SimpleNamespace(async_get_one=AsyncMock(side_effect=lambda *a, **kw: state.session))

    async def soft_delete(chat_id, **kwargs):
        assert chat_id == row.chat_id
        row.is_delete = True

    dao.delete_session = AsyncMock(side_effect=soft_delete)
    messages = SimpleNamespace(
        afilter_message_by_chat_id=AsyncMock(
            return_value=[SimpleNamespace(id=41, user_id=7, message="APP_DELETE_TEST")]
        )
    )
    schema = ModuleType("bisheng.api.v1.schema.chat_schema")
    schema.ChatMessageHistoryResponse = SimpleNamespace(from_chat_message_objs=lambda rows, *args: rows)
    monkeypatch.setitem(sys.modules, schema.__name__, schema)
    namespace = {
        "MessageSessionDao": dao,
        "_resolve_leaf_tenant_id": lambda user: 1,
        "WorkflowFileRepository": SimpleNamespace(soft_delete_owned_session=AsyncMock(side_effect=soft_delete)),
        "ChatMessageDao": messages,
        "UserDao": SimpleNamespace(aget_user=AsyncMock(return_value=SimpleNamespace(id=7))),
        "WorkFlowService": SimpleNamespace(get_logo_share_link=Mock(return_value="logo-url")),
        "AssistantDao": SimpleNamespace(aget_one_assistant=AsyncMock(return_value=object())),
        "FlowType": SimpleNamespace(ASSISTANT=SimpleNamespace(value=5), WORKSTATION=SimpleNamespace(value=4)),
        "AuditLogService": SimpleNamespace(delete_chat_assistant=AsyncMock()),
        "telemetry_service": SimpleNamespace(log_event=AsyncMock()),
        "BaseTelemetryTypeEnum": SimpleNamespace(DELETE_MESSAGE_SESSION="delete"),
        "trace_id_var": SimpleNamespace(get=lambda: "test"),
        "DeleteMessageSessionEventData": lambda **kw: kw,
    }
    # Postponed annotations let the isolated body retain production type hints.
    namespace["__builtins__"] = __builtins__
    source = ast.parse((BACKEND / "bisheng/chat_session/domain/chat.py").read_text())
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "ChatSessionService")
    cls.body = [
        node
        for node in cls.body
        if getattr(node, "name", None)
        in {
            "get_chat_history",
            "get_session_info",
            "delete_session",
        }
    ]
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[]
    )
    exec(compile(ast.fix_missing_locations(module), "chat.py", "exec"), namespace)
    service = namespace["ChatSessionService"]
    service._remove_attachments = AsyncMock()
    state.dao, state.messages, state.service, state.namespace = dao, messages, service, namespace
    return state


class User(BaseModel):
    user_id: int = 7

    @staticmethod
    def get_login_user():
        return User()


class ShareLink(BaseModel):
    resource_id: str


@pytest.fixture
async def client(lifecycle):
    router = APIRouter()
    namespace = {
        "router": router,
        "Depends": Depends,
        "Query": Query,
        "Union": Union,
        "UserPayload": User,
        "ShareLink": ShareLink,
        "header_share_token_parser": lambda: lifecycle.share,
        "bypass_tenant_filter_if": lambda enabled: nullcontext(),
        "ChatSessionService": lifecycle.service,
        "resp_200": lambda data: {"status_code": 200, "data": data},
        "UnAuthorizedError": SimpleNamespace(return_resp=lambda: {"status_code": 403}),
    }
    _load_nodes("bisheng/chat_session/api/endpoints/chat.py", {"get_chat_message", "get_chat_info"}, namespace)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield client


@pytest.mark.parametrize("shared", [False, True])
async def test_old_history_link_becomes_empty_after_owner_deletes_session(client, lifecycle, shared):
    if shared:
        lifecycle.share = ShareLink(resource_id="chat-1")
    params = {"chat_id": "chat-1", "flow_id": "app-1"}
    before = await client.get("/api/v1/chat/history", params=params)
    assert before.json()["data"][0]["message"] == "APP_DELETE_TEST"

    await lifecycle.service.delete_session("chat-1", User(), "127.0.0.1")
    lifecycle.messages.afilter_message_by_chat_id.reset_mock()

    after = await client.get("/api/v1/chat/history", params=params)
    assert after.status_code == 200
    assert after.json()["data"] == []
    lifecycle.messages.afilter_message_by_chat_id.assert_not_awaited()
    assert lifecycle.session.is_delete is True


async def test_deleted_title_link_returns_empty_without_resolving_logo(client, lifecycle):
    lifecycle.session.is_delete = True
    response = await client.get("/api/v1/chat/info", params={"chat_id": "chat-1"})
    assert response.json()["data"] is None
    lifecycle.namespace["WorkFlowService"].get_logo_share_link.assert_not_called()


async def test_active_title_retains_its_metadata(client, lifecycle):
    response = await client.get("/api/v1/chat/info", params={"chat_id": "chat-1"})
    assert response.json()["data"]["flow_logo"] == "logo-url"


@pytest.mark.parametrize("session_state", ["missing", "deleted", "different-app"])
async def test_unavailable_history_skips_message_lookup(lifecycle, session_state):
    if session_state == "missing":
        lifecycle.session = None
    elif session_state == "deleted":
        lifecycle.session.is_delete = True
    else:
        lifecycle.session.flow_id = "app-2"
    assert await lifecycle.service.get_chat_history("chat-1", "app-1") == []
    lifecycle.messages.afilter_message_by_chat_id.assert_not_awaited()


async def test_active_history_keeps_its_pagination(lifecycle):
    rows = await lifecycle.service.get_chat_history("chat-1", "app-1", "30", 10)
    assert rows[0].message == "APP_DELETE_TEST"
    lifecycle.messages.afilter_message_by_chat_id.assert_awaited_once_with(
        chat_id="chat-1",
        flow_id="app-1",
        message_id="30",
        page_size=10,
    )
