"""Management repair diagnostics preserve references without admitting execution."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import system_model_settings as subject
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.system_model_settings_repository import inheriting_children
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey


@pytest.mark.parametrize(
    "changes,server_changes,shared,status",
    [
        ({}, {}, (), "not_shared"),
        ({}, {}, (337,), "available"),
        ({"online": False}, {}, (337,), "offline"),
        ({"model_type": "embedding"}, {}, (337,), "wrong_type"),
        ({"tenant_id": 70}, {"tenant_id": 70}, (337,), "outside_tenant"),
        ({}, {"tenant_id": 70}, (337,), "outside_tenant"),
    ],
)
def test_diagnostics_use_real_share_and_type_facts(changes, server_changes, shared, status):
    model = LLMModel(id=933, server_id=337, tenant_id=1, model_name="Root model", model_type="llm", online=True)
    server = LLMServer(id=337, tenant_id=1, name="Root provider", type="openai")
    for key, value in changes.items():
        setattr(model, key, value)
    for key, value in server_changes.items():
        setattr(server, key, value)
    result = subject.diagnose_model_reference(
        ReferenceSpec("model_id", TargetKey("model", "933")), model, server, tenant_id=69, shared_server_ids=shared
    )
    assert result["status"] == status and result["model_id"] == 933
    assert result["model_name"] is None if status == "outside_tenant" else result["model_name"] == "Root model"


def test_unknown_model_keeps_original_id_without_inventing_a_name():
    result = subject.diagnose_model_reference(
        ReferenceSpec("asr_model_id", TargetKey("model", "922")), None, None, tenant_id=69, shared_server_ids=()
    )
    assert result == {"slot_key": "asr_model_id", "model_id": 922, "model_name": None, "status": "missing"}


async def test_five_column_repair_read_keeps_unshared_and_hidden_model_references(monkeypatch):
    authorize = AsyncMock()
    monkeypatch.setattr(subject.ModelDefaultApplication, "_authorize", authorize)
    monkeypatch.setattr(subject, "current_model_default_tenant", lambda expected=None: 69)

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(subject, "get_async_db_session", session)

    async def metadata(key, **kwargs):
        return SimpleNamespace(
            payload_json='{"model_id":933}' if key == "evaluation_llm" else "{}",
            inherited_from_root=True,
            fallback_blocked=False,
        )

    monkeypatch.setattr(subject, "get_model_default_read_runtime", lambda: SimpleNamespace(aget_default=metadata))
    monkeypatch.setattr(
        subject.LLMDao,
        "aget_model_by_ids",
        AsyncMock(
            return_value=[LLMModel(id=933, server_id=337, tenant_id=1, model_name="Root model", model_type="llm")]
        ),
    )
    monkeypatch.setattr(
        subject.LLMDao, "aget_server_by_ids", AsyncMock(return_value=[LLMServer(id=337, tenant_id=1, type="openai")])
    )
    shares = AsyncMock(return_value=[])
    monkeypatch.setattr(subject.LLMDao, "aget_shared_server_ids_for_leaf", shares)
    user = object()
    result = await subject.read_system_model_settings(user)
    assert result["tenant_id"] == 69 and len(result["sections"]) == 5
    section = next(row for row in result["sections"] if row["key"] == "evaluation_llm")
    assert section["references"][0]["status"] == "not_shared"
    assert section["references"][0]["model_id"] == 933 and section["inherited_from_root"]
    assert authorize.await_count == 2
    shares.assert_awaited_once_with(69, raise_on_error=True)


async def test_impact_counts_only_active_children_without_a_local_column_override():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Tenant.__table__.create)
            await connection.run_sync(TenantSystemModelConfig.__table__.create)
            await connection.execute(
                Tenant.__table__.insert(),
                [
                    {
                        "id": 1,
                        "tenant_code": "root",
                        "tenant_name": "Root",
                        "parent_tenant_id": None,
                        "status": "active",
                        "share_default_to_children": 1,
                    },
                    {
                        "id": 69,
                        "tenant_code": "c1",
                        "tenant_name": "Child1",
                        "parent_tenant_id": 1,
                        "status": "active",
                        "share_default_to_children": 1,
                    },
                    {
                        "id": 70,
                        "tenant_code": "c2",
                        "tenant_name": "Child2",
                        "parent_tenant_id": 1,
                        "status": "active",
                        "share_default_to_children": 1,
                    },
                    {
                        "id": 71,
                        "tenant_code": "off",
                        "tenant_name": "Inactive",
                        "parent_tenant_id": 1,
                        "status": "disabled",
                        "share_default_to_children": 1,
                    },
                ],
            )
            await connection.execute(
                TenantSystemModelConfig.__table__.insert(),
                [{"tenant_id": 69, "key": "assistant_llm", "value": "{}"}],
            )
        async with AsyncSession(engine) as session:
            result = await inheriting_children(session, ("assistant_llm", "workflow_llm"))
            assert result == {"assistant_llm": (70,), "workflow_llm": (69, 70)}
    finally:
        await engine.dispose()
