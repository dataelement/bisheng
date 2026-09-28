"""Regression test for the bug where deleting (or removing a model from) an
LLM server left stale ``model_id`` references in the 5 system-config rows
(knowledge_llm / assistant_llm / evaluation_llm / workflow_llm /
linsight_llm). The next ``update_*_llm`` write then tripped
``LlmModelConfigDeletedError`` because ``avalidate_system_model_refs``
rejects a model_id that no longer exists — and the knowledge-base picker
in the management UI kept showing the dropped model until the admin
manually cleared it.

Covers ``LLMService._clear_stale_model_refs_from_system_configs`` plus
the wiring from ``delete_llm_server`` and ``update_llm_server``.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    AssistantLLMItem,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    WorkbenchModelConfig,
    WSModel,
)


def _make_knowledge_llm(**overrides) -> KnowledgeLLMConfig:
    base = {
        "embedding_model_id": 10,
        "source_model_id": 11,
        "extract_title_model_id": 12,
        "qa_similar_model_id": 13,
        "asr_model_id": 14,
    }
    base.update(overrides)
    return KnowledgeLLMConfig(**base)


def _make_assistant_llm(**overrides) -> AssistantLLMConfig:
    base = {
        "llm_list": [
            AssistantLLMItem(model_id=20, default=True),
            AssistantLLMItem(model_id=21),
        ],
        "auto_llm": AssistantLLMItem(model_id=22),
    }
    base.update(overrides)
    return AssistantLLMConfig(**base)


def _make_evaluation_llm(model_id: int | None) -> EvaluationLLMConfig:
    return EvaluationLLMConfig(model_id=model_id)


def _make_workbench_llm() -> WorkbenchModelConfig:
    return WorkbenchModelConfig(
        models=[WSModel(id="30", name="m30"), WSModel(id="31", name="m31")],
        linsight_default_model_id="32",
        embedding_model=WSModel(id="33", name="m33"),
        asr_model=WSModel(id="34", name="m34"),
        tts_model=WSModel(id="35", name="m35"),
        chat_title_llm=WSModel(id="36", name="m36"),
    )


# --- the core cleanup helper -----------------------------------------------


@pytest.mark.asyncio
async def test_clear_stale_model_refs_no_op_when_empty_set():
    from bisheng.llm.domain.services.llm import LLMService

    upsert_mock = AsyncMock()
    with patch.object(
        LLMService, "_base_update_llm_config", upsert_mock,
    ):
        await LLMService._clear_stale_model_refs_from_system_configs(set())
    upsert_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_stale_model_refs_clears_knowledge_llm():
    from bisheng.llm.domain.services.llm import LLMService

    knowledge_llm = _make_knowledge_llm()
    with patch.object(
        LLMService,
        "aget_knowledge_llm_with_meta",
        AsyncMock(return_value=(knowledge_llm, False, False)),
    ), patch.object(
        LLMService, "aget_assistant_llm_with_meta",
        AsyncMock(return_value=(AssistantLLMConfig(), False, False)),
    ), patch.object(
        LLMService, "_aget_typed_with_meta",
        AsyncMock(return_value=(_make_evaluation_llm(None), False, False)),
    ), patch.object(
        LLMService, "aget_workbench_llm_with_meta",
        AsyncMock(return_value=(_make_workbench_llm(), False, False)),
    ), patch.object(
        LLMService, "_base_update_llm_config", AsyncMock(),
    ) as upsert_mock:
        # Drop model 11 (source_model_id) and 14 (asr_model_id).
        await LLMService._clear_stale_model_refs_from_system_configs(
            {11, 14}, tenant_id=1,
        )

    assert knowledge_llm.source_model_id is None
    assert knowledge_llm.asr_model_id is None
    # Untouched slots stay populated.
    assert knowledge_llm.embedding_model_id == 10
    assert knowledge_llm.extract_title_model_id == 12
    assert knowledge_llm.qa_similar_model_id == 13
    upsert_mock.assert_awaited_once()
    kwargs = upsert_mock.await_args.kwargs
    assert kwargs["key"] is ConfigKeyEnum.KNOWLEDGE_LLM


@pytest.mark.asyncio
async def test_clear_stale_model_refs_clears_assistant_llm_items():
    from bisheng.llm.domain.services.llm import LLMService

    assistant_llm = _make_assistant_llm()
    with patch.object(
        LLMService, "aget_knowledge_llm_with_meta",
        AsyncMock(return_value=(_make_knowledge_llm(), False, False)),
    ), patch.object(
        LLMService, "aget_assistant_llm_with_meta",
        AsyncMock(return_value=(assistant_llm, False, False)),
    ), patch.object(
        LLMService, "_aget_typed_with_meta",
        AsyncMock(return_value=(_make_evaluation_llm(None), False, False)),
    ), patch.object(
        LLMService, "aget_workbench_llm_with_meta",
        AsyncMock(return_value=(_make_workbench_llm(), False, False)),
    ), patch.object(
        LLMService, "_base_update_llm_config", AsyncMock(),
    ) as upsert_mock:
        # Drop 21 (in llm_list) and 22 (auto_llm); keep 20.
        await LLMService._clear_stale_model_refs_from_system_configs(
            {21, 22}, tenant_id=1,
        )

    assert [item.model_id for item in assistant_llm.llm_list] == [20]
    assert assistant_llm.auto_llm is None
    # Only the assistant row should have been rewritten.
    written_keys = {call.kwargs["key"] for call in upsert_mock.await_args_list}
    assert written_keys == {ConfigKeyEnum.ASSISTANT_LLM}


@pytest.mark.asyncio
async def test_clear_stale_model_refs_clears_evaluation_and_workflow():
    from bisheng.llm.domain.services.llm import LLMService

    evaluation = _make_evaluation_llm(model_id=50)
    workflow = _make_evaluation_llm(model_id=60)

    async def fake_aget_typed(key, model_cls, tenant_id):
        if key is ConfigKeyEnum.EVALUATION_LLM:
            return (evaluation, False, False)
        if key is ConfigKeyEnum.WORKFLOW_LLM:
            return (workflow, False, False)
        return (model_cls(), False, False)

    with patch.object(
        LLMService, "aget_knowledge_llm_with_meta",
        AsyncMock(return_value=(_make_knowledge_llm(), False, False)),
    ), patch.object(
        LLMService, "aget_assistant_llm_with_meta",
        AsyncMock(return_value=(AssistantLLMConfig(), False, False)),
    ), patch.object(
        LLMService, "_aget_typed_with_meta",
        AsyncMock(side_effect=fake_aget_typed),
    ), patch.object(
        LLMService, "aget_workbench_llm_with_meta",
        AsyncMock(return_value=(_make_workbench_llm(), False, False)),
    ), patch.object(
        LLMService, "_base_update_llm_config", AsyncMock(),
    ) as upsert_mock:
        await LLMService._clear_stale_model_refs_from_system_configs(
            {50, 60}, tenant_id=1,
        )

    assert evaluation.model_id is None
    assert workflow.model_id is None
    written_keys = {call.kwargs["key"] for call in upsert_mock.await_args_list}
    assert ConfigKeyEnum.EVALUATION_LLM in written_keys
    assert ConfigKeyEnum.WORKFLOW_LLM in written_keys


@pytest.mark.asyncio
async def test_clear_stale_model_refs_clears_workbench_linsight():
    from bisheng.llm.domain.services.llm import LLMService

    workbench = _make_workbench_llm()
    with patch.object(
        LLMService, "aget_knowledge_llm_with_meta",
        AsyncMock(return_value=(_make_knowledge_llm(), False, False)),
    ), patch.object(
        LLMService, "aget_assistant_llm_with_meta",
        AsyncMock(return_value=(AssistantLLMConfig(), False, False)),
    ), patch.object(
        LLMService, "_aget_typed_with_meta",
        AsyncMock(return_value=(_make_evaluation_llm(None), False, False)),
    ), patch.object(
        LLMService, "aget_workbench_llm_with_meta",
        AsyncMock(return_value=(workbench, False, False)),
    ), patch.object(
        LLMService, "_base_update_llm_config", AsyncMock(),
    ) as upsert_mock:
        # Drop the embedding model + one entry from ``models``.
        await LLMService._clear_stale_model_refs_from_system_configs(
            {30, 33}, tenant_id=1,
        )

    assert workbench.embedding_model is None
    assert [m.id for m in workbench.models] == ["31"]
    # Untouched: asr/tts/chat_title + linsight_default.
    assert workbench.asr_model.id == "34"
    assert workbench.tts_model.id == "35"
    assert workbench.chat_title_llm.id == "36"
    assert workbench.linsight_default_model_id == "32"
    written_keys = {call.kwargs["key"] for call in upsert_mock.await_args_list}
    assert ConfigKeyEnum.LINSIGHT_LLM in written_keys


@pytest.mark.asyncio
async def test_clear_stale_model_refs_skips_unaffected_configs():
    """When only one config is touched, only that config is rewritten."""
    from bisheng.llm.domain.services.llm import LLMService

    # The dropped ids don't appear anywhere except knowledge_llm.
    knowledge_llm = _make_knowledge_llm(embedding_model_id=99)
    with patch.object(
        LLMService,
        "aget_knowledge_llm_with_meta",
        AsyncMock(return_value=(knowledge_llm, False, False)),
    ), patch.object(
        LLMService, "aget_assistant_llm_with_meta",
        AsyncMock(return_value=(_make_assistant_llm(), False, False)),
    ), patch.object(
        LLMService, "_aget_typed_with_meta",
        AsyncMock(return_value=(_make_evaluation_llm(None), False, False)),
    ), patch.object(
        LLMService, "aget_workbench_llm_with_meta",
        AsyncMock(return_value=(_make_workbench_llm(), False, False)),
    ), patch.object(
        LLMService, "_base_update_llm_config", AsyncMock(),
    ) as upsert_mock:
        await LLMService._clear_stale_model_refs_from_system_configs(
            {99}, tenant_id=1,
        )

    assert knowledge_llm.embedding_model_id is None
    upsert_mock.assert_awaited_once()
    assert upsert_mock.await_args.kwargs["key"] is ConfigKeyEnum.KNOWLEDGE_LLM


# --- delete_llm_server wires the cleanup ------------------------------------


@pytest.mark.asyncio
async def test_delete_llm_server_clears_stale_config_refs():
    """End-to-end: deleting a server drops all of its models from the
    system-config rows in the same call."""
    from bisheng.llm.domain.services.llm import LLMService

    pre_server = MagicMock(id=1, tenant_id=7, name="s1", type="openai",
                            config={}, limit_flag=False, limit=0)
    dropped_models = [
        MagicMock(id=11, server_id=1),
        MagicMock(id=12, server_id=1),
    ]
    cleanup_mock = AsyncMock()

    with patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_server_by_id",
        AsyncMock(return_value=pre_server),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_server_ids",
        AsyncMock(return_value=dropped_models),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.adelete_server_by_id",
        AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm._write_llm_audit",
        AsyncMock(),
    ), patch.object(
        LLMService,
        "_clear_stale_model_refs_from_system_configs",
        cleanup_mock,
    ):
        await LLMService.delete_llm_server(
            request=MagicMock(), login_user=MagicMock(), server_id=1,
        )

    cleanup_mock.assert_awaited_once()
    args = cleanup_mock.await_args.args[0]
    assert args == {11, 12}
    assert cleanup_mock.await_args.kwargs.get("tenant_id") == 7


# --- update_llm_server wires the cleanup when models get removed -----------


@pytest.mark.asyncio
async def test_update_llm_server_clears_refs_for_removed_models():
    """When updating a server and removing a model from the list, the
    dropped model's id is forwarded to the cleanup helper."""
    from bisheng.llm.domain.services.llm import LLMService

    exist_server = MagicMock(id=2, tenant_id=7, name="s2", type="openai",
                              config={}, limit_flag=False, limit=0,
                              share_to_children=False)
    old_models = [
        MagicMock(id=21, server_id=2, model_name="a", model_type="llm"),
        MagicMock(id=22, server_id=2, model_name="b", model_type="llm"),
    ]
    new_server_info = MagicMock(
        id=2, models=[MagicMock(id=21)], tenant_id=7,
    )
    cleanup_mock = AsyncMock()
    fake_set_default = AsyncMock()
    fake_test_status = AsyncMock()
    fake_update_share = AsyncMock()

    with patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_server_by_id",
        AsyncMock(return_value=exist_server),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_server_ids",
        AsyncMock(return_value=old_models),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_server_by_name",
        AsyncMock(return_value=None),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.update_server_with_models",
        AsyncMock(return_value=exist_server),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aupdate_server_share",
        fake_update_share,
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_server_ids",
        AsyncMock(side_effect=[old_models, new_server_info.models]),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_type",
        AsyncMock(return_value=None),
    ), patch(
        "bisheng.llm.domain.services.llm._write_llm_audit",
        AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm.ResourceShareService.list_sharing_children",
        AsyncMock(return_value=[]),
    ), patch.object(
        LLMService, "get_one_llm", AsyncMock(return_value=new_server_info),
    ), patch.object(LLMService, "set_default_model", fake_set_default), \
         patch.object(LLMService, "test_model_status", fake_test_status), \
         patch.object(LLMService, "_clear_stale_model_refs_from_system_configs",
                      cleanup_mock):
        server_req = MagicMock(
            id=2, name="s2", description="", type="openai",
            limit_flag=False, limit=0, config={},
            models=[MagicMock(id=21, model_name="a", model_type="llm",
                              description="", config=None,
                              model_dump=MagicMock(return_value={
                                  "id": 21, "model_name": "a",
                                  "model_type": "llm",
                              }))],
        )
        server_req.share_to_children = False
        await LLMService.update_llm_server(
            request=MagicMock(), login_user=MagicMock(), server=server_req,
        )

    cleanup_mock.assert_awaited_once()
    assert cleanup_mock.await_args.args[0] == {22}
    assert cleanup_mock.await_args.kwargs.get("tenant_id") == 7


