"""update_workbench_llm merge-guard tests.

Regression for the prod incident where a stale/partial admin POST to
``/api/v1/llm/workbench`` — a ``WorkbenchModelConfig`` body that omitted
``models`` (so Pydantic defaulted it to ``None``) — wiped the entire Root
dialogue-model list, because the setter persists ``config_obj`` wholesale
with no field-level merge.

Contract:
  * ``models is None`` (field absent)  -> keep the previously stored list
  * ``models == []`` (explicit)         -> clears, as intended
  * ``models == [..]``                  -> replaces normally
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services.llm import LLMService

_OLD = WorkbenchModelConfig(
    models=[WSModel(id="727", name="deepseek"), WSModel(id="774", name="qwen")],
    embedding_model=WSModel(id="729", name="embed"),
)


async def _run_and_capture(config_obj: WorkbenchModelConfig) -> dict:
    """Drive update_workbench_llm with DB/validation mocked; return the JSON
    payload handed to aupsert."""
    with (
        patch(
            "bisheng.llm.domain.services.llm.avalidate_system_model_refs",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve",
            new=AsyncMock(return_value=(json.dumps(_OLD.model_dump()), False, False)),
        ),
        patch(
            "bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aupsert",
            new=AsyncMock(),
        ) as mock_upsert,
    ):
        await LLMService.update_workbench_llm(1, config_obj, MagicMock(), tenant_id=1)

    mock_upsert.assert_awaited_once()
    return json.loads(mock_upsert.await_args.kwargs["value"])


@pytest.mark.asyncio
async def test_omitted_models_preserves_existing():
    """The bug: a body without ``models`` must NOT null the stored list."""
    # embedding_model=None keeps the knowledge-rebuild branch out of the test.
    incoming = WorkbenchModelConfig(embedding_model=None)  # models defaults to None
    assert incoming.models is None

    persisted = await _run_and_capture(incoming)

    assert [m["id"] for m in persisted["models"]] == ["727", "774"]


@pytest.mark.asyncio
async def test_explicit_empty_models_clears():
    """An explicit empty array is a real intent and must still clear."""
    persisted = await _run_and_capture(WorkbenchModelConfig(models=[], embedding_model=None))
    assert persisted["models"] == []


@pytest.mark.asyncio
async def test_provided_models_replace_normally():
    incoming = WorkbenchModelConfig(models=[WSModel(id="840", name="qwen3.7-max")], embedding_model=None)
    persisted = await _run_and_capture(incoming)
    assert [m["id"] for m in persisted["models"]] == ["840"]
