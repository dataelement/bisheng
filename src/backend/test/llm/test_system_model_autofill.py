"""Auto-fill of empty system-model settings (system_model_autofill)."""

import json
from types import SimpleNamespace

import pytest

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.llm.domain.services import system_model_autofill as autofill
from bisheng.llm.domain.services.system_model_autofill import AUTOFILL_LEDGER_KEY, SLOTS, autofill_system_models

LLM = SimpleNamespace(id=1, model_type="llm", model_name="chat-a")
EMBED = SimpleNamespace(id=2, model_type="embedding", model_name="embed-a")
ASR = SimpleNamespace(id=3, model_type="asr_rt", model_name="asr-a")
TTS = SimpleNamespace(id=4, model_type="tts", model_name="tts-a")


class FakeStore:
    """In-memory tenant_system_model_config: {(tenant, key): json}, plus inherited keys."""

    def __init__(self, rows=None, inherited=()):
        self.rows = dict(rows or {})
        self.inherited = set(inherited)
        self.writes = []

    async def aget(self, tenant_id, key):
        value = self.rows.get((tenant_id, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def aresolve(self, tenant_id, key):
        if key in self.inherited:
            return json.dumps({}), True, False
        return self.rows.get((tenant_id, key)), False, False

    async def aupsert(self, tenant_id, key, value):
        self.rows[(tenant_id, key)] = value
        self.writes.append(key)

    def cfg(self, key):
        return json.loads(self.rows[(1, key.value)])

    def ledger(self):
        return set(json.loads(self.rows[(1, AUTOFILL_LEDGER_KEY)])["slots"])


@pytest.fixture
def store(monkeypatch):
    def install(models, **kwargs):
        fake = FakeStore(**kwargs)
        dao = autofill.TenantSystemModelConfigDao
        monkeypatch.setattr(dao, "aget", fake.aget)
        monkeypatch.setattr(dao, "aresolve", fake.aresolve)
        monkeypatch.setattr(dao, "aupsert", fake.aupsert)

        async def first_models(_tenant_id):
            return {autofill._kind_of(m.model_type): m for m in models}

        monkeypatch.setattr(autofill, "_first_model_by_kind", first_models)
        return fake

    return install


async def test_fresh_tenant_gets_every_slot_filled(store):
    fake = store([LLM, EMBED, ASR, TTS])

    filled = await autofill_system_models(1)

    assert set(filled) == {slot.id for slot in SLOTS}
    workbench = fake.cfg(ConfigKeyEnum.LINSIGHT_LLM)
    assert [m["id"] for m in workbench["models"]] == ["1"]
    assert workbench["linsight_default_model_id"] == "1"
    assert workbench["chat_default_model_id"] == "1"
    assert workbench["embedding_model"]["id"] == "2"
    assert workbench["asr_model"]["id"] == "3"
    assert workbench["tts_model"]["id"] == "4"
    assert workbench["memory_llm"]["id"] == "1"
    assert fake.cfg(ConfigKeyEnum.WORKFLOW_LLM)["model_id"] == 1
    assert fake.cfg(ConfigKeyEnum.KNOWLEDGE_LLM)["asr_model_id"] == 3
    assert fake.ledger() == {slot.id for slot in SLOTS}


async def test_upgrade_fills_only_the_empty_slot_and_keeps_admin_choices(store):
    # 104-like: everything configured except the task-mode default.
    workbench = {
        "models": [{"id": "7", "name": "chat-b", "displayName": "B"}],
        "chat_default_model_id": "7",
        "linsight_default_model_id": None,
        "embedding_model": {"id": "2"},
        "chat_title_llm": {"id": "7"},
    }
    fake = store([LLM, EMBED], rows={(1, ConfigKeyEnum.LINSIGHT_LLM.value): json.dumps(workbench)})

    await autofill_system_models(1)

    saved = fake.cfg(ConfigKeyEnum.LINSIGHT_LLM)
    # The default points into the configured list, not at the tenant's first model.
    assert saved["linsight_default_model_id"] == "7"
    assert saved["chat_default_model_id"] == "7"
    assert [m["id"] for m in saved["models"]] == ["7"]
    assert saved["chat_title_llm"]["id"] == "7"
    assert saved["memory_llm"]["id"] == "7"


async def test_slot_in_ledger_is_not_refilled_after_admin_clears_it(store):
    slot_id = f"{ConfigKeyEnum.LINSIGHT_LLM.value}.tts_model"
    fake = store(
        [TTS],
        rows={
            (1, ConfigKeyEnum.LINSIGHT_LLM.value): json.dumps({"tts_model": None}),
            (1, AUTOFILL_LEDGER_KEY): json.dumps({"slots": [slot_id]}),
        },
    )

    await autofill_system_models(1)

    assert fake.cfg(ConfigKeyEnum.LINSIGHT_LLM)["tts_model"] is None


async def test_slot_without_a_model_of_its_kind_waits_for_one(store):
    fake = store([LLM])
    await autofill_system_models(1)
    embedding_slot = f"{ConfigKeyEnum.LINSIGHT_LLM.value}.embedding_model"
    assert embedding_slot not in fake.ledger()

    # The embedding model arrives later: the slot is filled then.
    fake2 = store([LLM, EMBED], rows=fake.rows)
    filled = await autofill_system_models(1)
    assert embedding_slot in filled
    assert fake2.cfg(ConfigKeyEnum.LINSIGHT_LLM)["embedding_model"]["id"] == "2"


async def test_new_slot_added_later_is_filled_on_existing_deployment(store):
    fake = store([LLM])
    await autofill_system_models(1)
    writes_before = len(fake.writes)

    # A future release adds a setting: only that slot is filled, nothing else rewritten.
    new_slot = autofill.ModelSlot(
        id="evaluation_llm.future_model_id",
        config_key=ConfigKeyEnum.EVALUATION_LLM,
        kind=autofill.KIND_LLM,
        is_set=lambda _cfg: False,
        fill=lambda _cfg, _model: None,
    )
    filled = await autofill_system_models(1, (*SLOTS, new_slot))

    assert filled == ["evaluation_llm.future_model_id"]
    assert "evaluation_llm.future_model_id" in fake.ledger()
    assert len(fake.writes) - writes_before == 2  # the evaluation config + the ledger


async def test_inherited_config_is_left_inherited(store):
    fake = store([LLM], inherited={ConfigKeyEnum.LINSIGHT_LLM.value})

    await autofill_system_models(1)

    assert (1, ConfigKeyEnum.LINSIGHT_LLM.value) not in fake.rows
    assert not any(slot.startswith("linsight_llm.") for slot in fake.ledger())


async def test_second_run_is_a_no_op(store):
    fake = store([LLM, EMBED, ASR, TTS])
    await autofill_system_models(1)
    writes = len(fake.writes)

    assert await autofill_system_models(1) == []
    assert len(fake.writes) == writes
