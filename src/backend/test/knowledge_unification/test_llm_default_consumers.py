"""T478: unchanged business getters enforce full-source admission before model IO.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-89, AC-91, AC-92
"""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import delete
from sqlmodel import Session

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.llm.application import model_default_read as defaults
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig, TenantSystemModelConfigDao
from bisheng.llm.domain.services import llm as service
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_llm_default_read as reading
from test.knowledge_unification import test_model_default_native_target as native

reads = reading.reads
model_owner_tenant = reading.model_owner_tenant


@pytest.fixture
async def consumers(reads, monkeypatch):
    monkeypatch.setattr(defaults, "_runtime", reads.facade)
    # A missing new admission call must fail locally instead of touching the
    # deployment database through the old self-session DAO.
    monkeypatch.setattr(
        TenantSystemModelConfigDao, "resolve", Mock(side_effect=AssertionError("legacy default DAO bypass"))
    )
    monkeypatch.setattr(
        TenantSystemModelConfigDao,
        "aresolve",
        AsyncMock(side_effect=AssertionError("legacy default DAO bypass")),
    )
    return reads


@pytest.mark.parametrize(
    "key,payload,method,sync",
    [
        ("knowledge_llm", {"source_model_id": 11}, "get_knowledge_llm", True),
        ("knowledge_llm", {"source_model_id": 11}, "aget_knowledge_llm", False),
        ("assistant_llm", {"auto_llm": {"model_id": 11}}, "get_assistant_llm", False),
        ("assistant_llm", {"auto_llm": {"model_id": 11}}, "sync_get_assistant_llm", True),
        ("evaluation_llm", {"model_id": 11}, "get_evaluation_llm", False),
        ("evaluation_llm", {"model_id": 11}, "sync_get_evaluation_llm", True),
        ("workflow_llm", {"model_id": 11}, "get_workflow_llm", False),
        (
            "linsight_llm",
            {"models": [{"id": "11", "name": "old"}], "chat_title_llm": {"id": "22", "name": "valid"}},
            "get_workbench_llm",
            False,
        ),
        ("linsight_llm", {"models": [{"id": "11", "name": "old"}]}, "get_workbench_llm_sync", True),
    ],
)
async def test_existing_business_getters_reject_one_invalid_target_in_whole_key(consumers, key, payload, method, sync):
    with Session(consumers.engine) as session, session.begin():
        native.seed_default(session, key=key, payload=payload)
        session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_tenant_id=101,
                target_type="model",
                target_id="11",
                operation_id="deleted-original",
                operation_type="force_delete_model",
                actor_type="user",
                actor_id="7",
                stage="deleted",
            )
        )
    with pytest.raises(ResourceReferenceInvalidError):
        if sync:
            getattr(service.LLMService, method)()
        else:
            await getattr(service.LLMService, method)()


async def test_original_knowledge_consumer_never_initializes_model_before_full_admission(consumers, monkeypatch):
    with Session(consumers.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key="knowledge_llm", value='{"source_model_id":11}'))
    model = Mock(side_effect=AssertionError("model IO before reference admission"))
    monkeypatch.setattr(service.LLMService, "get_bisheng_llm_sync", model)
    with pytest.raises(ReferenceCoverageNotReadyError):
        service.LLMService.get_knowledge_source_llm(7)
    model.assert_not_called()


@pytest.mark.parametrize(
    "key,endpoint,field,value",
    [
        ("knowledge_llm", "get_knowledge_llm", "source_model_id", 777),
        ("assistant_llm", "get_assistant_llm", "auto_llm", {"model_id": 777}),
        ("evaluation_llm", "get_evaluation_llm", "model_id", 777),
        ("workflow_llm", "get_workflow_llm", "model_id", 777),
    ],
)
async def test_management_get_returns_unindexed_invalid_original_ids_for_manual_repair(
    consumers, key, endpoint, field, value
):
    import json

    from bisheng.llm.api import router as api

    with Session(consumers.engine) as session, session.begin():
        session.add(TenantSystemModelConfig(tenant_id=101, key=key, value=json.dumps({field: value})))
    user = UserPayload(user_id=7, user_name="admin", tenant_id=101, user_role=[])
    result = await getattr(api, endpoint)(request=None, login_user=user)
    stored = result.data["data"][field]
    assert stored["model_id"] == 777 if isinstance(stored, dict) else stored == 777
    assert result.data["inherited_from_root"] is False


async def test_workbench_management_raw_settings_preserves_invalid_asr_without_probe(consumers, monkeypatch):
    from bisheng.llm.api import router as api

    with Session(consumers.engine) as session, session.begin():
        session.add(
            TenantSystemModelConfig(
                tenant_id=101,
                key="linsight_llm",
                value='{"asr_model":{"id":"777","name":"deleted"},"models":[{"id":"11","name":"old"}]}',
            )
        )
    monkeypatch.setattr(api, "_assert_can_write_system_config", AsyncMock())
    monkeypatch.setattr(
        service.BishengASR,
        "get_model_server_info",
        AsyncMock(side_effect=AssertionError("raw repair must not resolve invalid model")),
    )
    result = await api.get_workbench_settings(
        login_user=UserPayload(user_id=7, user_name="admin", tenant_id=101, user_role=[])
    )
    assert result.data["data"]["asr_model"]["id"] == "777"
    assert result.data["data"]["models"][0]["id"] == "11"


async def test_strict_default_getter_does_not_accept_explicit_other_tenant(consumers):
    with pytest.raises(ResourceReferenceInvalidError):
        await service.LLMService.get_evaluation_llm(tenant_id=202)
