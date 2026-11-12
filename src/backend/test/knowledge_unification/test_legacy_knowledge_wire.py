"""T267: server-owned fields persist without expanding legacy responses.

Coverage: AC-65, AC-66, AC-68.
The actual create endpoint returns a raw ORM inside an Any envelope; a Base
DTO field-list assertion alone does not protect that serialization path.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import Session, SQLModel, create_engine, select

from bisheng.knowledge.domain.models.knowledge import Knowledge

PRIVATE_VALUES = {
    "processing_defaults": {"schema_version": 1},
    "processing_config_version": 8,
    "model_config_revision": 9,
    "model_transition": {"operation_id": "internal-switch"},
    "index_generation": "internal-generation",
    "migration_origin": "internal-run",
}


async def test_actual_legacy_create_response_omits_internal_fields(monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.knowledge.api.endpoints import knowledge as endpoint
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    row = Knowledge(id=7, tenant_id=101, user_id=11, name="legacy", type=3, **PRIVATE_VALUES)

    async def prepare(*_args, **_kwargs):
        return SimpleNamespace(tenant_id=101)

    async def create(*_args, **_kwargs):
        return row

    monkeypatch.setattr(endpoint.KnowledgeCreationPolicy, "prepare", prepare)
    monkeypatch.setattr(KnowledgeSpaceService, "create_knowledge_space", create)
    monkeypatch.setattr(endpoint.KnowledgeService, "aconvert_knowledge_read", AsyncMock(return_value=[row]))
    response = await endpoint.create_knowledge(
        request=SimpleNamespace(),
        login_user=UserPayload(user_id=11, tenant_id=101, user_role=[]),
        knowledge=endpoint.KnowledgeWebCreate(name="legacy", type=0, expected_tenant_id=101),
    )
    data = response.model_dump(mode="json")["data"]
    assert data["id"] == 7 and data["name"] == "legacy"
    assert data["type"] == 0 and row.type == 3
    assert not PRIVATE_VALUES.keys() & data.keys()


def test_internal_fields_remain_database_columns_and_owner_attributes(tenant_context):
    tenant_context(101)
    engine = create_engine("sqlite://")
    try:
        SQLModel.metadata.create_all(engine, tables=[Knowledge.__table__])
        with Session(engine) as session:
            session.add(Knowledge(id=7, tenant_id=101, user_id=11, name="legacy", type=3, **PRIVATE_VALUES))
            session.commit()
            row = session.exec(select(Knowledge).where(Knowledge.id == 7)).one()
            assert {key: getattr(row, key) for key in PRIVATE_VALUES} == PRIVATE_VALUES
            assert not PRIVATE_VALUES.keys() & row.model_dump().keys()
    finally:
        engine.dispose()
