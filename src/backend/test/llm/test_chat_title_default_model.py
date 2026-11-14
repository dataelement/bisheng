"""The first LLM a platform adds becomes its conversation-title model."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services import llm as module
from bisheng.llm.domain.services.llm import LLMService
from test.knowledge_unification.test_ref_repo import tenant


@pytest.fixture
def config_store(monkeypatch):
    actor = UserPayload(user_id=7, user_name="admin", tenant_id=101, user_role=[])
    # Every other LLM setting is already chosen, so only the title slot is in play.
    workbench = WorkbenchModelConfig(
        models=[WSModel(id="11", name="m")], chat_default_model_id="11", linsight_default_model_id="11"
    )
    store = {"workbench": workbench, "saved": None, "actor": actor}

    @asynccontextmanager
    async def sessions():
        yield object()

    async def resolve(_repository, _session, key):
        payloads = {
            "knowledge_llm": '{"extract_title_model_id":11,"source_model_id":11,"qa_similar_model_id":11}',
            "evaluation_llm": '{"model_id":11}',
            "workflow_llm": '{"model_id":11}',
            "assistant_llm": '{"auto_llm":{"model_id":11},"llm_list":[{"model_id":11}]}',
            "linsight_llm": store["workbench"].model_dump_json(),
        }
        return SimpleNamespace(inherited_from_root=False, own=SimpleNamespace(payload_json=payloads[key]))

    async def update(_user, workbench, _tasks, *, login_user):
        assert login_user is actor
        store["saved"] = workbench

    authorize = AsyncMock()
    monkeypatch.setattr(module, "get_async_db_session", sessions)
    monkeypatch.setattr(module.ModelDefaultRepository, "aresolve", resolve)
    monkeypatch.setattr(module.ModelDefaultApplication, "_authorize", authorize)
    monkeypatch.setattr(LLMService, "update_workbench_llm", update)
    with tenant(101):
        yield store
    authorize.assert_awaited_once_with(actor, 101)


@pytest.mark.parametrize("empty_slot", [None, WSModel(id="")])
async def test_first_llm_fills_an_empty_title_slot(config_store, empty_slot):
    config_store["workbench"].chat_title_llm = empty_slot

    await LLMService.set_default_model(
        SimpleNamespace(id=30, model_type="llm", model_name="dsv4"), login_user=config_store["actor"]
    )

    assert config_store["saved"].chat_title_llm.id == "30"


async def test_a_chosen_title_model_is_kept(config_store):
    config_store["workbench"].chat_title_llm = WSModel(id="7")
    # memory_llm is another empty LLM slot; set it so only the title slot is under test.
    config_store["workbench"].memory_llm = WSModel(id="7")

    await LLMService.set_default_model(
        SimpleNamespace(id=30, model_type="llm", model_name="dsv4"), login_user=config_store["actor"]
    )

    assert config_store["saved"] is None


@pytest.mark.parametrize("first_llm_id, seeded", [(30, True), (5, False)])
async def test_only_the_first_llm_on_the_platform_seeds_defaults(monkeypatch, first_llm_id, seeded):
    from bisheng.llm.domain.models.llm_server import LLMDao

    monkeypatch.setattr(LLMDao, "aget_model_by_type", AsyncMock(return_value=SimpleNamespace(id=first_llm_id)))
    set_default = AsyncMock()
    monkeypatch.setattr(LLMService, "set_default_model", set_default)
    monkeypatch.setattr(LLMService, "probe_models_in_background", AsyncMock())
    server = SimpleNamespace(models=[SimpleNamespace(id=30, model_type="llm")])

    await LLMService.add_llm_server_hook(None, None, server)

    assert set_default.await_count == (1 if seeded else 0)
