"""Linsight task-mode LLM resolution (bugfix).

The per-task execution LLM used by ``LinsightWorkflowTask`` (for tool init and
helper calls) must honour the per-task ``model`` chosen at submit time and
persisted on ``LinsightSessionVersion.model`` — the same model the agent itself
runs on. The previous ``_get_llm`` ignored it and always pulled the tenant
``linsight_default_model_id``, so a task could fail at init even though the
frontend selected a perfectly valid model (and the tenant default was
missing/deleted/offline).

These tests pin two behaviours:
1. ``_get_llm`` resolves the frontend-supplied per-task model.
2. When resolution fails, the original exception is preserved (``__cause__``)
   so the real stack trace surfaces in logs instead of the generic message.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, TaskExecutionError
from bisheng.llm.domain.services import LLMService


def _session(*, model: str | None, svid: str = "SV-1") -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id=svid,
        session_id="chat-1",
        user_id=42,
        question="帮我写周报",
        model=model,
        tenant_id=7,
    )


@pytest.fixture
def patch_linsight_conf(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        agent_factory,
        "settings",
        SimpleNamespace(get_linsight_conf=lambda: SimpleNamespace(default_temperature=0.1)),
    )


async def test_get_llm_uses_per_task_model(monkeypatch: pytest.MonkeyPatch, patch_linsight_conf):
    """The frontend-supplied per-task model is used, not the tenant default."""
    # Tenant default is intentionally absent: only the per-task model can save us.
    monkeypatch.setattr(
        LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(linsight_default_model_id=None)),
    )
    fake_llm = object()
    get_llm_mock = AsyncMock(return_value=fake_llm)
    monkeypatch.setattr(LLMService, "get_bisheng_linsight_llm", get_llm_mock)

    task = LinsightWorkflowTask()
    task.session_version_id = "SV-1"
    session_model = _session(model="frontend-model-xyz")

    result = await task._get_llm(session_model)

    assert result is fake_llm
    assert get_llm_mock.await_args.kwargs["model_id"] == "frontend-model-xyz"


async def test_get_llm_preserves_original_exception(monkeypatch: pytest.MonkeyPatch, patch_linsight_conf):
    """A resolution failure is re-raised as TaskExecutionError chained to the cause."""
    monkeypatch.setattr(
        LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(linsight_default_model_id="tenant-default")),
    )
    original = RuntimeError("model offline")
    monkeypatch.setattr(LLMService, "get_bisheng_linsight_llm", AsyncMock(side_effect=original))

    task = LinsightWorkflowTask()
    task.session_version_id = "SV-1"
    session_model = _session(model="frontend-model-xyz")

    with pytest.raises(TaskExecutionError) as excinfo:
        await task._get_llm(session_model)

    assert excinfo.value.__cause__ is original
