from __future__ import annotations

from unittest.mock import ANY, MagicMock

import pytest

from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    UploadStepDispatchContext,
)
from bisheng.worker.knowledge import file_worker


async def test_upload_parse_dispatch_carries_stable_request_and_generation(monkeypatch: pytest.MonkeyPatch):
    enqueue = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.knowledge.scheduler.enqueue_or_dispatch",
        enqueue,
    )
    context = UploadStepDispatchContext(
        tenant_id=23,
        request_id=41,
        instance_id=51,
        execution_token="generation-1",
        step_code="upload.parse",
        idempotency_key="f046:41:upload.parse",
        file_id=71,
        file_name="report.pdf",
        applicant_user_id=7,
        space_id=8,
        checkpoint={},
    )

    receipt = await KnowledgeSpaceMutationExecutor._dispatch_parse(context)

    assert receipt == "scheduler:f046:41:upload.parse"
    enqueue.assert_called_once_with(
        user_id=7,
        file_id=71,
        file_name="report.pdf",
        preview_cache_key=ANY,
        callback_url=None,
        idempotency_key="f046:41:upload.parse",
        file_change_request_id=41,
        file_change_execution_token="generation-1",
    )


@pytest.mark.parametrize(
    "headers,request_id,token",
    [
        ({}, 41, "generation-1"),
        ({"tenant_id": 23}, None, "generation-1"),
        ({"tenant_id": 23}, 41, None),
        ({"tenant_id": "bad"}, 41, "generation-1"),
    ],
)
def test_file_change_parse_context_fails_closed_without_complete_identity(headers, request_id, token):
    with pytest.raises(ValueError, match="file change parse"):
        file_worker._file_change_parse_context(
            headers=headers,
            request_id=request_id,
            execution_token=token,
        )


def test_file_change_parse_callback_uses_explicit_tenant_header(monkeypatch: pytest.MonkeyPatch):
    apply_async = MagicMock()
    monkeypatch.setattr(
        "bisheng.worker.approval.file_change_tasks.acknowledge_file_change_upload_pipeline.apply_async",
        apply_async,
    )

    file_worker._dispatch_file_change_upload_pipeline_callback(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
        file_id=71,
    )

    apply_async.assert_called_once_with(
        kwargs={
            "request_id": 41,
            "execution_token": "generation-1",
            "file_id": 71,
        },
        headers={"tenant_id": 23},
    )
