# ruff: noqa: E402

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from loguru import logger

from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactClaimResult,
    PdfArtifactClaimState,
    PdfArtifactCompleteResult,
)
from bisheng.knowledge.pdf.converter import (
    ConversionContext,
    ConversionResult,
    PdfConversionError,
)

_BACKEND = Path(__file__).resolve().parents[3]
sys.modules["bisheng.worker"].__path__ = [str(_BACKEND / "bisheng/worker")]
sys.modules["bisheng.worker.knowledge"].__path__ = [str(_BACKEND / "bisheng/worker/knowledge")]

from bisheng.worker.knowledge.pdf_artifact_worker import (
    PdfArtifactProcessor,
    PdfArtifactProcessOutcome,
    PdfArtifactSourceChangedError,
    PdfArtifactTaskFailureAction,
    PdfArtifactTaskFailureDecision,
    PdfArtifactTenantMismatchError,
    _process_pdf_artifact_attempt,
    record_pdf_artifact_task_failure,
)


def _pdf_bytes() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "valid pdf")
    content = document.tobytes()
    document.close()
    return content


def _artifact(*, source_name="original/101.docx", source_md5="m1"):
    return KnowledgeFilePdfArtifact(
        id=1,
        tenant_id=7,
        knowledge_file_id=101,
        source_object_name=source_name,
        source_md5=source_md5,
        generation=2,
        status=KnowledgeFilePdfArtifactStatus.PROCESSING.value,
        attempt_count=1,
    )


def _file(*, file_name="report.docx", object_name="original/101.docx", md5="m1", metadata=None):
    return KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=9,
        file_name=file_name,
        file_type=FileType.FILE.value,
        object_name=object_name,
        md5=md5,
        user_metadata=metadata or {},
    )


class _Repository:
    def __init__(self, artifact=None, *, completed=True) -> None:
        self.artifact = artifact or _artifact()
        self.claim_state = PdfArtifactClaimState.CLAIMED
        self.completed = completed
        self.completions = []
        self.retries = []
        self.failures = []
        self.previous_object_name = None
        self.previous_origin = None

    def claim_generation(self, tenant_id, knowledge_file_id, generation, started_at):
        return PdfArtifactClaimResult(self.claim_state, self.artifact)

    def complete_generation(self, **kwargs):
        self.completions.append(kwargs)
        return PdfArtifactCompleteResult(
            completed=self.completed,
            artifact=self.artifact,
            previous_object_name=self.previous_object_name,
            previous_origin=self.previous_origin,
        )

    def mark_retry(self, tenant_id, knowledge_file_id, generation, last_error):
        self.retries.append((tenant_id, knowledge_file_id, generation, last_error))
        return True

    def fail_generation(self, tenant_id, knowledge_file_id, generation, last_error):
        self.failures.append((tenant_id, knowledge_file_id, generation, last_error))
        return True


class _Storage:
    def __init__(self, objects) -> None:
        self.objects = dict(objects)
        self.puts = []
        self.removed = []

    def get_object_sync(self, object_name):
        if object_name not in self.objects:
            raise FileNotFoundError(object_name)
        return self.objects[object_name]

    def put_object_sync(self, *, object_name, file, content_type):
        self.objects[object_name] = Path(file).read_bytes()
        self.puts.append((object_name, content_type))

    def remove_object_sync(self, object_name):
        self.removed.append(object_name)
        self.objects.pop(object_name, None)


class _Converter:
    def __init__(self) -> None:
        self.calls = []

    def convert(self, source_path, output_dir, context):
        self.calls.append((source_path, output_dir, context))
        output_path = output_dir / "generated.pdf"
        output_path.write_bytes(_pdf_bytes())
        return ConversionResult(output_path, "fake")


def _processor(repository, storage, file, converter=None):
    return PdfArtifactProcessor(
        repository=repository,
        storage=storage,
        file_loader=lambda tenant_id, file_id: file,
        converter_registry=converter or _Converter(),
        conversion_context=ConversionContext(timeout_seconds=30),
        attempt_token_factory=lambda: "attempt-a",
        now_factory=lambda: datetime(2026, 7, 20),
    )


def test_original_pdf_is_validated_and_referenced_without_copy() -> None:
    repository = _Repository(_artifact(source_name="original/101.pdf"))
    storage = _Storage({"original/101.pdf": _pdf_bytes()})
    converter = _Converter()

    outcome = _processor(
        repository,
        storage,
        _file(file_name="report.pdf", object_name="original/101.pdf"),
        converter,
    ).process(knowledge_file_id=101, generation=2, tenant_id=7)

    assert outcome == PdfArtifactProcessOutcome.COMPLETED
    assert repository.completions[0]["origin"] == KnowledgeFilePdfArtifactOrigin.ORIGINAL
    assert repository.completions[0]["object_name"] == "original/101.pdf"
    assert converter.calls == []
    assert storage.puts == []


