"""Channel SourceOwner reads real roots and every saved option, not client DTOs.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-91, AC-92.
"""

import json
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.channel.application import reference_source_owner as owner_module
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.source_contracts import SourceReadRequest, payload_digest
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def source(business, monkeypatch):
    root = await fixtures.create(business, sync=fixtures.config(10, folder="30", enabled=False))
    check = AsyncMock()
    monkeypatch.setattr(owner_module, "require_business_action", check)
    return business, root, ChannelReferenceSourceOwner(), check


async def test_snapshot_is_canonical_complete_and_column_only(source):
    context, root, owner, check = source
    async with context.sessions() as session, session.begin():
        snapshot = await owner.aresolve_source(session, SourceReadRequest("channel_sync", root.id), context.user)
        payload = json.loads(snapshot.payload_json)
        assert snapshot.source_key.tenant_id == 101 and snapshot.source_key.source_version == "current"
        assert snapshot.configuration_digest == payload_digest(snapshot.payload_json)
        assert payload["channel"]["id"] == root.id
        assert payload["sync"][0]["folder_id"] == "30" and not payload["sync"][0]["is_enabled"]
        assert {(ref.slot_key, ref.target.target_id) for ref in snapshot.references} == {
            ("main.space", "10"),
            ("main.folder", "30"),
        }
        assert not session.identity_map and not session.new and not session.dirty
        check.assert_awaited_once_with(context.user, resource_type="channel", resource_id=root.id, action="visible")


async def test_authorization_is_real_and_repeated_after_current_read(source):
    context, root, owner, check = source
    async with context.sessions() as session, session.begin():
        request = SourceReadRequest("channel_sync", root.id)
        snapshot = await owner.aresolve_source(session, request, context.user)
        check.side_effect = UnAuthorizedError()
        with pytest.raises(UnAuthorizedError):
            await owner.arevalidate_source(session, request, context.user, snapshot)
        assert check.await_count == 2


async def test_changed_configuration_is_not_accepted_because_references_are_equal(source):
    context, root, owner, _ = source
    async with context.sessions() as session, session.begin():
        request = SourceReadRequest("channel_sync", root.id)
        snapshot = await owner.aresolve_source(session, request, context.user)
        await session.execute(
            sa.update(ChannelKnowledgeSync).where(ChannelKnowledgeSync.channel_id == root.id).values(is_enabled=True)
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.arevalidate_source(session, request, context.user, snapshot)


@pytest.mark.parametrize("channel", ["root", "foreign", "missing"])
async def test_candidate_does_not_expand_current_tenant_to_static_root_sharing(source, channel):
    context, _, owner, _ = source
    async with context.sessions() as session, session.begin():
        with pytest.raises(ChannelNotFoundError):
            await owner.aresolve_source(session, SourceReadRequest("channel_sync", channel), context.user)
        assert not session.identity_map


@pytest.mark.parametrize(
    "request",
    [
        SourceReadRequest("assistant", "own"),
        SourceReadRequest("channel_sync", "own", "other"),
        SourceReadRequest("channel_sync", "own", purpose="inspect", inspect_token="not-channel-evidence"),
    ],
)
async def test_request_cannot_substitute_source_type_version_or_inspect_credential(source, request):
    context, _, owner, _ = source
    async with context.sessions() as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aresolve_source(session, request, context.user)


async def test_malformed_stored_folder_is_not_sanitized_to_space_root(source):
    context, root, owner, _ = source
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.channel_id == root.id)
            .values(folder_id="missing")
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aresolve_source(session, SourceReadRequest("channel_sync", root.id), context.user)
