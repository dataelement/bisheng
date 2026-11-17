"""Channel fingerprints must use the same representation as persisted storage."""

from datetime import datetime

import pytest
import sqlalchemy as sa

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import KnowledgeSyncConfig
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from test.knowledge_unification import test_ch_bindings as native

store = native.store
tenant = native.tenant
business = native.business


@pytest.fixture(autouse=True)
async def second_precision_storage(store):
    # Match the shipped MySQL DATETIME(0) boundary in the regular SQLite suite.
    # The AFTER INSERT trigger changes only the stored value, not the ORM object.
    async with store.begin() as connection:
        await connection.execute(
            sa.text("""
            CREATE TRIGGER channel_datetime_zero_precision AFTER INSERT ON channel
            BEGIN
              UPDATE channel SET create_time = substr(NEW.create_time, 1, 19)
              WHERE id = NEW.id;
            END
        """)
        )


@pytest.mark.parametrize("microsecond", [1, 123456, 999999])
@pytest.mark.parametrize("sync_enabled", [False, True])
async def test_create_channel_survives_database_time_precision(business, microsecond, sync_enabled):
    channel = Channel(
        name="Second precision channel",
        description="Fresh channel with no concurrent writer",
        visibility=ChannelVisibilityEnum.PRIVATE,
        user_id=business.user.user_id,
        tenant_id=business.user.tenant_id,
        create_time=datetime(2026, 11, 16, 12, 0, 0, microsecond),
    )
    result = await business.service._persist_channel_configuration(
        business.user,
        new_channel=channel,
        sync_cfg=KnowledgeSyncConfig.model_validate(
            native.config(*(10,) if sync_enabled else (), enabled=sync_enabled)
        ),
    )
    assert result.id == channel.id
    assert result.create_time == datetime(2026, 11, 16, 12, 0, 0)
    async with business.sessions() as session:
        restored = await session.get(Channel, result.id)
        assert restored.name == "Second precision channel"
        assert restored.create_time == result.create_time
    state = await native.state(business)
    assert sum(row["id"] == result.id for row in state["channel"]) == 1
    assert sum(row["business_id"] == result.id for row in state["space_channel_member"]) == 1
    assert sum(row["source_id"] == result.id for row in state["business_resource_reference"]) == int(sync_enabled)
    business.adapter.authorize_created.assert_awaited_once()


async def test_real_configuration_change_still_rolls_back(business, monkeypatch):
    channel = await native.create(business, sync=native.config(enabled=False))
    before = await native.state(business)
    prepare = business.runtime.aprepare_source_bindings

    async def change_after_candidate_read(session, *args, **kwargs):
        # Simulate a database value changing after the candidate was captured.
        # Disable identity-map synchronization so the final locked read must
        # detect it, just as it would for another transaction's committed write.
        await session.execute(
            sa.update(Channel)
            .where(Channel.id == channel.id)
            .values(description="changed after candidate read")
            .execution_options(synchronize_session=False)
        )
        return await prepare(session, *args, **kwargs)

    monkeypatch.setattr(business.runtime, "aprepare_source_bindings", change_after_candidate_read)
    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        await business.service._persist_channel_configuration(
            business.user, channel_id=channel.id, changes={"name": "must not be written"}
        )
    assert error.value.kwargs["reason"] == "channel_source_changed"
    assert await native.state(business) == before
