"""F073 shared task-mode submit core (spec AC-08, AC-32, AC-33, AC-34).

DB / telemetry / attachment promotion / queue are patched; the units under test
are the new ``submit_user_question`` parameters and ``submit_task_turn``'s two
enqueue policies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.linsight import LinsightStartTaskError, LinsightUseUpError
from bisheng.common.errcode.open_api import OpenApiTaskQueueUnavailableError
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.linsight.domain.services import workbench_impl
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.workstation.domain.schemas.chat import APIChatCompletion
from bisheng.workstation.domain.services import task_submit_service


@pytest.fixture
def io(monkeypatch: pytest.MonkeyPatch):
    async def _config_off(self):
        return {}

    monkeypatch.setattr(type(task_submit_service.settings), "aget_all_config", _config_off)
    captured: dict = {"versions": [], "promote_kwargs": None, "telemetry": None}

    async def _insert_session(_cls, data: MessageSession):
        captured["session"] = data
        return data

    async def _insert_version(_cls, data):
        captured["versions"].append(data)
        return data

    async def _promote(files, _uid, **kwargs):
        captured["promote_kwargs"] = kwargs
        return files

    async def _log_event(**kwargs):
        captured["telemetry"] = kwargs["event_data"]

    monkeypatch.setattr(MessageSessionDao, "async_insert_one", classmethod(_insert_session))
    monkeypatch.setattr(LinsightSessionVersionDao, "insert_one", classmethod(_insert_version))
    monkeypatch.setattr(ChatMessageDao, "ainsert_one", classmethod(AsyncMock(side_effect=lambda _c, m: m)))
    monkeypatch.setattr(workbench_impl, "promote_chat_attachments", _promote)
    monkeypatch.setattr(workbench_impl.telemetry_service, "log_event", _log_event)
    return captured


def _user(user_id: int = 7):
    user = MagicMock()
    user.user_id = user_id
    return user


def _service_account_subject():
    return SessionSubject.service_account(
        tenant_id=1, service_account_id=42, resource_owner_user_id=7, external_user_id="emp-1"
    )


async def test_workbench_defaults_are_unchanged(io):
    submit_obj = LinsightQuestionSubmitSchema(question="q", session_id=None)
    await LinsightWorkbenchImpl.submit_user_question(submit_obj, _user())

    assert io["session"].api_subject_type is None
    assert io["session"].name == "New Chat"
    assert io["promote_kwargs"] == {}
    assert io["telemetry"].source == "platform"
    assert io["versions"][-1].api_meta is None


async def test_service_account_subject_hides_the_run_from_the_owner(io):
    subject = _service_account_subject()
    submit_obj = LinsightQuestionSubmitSchema(question="q", session_id=None)
    await LinsightWorkbenchImpl.submit_user_question(
        submit_obj,
        _user(7),
        session_subject=subject,
        api_meta={"channel": "open_api_v2"},
        telemetry_source="api",
        session_name="Contract review",
    )

    session = io["session"]
    assert session.user_id == 7  # compatibility id = resource owner
    assert session.api_subject_type == "service_account"
    assert session.api_subject_id == 42
    assert session.external_user_id == "emp-1"
    assert session.name == "Contract review"
    assert io["promote_kwargs"] == {"storage_partition": subject.storage_partition}
    assert io["telemetry"].source == "api"
    assert io["versions"][-1].api_meta == {"channel": "open_api_v2"}


async def test_delegated_subject_keeps_the_run_on_the_employee(io):
    subject = SessionSubject.natural_person(tenant_id=1, user_id=9)
    submit_obj = LinsightQuestionSubmitSchema(question="q", session_id=None)
    await LinsightWorkbenchImpl.submit_user_question(submit_obj, _user(9), session_subject=subject)

    assert io["session"].user_id == 9
    assert io["session"].api_subject_type is None


def _request() -> APIChatCompletion:
    return APIChatCompletion(clientTimestamp="t", model="7", text="do it", task_mode=True)


async def test_strict_enqueue_failure_fails_the_version_and_raises_26068(io, monkeypatch):
    persisted = AsyncMock()
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", persisted)
    monkeypatch.setattr(
        linsight_execute_utils, "enqueue_session_for_execution", AsyncMock(side_effect=RuntimeError("redis down"))
    )

    with pytest.raises(OpenApiTaskQueueUnavailableError) as exc_info:
        await task_submit_service.submit_task_turn(_request(), _user(), strict_enqueue=True)

    assert (exc_info.value.code, exc_info.value.http_status) == (26068, 503)
    version = io["versions"][-1]
    assert version.status == SessionVersionStatusEnum.FAILED
    assert version.output_result["error_type"] == "service_unavailable"
    # the task-turn row is written before enqueue and again with the failure
    assert persisted.await_count == 2


async def test_task_turn_is_persisted_before_enqueue(io, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        linsight_execute_utils, "persist_task_turn_message", AsyncMock(side_effect=lambda *_: order.append("persist"))
    )
    monkeypatch.setattr(
        linsight_execute_utils,
        "enqueue_session_for_execution",
        AsyncMock(side_effect=lambda *_: order.append("enqueue")),
    )

    await task_submit_service.submit_task_turn(_request(), _user(), strict_enqueue=True)

    assert order == ["persist", "enqueue"]


async def test_invite_switch_rejects_a_submit_with_no_remaining_uses(io, monkeypatch):
    async def _config_on(self):
        return {"linsight_invitation_code": True}

    monkeypatch.setattr(type(task_submit_service.settings), "aget_all_config", _config_on)
    monkeypatch.setattr(
        task_submit_service.InviteCodeService,
        "use_invite_code",
        AsyncMock(return_value=False),
    )

    with pytest.raises(LinsightUseUpError):
        await task_submit_service.submit_task_turn(_request(), _user())

    assert io["versions"] == []


async def test_run_id_travels_in_the_queue_item_only_when_given(io, monkeypatch):
    """F004: the worker claims the conversation under the id the send entry reserved it with."""
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    enqueue = AsyncMock()
    monkeypatch.setattr(linsight_execute_utils, "enqueue_session_for_execution", enqueue)

    _session, version = await task_submit_service.submit_task_turn(_request(), _user(), run_id="run-reserved")
    enqueue.assert_awaited_once_with(version, run_id="run-reserved")

    # Every other caller (Open API, legacy send) enqueues exactly as before.
    enqueue.reset_mock()
    _session, version = await task_submit_service.submit_task_turn(_request(), _user())
    enqueue.assert_awaited_once_with(version)


async def test_queue_item_of_a_reserved_run_carries_the_run_id(monkeypatch):
    import bisheng.linsight.worker as worker_mod

    put = AsyncMock()

    class _Queue:
        def __init__(self, *args, **kwargs):
            self.put = put

    monkeypatch.setattr(worker_mod, "LinsightQueue", _Queue)
    monkeypatch.setattr(linsight_execute_utils, "get_redis_client", AsyncMock(return_value=object()))
    version = MagicMock()
    version.id, version.tenant_id = "sv-1", 3

    await linsight_execute_utils.enqueue_session_for_execution(version, run_id="run-reserved")
    await linsight_execute_utils.enqueue_session_for_execution(version)

    reserved, legacy = (call.kwargs["data"] for call in put.await_args_list)
    assert reserved == worker_mod.encode_queue_item("sv-1", tenant_id=3, run_id="run-reserved")
    assert reserved["run_id"] == "run-reserved"
    assert "run_id" not in legacy


async def test_relay_turn_writes_no_second_question_row(io, monkeypatch):
    """F004 relay run: the question rows exist since the messages joined the inbox."""
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(linsight_execute_utils, "enqueue_session_for_execution", AsyncMock())
    user_turn = AsyncMock()
    monkeypatch.setattr(linsight_execute_utils, "persist_task_user_turn", user_turn)

    await task_submit_service.submit_task_turn(_request(), _user(), persist_user_turn=False)
    user_turn.assert_not_awaited()
    assert len(io["versions"]) == 1

    await task_submit_service.submit_task_turn(_request(), _user())
    user_turn.assert_awaited_once()


async def test_reserved_run_enqueue_failure_fails_the_version_and_raises(io, monkeypatch):
    """F004: the conversation is reserved for this run with the 4-hour queued lease.

    A browser start-execute carries no run id and would wait behind that
    reservation, so the failure is raised and the caller frees the conversation.
    """
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(
        linsight_execute_utils, "enqueue_session_for_execution", AsyncMock(side_effect=RuntimeError("redis down"))
    )

    with pytest.raises(LinsightStartTaskError):
        await task_submit_service.submit_task_turn(_request(), _user(), run_id="run-reserved")

    version = io["versions"][-1]
    assert version.status == SessionVersionStatusEnum.FAILED
    assert version.output_result["error_type"] == "service_unavailable"


async def test_reserved_run_id_is_stored_on_the_run_record_before_enqueue(io, monkeypatch):
    """F004: a run still in the worker queue is found by its run id (stop, answer)."""
    from bisheng.linsight.domain.task_exec import RUN_ID_META_KEY

    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    seen: dict = {}

    async def enqueue(version, **kwargs):
        seen["meta_at_enqueue"] = dict(version.api_meta or {})

    monkeypatch.setattr(linsight_execute_utils, "enqueue_session_for_execution", enqueue)

    _session, version = await task_submit_service.submit_task_turn(_request(), _user(), run_id="run-reserved")
    assert seen["meta_at_enqueue"][RUN_ID_META_KEY] == "run-reserved"
    assert io["versions"][-1].api_meta[RUN_ID_META_KEY] == "run-reserved"

    # Every other caller leaves the record as it was.
    _session, plain = await task_submit_service.submit_task_turn(_request(), _user())
    assert not plain.api_meta
