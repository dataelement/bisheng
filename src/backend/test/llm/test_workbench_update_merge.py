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

from bisheng.common.errcode.llm import WorkbenchChatDefaultModelError, WorkbenchEmbeddingError
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


@pytest.mark.parametrize("invalid_model_id", ["", "null", "undefined", "0", "-1"])
@pytest.mark.asyncio
async def test_invalid_embedding_model_id_returns_business_error(invalid_model_id: str):
    config = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max")],
        embedding_model=WSModel(id=invalid_model_id),
    )

    with patch(
        "bisheng.llm.domain.services.llm.avalidate_system_model_refs",
        new=AsyncMock(),
    ) as mock_validate:
        with pytest.raises(WorkbenchEmbeddingError) as exc_info:
            await LLMService.update_workbench_llm(1, config, MagicMock(), tenant_id=1)

    assert exc_info.value.code == 10810
    mock_validate.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_default_model_id_persists_alongside_linsight_default():
    """chat_default_model_id is a sibling of linsight_default_model_id — both
    land in the same stored JSON without overwriting each other."""
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max"), WSModel(id="841", name="deepseek-v4")],
        linsight_default_model_id="840",
        chat_default_model_id="841",
        embedding_model=None,
    )
    persisted = await _run_and_capture(incoming)
    assert persisted["linsight_default_model_id"] == "840"
    assert persisted["chat_default_model_id"] == "841"


@pytest.mark.asyncio
async def test_chat_default_model_id_none_is_allowed():
    """No daily-chat default configured is a valid state."""
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max")],
        chat_default_model_id=None,
        embedding_model=None,
    )
    persisted = await _run_and_capture(incoming)
    assert persisted["chat_default_model_id"] is None


@pytest.mark.asyncio
async def test_chat_default_model_id_must_come_from_models_list():
    """A default outside the configured workbench chat model list is rejected."""
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max")],
        chat_default_model_id="999",
        embedding_model=None,
    )
    with patch(
        "bisheng.llm.domain.services.llm.avalidate_system_model_refs",
        new=AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve",
        new=AsyncMock(return_value=(json.dumps(_OLD.model_dump()), False, False)),
    ):
        with pytest.raises(WorkbenchChatDefaultModelError) as exc_info:
            await LLMService.update_workbench_llm(1, incoming, MagicMock(), tenant_id=1)

    assert exc_info.value.code == 10811


@pytest.mark.parametrize("invalid_model_id", ["", "null", "undefined", "0", "-1", "abc"])
@pytest.mark.asyncio
async def test_chat_default_model_id_rejects_non_model_values(invalid_model_id: str):
    incoming = WorkbenchModelConfig(
        models=[WSModel(id="840", name="qwen3.7-max")],
        chat_default_model_id=invalid_model_id,
        embedding_model=None,
    )
    with patch(
        "bisheng.llm.domain.services.llm.avalidate_system_model_refs",
        new=AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve",
        new=AsyncMock(return_value=(json.dumps(_OLD.model_dump()), False, False)),
    ):
        with pytest.raises(WorkbenchChatDefaultModelError):
            await LLMService.update_workbench_llm(1, incoming, MagicMock(), tenant_id=1)


@pytest.mark.asyncio
async def test_chat_default_model_id_validated_against_merged_old_models():
    """When the body omits ``models`` (merge-guard keeps the stored list), the
    default is checked against that effective list — old id passes, new id not
    in the stored list fails."""
    # "727" exists only in the stored (_OLD) list.
    incoming = WorkbenchModelConfig(chat_default_model_id="727", embedding_model=None)
    persisted = await _run_and_capture(incoming)
    assert persisted["chat_default_model_id"] == "727"
    assert [m["id"] for m in persisted["models"]] == ["727", "774"]

    incoming_bad = WorkbenchModelConfig(chat_default_model_id="840", embedding_model=None)
    with patch(
        "bisheng.llm.domain.services.llm.avalidate_system_model_refs",
        new=AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm.TenantSystemModelConfigDao.aresolve",
        new=AsyncMock(return_value=(json.dumps(_OLD.model_dump()), False, False)),
    ):
        with pytest.raises(WorkbenchChatDefaultModelError):
            await LLMService.update_workbench_llm(1, incoming_bad, MagicMock(), tenant_id=1)
