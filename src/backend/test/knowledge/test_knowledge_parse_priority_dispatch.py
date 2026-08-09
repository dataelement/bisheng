from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services.knowledge_parse_dispatch_service import (
    KnowledgeParseAttemptKind,
    KnowledgeParseDispatchService,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]


class FakeTask:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(id="ticket-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("priority", "transport_priority"),
    [
        (KnowledgeParsePriority.HIGH, 0),
        (KnowledgeParsePriority.MEDIUM, 3),
        (KnowledgeParsePriority.LOW, 9),
    ],
)
async def test_dispatch_uses_snapshot_queue_priority_and_headers(
    priority: KnowledgeParsePriority,
    transport_priority: int,
) -> None:
    snapshot_service = AsyncMock()
    snapshot_service.get_or_create = AsyncMock(return_value=priority)
    task = FakeTask()
    service = KnowledgeParseDispatchService(
        snapshot_service,
        ticket_id_factory=lambda: "ticket-1",
    )
    tenant_token = set_current_tenant_id(7)
    try:
        ticket_id = await service.dispatch(
            attempt_kind=KnowledgeParseAttemptKind.INITIAL,
            file_id=11,
            preview_cache_key="preview",
            callback_url="https://callback.invalid",
            operator_user_id=5,
            operator_is_global_super=False,
            task=task,
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert ticket_id == "ticket-1"
    assert task.calls == [
        {
            "args": [11, "preview", "https://callback.invalid"],
            "queue": "knowledge_celery",
            "priority": transport_priority,
            "headers": {
                "knowledge_parse_priority": priority.value,
                "knowledge_parse_attempt_kind": "initial",
                "knowledge_parse_queue_ticket_id": "ticket-1",
                "knowledge_parse_file_id": 11,
                "tenant_id": 7,
            },
            "task_id": "ticket-1",
        }
    ]


@pytest.mark.asyncio
async def test_initial_dispatch_uses_one_parse_message_and_attempt_kind_header() -> None:
    snapshot_service = AsyncMock()
    snapshot_service.get_or_create = AsyncMock(return_value=KnowledgeParsePriority.MEDIUM)
    task = FakeTask()
    service = KnowledgeParseDispatchService(
        snapshot_service,
        ticket_id_factory=lambda: "initial-ticket",
    )

    await service.dispatch(
        attempt_kind="initial",
        file_id=21,
        tenant_id=1,
        knowledge_id=10,
        task=task,
    )

    assert task.calls[0]["headers"]["knowledge_parse_attempt_kind"] == "initial"
    assert "knowledge_parse_stage" not in task.calls[0]["headers"]


@pytest.mark.asyncio
async def test_upload_batch_dispatches_initial_lifecycle_without_title_message() -> None:
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    process_files = [SimpleNamespace(id=31)]
    with pytest.MonkeyPatch.context() as monkeypatch:
        dispatch = AsyncMock()
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task",
            dispatch,
        )
        await KnowledgeSpaceService.enqueue_file_title_extraction(
            process_files,
            ["preview"],
            operator_user_id=5,
            operator_is_global_super=False,
        )

    assert dispatch.await_count == 1
    assert dispatch.await_args.kwargs["attempt_kind"] == "initial"
    assert "stage" not in dispatch.await_args.kwargs


@pytest.mark.asyncio
async def test_dispatch_propagates_broker_failure(caplog) -> None:
    snapshot_service = AsyncMock()
    snapshot_service.get_or_create = AsyncMock(return_value=KnowledgeParsePriority.MEDIUM)
    service = KnowledgeParseDispatchService(snapshot_service)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.dispatch(
            attempt_kind=KnowledgeParseAttemptKind.RETRY,
            file_id=12,
            task=FakeTask(error=RuntimeError("broker unavailable")),
        )

    assert "knowledge parse task publish failed" in caplog.text


@pytest.mark.asyncio
async def test_queue_index_failure_does_not_block_celery_publish(caplog) -> None:
    snapshot_service = AsyncMock()
    snapshot_service.get_or_create = AsyncMock(return_value=KnowledgeParsePriority.LOW)
    queue_repository = AsyncMock()
    queue_repository.create_publishing = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    task = FakeTask()
    service = KnowledgeParseDispatchService(
        snapshot_service,
        queue_repository=queue_repository,
        ticket_id_factory=lambda: "ticket-index-failure",
    )

    result = await service.dispatch(
        attempt_kind=KnowledgeParseAttemptKind.INITIAL,
        file_id=13,
        tenant_id=1,
        knowledge_id=10,
        task=task,
    )

    assert result == "ticket-1"
    assert task.calls[0]["task_id"] == "ticket-index-failure"
    assert "knowledge parse queue index create failed" in caplog.text


@pytest.mark.asyncio
async def test_broker_failure_best_effort_cleans_created_ticket() -> None:
    snapshot_service = AsyncMock()
    snapshot_service.get_or_create = AsyncMock(return_value=KnowledgeParsePriority.MEDIUM)
    queue_repository = AsyncMock()
    service = KnowledgeParseDispatchService(
        snapshot_service,
        queue_repository=queue_repository,
        ticket_id_factory=lambda: "ticket-broker-failure",
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.dispatch(
            attempt_kind=KnowledgeParseAttemptKind.RETRY,
            file_id=14,
            tenant_id=1,
            knowledge_id=10,
            task=FakeTask(error=RuntimeError("broker unavailable")),
        )

    queue_repository.remove_ticket.assert_awaited_once()


def test_parse_tasks_declare_medium_default_priority() -> None:
    task_files = (
        BACKEND_DIR / "bisheng/worker/knowledge/file_title_worker.py",
        BACKEND_DIR / "bisheng/worker/knowledge/file_worker.py",
    )
    target_names = {
        "extract_knowledge_file_title_celery",
        "parse_knowledge_file_celery",
        "retry_knowledge_file_celery",
    }
    priorities: dict[str, int] = {}
    for path in task_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in target_names:
                continue
            decorator = next(
                decorator
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "task"
            )
            priorities[node.name] = next(
                keyword.value.value
                for keyword in decorator.keywords
                if keyword.arg == "priority" and isinstance(keyword.value, ast.Constant)
            )

    assert priorities == dict.fromkeys(target_names, 3)


def test_production_code_has_no_direct_parse_task_publish_bypass() -> None:
    forbidden = {
        "extract_knowledge_file_title_celery",
        "parse_knowledge_file_celery",
        "retry_knowledge_file_celery",
    }
    violations: list[str] = []
    for root in (BACKEND_DIR / "bisheng", BACKEND_DIR / "scripts"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"delay", "apply_async"}:
                    continue
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id in forbidden:
                    violations.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")
    assert violations == []
