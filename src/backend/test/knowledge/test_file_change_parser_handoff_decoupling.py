from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    KnowledgeSpaceMutationExecutor,
    UploadStepDispatchContext,
)
from bisheng.worker.knowledge import file_worker, scheduler

TENANT_ID = 23


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _upload_context() -> UploadStepDispatchContext:
    return UploadStepDispatchContext(
        tenant_id=TENANT_ID,
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


def test_parser_and_scheduler_have_no_approval_callback_or_storage_dependency() -> None:
    sources = {
        "file_worker": inspect.getsource(file_worker),
        "scheduler": inspect.getsource(scheduler),
    }
    forbidden = (
        "bisheng.approval",
        "bisheng.worker.approval",
        "ApprovalInstance",
        "ApprovalOutbox",
        "approval_instance_repository",
        "approval_outbox",
        "build_runtime_handler",
        "deferred",
        "outbox_id",
    )

    for module_name, source in sources.items():
        used = [fragment for fragment in forbidden if fragment in source]
        assert used == [], f"{module_name} still owns an Approval callback: {used}"


def test_parser_and_scheduler_public_api_carries_no_f046_callback_identity() -> None:
    parse_parameters = inspect.signature(file_worker.parse_knowledge_file_celery.run).parameters
    scheduler_parameters = inspect.signature(scheduler.enqueue_or_dispatch).parameters

    for parameters in (parse_parameters, scheduler_parameters):
        assert "file_change_request_id" not in parameters
        assert "file_change_execution_token" not in parameters
        assert "outbox_id" not in parameters

    assert not hasattr(file_worker, "_dispatch_file_change_upload_pipeline_callback")
    assert not hasattr(file_worker, "_file_change_parse_context")


async def test_f046_upload_business_completion_is_plain_knowledge_scheduler_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = MagicMock()
    monkeypatch.setattr(scheduler, "enqueue_or_dispatch", enqueue)
    token = set_current_tenant_id(TENANT_ID)
    try:
        receipt = await KnowledgeSpaceMutationExecutor._dispatch_parse(_upload_context())
    finally:
        current_tenant_id.reset(token)

    assert receipt == "scheduler:f046:41:upload.parse"
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs == {
        "user_id": 7,
        "file_id": 71,
        "file_name": "report.pdf",
        "preview_cache_key": enqueue.call_args.kwargs["preview_cache_key"],
        "callback_url": None,
        "idempotency_key": "f046:41:upload.parse",
    }


def test_idempotent_scheduler_dispatch_requires_explicit_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_async = MagicMock()
    monkeypatch.setattr(scheduler, "_fair_scheduler_enabled", lambda: False)
    monkeypatch.setattr(scheduler, "decide_queue", lambda _file_name: scheduler.KNOWLEDGE_QUEUE)
    monkeypatch.setattr(scheduler, "_parse_apply_async", apply_async)

    with pytest.raises(RuntimeError, match="tenant context"):
        scheduler.enqueue_or_dispatch(
            user_id=7,
            file_id=71,
            file_name="report.pdf",
            preview_cache_key="preview:71",
            callback_url=None,
            idempotency_key="f046:41:upload.parse",
        )

    apply_async.assert_not_called()


def test_direct_scheduler_dispatch_is_stable_and_owned_by_knowledge_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_async = MagicMock()
    monkeypatch.setattr(scheduler, "_fair_scheduler_enabled", lambda: False)
    monkeypatch.setattr(scheduler, "decide_queue", lambda _file_name: scheduler.KNOWLEDGE_QUEUE)
    monkeypatch.setattr(scheduler, "_parse_apply_async", apply_async)
    token = set_current_tenant_id(TENANT_ID)
    try:
        for _ in range(2):
            scheduler.enqueue_or_dispatch(
                user_id=7,
                file_id=71,
                file_name="report.pdf",
                preview_cache_key="preview:71",
                callback_url=None,
                idempotency_key="f046:41:upload.parse",
            )
    finally:
        current_tenant_id.reset(token)

    assert apply_async.call_count == 2
    for call in apply_async.call_args_list:
        assert call.kwargs == {
            "args": [71, "preview:71", ""],
            "queue": "knowledge_celery",
            "task_id": "f046:41:upload.parse",
            "headers": {"tenant_id": TENANT_ID},
        }


def test_scheduler_broker_failure_propagates_without_approval_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "_fair_scheduler_enabled", lambda: False)
    monkeypatch.setattr(scheduler, "decide_queue", lambda _file_name: scheduler.KNOWLEDGE_QUEUE)
    monkeypatch.setattr(
        scheduler,
        "_parse_apply_async",
        MagicMock(side_effect=RuntimeError("knowledge broker unavailable")),
    )
    token = set_current_tenant_id(TENANT_ID)
    try:
        with pytest.raises(RuntimeError, match="knowledge broker unavailable"):
            scheduler.enqueue_or_dispatch(
                user_id=7,
                file_id=71,
                file_name="report.pdf",
                preview_cache_key="preview:71",
                callback_url=None,
                idempotency_key="f046:41:upload.parse",
            )
    finally:
        current_tenant_id.reset(token)


def test_parser_failure_propagates_and_restores_tenant_without_business_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        file_worker,
        "_parse_knowledge_file_task_body",
        MagicMock(side_effect=RuntimeError("parser failed")),
    )
    file_worker.parse_knowledge_file_celery.request = SimpleNamespace(headers={"tenant_id": TENANT_ID})
    outer = set_current_tenant_id(99)
    try:
        with pytest.raises(RuntimeError, match="parser failed"):
            file_worker.parse_knowledge_file_celery.run(71)
        assert current_tenant_id.get() == 99
    finally:
        current_tenant_id.reset(outer)
