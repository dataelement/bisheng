"""T294: inspection preserves original selections without inventing target metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.services import assistant as assistant_module
from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import AssistantUpdateReq
from bisheng.assistant.application.execution_admission import AssistantExecutionAdmission
from bisheng.assistant.domain.services.reference_extractor import extract_assistant_references
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.database.models.assistant import Assistant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    ReferenceTargetReadFact,
    SourceReferenceReadResult,
    canonical_payload_json,
    payload_digest,
)
from test.knowledge_unification import test_as_bindings as bindings_tests

assistant_business = bindings_tests.assistant_business
assistant_tenant = bindings_tests.assistant_tenant


@pytest.fixture
def view(monkeypatch):
    user = UserPayload(user_id=9, user_name="actor", tenant_id=101, user_role=[])
    row = Assistant(id="assistant-a", tenant_id=101, user_id=8, model_name="7", name="persisted")
    links = [{"knowledge_id": target, "tool_id": 0, "flow_id": ""} for target in (10, 99, 20)]
    payload = canonical_payload_json({"assistant": row.model_dump(mode="json"), "links": links})
    refs = extract_assistant_references(model_name="7", knowledge_ids=(10, 99, 20))
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(101, "assistant", row.id, "current"), refs, "assistant-v1", payload_digest(payload), payload
    )
    states = tuple(
        ReferenceTargetReadFact(
            ref.target,
            "invalid_legacy" if ref.target.target_id == "99" else "valid",
            ref.target.target_type != "model" and ref.target.target_id != "99",
            None if ref.target.target_id == "99" else 101,
        )
        for ref in refs
    )
    prepare = AsyncMock(return_value=SourceReferenceReadResult(snapshot, states, 3, 4))
    monkeypatch.setattr(AssistantExecutionAdmission, "prepare", prepare)
    monkeypatch.setattr(assistant_module.AssistantDao, "aget_one_assistant", AsyncMock(return_value=row))
    rows = [Knowledge(id=target, name=f"actual-{target}", user_id=8, tenant_id=101, type=3) for target in (10, 20)]
    monkeypatch.setattr(assistant_module.KnowledgeDao, "get_list_by_ids", MagicMock(return_value=rows))
    decorate = MagicMock(side_effect=lambda tools, flows, ids: ([], [], [item for item in rows if item.id in ids]))
    monkeypatch.setattr(AssistantService, "get_link_info", decorate)
    monkeypatch.setattr(AssistantService, "get_logo_share_link_async", AsyncMock(return_value="logo"))

    async def visible(identity, *, resource_type, resource_id, action):
        assert identity is user
        return action == "visible" and int(resource_id) != 20 if resource_type != "assistant" else action == "visible"

    check = AsyncMock(side_effect=visible)
    monkeypatch.setattr(assistant_module, "check_business_action", check)
    return user, prepare, decorate, check, rows


async def test_original_missing_and_hidden_ids_survive_with_truthful_reference_states(view):
    user, prepare, _decorate, _check, _rows = view
    result = await AssistantService.get_assistant_info("assistant-a", user)
    assert result.model_name == "7" and result.knowledge_ids == [10, 99, 20]
    assert [item.id for item in result.knowledge_list] == [10]
    states = [item.model_dump() for item in result.reference_states]
    assert {item["target_id"] for item in states} == {"7", "10", "20", "99"}
    assert next(item for item in states if item["target_id"] == "99")["state"] == "invalid_legacy"
    assert next(item for item in states if item["target_id"] == "7")["is_valid"] is False
    assert all(set(item) == {"slot_key", "target_type", "target_id", "state", "is_valid"} for item in states)
    prepare.assert_awaited_once_with(user, "assistant-a", purpose="inspect", inspect_token=None)


@pytest.mark.parametrize(
    "kind,resource_type", [(0, "knowledge_library"), (1, "knowledge_library"), (3, "knowledge_space")]
)
async def test_metadata_visibility_uses_actual_knowledge_kind(view, kind, resource_type):
    user, _prepare, _decorate, check, rows = view
    rows[0].type = kind
    await AssistantService.get_assistant_info("assistant-a", user)
    assert any(
        call.kwargs == {"resource_type": resource_type, "resource_id": 10, "action": "visible"}
        for call in check.await_args_list
    )


async def test_share_object_only_supplies_token_for_actual_owner_revalidation(view):
    user, prepare, _decorate, _check, _rows = view
    share = SimpleNamespace(share_token="actual-token", resource_id="not-the-assistant", meta_data={"flowId": "forged"})
    result = await AssistantService.get_assistant_info("assistant-a", user, share)
    assert result.knowledge_ids == [10, 99, 20]
    prepare.assert_awaited_once_with(user, "assistant-a", purpose="inspect", inspect_token="actual-token")


async def test_missing_reference_coverage_is_not_an_empty_successful_info(view):
    user, prepare, decorate, _check, _rows = view
    prepare.side_effect = ReferenceCoverageNotReadyError()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await AssistantService.get_assistant_info("assistant-a", user)
    decorate.assert_not_called()


async def test_write_responses_preserve_known_ids_but_do_not_claim_to_inspect_states(assistant_business, monkeypatch):
    context = assistant_business
    inspect = AsyncMock(side_effect=AssertionError("write response must not perform post-commit inspection"))
    monkeypatch.setattr(AssistantExecutionAdmission, "prepare", inspect)
    created = await AssistantService.create_assistant(
        context.request, context.user, Assistant(id="assistant-a", name="new", user_id=7)
    )
    assert created.knowledge_ids == [] and created.reference_states is None
    updated = await AssistantService.update_assistant(
        context.request,
        context.user,
        AssistantUpdateReq(id="assistant-a", name="new", model_name="1", knowledge_list=[10], temperature=1),
    )
    assert updated.knowledge_ids == [10] and updated.reference_states is None
    unchanged = await AssistantService.update_assistant(
        context.request, context.user, AssistantUpdateReq(id="assistant-a", name="new", model_name="1", temperature=1)
    )
    assert unchanged.knowledge_ids == [10] and unchanged.reference_states is None
    inspect.assert_not_awaited()
