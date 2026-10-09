"""Multi-turn input errors of POST /api/v2/workflow/invoke are 400, not 500."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
from bisheng.main import app
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from test.open_api.test_dependencies import service_account_principal

WORKFLOW_ID = "00000000000000000000000000000001"
CHAT_ID = "c" * 32
SESSION_ID = f"{CHAT_ID}_async_task_id"
SERVICE = "bisheng.workflow.domain.services.published_workflow_service"
CALLBACK = "bisheng.worker.workflow.redis_callback"

FORM_MESSAGE = {
    "node_id": "input_1",
    "input_schema": {"tab": "form_input", "value": [{"key": "city", "value": "City"}]},
}
DIALOG_MESSAGE = {"node_id": "input_1", "input_schema": {"tab": "dialog_input", "key": "user_input"}}
CHOOSE_MESSAGE = {"node_id": "output_1", "key": "output_result"}


def _message(category: str, body: dict, chat_id: str = CHAT_ID):
    return SimpleNamespace(id=5, chat_id=chat_id, category=category, message=json.dumps(body))


class _Callback:
    """RedisCallback stand-in that keeps the real input verification."""

    def __init__(self, message_db):
        self.message_db = message_db
        self.continued = False

    def __call__(self, unique_id, workflow_id, chat_id, user_id, source):
        real = RedisCallback.__new__(RedisCallback)
        real.chat_id = chat_id
        real.redis_client = SimpleNamespace(aset=AsyncMock())
        real.workflow_input_key = "input"
        real.workflow_expire_time = 60
        real.save_chat_message = MagicMock()
        real.get_workflow_status = lambda: {"status": WorkflowStatus.INPUT.value}
        real.async_set_workflow_status = AsyncMock()
        return real


@pytest.fixture
def waiting_workflow(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal(scopes=frozenset({"workflow:invoke"}))),
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.workflow.get_open_api_operator", lambda: SimpleNamespace(user_id=12)
    )
    monkeypatch.setattr("bisheng.open_endpoints.api.endpoints.workflow.require_business_action", AsyncMock())
    workflow = SimpleNamespace(id=WORKFLOW_ID, name="wf", data={})
    monkeypatch.setattr(f"{SERVICE}.PublishedWorkflowService.get_workflow", AsyncMock(return_value=workflow))
    monkeypatch.setattr(
        f"{SERVICE}.ChatSessionService.get_subject_session_if_exists",
        AsyncMock(return_value=SimpleNamespace(flow_id=WORKFLOW_ID)),
    )
    monkeypatch.setattr(f"{SERVICE}.workflow_stateful_worker.find_task_node", AsyncMock(return_value="q"))
    continue_task = MagicMock()
    monkeypatch.setattr(f"{SERVICE}.continue_workflow", continue_task)
    monkeypatch.setattr(f"{CALLBACK}.ChatMessageDao.aupdate_message_model", AsyncMock())

    def install(message_db):
        monkeypatch.setattr(f"{SERVICE}.RedisCallback", _Callback(message_db))
        monkeypatch.setattr(f"{CALLBACK}.ChatMessageDao.aget_message_by_id", AsyncMock(return_value=message_db))
        return continue_task

    return install


async def _invoke(body: dict):
    payload = {"workflow_id": WORKFLOW_ID, "session_id": SESSION_ID, "stream": False, **body}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/v2/workflow/invoke", json=payload, headers={"Authorization": "Bearer bs-sak-x"})


@pytest.mark.parametrize(
    "message_db,body",
    [
        # input without message_id, and message_id without input
        (_message("input", FORM_MESSAGE), {"input": {"input_1": {"city": "Paris"}}}),
        (_message("input", FORM_MESSAGE), {"message_id": 5}),
        # message_id that does not exist, or that belongs to another session
        (None, {"input": {"input_1": {"city": "Paris"}}, "message_id": 5}),
        (
            _message("input", FORM_MESSAGE, chat_id="d" * 32),
            {"input": {"input_1": {"city": "Paris"}}, "message_id": 5},
        ),
        # message that does not wait for input
        (_message("output_msg", {"node_id": "output_2"}), {"input": {"output_2": {"x": 1}}, "message_id": 5}),
        # node ID that is not the waiting node
        (_message("input", FORM_MESSAGE), {"input": {"other_node": {"city": "Paris"}}, "message_id": 5}),
        (
            _message("output_with_choose_msg", CHOOSE_MESSAGE),
            {"input": {"other_node": {"output_result": "a"}}, "message_id": 5},
        ),
        (
            _message("output_with_input_msg", CHOOSE_MESSAGE),
            {"input": {"output_1": {"wrong_key": "a"}}, "message_id": 5},
        ),
        # node input that is not an object
        (_message("input", FORM_MESSAGE), {"input": {"input_1": "Paris"}, "message_id": 5}),
        # form fields that do not match the form definition
        (_message("input", FORM_MESSAGE), {"input": {"input_1": {}}, "message_id": 5}),
        (_message("input", FORM_MESSAGE), {"input": {"input_1": {"city": "Paris", "extra": 1}}, "message_id": 5}),
        (_message("input", DIALOG_MESSAGE), {"input": {"input_1": {"wrong": "hi"}}, "message_id": 5}),
    ],
)
async def test_invalid_user_input_is_a_400_business_error(waiting_workflow, message_db, body):
    continue_task = waiting_workflow(message_db)

    response = await _invoke(body)

    assert response.status_code == 400
    assert response.json()["status_code"] == WorkFlowInvalidUserInputError.Code
    continue_task.apply_async.assert_not_called()


async def test_valid_user_input_continues_the_workflow(waiting_workflow, monkeypatch):
    continue_task = waiting_workflow(_message("input", FORM_MESSAGE))

    async def no_events(*_args, **_kwargs):
        return
        yield

    monkeypatch.setattr(f"{SERVICE}.PublishedWorkflowService.iter_events", no_events)
    monkeypatch.setattr("bisheng.open_endpoints.api.endpoints.workflow.telemetry_service.log_event", AsyncMock())

    response = await _invoke({"input": {"input_1": {"city": "Paris"}}, "message_id": 5})

    assert response.status_code == 200
    continue_task.apply_async.assert_called_once()
