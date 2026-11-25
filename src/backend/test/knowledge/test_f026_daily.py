"""F026 T039/T040: daily-chat → task handoff and the task-time frozen range.

Three behaviours are pinned here:

1. **Handoff (T040)** — "turn this conversation into a task" must carry the
   per-space fixed tag references together with the space ids. A legacy client
   that never sent the field keeps the *unrecorded* state instead of being
   silently upgraded to "no tags" or to "the whole space".
2. **Daily tool (T039)** — a model tag condition that cannot be resolved, or
   that matches nothing, must never degrade into an unconditional query of that
   space; the user pinned tag is always enforced and the model cannot widen it.
3. **Task tool (T040)** — the frozen range is read from the task record, never
   widened by model arguments, and a fixed tag reference that is gone is an
   explicit error — with no provider/native query emitted.
4. **Regenerate** reuses the original round's scope; only an explicit "use the
   current materials" switch takes the current picker, and a round with no
   recorded scope is refused explicitly instead of widening to the whole space.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.workstation.domain.schemas.chat import APIChatCompletion, UseKnowledgeBaseParam


def _request(**knowledge_base) -> APIChatCompletion:
    return APIChatCompletion.model_validate(
        {"clientTimestamp": "0", "model": "727", "text": "q", "use_knowledge_base": knowledge_base}
    )


# ---------------------------------------------------------------------------
# 1. daily → task handoff carries the fixed tag selection
# ---------------------------------------------------------------------------


def test_task_handoff_carries_the_fixed_space_tags():
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    submit = _to_linsight_submit(
        _request(knowledge_space_ids=[7], knowledge_space_tag_filters={"7": 11}, organization_knowledge_ids=[3])
    )

    assert submit.knowledge_space_ids == [7]
    assert submit.organization_knowledge_ids == [3]
    assert submit.knowledge_space_tag_filters == {7: 11}
    assert submit.scope_state == "fixed"
    assert submit.tag_ref_for(7) == 11


def test_task_handoff_keeps_a_legacy_round_unrecorded():
    """Old clients omit the field entirely: that is "no record", not "no tag"."""
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    submit = _to_linsight_submit(_request(knowledge_space_ids=[7]))

    assert submit.knowledge_space_ids == [7]
    assert submit.knowledge_space_tag_filters is None
    assert submit.scope_state == "unrecorded"


def test_task_handoff_keeps_an_explicit_empty_selection():
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    submit = _to_linsight_submit(_request(knowledge_space_ids=[7], knowledge_space_tag_filters={}))

    assert submit.knowledge_space_tag_filters == {}
    assert submit.scope_state == "unspecified"


def test_task_handoff_without_any_selection_records_nothing():
    from bisheng.workstation.domain.services.chat_service import _to_linsight_submit

    submit = _to_linsight_submit(APIChatCompletion(clientTimestamp="0", model="727", text="q"))

    assert submit.knowledge_space_ids is None
    assert submit.knowledge_space_tag_filters is None


# ---------------------------------------------------------------------------
# 2. daily tool: an unresolvable / empty tag condition never becomes a query
# ---------------------------------------------------------------------------


def _daily_tool(monkeypatch, kbs, query):
    from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
    from bisheng.workstation.domain.services import chat_service as module

    monkeypatch.setattr(module.WorkStationService, "queryChunksFromDB", query)
    return module._build_knowledge_search_tool(
        kbs,
        SimpleNamespace(user_id=42),
        1000,
        CitationRegistryCollector(),
    )


async def test_daily_tool_skips_a_space_whose_tag_condition_failed(monkeypatch):
    from bisheng.database.models.tag import TagDao
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    query = AsyncMock(return_value=([], [], []))
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_filters", AsyncMock(return_value=[SimpleNamespace(id=40)]))
    monkeypatch.setattr(TagDao, "get_tags_by_resource", MagicMock(side_effect=RuntimeError("tag store down")))
    tool = await _daily_tool(monkeypatch, [{"id": 7, "source": "space"}, {"id": 8, "source": "space"}], query)

    payload = json.loads(
        await tool.ainvoke(
            {
                "knowledge_base_ids": ["7", "8"],
                "query": "Q",
                "filters": {"knowledge_base_filters": [{"knowledge_base_id": "7", "tags": ["财务"]}]},
            }
        )
    )

    # The unparseable space is NOT searched at all; the other space still is.
    params = query.await_args.kwargs["use_knowledge_param"]
    assert params.knowledge_space_ids == [8]
    assert any("<knowledge_base_id>7</knowledge_base_id>" in str(item) for item in payload)
    assert any("标签" in str(item) for item in payload)


async def test_daily_tool_short_circuits_a_zero_match_tag_condition(monkeypatch):
    from bisheng.database.models.tag import TagDao
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    query = AsyncMock(return_value=([], [], []))
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_filters", AsyncMock(return_value=[SimpleNamespace(id=40)]))
    monkeypatch.setattr(TagDao, "get_tags_by_resource", MagicMock(return_value={40: [SimpleNamespace(name="other")]}))
    tool = await _daily_tool(monkeypatch, [{"id": 7, "source": "space"}], query)

    payload = json.loads(
        await tool.ainvoke(
            {
                "knowledge_base_ids": ["7"],
                "query": "Q",
                "filters": {"knowledge_base_filters": [{"knowledge_base_id": "7", "tags": ["财务"]}]},
            }
        )
    )

    # Zero matching files means zero fragments — the space is not queried at all.
    query.assert_not_awaited()
    assert any("标签" in str(item) for item in payload)


async def test_daily_tool_keeps_the_user_pinned_tag_against_model_filters(monkeypatch):
    query = AsyncMock(return_value=([], [], []))
    tool = await _daily_tool(monkeypatch, [{"id": 7, "source": "space", "selected_tag_id": 11}], query)

    await tool.ainvoke(
        {
            "knowledge_base_ids": ["7"],
            "query": "Q",
            "filters": {"knowledge_base_filters": [{"knowledge_base_id": "7", "tags": ["other tag"]}]},
        }
    )

    assert query.await_args.kwargs["use_knowledge_param"].knowledge_space_tag_filters == {7: 11}


# ---------------------------------------------------------------------------
# 3. task tool: frozen range, no widening, explicit error on stale tag
# ---------------------------------------------------------------------------


def _task_tool(**kwargs):
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    return module.SearchKnowledgeBase(**kwargs)


def _stub_providers(hits=None):
    """Stub for the shared ProviderRetrieval the tool must drive (not a second assembly)."""
    return SimpleNamespace(
        route=AsyncMock(return_value=SimpleNamespace(space_id=7, remote_kb_id="kb")),
        retrieve=AsyncMock(return_value=list(hits or [])),
    )


@asynccontextmanager
async def _runtime(providers):
    yield providers


async def test_task_tool_pins_the_frozen_tag_selection(monkeypatch):
    from bisheng.database.models.tag import TagBusinessTypeEnum
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    providers = _stub_providers(
        [
            (
                7,
                Document(
                    page_content="hit",
                    metadata={"knowledge_id": 7, "document_id": 40, "document_name": "f", "source": "f"},
                ),
            )
        ]
    )
    monkeypatch.setattr(module, "request_provider_retrieval", lambda: _runtime(providers))
    monkeypatch.setattr(
        module.KnowledgeDao,
        "query_by_id",
        MagicMock(return_value=SimpleNamespace(id=7, name="space", type=3, model=1)),
    )
    monkeypatch.setattr(
        module.TagDao,
        "get_tag",
        AsyncMock(
            return_value=SimpleNamespace(
                id=11, name="财务", business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE, business_id="7"
            )
        ),
    )
    # This case pins the frozen scope, not citation infrastructure: keep the
    # shared registry/relation stores untouched by a unit test.
    monkeypatch.setattr(module, "annotate_rag_documents_with_citations", lambda documents: documents)
    monkeypatch.setattr(module, "collect_rag_citation_registry_items", lambda documents: [])
    monkeypatch.setattr(module, "cache_citation_registry_items", AsyncMock())
    tool = _task_tool(
        allowed_knowledge_ids={"7"},
        task_scope=module.TaskKnowledgeScope(knowledge_ids=(7,), tag_refs={7: 11}),
        login_user=SimpleNamespace(user_id=42),
    )

    payload = json.loads(await tool._arun(query="q", knowledge_id="7"))

    selection = providers.retrieve.await_args.args[2]
    assert selection.tag_ref_ids == (11,)
    assert payload["状态"] == "成功"


async def test_task_tool_refuses_a_space_outside_the_frozen_range(monkeypatch):
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    tool = _task_tool(
        allowed_knowledge_ids={"7", "8"},
        task_scope=module.TaskKnowledgeScope(knowledge_ids=(7,), tag_refs={}),
        login_user=SimpleNamespace(user_id=42),
    )
    search = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(module.SearchKnowledgeBase, "search_knowledge", search)

    payload = json.loads(await tool._arun(query="q", knowledge_id="8"))

    assert payload["状态"] == "无权限"
    search.assert_not_awaited()


async def test_task_tool_errors_on_a_stale_tag_ref_without_querying(monkeypatch):
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    providers = _stub_providers()
    monkeypatch.setattr(module, "request_provider_retrieval", lambda: _runtime(providers))
    monkeypatch.setattr(
        module.KnowledgeDao,
        "query_by_id",
        MagicMock(return_value=SimpleNamespace(id=7, name="space", type=3, model=1)),
    )
    monkeypatch.setattr(module.TagDao, "get_tag", AsyncMock(return_value=None))
    tool = _task_tool(
        allowed_knowledge_ids={"7"},
        task_scope=module.TaskKnowledgeScope(knowledge_ids=(7,), tag_refs={7: 11}),
        login_user=SimpleNamespace(user_id=42),
    )

    payload = json.loads(await tool._arun(query="q", knowledge_id="7"))

    assert payload["状态"] == "失败"
    assert "标签" in payload["错误信息"]
    providers.retrieve.assert_not_awaited()


async def test_task_tool_errors_when_the_frozen_scope_has_no_identity(monkeypatch):
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    monkeypatch.setattr(
        module.KnowledgeDao,
        "query_by_id",
        MagicMock(return_value=SimpleNamespace(id=7, name="space", type=3, model=1)),
    )
    tool = _task_tool(
        allowed_knowledge_ids={"7"},
        task_scope=module.TaskKnowledgeScope(knowledge_ids=(7,), tag_refs={7: 11}),
    )

    payload = json.loads(await tool._arun(query="q", knowledge_id="7"))

    assert payload["状态"] == "失败"


async def test_task_tool_falls_back_to_the_legacy_chain_when_nothing_is_recorded(monkeypatch):
    """A task created before the field existed keeps the historical behaviour."""
    from bisheng.tool.domain.langchain import linsight_knowledge as module

    tool = _task_tool(
        allowed_knowledge_ids={"7"},
        task_scope=module.TaskKnowledgeScope(recorded=False),
        login_user=SimpleNamespace(user_id=42),
    )
    search = AsyncMock(return_value='{"状态": "成功"}')
    monkeypatch.setattr(module.SearchKnowledgeBase, "search_knowledge", search)

    await tool._arun(query="q", knowledge_id="7")

    search.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. regenerate keeps the original round scope
# ---------------------------------------------------------------------------


def _original_row(extra: dict | None, *, user_id=42, message_id=91):
    from bisheng.database.models.message import ChatMessage

    return ChatMessage(
        id=message_id,
        tenant_id=1,
        user_id=user_id,
        chat_id="c1",
        flow_id="",
        type="over",
        is_bot=False,
        sender="User",
        message=json.dumps({"query": "original", "files": []}),
        extra=json.dumps(extra or {}),
        category="question",
        source=0,
    )


def _regenerate_request(**knowledge_base) -> APIChatCompletion:
    payload = {
        "clientTimestamp": "0",
        "model": "727",
        "text": "original",
        "conversationId": "c1",
        "isRegenerate": True,
        "messageId": "91",
        "use_knowledge_base": knowledge_base,
    }
    return APIChatCompletion.model_validate(payload)


@pytest.fixture
def owned_question_session(monkeypatch):
    from bisheng.database.models.session import MessageSession, MessageSessionDao
    from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService
    from bisheng.workstation.domain.services import chat_service as module

    session = MessageSession(chat_id="c1", flow_type=15, user_id=42, tenant_id=1)
    monkeypatch.setattr(module, "workbench_tenant_id", lambda user: 1)
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(return_value=session))
    monkeypatch.setattr(KnowledgePermissionService, "filter_knowledge_ids_by_action_async", AsyncMock(return_value=[7]))
    monkeypatch.setattr(KnowledgeSpaceTagFilterService, "validate_selection", AsyncMock())


async def test_regenerate_reuses_the_original_round_scope(monkeypatch, owned_question_session):
    from bisheng.workstation.domain.services import chat_service as module

    row = _original_row(
        {
            "knowledge_scope": {
                "version": 1,
                "recorded": True,
                "knowledge_space_ids": [7],
                "organization_knowledge_ids": [],
                "knowledge_space_tag_filters": {"7": 11},
            }
        }
    )
    monkeypatch.setattr(module.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=row))
    # The picker now says tag 12 for the same space: regenerate must ignore it.
    data = _regenerate_request(knowledge_space_ids=[7], knowledge_space_tag_filters={"7": 12})

    selection, scope = await module._resolve_round_knowledge_selection(data, SimpleNamespace(user_id=42))

    assert selection.knowledge_space_ids == [7]
    assert selection.knowledge_space_tag_filters == {7: 11}
    # Persisted scope is JSON-safe: keys are strings, the selection boundary
    # converts them back to ints (see ``_selection_from_scope``).
    assert scope["knowledge_space_tag_filters"] == {"7": 11}


async def test_regenerate_without_a_recorded_scope_is_refused(monkeypatch, owned_question_session):
    from bisheng.workstation.domain.services import chat_service as module

    monkeypatch.setattr(module.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=_original_row({})))
    data = _regenerate_request(knowledge_space_ids=[7])

    with pytest.raises(module.KnowledgeScopeUnavailable) as caught:
        await module._resolve_round_knowledge_selection(data, SimpleNamespace(user_id=42))

    assert caught.value.code == 12048
    assert "资料范围" in str(caught.value)


async def test_regenerate_on_a_legacy_round_is_refused_not_widened(monkeypatch, owned_question_session):
    """A round recorded before the tag field existed has *no* recoverable scope."""
    from bisheng.workstation.domain.services import chat_service as module

    row = _original_row(
        {
            "knowledge_scope": {
                "version": 1,
                "recorded": False,
                "knowledge_space_ids": [7],
                "organization_knowledge_ids": [],
                "knowledge_space_tag_filters": None,
            }
        }
    )
    monkeypatch.setattr(module.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=row))

    with pytest.raises(module.KnowledgeScopeUnavailable):
        await module._resolve_round_knowledge_selection(
            _regenerate_request(knowledge_space_ids=[7]), SimpleNamespace(user_id=42)
        )


async def test_explicit_use_current_materials_takes_the_current_picker(monkeypatch, owned_question_session):
    from bisheng.workstation.domain.services import chat_service as module

    # A legacy question can be replayed with current materials, but its ownership
    # must still be verified.
    lookup = AsyncMock(return_value=_original_row({}))
    monkeypatch.setattr(module.ChatMessageDao, "aget_message_by_id", lookup)
    data = _regenerate_request(knowledge_space_ids=[7], knowledge_space_tag_filters={"7": 12})
    data.useCurrentMaterials = True

    selection, scope = await module._resolve_round_knowledge_selection(data, SimpleNamespace(user_id=42))

    assert selection.knowledge_space_tag_filters == {7: 12}
    assert scope["knowledge_space_tag_filters"] == {"7": 12}
    lookup.assert_awaited_once_with(91)


async def test_regenerate_of_a_foreign_message_is_refused(monkeypatch, owned_question_session):
    from bisheng.workstation.domain.services import chat_service as module

    row = _original_row({"knowledge_scope": {"version": 1, "recorded": True, "knowledge_space_ids": [7]}}, user_id=999)
    monkeypatch.setattr(module.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=row))

    with pytest.raises(module.KnowledgeScopeUnavailable):
        await module._resolve_round_knowledge_selection(
            _regenerate_request(knowledge_space_ids=[7]), SimpleNamespace(user_id=42)
        )


def test_round_scope_is_serialisable_for_the_question_row():
    from bisheng.workstation.domain.services import chat_service as module

    data = APIChatCompletion.model_validate(
        {
            "clientTimestamp": "0",
            "model": "727",
            "text": "q",
            "use_knowledge_base": {"knowledge_space_ids": [7], "knowledge_space_tag_filters": {"7": 11}},
        }
    )
    scope = module._round_knowledge_scope(data)
    assert scope["recorded"] is True
    # Persisted form is JSON-safe (string keys); the retrieval boundary converts
    # them back to ints, which is what the selection assertions above pin.
    assert scope["knowledge_space_tag_filters"] == {"7": 11}
    assert json.loads(json.dumps(scope)) == scope

    legacy = APIChatCompletion.model_validate(
        {"clientTimestamp": "0", "model": "727", "text": "q", "use_knowledge_base": {"knowledge_space_ids": [7]}}
    )
    legacy_scope = module._round_knowledge_scope(legacy)
    assert legacy_scope["recorded"] is False
    assert legacy_scope["knowledge_space_tag_filters"] is None
    assert UseKnowledgeBaseParam(**{"knowledge_space_ids": [7]}).tag_scope_recorded is False
