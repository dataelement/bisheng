"""F047: task completion persists only report-cited sources onto the task message."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.message import ChatMessage
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask


def _session(*, svid: str = "SV-1", chat_id: str = "chat-1", answer: str = "最终答案"):
    return LinsightSessionVersion(
        id=svid,
        session_id=chat_id,
        user_id=1,
        question="写报告",
        output_result={"answer": answer},
        tenant_id=1,
    )


def _msg(message_id: int = 42) -> ChatMessage:
    return ChatMessage(
        id=message_id,
        user_id=1,
        chat_id="chat-1",
        is_bot=True,
        category="task",
        message="最终答案",
    )


@pytest.fixture
def completion_task(monkeypatch: pytest.MonkeyPatch):
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    task._state_manager.get_execution_tasks = AsyncMock(return_value=[])
    task._complete_session_pseudo_task = AsyncMock()
    task._converge_task_rows_on_completion = AsyncMock()
    task._terminate_unfinished_tasks = AsyncMock()
    task._final_result = SimpleNamespace(answer="最终答案")
    task._last_assistant_text = "最终答案"
    task._partial_salvage = "salvaged body"
    task._partial_error = RuntimeError("loop")
    task.file_dir = None
    task._persist_report_citations = AsyncMock()
    msg = _msg()
    monkeypatch.setattr(linsight_execute_utils, "read_file_directory", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "get_final_result_file", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "build_fallback_report_file", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "get_all_files_from_session", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock(return_value=msg))
    return task, msg


async def test_success_persists_citations_after_task_message(completion_task):
    task, msg = completion_task
    await task._handle_task_success(_session())
    task._persist_report_citations.assert_awaited_once()
    args = task._persist_report_citations.await_args.args
    assert args[1] is msg


async def test_direct_answer_persists_citations(completion_task):
    task, msg = completion_task
    await task._handle_direct_answer_completion(_session())
    task._persist_report_citations.assert_awaited_once()
    assert task._persist_report_citations.await_args.args[1] is msg


async def test_partial_persists_citations(completion_task):
    task, msg = completion_task
    await task._handle_task_partial(_session())
    task._persist_report_citations.assert_awaited_once()
    assert task._persist_report_citations.await_args.args[1] is msg


async def test_failure_does_not_persist_citations(completion_task, monkeypatch: pytest.MonkeyPatch):
    task, _msg = completion_task
    from bisheng.linsight.domain import task_exec as te

    monkeypatch.setattr(
        te,
        "settings",
        SimpleNamespace(aget_all_config=AsyncMock(return_value={})),
    )
    await task._handle_task_failure(_session(), "boom")
    task._persist_report_citations.assert_not_awaited()


async def test_persist_report_citations_reads_md_and_calls_helper(tmp_path, monkeypatch: pytest.MonkeyPatch):
    report = tmp_path / "report.md"
    report.write_text("正文。cited", encoding="utf-8")
    captured = {}

    async def fake_persist(*, message_id, chat_id, report_texts):
        captured["message_id"] = message_id
        captured["chat_id"] = chat_id
        captured["report_texts"] = report_texts
        return []

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.persist_linsight_report_citations",
        fake_persist,
    )
    task = LinsightWorkflowTask()
    session = _session(answer="口播摘要")
    await task._persist_report_citations(
        session,
        _msg(7),
        [{"file_path": str(report)}, {"file_path": str(tmp_path / "missing.md")}],
    )
    assert captured["message_id"] == 7
    assert captured["chat_id"] == "chat-1"
    assert "口播摘要" in captured["report_texts"]
    assert "正文。cited" in captured["report_texts"]


async def test_persist_report_citations_swallows_helper_errors(monkeypatch: pytest.MonkeyPatch):
    async def boom(**kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.persist_linsight_report_citations",
        boom,
    )
    task = LinsightWorkflowTask()
    await task._persist_report_citations(_session(), _msg(), [])


async def test_persist_report_citations_attaches_sources_to_output_result(monkeypatch: pytest.MonkeyPatch):
    from bisheng.citation.domain.schemas.citation_schema import (
        CitationRegistryItemSchema,
        CitationType,
        RagCitationItemSchema,
        RagCitationPayloadSchema,
    )

    item = CitationRegistryItemSchema(
        citationId="knowledgesearch_aaa",
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            knowledgeName="政策文档",
            documentId=11,
            documentName="政策.pdf",
            previewUrl="https://minio/preview",
            items=[RagCitationItemSchema(itemId="1", chunkId="c1", content="…", page=3)],
        ),
    )

    async def fake_persist(*, message_id, chat_id, report_texts):
        assert message_id == 7
        assert chat_id == "chat-1"
        return [item]

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.persist_linsight_report_citations",
        fake_persist,
    )
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    session = _session(answer="口播摘要")
    original_output = session.output_result
    await task._persist_report_citations(session, _msg(7), [])

    assert session.output_result is not original_output
    citations = session.output_result["citations"]
    assert citations[0]["citationId"] == "knowledgesearch_aaa"
    assert citations[0]["sourcePayload"]["documentName"] == "政策.pdf"
    assert "previewUrl" not in citations[0]["sourcePayload"]
    task._state_manager.set_session_version_info.assert_awaited_once_with(session)


async def test_persist_report_citations_copies_marked_paragraphs_into_answer(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from bisheng.citation.domain.schemas.citation_schema import (
        CitationRegistryItemSchema,
        CitationType,
        RagCitationItemSchema,
        RagCitationPayloadSchema,
    )
    from bisheng.citation.domain.services.citation_prompt_helper import (
        CITATION_END_MARKER,
        CITATION_START_MARKER,
    )

    marker = f"{CITATION_START_MARKER}knowledgesearch_aaa:10{CITATION_END_MARKER}"
    report = tmp_path / "report.md"
    report.write_text(f"背景无引用。\n\n补测 20/20{marker}\n", encoding="utf-8")
    item = CitationRegistryItemSchema(
        citationId="knowledgesearch_aaa",
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            documentId=11,
            documentName="政策.pdf",
            items=[RagCitationItemSchema(itemId="10", chunkId="c1", content="…", page=3)],
        ),
    )

    async def fake_persist(*, message_id, chat_id, report_texts):
        return [item]

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.persist_linsight_report_citations",
        fake_persist,
    )
    persist_message = AsyncMock()
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", persist_message)
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    session = _session(answer="已梳理近期问题。")
    original_output = session.output_result
    await task._persist_report_citations(session, _msg(7), [{"file_path": str(report)}])
    persist_message.assert_awaited_once_with(session)

    assert session.output_result is not original_output
    answer = session.output_result["answer"]
    assert answer.startswith("已梳理近期问题。")
    assert "补测 20/20" in answer
    assert "背景无引用" not in answer
    assert marker in answer
