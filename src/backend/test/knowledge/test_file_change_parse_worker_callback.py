from __future__ import annotations

import inspect
from unittest.mock import ANY, MagicMock

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    UploadStepDispatchContext,
)
from bisheng.worker.knowledge import file_worker


async def test_upload_parse_handoff_uses_regular_knowledge_scheduler(monkeypatch: pytest.MonkeyPatch):
    enqueue = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch",
        enqueue,
    )
    context = UploadStepDispatchContext(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
        step_code="upload.parse",
        idempotency_key="f046:41:upload.parse",
        file_id=71,
        file_name="report.pdf",
        applicant_user_id=7,
        space_id=8,
        checkpoint={},
    )
    token = set_current_tenant_id(23)
    try:
        receipt = await KnowledgeSpaceMutationExecutor._dispatch_parse(context)
    finally:
        current_tenant_id.reset(token)

    assert receipt == "scheduler:f046:41:upload.parse"
    enqueue.assert_called_once_with(
        user_id=7,
        file_id=71,
        file_name="report.pdf",
        preview_cache_key=ANY,
        callback_url=None,
        idempotency_key="f046:41:upload.parse",
    )


def test_parse_worker_has_no_file_change_terminal_callback_surface():
    parameters = inspect.signature(file_worker.parse_knowledge_file_celery.run).parameters

    assert set(parameters) == {"file_id", "preview_cache_key", "callback_url"}
    assert not hasattr(file_worker, "_file_change_parse_context")
    assert not hasattr(file_worker, "_dispatch_file_change_upload_pipeline_callback")