def test_attempt_log_correlates_tenant_generation_format_and_attempt() -> None:
    repository = _Repository(_artifact(source_name="original/101.pdf"))
    storage = _Storage({"original/101.pdf": _pdf_bytes()})
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    try:
        _processor(
            repository,
            storage,
            _file(file_name="report.pdf", object_name="original/101.pdf"),
        ).process(knowledge_file_id=101, generation=2, tenant_id=7)
    finally:
        logger.remove(sink_id)

    rendered = "\n".join(messages)
    assert "tenant_id=7" in rendered
    assert "file_id=101" in rendered
    assert "generation=2" in rendered
    assert "format=pdf" in rendered
    assert "attempt=1" in rendered


def test_pdf_processing_does_not_mutate_knowledge_parse_state() -> None:
    repository = _Repository(_artifact(source_name="original/101.pdf"))
    storage = _Storage({"original/101.pdf": _pdf_bytes()})
    file = _file(file_name="report.pdf", object_name="original/101.pdf")
    file.status = KnowledgeFileStatus.SUCCESS.value
    file.remark = "keep-parse-result"
    file.update_time = datetime(2026, 7, 1, 8, 30)

    outcome = _processor(repository, storage, file).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    assert outcome == PdfArtifactProcessOutcome.COMPLETED
    assert file.status == KnowledgeFileStatus.SUCCESS.value
    assert file.remark == "keep-parse-result"
    assert file.update_time == datetime(2026, 7, 1, 8, 30)


def test_current_valid_preview_is_referenced_without_generated_copy() -> None:
    repository = _Repository()
    storage = _Storage(
        {
            "original/101.docx": b"docx",
            "preview/101.pdf": _pdf_bytes(),
        }
    )
    converter = _Converter()
    file = _file(
        metadata={
            "pdf_preview_object_name": "preview/101.pdf",
            "pdf_preview_source_md5": "m1",
        }
    )

    outcome = _processor(repository, storage, file, converter).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    assert outcome == PdfArtifactProcessOutcome.COMPLETED
    assert repository.completions[0]["origin"] == KnowledgeFilePdfArtifactOrigin.PARSE_PREVIEW
    assert repository.completions[0]["object_name"] == "preview/101.pdf"
    assert converter.calls == []
    assert storage.puts == []


def test_invalid_preview_falls_back_to_generated_attempt_object() -> None:
    repository = _Repository()
    storage = _Storage(
        {
            "original/101.docx": b"docx",
            "preview/101.pdf": b"invalid pdf",
        }
    )
    file = _file(
        metadata={
            "pdf_preview_object_name": "preview/101.pdf",
            "pdf_preview_source_md5": "m1",
        }
    )

    outcome = _processor(repository, storage, file).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    expected = "knowledge/pdf-artifacts/101/2/attempt-a.pdf"
    assert outcome == PdfArtifactProcessOutcome.COMPLETED
    assert repository.completions[0]["origin"] == KnowledgeFilePdfArtifactOrigin.GENERATED
    assert repository.completions[0]["object_name"] == expected
    assert storage.puts == [(expected, "application/pdf")]


def test_preview_without_matching_provenance_is_not_read() -> None:
    repository = _Repository()
    storage = _Storage(
        {
            "original/101.docx": b"docx",
            "preview/101.pdf": _pdf_bytes(),
        }
    )
    file = _file(
        metadata={
            "pdf_preview_object_name": "preview/101.pdf",
            "pdf_preview_source_md5": "old-md5",
        }
    )

    _processor(repository, storage, file).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    assert repository.completions[0]["origin"] == KnowledgeFilePdfArtifactOrigin.GENERATED


def test_generated_candidate_is_reclaimed_when_conditional_complete_loses() -> None:
    repository = _Repository(completed=False)
    storage = _Storage({"original/101.docx": b"docx"})

    outcome = _processor(repository, storage, _file()).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    expected = "knowledge/pdf-artifacts/101/2/attempt-a.pdf"
    assert outcome == PdfArtifactProcessOutcome.STALE
    assert storage.removed == [expected]


def test_success_reclaims_only_replaced_generated_object() -> None:
    repository = _Repository()
    repository.previous_object_name = "knowledge/pdf-artifacts/101/1/old.pdf"
    repository.previous_origin = KnowledgeFilePdfArtifactOrigin.GENERATED.value
    storage = _Storage(
        {
            "original/101.docx": b"docx",
            repository.previous_object_name: _pdf_bytes(),
        }
    )

    _processor(repository, storage, _file()).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    assert storage.removed == [repository.previous_object_name]


def test_stale_or_completed_claim_exits_without_storage_access() -> None:
    repository = _Repository()
    repository.claim_state = PdfArtifactClaimState.ALREADY_COMPLETED
    storage = _Storage({})

    outcome = _processor(repository, storage, _file()).process(
        knowledge_file_id=101,
        generation=2,
        tenant_id=7,
    )

    assert outcome == PdfArtifactProcessOutcome.ALREADY_COMPLETED
    assert repository.completions == []


