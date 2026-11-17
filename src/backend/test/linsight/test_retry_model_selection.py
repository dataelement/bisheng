"""Task retries save the current selector's model before worker dispatch."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.linsight.api.endpoints import linsight as endpoint
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum


@pytest.fixture
def retry_env(monkeypatch):
    record = SimpleNamespace(
        id="task-1",
        session_id="chat-1",
        user_id=7,
        tenant_id=1,
        status=SessionVersionStatusEnum.FAILED,
        model="936",
    )
    state = {"record": record, "enqueued": [], "queue_failure": False}
    monkeypatch.setattr(endpoint.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=record))
    monkeypatch.setattr(endpoint.MessageSessionDao, "touch_session", AsyncMock())
    monkeypatch.setattr(endpoint, "get_redis_client", AsyncMock(return_value=object()))

    async def update(ids, status, **fields):
        assert ids == ["task-1"]
        record.status = status
        for key, value in fields.items():
            setattr(record, key, value)

    state["update"] = AsyncMock(side_effect=update)
    monkeypatch.setattr(endpoint.LinsightSessionVersionDao, "batch_update_session_versions_status", state["update"])

    class Queue:
        def __init__(self, *_args, **_kwargs):
            pass

        async def put(self, data):
            if state["queue_failure"]:
                raise RuntimeError("queue unavailable")
            state["enqueued"].append({"data": data, "model": record.model, "status": record.status})

    worker = ModuleType("bisheng.linsight.worker")
    worker.LinsightQueue = Queue
    worker.encode_queue_item = lambda svid, **kwargs: {"session_version_id": svid, **kwargs}
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", worker)
    return state


async def test_retry_persists_replacement_model_before_enqueue(retry_env):
    response = await endpoint.continue_conversation(
        session_version_id="task-1",
        question="Original question",
        model="954",
        login_user=SimpleNamespace(user_id=7),
    )
    assert response.status_code == 200
    assert retry_env["enqueued"] == [
        {
            "data": {"session_version_id": "task-1", "continue_question": "Original question", "tenant_id": 1},
            "model": "954",
            "status": SessionVersionStatusEnum.IN_PROGRESS,
        }
    ]


@pytest.mark.parametrize("model,status_code", [("954", 200), ("", 422)])
async def test_http_retry_model_contract(retry_env, model, status_code):
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/workbench/continue",
            json={"session_version_id": "task-1", "question": "Original question", "model": model},
        )
    assert response.status_code == status_code
    if status_code == 200:
        assert retry_env["enqueued"][0]["model"] == "954"
    else:
        retry_env["update"].assert_not_awaited()


async def test_follow_up_without_model_preserves_original_selection(retry_env):
    response = await endpoint.continue_conversation(
        session_version_id="task-1",
        question="Follow-up",
        login_user=SimpleNamespace(user_id=7),
    )
    assert response.status_code == 200
    assert retry_env["enqueued"][0]["model"] == "936"


async def test_enqueue_failure_restores_failed_status_and_original_model(retry_env):
    retry_env["queue_failure"] = True
    response = await endpoint.continue_conversation(
        session_version_id="task-1",
        question="Original question",
        model="954",
        login_user=SimpleNamespace(user_id=7),
    )
    assert response.status_code != 200
    assert retry_env["record"].status == SessionVersionStatusEnum.FAILED
    assert retry_env["record"].model == "936"
    assert retry_env["enqueued"] == []


@pytest.mark.parametrize(
    "owner,status", [(8, SessionVersionStatusEnum.FAILED), (7, SessionVersionStatusEnum.IN_PROGRESS)]
)
async def test_foreign_or_running_task_cannot_change_model(retry_env, owner, status):
    retry_env["record"].user_id = owner
    retry_env["record"].status = status
    response = await endpoint.continue_conversation(
        session_version_id="task-1",
        question="Original question",
        model="954",
        login_user=SimpleNamespace(user_id=7),
    )
    assert response.status_code != 200
    retry_env["update"].assert_not_awaited()
    assert retry_env["record"].model == "936"
    assert retry_env["enqueued"] == []
