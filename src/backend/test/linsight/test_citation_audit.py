"""F069 T006: completion-time citation audit on the three completion paths.

Covers AC-01 (audit fields on every completion path), AC-03 (WARNING when
sources were retrieved but nothing was cited), AC-05 (html-only deliverable
counts as uncited, not as no-sources) and AC-26 (no new event types, answer
text untouched).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from bisheng.database.models.message import ChatMessage
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

MARKER = "knowledgesearch_ab12cd34:3"


def _session(*, answer: str = "最终答案") -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="SV-1",
        session_id="chat-1",
        user_id=1,
        question="写报告",
        output_result={"answer": answer},
        tenant_id=1,
        model="deepseek-v4-pro",
    )


def _msg() -> ChatMessage:
    return ChatMessage(id=42, user_id=1, chat_id="chat-1", is_bot=True, category="task", message="最终答案")


def _file(path) -> dict:
    return {"file_path": str(path), "file_name": path.name if hasattr(path, "name") else str(path)}


@pytest.fixture
def completion_task(monkeypatch: pytest.MonkeyPatch):
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    task._state_manager.get_execution_tasks = AsyncMock(return_value=[SimpleNamespace(task_data={})])
    task._complete_session_pseudo_task = AsyncMock()
    task._converge_task_rows_on_completion = AsyncMock()
    task._terminate_unfinished_tasks = AsyncMock()
    task._final_result = SimpleNamespace(answer="最终答案")
    task._last_assistant_text = "最终答案"
    task._partial_salvage = "salvaged body"
    task._partial_error = RuntimeError("loop")
    task.file_dir = None
    task._persist_report_citations = AsyncMock()
    task._citation_scope = SimpleNamespace(seen_keys={"knowledgesearch_ab12cd34:3", "websearch_11223344:1"})
    monkeypatch.setattr(linsight_execute_utils, "read_file_directory", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "get_final_result_file", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "build_fallback_report_file", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "get_all_files_from_session", AsyncMock(return_value=[]))
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock(return_value=_msg()))
    return task


def _set_final_files(monkeypatch, files: list[dict]):
    monkeypatch.setattr(linsight_execute_utils, "get_final_result_file", AsyncMock(return_value=files))


@pytest.fixture
def audit_log():
    """Collect loguru records as (level, message) tuples (caplog does not see loguru)."""
    records: list[tuple[str, str]] = []
    sink_id = logger.add(lambda msg: records.append((msg.record["level"].name, msg.record["message"])), level="INFO")
    try:
        yield records
    finally:
        logger.remove(sink_id)


AUDIT_KEYS = {
    "sources_seen",
    "cited",
    "unknown_handles",
    "bracket_numbers",
    "footnotes_without_defs",
    "scanned_files",
    "html_only",
    "status",
}


# --------------------------------------------------------------------------
# three completion paths all carry the audit
# --------------------------------------------------------------------------
async def test_success_path_writes_audit(completion_task, monkeypatch, tmp_path):
    report = tmp_path / "report.md"
    report.write_text(f"结论。{MARKER}", encoding="utf-8")
    _set_final_files(monkeypatch, [_file(report)])
    session = _session()

    await completion_task._handle_task_success(session)

    audit = session.output_result["citation_audit"]
    assert AUDIT_KEYS <= set(audit)
    assert audit["status"] == "cited"
    assert audit["sources_seen"] == 2
    assert audit["cited"] == 1
    assert audit["scanned_files"] == ["report.md"]
    assert session.output_result["answer"] == "最终答案"


async def test_partial_path_writes_audit(completion_task, monkeypatch):
    session = _session()

    await completion_task._handle_task_partial(session)

    audit = session.output_result["citation_audit"]
    assert AUDIT_KEYS <= set(audit)
    assert audit["status"] == "uncited"
    assert session.output_result["partial"] is True


async def test_direct_answer_path_writes_audit(completion_task, monkeypatch):
    session = _session()

    await completion_task._handle_direct_answer_completion(session)

    audit = session.output_result["citation_audit"]
    assert AUDIT_KEYS <= set(audit)
    assert audit["status"] == "uncited"
    assert session.output_result["answer"] == "最终答案"


# --------------------------------------------------------------------------
# status rules and logging
# --------------------------------------------------------------------------
async def test_uncited_logs_warning_with_model(completion_task, monkeypatch, tmp_path, audit_log):
    report = tmp_path / "report.md"
    report.write_text("正文没有任何标记。据知识库《规则》……", encoding="utf-8")
    _set_final_files(monkeypatch, [_file(report)])
    session = _session()

    await completion_task._handle_task_success(session)

    warnings = [m for level, m in audit_log if level == "WARNING" and "[linsight-citation-audit]" in m]
    assert warnings, "uncited must be surfaced as a WARNING line"
    line = warnings[0]
    assert "status=uncited" in line
    assert "model=deepseek-v4-pro" in line
    assert "sources_seen=2" in line
    assert session.output_result["citation_audit"]["status"] == "uncited"


async def test_no_sources_is_info_not_warning(completion_task, monkeypatch, audit_log):
    completion_task._citation_scope = SimpleNamespace(seen_keys=set())
    session = _session()

    await completion_task._handle_task_success(session)

    audit = session.output_result["citation_audit"]
    assert audit["status"] == "no_sources"
    assert not [m for level, m in audit_log if level == "WARNING" and "[linsight-citation-audit]" in m]
    assert [m for level, m in audit_log if level == "INFO" and "status=no_sources" in m]


async def test_missing_scope_means_no_sources(completion_task):
    completion_task._citation_scope = None
    session = _session()

    await completion_task._handle_task_success(session)

    assert session.output_result["citation_audit"]["status"] == "no_sources"


async def test_html_only_deliverable_is_uncited(completion_task, monkeypatch, tmp_path):
    page = tmp_path / "report.html"
    page.write_text(f"<p>{MARKER}</p>", encoding="utf-8")
    _set_final_files(monkeypatch, [_file(page)])
    session = _session()

    await completion_task._handle_task_success(session)

    audit = session.output_result["citation_audit"]
    assert audit["status"] == "uncited"
    assert audit["html_only"] is True
    assert audit["scanned_files"] == []


async def test_footnotes_and_bracket_numbers_are_counted_not_converted(completion_task, monkeypatch, tmp_path):
    report = tmp_path / "report.md"
    body = "第一句[^1]。第二句[^2]。第三句 [3]。定义行只出现一次：\n[^1]: 知识库·规则\n"
    report.write_text(body, encoding="utf-8")
    _set_final_files(monkeypatch, [_file(report)])
    session = _session()

    await completion_task._handle_task_success(session)

    audit = session.output_result["citation_audit"]
    assert audit["status"] == "uncited"
    assert audit["footnotes_without_defs"] == 1  # two refs, one definition
    assert audit["bracket_numbers"] == 1
    assert report.read_text(encoding="utf-8") == body  # nothing rewritten
    assert session.output_result["answer"] == "最终答案"


async def test_audit_failure_never_blocks_completion(completion_task, monkeypatch):
    completion_task._citation_scope = SimpleNamespace(seen_keys=None)
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.extract_citation_ids_from_text",
        lambda _t: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    session = _session()

    await completion_task._handle_task_success(session)

    assert session.status.value == "completed" if hasattr(session.status, "value") else True
    assert session.output_result["citation_audit"] == {}
    completion_task._persist_report_citations.assert_awaited_once()


# --------------------------------------------------------------------------
# persisted count lands on the audit even when nothing was cited
# --------------------------------------------------------------------------
async def test_persist_records_zero_persisted_on_audit(monkeypatch):
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    session = _session()
    session.output_result = {"answer": "最终答案", "citation_audit": {"status": "uncited"}}
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.persist_linsight_report_citations",
        AsyncMock(return_value=[]),
    )

    await task._persist_report_citations(session, _msg(), [])

    assert session.output_result["citation_audit"]["persisted"] == 0
    assert "citations" not in session.output_result
    # the zero count must be saved too (116 baseline: uncited rows had persisted=None)
    task._state_manager.set_session_version_info.assert_awaited_once_with(session)


# --------------------------------------------------------------------------
# F069 P1: answer handles are converted; audit reports unknown / converted
# --------------------------------------------------------------------------
class _HandleScope(SimpleNamespace):
    def note_conversion(self, converted, unknown):
        self.converted_count = getattr(self, "converted_count", 0) + converted
        for h in unknown:
            self.unknown_handles[h] = self.unknown_handles.get(h, 0) + 1


def _handle_scope(enabled=True):
    return _HandleScope(
        enabled=enabled,
        seen_keys={"knowledgesearch_ab12cd34:3"},
        handles={"S3": "knowledgesearch_ab12cd34:3"},
        unknown_handles={},
        converted_count=0,
    )


async def test_answer_handles_become_markers_before_fallback_report(completion_task, monkeypatch):
    completion_task._citation_scope = _handle_scope()
    completion_task._final_result = SimpleNamespace(answer="结论如下。[S3] 另一句。[S9]")
    completion_task._last_assistant_text = completion_task._final_result.answer
    fallback = AsyncMock(return_value=[])
    monkeypatch.setattr(linsight_execute_utils, "build_fallback_report_file", fallback)
    session = _session()

    await completion_task._handle_task_success(session)

    answer = session.output_result["answer"]
    assert answer.startswith(f"结论如下。{MARKER}")
    assert "[S3]" not in answer and "[S9]" in answer  # unknown stays literal
    assert fallback.await_args.kwargs["answer"] == answer  # the fallback report gets the converted text
    audit = session.output_result["citation_audit"]
    assert audit["status"] == "cited"
    assert audit["unknown_handles"] == ["S9"]
    assert audit["converted"] == 1
    assert audit["handles_enabled"] is True


async def test_answer_untouched_under_verbatim_contract(completion_task):
    completion_task._citation_scope = _handle_scope(enabled=False)
    completion_task._final_result = SimpleNamespace(answer="结论。[S3]")
    completion_task._last_assistant_text = "结论。[S3]"
    session = _session()

    await completion_task._handle_task_success(session)

    assert session.output_result["answer"] == "结论。[S3]"
    assert session.output_result["citation_audit"]["handles_enabled"] is False


async def test_partial_path_converts_answer_too(completion_task):
    completion_task._citation_scope = _handle_scope()
    completion_task._partial_salvage = "抢救出来的正文。[S3]"
    session = _session()

    await completion_task._handle_task_partial(session)

    assert MARKER in session.output_result["answer"]
    assert "[S3]" not in session.output_result["answer"]


async def test_audit_log_line_carries_converted_and_unknown(completion_task, audit_log):
    completion_task._citation_scope = _handle_scope()
    completion_task._final_result = SimpleNamespace(answer="结论。[S3][S42]")
    completion_task._last_assistant_text = completion_task._final_result.answer
    session = _session()

    await completion_task._handle_task_success(session)

    lines = [m for _, m in audit_log if "[linsight-citation-audit]" in m]
    assert lines and "converted=1" in lines[-1] and "unknown_handles=1" in lines[-1] and "handles_enabled=True" in lines[-1]
