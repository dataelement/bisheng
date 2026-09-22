"""Portal routing never falls back to pre-retrieval permission expansion."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf


@pytest.mark.parametrize(
    "case",
    [
        "default_off",
        "unlisted",
        "missing_route",
        "disabled_route",
        "storage_off",
        "mixed",
        "empty",
        "nonportal",
        "success",
        "plain_chat",
        "uploaded_file",
        "slow_uploaded_file",
        "document_deadline",
        "retrieval_after_document_deadline",
    ],
)
async def test_portal_requires_shared_strategy_and_errors_do_not_reach_model(monkeypatch, case):
    from bisheng.common.services.config_service import settings
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.rag import shared_space_storage as storage
    from bisheng.workstation.domain.services import chat_service

    config = KnowledgeRetrievalRuntimeConf()
    document_cases = {"uploaded_file", "slow_uploaded_file", "document_deadline", "retrieval_after_document_deadline"}
    if case in document_cases - {"uploaded_file"}:
        config.total_timeout_seconds = 0.05
        config.portal_qa_request_timeout_seconds = 0.08 if case == "document_deadline" else 2
        config.portal_qa_heartbeat_seconds = 0.005
    if case == "unlisted":
        config.portal_unified_qa_enabled = True
        config.portal_unified_qa_tenant_ids = [999]
        config.portal_unified_qa_user_ids = [999]
    monkeypatch.setattr(settings, "async_get_knowledge", AsyncMock(return_value=SimpleNamespace(retrieval=config)))
    monkeypatch.setattr(chat_service.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(0, None)))
    succeeds = case in {"success", "plain_chat", "uploaded_file", "slow_uploaded_file"}

    async def answer(messages):
        yield SimpleNamespace(content="answer", additional_kwargs={})

    llm = SimpleNamespace(
        astream=Mock(side_effect=answer if succeeds else AssertionError("model must not run after retrieval failure"))
    )
    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(
            return_value=(
                SimpleNamespace(maxTokens=1000, systemPrompt=""),
                SimpleNamespace(chat_id="chat-test", user_id=1, name="existing"),
                SimpleNamespace(id=1),
                llm,
                SimpleNamespace(displayName="model"),
                False,
            )
        ),
    )
    selected = [{"id": 10, "type": KnowledgeTypeEnum.SPACE.value}]
    if case == "mixed":
        selected.append({"id": 20, "type": KnowledgeTypeEnum.NORMAL.value})
    elif case in {"empty", "plain_chat"} | document_cases:
        selected = []
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=selected))
    monkeypatch.setattr(
        storage,
        "aresolve_space_shared_routing",
        AsyncMock(
            return_value=(None if case == "missing_route" else SimpleNamespace(shared_enabled=case != "disabled_route"))
        ),
    )
    old_scope = AsyncMock(return_value=None)
    old_retrieve = AsyncMock(side_effect=RuntimeError("legacy stop"))
    unified = AsyncMock(side_effect=RuntimeError("new retrieval failed"))
    monkeypatch.setattr(chat_service, "_resolve_user_kb_file_filters", old_scope)
    monkeypatch.setattr(chat_service, "_retrieve_selected_knowledge_context", old_retrieve)
    if case == "success":
        from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalResult

        unified.side_effect = None
        unified.return_value = ("authorized context", QaRetrievalResult())
    if case not in {"plain_chat"} | document_cases:
        monkeypatch.setattr(chat_service, "_unified_portal_context", unified)
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    timeout_log = Mock()
    monkeypatch.setattr(chat_service.logger, "warning", timeout_log)
    if case in document_cases:
        monkeypatch.setattr(chat_service, "async_file_download", AsyncMock(return_value=("/tmp/attachment.pdf", "attachment.pdf")))
        async def parse_pdf(**kwargs):
            if case != "uploaded_file":
                await asyncio.sleep(0.15)
            return "合同约定交货日期为十月一日。"

        monkeypatch.setattr(chat_service, "get_file_content", AsyncMock(side_effect=parse_pdf))
        from bisheng.knowledge.domain.services import portal_qa_retrieval_service

        monkeypatch.setattr(portal_qa_retrieval_service, "retrieve_portal_qa", AsyncMock(side_effect=AssertionError("附件独立问答不得召回知识库")))
        if case == "retrieval_after_document_deadline":
            from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan

            monkeypatch.setattr(portal_qa_retrieval_service, "build_portal_qa_plan", AsyncMock(return_value=QaRetrievalPlan((10,))))

            async def slow_retrieval(**kwargs):
                await asyncio.Event().wait()

            monkeypatch.setattr(portal_qa_retrieval_service, "retrieve_portal_qa", AsyncMock(side_effect=slow_retrieval))
        chat_service._agent_initialize_chat.return_value[4].visual = False
    else:
        monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=1000))
    monkeypatch.setattr(chat_service, "WorkStationService", SimpleNamespace(get_chat_history=AsyncMock(return_value=[])))
    persist = AsyncMock(return_value=SimpleNamespace(id=2))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", persist)
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock())

    response = await chat_service.stream_chat_completion(
        None,
        APIChatCompletion(
            clientTimestamp="2026-09-17T13:40:00", model="1", text="question",
            **({
                "files": [{"filepath": "/tmp/attachment.pdf", "filename": "attachment.pdf"}],
                "use_knowledge_base": {"knowledge_space_ids": [], "knowledge_scope": {"mode": "none"}},
            } if case in document_cases else {}),
        ),
        SimpleNamespace(user_id=1, tenant_id=7),
        portal_context=case != "nonportal",
    )
    body = "".join([chunk async for chunk in response.body_iterator])
    if succeeds:
        assert "event: error" not in body
        assert '"final": true' in body
        llm.astream.assert_called_once()
        persist.assert_awaited_once()
        old_scope.assert_not_awaited()
        old_retrieve.assert_not_awaited()
        content = llm.astream.call_args.args[0][-1].content
        assert ("authorized context" in content) == (case == "success")
        if case in {"plain_chat"} | document_cases:
            assert "retrieved_knowledge_context" not in content
            storage.aresolve_space_shared_routing.assert_not_awaited()
        if case in document_cases:
            assert "合同约定交货日期为十月一日" in content
            chat_service.get_file_content.assert_awaited_once()
            portal_qa_retrieval_service.retrieve_portal_qa.assert_not_awaited()
        return
    assert "event: error" in body
    llm.astream.assert_not_called()
    if case == "document_deadline":
        assert '"kind": "document"' in body
        portal_qa_retrieval_service.retrieve_portal_qa.assert_not_awaited()
        timeout_log.assert_called_once()
        assert timeout_log.call_args.args[1] == "document"
        return
    if case == "retrieval_after_document_deadline":
        assert '"kind": "retrieval"' in body
        portal_qa_retrieval_service.retrieve_portal_qa.assert_awaited_once()
        return
    if case == "nonportal":
        old_scope.assert_awaited_once()
        old_retrieve.assert_awaited_once()
        unified.assert_not_awaited()
    else:
        old_scope.assert_not_awaited()
        old_retrieve.assert_not_awaited()
        assert unified.await_count == (1 if case in {"default_off", "unlisted", "empty", "disabled_route", "storage_off"} else 0)
