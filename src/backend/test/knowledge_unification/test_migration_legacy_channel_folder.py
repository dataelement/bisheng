"""AC-118: retain the old picker payload, migrate real references and allow repair."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.application import reference_source_owner as owner_module
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.services import channel_service as service_module
from bisheng.channel.domain.services.reference_extractor import channel_sync_scope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.application.source_contracts import ReadIdentityFacts
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_migration_inventory_repository as rows
from test.knowledge_unification.test_migration_references_application import app
from test.knowledge_unification.test_migration_references_application import complete as complete
from test.knowledge_unification.test_migration_references_application import native as native
from test.knowledge_unification.test_migration_references_application import published_input as published_input
from test.knowledge_unification.test_migration_references_application import raw_resource_native as raw_resource_native
from test.knowledge_unification.test_migration_references_application import resource_native as resource_native
from test.knowledge_unification.test_migration_references_application import transport as transport

LEGACY_FOLDER = "new-folder-1730000000000"


async def seed_legacy(database):
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(rows.channel("legacy-channel"))
        session.add_all(
            [
                ChannelKnowledgeSync(
                    id="legacy-binding",
                    channel_id="legacy-channel",
                    knowledge_space_id="9000",
                    folder_id=LEGACY_FOLDER,
                    folder_path="Original folder",
                    user_id=7,
                    is_enabled=True,
                ),
                ChannelKnowledgeSync(
                    id="normal-binding",
                    channel_id="legacy-channel",
                    knowledge_space_id="9000",
                    sub_channel_name="normal",
                    user_id=7,
                    is_enabled=False,
                ),
            ]
        )


class Identity:
    async def acapture(self, identity):
        return ReadIdentityFacts(101, ("user", identity.user_id))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_legacy}], indirect=True)
async def test_m2_through_m4_and_resume_keep_configuration_and_real_space_guards(published_input, monkeypatch):
    value = published_input
    async with value.sessions() as session, session.begin():
        before = (
            (await session.execute(sa.select(ChannelKnowledgeSync.__table__).order_by(ChannelKnowledgeSync.id)))
            .mappings()
            .all()
        )
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    async with value.sessions() as session, session.begin():
        after = (
            (await session.execute(sa.select(ChannelKnowledgeSync.__table__).order_by(ChannelKnowledgeSync.id)))
            .mappings()
            .all()
        )
        assert before == after
        references = (
            (
                await session.execute(
                    sa.select(BusinessResourceReference.__table__).where(
                        BusinessResourceReference.source_id == "legacy-channel"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert {(row["slot_key"], row["target_type"], row["target_id"]) for row in references} == {
            ("main.space", "knowledge_space", "9000"),
            (f"{channel_sync_scope('normal')}.space", "knowledge_space", "9000"),
        }
        inbound = await ReferenceRepository().alist_inbound_targets(session, (TargetKey("knowledge_space", 9000),))
        assert any(row.source_id == "legacy-channel" for row in inbound)

    monkeypatch.setattr(owner_module, "require_business_action", AsyncMock())
    verifier = SourceReadVerifier({"channel_sync": ChannelReferenceSourceOwner()}, Identity())
    reader = ReferenceSourceReadRuntime(
        verifier, SourceReadRepository(verifier), {"knowledge_space": KnowledgeSourceReadTargetOwner(verifier)}
    )
    monkeypatch.setattr(service_module, "get_reference_read_runtime", AsyncMock(return_value=reader))
    monkeypatch.setattr(service_module, "get_async_db_session", value.sessions)
    monkeypatch.setattr(service_module, "batch_check_business_visible", AsyncMock(return_value={}))
    monkeypatch.setattr(service_module.KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=[]))
    user = UserPayload(user_id=7, tenant_id=101, user_name="owner", user_role=[])
    config = await service_module.ChannelService._load_knowledge_sync(None, "legacy-channel", user)
    item = next(item for item in config.main.spaces if item.folder_id == LEGACY_FOLDER)
    assert item.folder_path == "Original folder"
    assert any(state.target_id == LEGACY_FOLDER and not state.is_valid for state in item.reference_states)
    assert await app(value).arun_references(**value.input, operator_id=7) == result


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_legacy}], indirect=True)
async def test_placeholder_change_after_freeze_cannot_be_hidden_by_equal_references(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        await session.execute(
            sa.update(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.id == "legacy-binding")
            .values(folder_id="new-folder-1730000000001")
        )
    with pytest.raises(BaseErrorCode):
        await app(value).arun_references(**value.input, operator_id=7)
