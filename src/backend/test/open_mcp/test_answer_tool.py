import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_mcp import answer as answer_service
from bisheng.open_mcp.contracts import KnowledgeAnswerInput
from bisheng.open_mcp.registry import TOOL_REGISTRY, list_tools_for
from bisheng.open_mcp.tools import answer as answer_tools


def _principal(*, actor_kind):
    natural_person = actor_kind == "natural_person"
    return OpenApiPrincipal(
        credential_id=1,
        actor_kind=actor_kind,
        actor_id=2,
        actor_name="caller",
        tenant_id=3,
        resource_owner_user_id=2,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="user" if natural_person else "service_account",
        authorization_subject_id=2,
        effective_user_id=2 if natural_person else None,
    )


def test_answer_model_id_falls_back_to_server_default(monkeypatch):
    monkeypatch.setattr(answer_service.settings.open_mcp, "answer_default_model_id", 42)

    assert answer_service.resolve_model_id(None) == 42
    assert answer_service.resolve_model_id(7) == 7


def test_answer_without_any_model_is_a_clear_argument_error(monkeypatch):
    monkeypatch.setattr(answer_service.settings.open_mcp, "answer_default_model_id", None)

    with pytest.raises(HTTPException) as exc:
        answer_service.resolve_model_id(None)

    assert exc.value.status_code == 400
    assert "answer_default_model_id" in exc.value.detail


def test_answer_input_limits():
    with pytest.raises(ValidationError):
        KnowledgeAnswerInput(query="q", knowledge_base_ids=[])
    with pytest.raises(ValidationError):
        KnowledgeAnswerInput(query="q", knowledge_base_ids=[1], top_k=51)
    with pytest.raises(ValidationError):
        KnowledgeAnswerInput(query="q", knowledge_base_ids=[1], user_id=3)


def test_answer_is_read_scope_and_hidden_from_personal_keys():
    tool = TOOL_REGISTRY["bisheng_knowledge_answer"]
    assert tool.scope == "knowledge:read"
    assert tool.allow_pat is False
    assert "bisheng_knowledge_answer" not in {t.name for t in list_tools_for(_principal(actor_kind="natural_person"))}
    assert "bisheng_knowledge_answer" in {t.name for t in list_tools_for(_principal(actor_kind="service_account"))}


@pytest.mark.asyncio
async def test_answer_handler_maps_declared_fields_only(monkeypatch):
    async def fake_answer(*, command):
        assert command.query == "报销期限"
        return {
            "answer": "30 天内",
            "has_context": True,
            "model_id": 42,
            "references": [{"knowledge_id": 1, "document_id": 2, "document_name": "制度.docx", "internal": "x"}],
            "debug": "x",
        }

    monkeypatch.setattr(answer_service, "answer_knowledge", fake_answer)

    result = await answer_tools.knowledge_answer(KnowledgeAnswerInput(query="报销期限", knowledge_base_ids=[1]))

    dumped = result.model_dump()
    assert dumped["answer"] == "30 天内"
    assert "debug" not in dumped
    assert "internal" not in dumped["references"][0]
