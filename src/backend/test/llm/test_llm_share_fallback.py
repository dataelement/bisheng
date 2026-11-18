"""Actual provider sharing grants access; default inheritance only selects IDs.

Native full-source and slot admission are covered in knowledge_unification.
These tests retain wrapper, legacy validation and read-delegation coverage.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain import share_fallback as fallback


@pytest.fixture(autouse=True)
def execution_tenant():
    previous = get_current_tenant_id()
    set_current_tenant_id(5)
    yield
    set_current_tenant_id(previous)


@pytest.mark.parametrize("sync", [True, False])
@pytest.mark.parametrize("kind", ["model", "server"])
@pytest.mark.parametrize(
    "owner,shared,allowed", [(5, (), True), (1, ("7",), True), (1, (), False), (99, ("7",), False)]
)
async def test_read_requires_own_or_actual_root_provider_share(monkeypatch, sync, kind, owner, shared, allowed):
    row = SimpleNamespace(id=42 if kind == "model" else 7, server_id=7, tenant_id=owner)
    relation = SimpleNamespace(
        list_resource_ids_sync=MagicMock(return_value=shared), list_resource_ids=AsyncMock(return_value=shared)
    )
    monkeypatch.setattr(fallback, "get_permission_relation_api_sync", lambda: relation)
    monkeypatch.setattr(fallback, "get_permission_relation_api", AsyncMock(return_value=relation))
    name = f"{'get' if sync else 'aget'}_{kind}_by_id"
    lookup = MagicMock(return_value=row) if sync else AsyncMock(return_value=row)
    monkeypatch.setattr(fallback.LLMDao, name, lookup)
    method = getattr(fallback, name + "_with_share_fallback")
    actual = method(row.id) if sync else await method(row.id)
    assert (actual is row) is allowed
    lookup.assert_called_once_with(row.id, cache=False)


# --- BishengBase integration ------------------------------------------------


def test_bisheng_base_resolves_root_shared_pair():
    """BishengBase.get_model_server_info_sync transparently surfaces a
    root-shared (model, server) pair to a child caller — this is the path
    BishengEmbedding/LLM/Rerank/ASR/TTS take during instantiation, and the
    one that previously raised "embeddingModel configuration has been
    deleted" against a freshly created child tenant."""
    from bisheng.llm.domain.llm.base import BishengBase

    root_model = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    root_server = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)

    with (
        patch(
            "bisheng.llm.domain.llm.base.get_model_by_id_with_share_fallback",
            return_value=root_model,
        ) as mock_m,
        patch(
            "bisheng.llm.domain.llm.base.get_server_by_id_with_share_fallback",
            return_value=root_server,
        ) as mock_s,
    ):
        m, s = BishengBase.get_model_server_info_sync(42)

    assert m is root_model
    assert s is root_server
    mock_m.assert_called_once_with(42, cache=True)
    mock_s.assert_called_once_with(7, cache=True)


def test_bisheng_base_propagates_none_when_share_blocked():
    """Share=off / row truly missing → fallback returns None and
    BishengBase short-circuits without looking up the server. The caller
    (BishengEmbedding._init_client) raises the deterministic
    "deleted, please reconfigure" error, which is correct for a revoked
    share."""
    from bisheng.llm.domain.llm.base import BishengBase

    with (
        patch(
            "bisheng.llm.domain.llm.base.get_model_by_id_with_share_fallback",
            return_value=None,
        ),
        patch(
            "bisheng.llm.domain.llm.base.get_server_by_id_with_share_fallback",
        ) as mock_s,
    ):
        m, s = BishengBase.get_model_server_info_sync(42)

    assert (m, s) == (None, None)
    mock_s.assert_not_called()


@pytest.mark.asyncio
async def test_bisheng_base_async_resolves_root_shared_pair():
    from bisheng.llm.domain.llm.base import BishengBase

    root_model = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    root_server = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)

    with (
        patch(
            "bisheng.llm.domain.llm.base.aget_model_by_id_with_share_fallback",
            new=AsyncMock(return_value=root_model),
        ),
        patch(
            "bisheng.llm.domain.llm.base.aget_server_by_id_with_share_fallback",
            new=AsyncMock(return_value=root_server),
        ),
    ):
        m, s = await BishengBase.get_model_server_info(42)

    assert m is root_model
    assert s is root_server


# --- cache key namespacing --------------------------------------------------


# --- avalidate_system_model_refs --------------------------------------------


@pytest.mark.asyncio
async def test_validate_drops_none_and_empty_without_db():
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
    ) as mock_get:
        await avalidate_system_model_refs([None, 0, "", None], target_tenant_id=1)
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_validate_accepts_models_in_target_tenant():
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    rows = [MagicMock(id=42, tenant_id=5), MagicMock(id=43, tenant_id=5)]
    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
        new=AsyncMock(return_value=rows),
    ):
        await avalidate_system_model_refs([42, 43], target_tenant_id=5)