def test_source_snapshot_change_never_completes_old_generation() -> None:
    repository = _Repository()
    storage = _Storage({"original/101.docx": b"new content"})

    with pytest.raises(PdfArtifactSourceChangedError):
        _processor(repository, storage, _file(md5="m2")).process(
            knowledge_file_id=101,
            generation=2,
            tenant_id=7,
        )
    assert repository.completions == []


def test_retry_and_terminal_failure_store_only_bounded_error_type() -> None:
    repository = _Repository()
    config = KnowledgePdfArtifactConf(
        max_retries=3,
        retry_base_seconds=10,
        retry_max_seconds=30,
    )
    error = PdfConversionError("secret document body")

    retry = record_pdf_artifact_task_failure(
        repository=repository,
        tenant_id=7,
        knowledge_file_id=101,
        generation=2,
        completed_retries=0,
        config=config,
        error=error,
    )
    failed = record_pdf_artifact_task_failure(
        repository=repository,
        tenant_id=7,
        knowledge_file_id=101,
        generation=2,
        completed_retries=3,
        config=config,
        error=error,
    )

    assert retry.action == PdfArtifactTaskFailureAction.RETRY
    assert retry.countdown == 10
    assert failed.action == PdfArtifactTaskFailureAction.FAILED
    assert repository.retries[0][-1] == "process:PdfConversionError"
    assert repository.failures[0][-1] == "process:PdfConversionError"


def test_celery_retry_uses_only_sanitized_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    config = KnowledgePdfArtifactConf(
        max_retries=3,
        retry_base_seconds=10,
        retry_max_seconds=30,
    )
    celery_mock = sys.modules["bisheng.worker.main"].bisheng_celery
    task_function = celery_mock.task.return_value.call_args.args[0]
    run_globals = task_function.__globals__
    monkeypatch.setitem(
        run_globals,
        "settings",
        SimpleNamespace(get_knowledge=lambda: SimpleNamespace(pdf_artifact=config)),
    )

    def fail_attempt(**kwargs):
        raise PdfConversionError("password=must-not-leak")

    monkeypatch.setitem(run_globals, "_process_pdf_artifact_attempt", fail_attempt)
    monkeypatch.setitem(
        run_globals,
        "_record_failure_with_new_session",
        lambda **kwargs: PdfArtifactTaskFailureDecision(
            PdfArtifactTaskFailureAction.RETRY,
            countdown=10,
        ),
    )
    captured: dict = {}

    class RetrySignal(RuntimeError):
        pass

    def fake_retry(**kwargs):
        captured.update(kwargs)
        raise RetrySignal("retry")

    task = SimpleNamespace(
        request=SimpleNamespace(retries=0),
        retry=fake_retry,
    )

    with pytest.raises(RetrySignal):
        task_function(task, 101, 2, 7)

    assert isinstance(captured["exc"], PdfConversionError)
    assert str(captured["exc"]) == "process:PdfConversionError"
    assert captured["countdown"] == 10
    assert captured["max_retries"] == 3


def test_failure_state_persistence_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    config = KnowledgePdfArtifactConf()
    celery_mock = sys.modules["bisheng.worker.main"].bisheng_celery
    task_function = celery_mock.task.return_value.call_args.args[0]
    run_globals = task_function.__globals__
    monkeypatch.setitem(
        run_globals,
        "settings",
        SimpleNamespace(get_knowledge=lambda: SimpleNamespace(pdf_artifact=config)),
    )

    def fail_attempt(**kwargs):
        raise PdfConversionError("document-secret=must-not-leak")

    def fail_persistence(**kwargs):
        raise RuntimeError("database-password=must-not-leak")

    monkeypatch.setitem(run_globals, "_process_pdf_artifact_attempt", fail_attempt)
    monkeypatch.setitem(run_globals, "_record_failure_with_new_session", fail_persistence)
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    task = SimpleNamespace(request=SimpleNamespace(retries=0))

    try:
        with pytest.raises(PdfConversionError) as error:
            task_function(task, 101, 2, 7)
    finally:
        logger.remove(sink_id)

    rendered = "\n".join(messages)
    assert str(error.value) == "process:PdfConversionError"
    assert "process_error_type=PdfConversionError" in rendered
    assert "persistence_error_type=RuntimeError" in rendered
    assert "must-not-leak" not in rendered


def test_task_attempt_rejects_mismatched_tenant_context(tenant_context) -> None:
    tenant_context(8)

    with pytest.raises(PdfArtifactTenantMismatchError):
        _process_pdf_artifact_attempt(
            tenant_id=7,
            knowledge_file_id=101,
            generation=2,
            config=KnowledgePdfArtifactConf(),
        )


def test_pdf_task_has_stable_registered_name() -> None:
    source = (_BACKEND / "bisheng/worker/knowledge/pdf_artifact_worker.py").read_text(encoding="utf-8")
    assert 'name="bisheng.worker.knowledge.pdf_artifact_worker.generate_knowledge_file_pdf_celery"' in source
