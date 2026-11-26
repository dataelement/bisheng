"""Saved invalid selections explain failed saves without opening a write path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.assistant.application import reference_validation as module
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    ReferenceTargetReadFact,
    SourceReferenceReadResult,
    canonical_payload_json,
    payload_digest,
)


@pytest.fixture
def saved_selection(monkeypatch):
    refs = tuple(ReferenceSpec("knowledge_list", TargetKey("knowledge_space", str(i))) for i in (4387, 4402, 4409))
    payload = canonical_payload_json({"assistant": {"id": "assistant-a"}, "links": []})
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(1, "assistant", "assistant-a", "current"), refs, "v1", payload_digest(payload), payload
    )
    states = tuple(
        ReferenceTargetReadFact(
            ref.target,
            "invalid_missing" if ref.target.target_id == "4402" else "valid",
            ref.target.target_id != "4402",
            1,
        )
        for ref in snapshot.references
    )
    result = SourceReferenceReadResult(snapshot, states)
    refusal = NotFoundError.http_exception()
    boundary = AsyncMock(side_effect=refusal)
    inspect = AsyncMock(return_value=result)
    permission = AsyncMock()
    monkeypatch.setattr(module.AssistantBoundaryService, "authorize_knowledge_bindings", boundary)
    monkeypatch.setattr(module.AssistantExecutionAdmission, "prepare", inspect)
    monkeypatch.setattr(module, "require_business_action", permission)
    return SimpleNamespace(
        user=object(), boundary=boundary, inspect=inspect, permission=permission, result=result, refusal=refusal
    )


async def test_saved_missing_knowledge_identifies_exact_target(saved_selection):
    h = saved_selection
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", [4387, 4402, 4409])
    assert caught.value.code == 10996
    assert caught.value.kwargs == {
        "reason": "reference_target_invalid",
        "reference_errors": [{"resource_type": "knowledge_space", "target_id": "4402", "state": "invalid_missing"}],
    }
    h.permission.assert_awaited_once_with(h.user, resource_type="assistant", resource_id="assistant-a", action="edit")
    h.inspect.assert_awaited_once_with(h.user, "assistant-a", purpose="inspect")
    assert caught.value.__cause__ is h.refusal


@pytest.mark.parametrize("state", ["invalid_deleted", "deleting", "invalid_scope"])
async def test_saved_target_retains_exact_owner_cause(saved_selection, state):
    h = saved_selection
    facts = tuple(
        ReferenceTargetReadFact(fact.key, state, False, 1) if fact.key.target_id == "4402" else fact
        for fact in h.result.target_states
    )
    h.inspect.return_value = SourceReferenceReadResult(h.result.snapshot, facts)
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", [4402])
    assert caught.value.kwargs["reference_errors"][0]["state"] == state


async def test_valid_binding_uses_original_authorization_without_extra_inspection(saved_selection):
    h = saved_selection
    h.boundary.side_effect = None
    await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", [4387])
    h.boundary.assert_awaited_once_with(h.user, [4387])
    h.inspect.assert_not_awaited()
    h.permission.assert_not_awaited()


@pytest.mark.parametrize("error", [HTTPException(403), HTTPException(500), UnAuthorizedError()])
async def test_other_refusals_are_preserved_without_inspection(saved_selection, error):
    h = saved_selection
    h.boundary.side_effect = error
    with pytest.raises(type(error)) as caught:
        await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", [4402])
    assert caught.value is error
    h.inspect.assert_not_awaited()
    h.permission.assert_not_awaited()


async def test_non_editor_cannot_inspect_saved_targets(saved_selection):
    h = saved_selection
    h.permission.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", [4402])
    h.inspect.assert_not_awaited()


@pytest.mark.parametrize("ids", [[999], [4387, 999]])
async def test_unknown_new_ids_keep_original_non_disclosing_response(saved_selection, ids):
    h = saved_selection
    with pytest.raises(HTTPException) as caught:
        await module.authorize_assistant_knowledge_bindings(h.user, "assistant-a", ids)
    assert caught.value is h.refusal


async def test_failed_assistant_save_never_opens_business_write_session(saved_selection, monkeypatch):
    from bisheng.api.services import assistant as service

    database = Mock(side_effect=AssertionError("must not open a write transaction"))
    monkeypatch.setattr(service, "get_async_db_session", database)
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await service.AssistantService._persist_assistant_changes(
            "assistant-a", saved_selection.user, changes={"status": 2}, knowledge_ids=[4387, 4402, 4409]
        )
    assert caught.value.kwargs["reference_errors"][0]["target_id"] == "4402"
    database.assert_not_called()