@pytest.mark.asyncio
async def test_validate_accepts_root_when_target_is_child():
    """The exact whitelist that justifies the share_fallback's read path —
    a Child setter is allowed to reference a Root-owned model so children
    can pin a shared default."""
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    row = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    relation = SimpleNamespace(list_resource_ids=AsyncMock(return_value=("7",)))
    with (
        patch("bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids", new=AsyncMock(return_value=[row])),
        patch("bisheng.llm.domain.share_fallback.get_permission_relation_api", new=AsyncMock(return_value=relation)),
    ):
        await avalidate_system_model_refs([42], target_tenant_id=5)
        relation.list_resource_ids.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_rejects_root_setter_referencing_child_model():
    """The exact bug we just hit: ``tenant_system_model_config`` for Root
    pointing at a Child-owned model. Validator must fail-closed so this
    can't be reintroduced after the data repair."""
    from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    row = MagicMock(id=5, tenant_id=3)  # Child 3 owns this gpt-4o
    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
        new=AsyncMock(return_value=[row]),
    ):
        with pytest.raises(Exception) as exc_info:
            await avalidate_system_model_refs([5], target_tenant_id=ROOT_TENANT_ID)
        # http_exception encodes the errcode as the HTTPException status_code.
        assert exc_info.value.status_code == LLMModelNotAccessibleError.Code


@pytest.mark.asyncio
async def test_validate_rejects_child_setter_referencing_other_child_model():
    """Child A may not pin a model owned by Child B — the share_default_to_
    children policy is Root → all-Children only, not lateral."""
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    row = MagicMock(id=42, tenant_id=4)
    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
        new=AsyncMock(return_value=[row]),
    ):
        with pytest.raises(Exception):
            await avalidate_system_model_refs([42], target_tenant_id=5)


@pytest.mark.asyncio
async def test_validate_rejects_when_model_id_not_found():
    """A non-existent model_id is not silently accepted — that would let an
    UI-edited payload sneak past with no row to inspect later."""
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(Exception):
            await avalidate_system_model_refs([999], target_tenant_id=1)


@pytest.mark.asyncio
async def test_validate_accepts_string_model_ids_from_ws_model():
    """WorkbenchModelConfig stores model ids as ``str`` in nested WSModel —
    coerce to int silently and validate normally."""
    from bisheng.llm.domain.share_fallback import avalidate_system_model_refs

    row = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        "bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_ids",
        new=AsyncMock(return_value=[row]),
    ):
        await avalidate_system_model_refs(["7", None, ""], target_tenant_id=ROOT_TENANT_ID)


async def test_workbench_management_metadata_keeps_invalid_ids_for_repair():
    from bisheng.llm.domain.services.llm import LLMService

    payload = {"models": [{"id": "10", "name": "Root"}, {"id": "30", "name": "deleted"}], "chat_default_model_id": "30"}
    facade = SimpleNamespace(
        aget_default=AsyncMock(
            return_value=SimpleNamespace(
                payload_json=json.dumps(payload), inherited_from_root=True, fallback_blocked=False
            )
        )
    )
    with patch("bisheng.llm.domain.services.llm.get_model_default_read_runtime", return_value=facade):
        config, inherited, blocked = await LLMService.aget_workbench_llm_with_meta(tenant_id=5)
    assert inherited and not blocked
    assert [model.id for model in config.models] == ["10", "30"]
    assert config.chat_default_model_id == "30"


async def test_knowledge_setter_passes_every_slot_to_governed_application():
    from bisheng.llm.domain.schemas import KnowledgeLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    payload = KnowledgeLLMConfig(
        embedding_model_id=4, source_model_id=7, extract_title_model_id=7, qa_similar_model_id=7, asr_model_id=9
    )
    with patch.object(LLMService, "_save_model_default", new=AsyncMock(return_value=payload)) as save:
        actual = await LLMService.update_knowledge_llm(payload, tenant_id=5)
    assert actual is payload
    assert save.await_args.args == ("knowledge_llm", payload)
    assert save.await_args.kwargs["tenant_id"] == 5


async def test_cross_tenant_setter_is_refused_before_persistence():
    from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
    from bisheng.llm.domain.schemas import EvaluationLLMConfig
    from bisheng.llm.domain.services.llm import LLMService

    with patch("bisheng.llm.domain.services.llm.ModelDefaultApplication._asave", new=AsyncMock()) as persist:
        with pytest.raises(ResourceReferenceInvalidError):
            await LLMService.update_evaluation_llm(EvaluationLLMConfig(model_id=5), tenant_id=ROOT_TENANT_ID)
        persist.assert_not_awaited()
