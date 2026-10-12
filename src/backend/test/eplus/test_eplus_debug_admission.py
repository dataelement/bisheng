"""Debug admission must not turn a test user into a scope bypass."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.eplus.domain.schemas.debug import DebugContext, DebugHistoryTurn, DebugRunRequest
from bisheng.eplus.domain.services.debug_admission import DebugAdmissionService


def snapshot():
    return DebugContext(
        tenant_id=7,
        operator_id=1,
        test_user_id=2,
        test_user_name="Tester",
        external_user_id="",
        assistant=SimpleNamespace(id="a", tenant_id=7, is_delete=0, status=2, name="A", model_name="30"),
        robot_scope=AssistantRobotScope(bot_config_id=3, space_ids=(11,), scope_version=1),
        bot_id="bot",
        spaces=({"id": 11, "name": "Dept"},),
    )


class Reader:
    def __init__(self, value):
        self.value = value

    async def load_context(self, assistant_id, test_user_id, operator_id):
        return self.value


class Authorization:
    async def require_login(self, operator):
        if operator.user_id <= 0 or operator.tenant_id != 7:
            raise HTTPException(403)

    async def can_switch_user(self, operator):
        return operator.admin


def operator(**kwargs):
    return SimpleNamespace(user_id=1, tenant_id=7, admin=True, edit=True, **kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        {"space_ids": [999]},
        {"model_id": 99},
        {"query": "   "},
        {"test_user_id": 0},
        {"history": [{"question": "hi", "answer": "ok", "role": "system"}]},
        {"history": [{"question": "hi", "answer": "x" * 16001}]},
    ],
)
def test_request_rejects_scope_override_and_invalid_content(payload):
    with pytest.raises(ValidationError):
        DebugRunRequest.model_validate({"query": "hi", "test_user_id": 2, **payload})


def test_history_limits_and_question_normalization():
    assert DebugRunRequest(query=" hi ", test_user_id=2).query == "hi"
    with pytest.raises(ValidationError):
        DebugRunRequest(query="hi", test_user_id=2, history=[DebugHistoryTurn(question="hi", answer="ok")] * 21)
    with pytest.raises(ValidationError):
        DebugRunRequest(query="hi", test_user_id=2, history=[DebugHistoryTurn(question="hi", answer="x" * 16000)] * 5)


async def test_logged_in_user_without_edit_can_debug_as_self():
    service = DebugAdmissionService(Authorization(), Reader(replace(snapshot(), test_user_id=1)))
    value = await service.context(SimpleNamespace(user_id=1, tenant_id=7, admin=False, edit=False), "a", 1)
    assert value.public_view()["test_user_id"] == 1
    assert value.public_view()["can_switch_user"] is False


async def test_non_admin_cannot_impersonate_another_user():
    service = DebugAdmissionService(Authorization(), Reader(snapshot()))
    with pytest.raises(HTTPException) as exc:
        await service.context(SimpleNamespace(user_id=1, tenant_id=7, admin=False, edit=False), "a", 2)
    assert exc.value.status_code == 403


async def test_admin_without_edit_can_switch_test_user():
    service = DebugAdmissionService(Authorization(), Reader(snapshot()))
    value = await service.context(SimpleNamespace(user_id=1, tenant_id=7, admin=True, edit=False), "a", 2)
    assert value.public_view()["test_user_id"] == 2
    assert value.public_view()["can_switch_user"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": 8},
        {"test_user_id": 999},
        {"operator_id": 99},
        {"robot_scope": AssistantRobotScope(bot_config_id=3, space_ids=(), scope_version=1)},
        {"spaces": ()},
    ],
)
async def test_invalid_snapshots_fail_closed(change):
    service = DebugAdmissionService(Authorization(), Reader(replace(snapshot(), **change)))
    with pytest.raises(HTTPException):
        await service.context(operator(), "a", 2)


async def test_fresh_binding_and_safe_public_view():
    reader = Reader(snapshot())
    service = DebugAdmissionService(Authorization(), reader)
    first = await service.context(operator(), "a", 2)
    assert first.public_view()["space_ids"] == [11]
    reader.value = replace(
        snapshot(), robot_scope=AssistantRobotScope(3, (12,), 2), spaces=({"id": 12, "name": "Other"},)
    )
    second = await service.context(operator(), "a", 2)
    assert second.public_view()["space_ids"] == [12]
    assert "assistant" not in second.public_view()
    assert "secret" not in str(second.public_view()).lower()