@pytest.mark.asyncio
async def test_update_llm_server_skips_cleanup_when_nothing_removed():
    """No ids missing from the new list → no cleanup call."""
    from bisheng.llm.domain.services.llm import LLMService

    exist_server = MagicMock(id=3, tenant_id=7, name="s3", type="openai",
                              config={}, limit_flag=False, limit=0,
                              share_to_children=False)
    same_models = [
        MagicMock(id=31, server_id=3, model_name="a", model_type="llm"),
    ]
    new_server_info = MagicMock(
        id=3, models=list(same_models), tenant_id=7,
    )
    cleanup_mock = AsyncMock()

    with patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_server_by_id",
        AsyncMock(return_value=exist_server),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_server_ids",
        AsyncMock(side_effect=[same_models, same_models]),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_server_by_name",
        AsyncMock(return_value=None),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.update_server_with_models",
        AsyncMock(return_value=exist_server),
    ), patch(
        "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_type",
        AsyncMock(return_value=None),
    ), patch(
        "bisheng.llm.domain.services.llm._write_llm_audit",
        AsyncMock(),
    ), patch(
        "bisheng.llm.domain.services.llm.ResourceShareService.list_sharing_children",
        AsyncMock(return_value=[]),
    ), patch.object(
        LLMService, "get_one_llm", AsyncMock(return_value=new_server_info),
    ), patch.object(LLMService, "set_default_model", AsyncMock()), \
         patch.object(LLMService, "test_model_status", AsyncMock()), \
         patch.object(LLMService, "_clear_stale_model_refs_from_system_configs",
                      cleanup_mock):
        server_req = MagicMock(
            id=3, name="s3", description="", type="openai",
            limit_flag=False, limit=0, config={},
            models=[MagicMock(id=31, model_name="a", model_type="llm",
                              description="", config=None,
                              model_dump=MagicMock(return_value={
                                  "id": 31, "model_name": "a",
                                  "model_type": "llm",
                              }))],
        )
        server_req.share_to_children = False
        await LLMService.update_llm_server(
            request=MagicMock(), login_user=MagicMock(), server=server_req,
        )

    cleanup_mock.assert_not_awaited()
