"""F050 Channel creation, retry, business settings, and initial Grant contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelCreationRequestConflictError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget

_CS = "bisheng.channel.domain.services.channel_service"


class _LoginUser:
    user_id = 7
    user_name = "creator"
    tenant_id = 3


class _Adapter:
    def __init__(self, owner_error: Exception | None = None) -> None:
        self.owner_error = owner_error
        self.authorized = 0

    async def authorize_created(self, **kwargs):
        self.authorized += 1
        if self.owner_error is not None:
            raise self.owner_error

    async def resolve_permission_target(self, **kwargs):
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=3,
            resource_type="channel",
            resource_id=kwargs["resource_id"],
            resource_version=1,
            context_version="channel:v1",
        )


class _InitialGrants:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests = []

    async def apply(self, **kwargs):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        source = SimpleNamespace(source_id=92, active=True, protected=False)
        return SimpleNamespace(resource_version=2, grants=(SimpleNamespace(sources=(source,)),))


def _request(*, request_id: str | None = "req-1") -> CreateChannelRequest:
    return CreateChannelRequest.model_validate(
        {
            "name": "News",
            "source_list": ["source-a"],
            "visibility": "public",
            "description": "Daily",
            "filter_rules": [
                {
                    "relation": "and",
                    "rules": [{"type": "single", "rule_type": "include", "keywords": ["AI"]}],
                    "channel_type": "main",
                }
            ],
            "knowledge_sync": {
                "main": {
                    "enabled": True,
                    "spaces": [{"knowledge_space_id": "10", "folder_id": "20"}],
                },
                "subs": [],
            },
            "creation_request_id": request_id,
            "initial_permissions": (
                {
                    "expected_catalog_release_id": 42,
                    "grants": [{"model_key": "viewer", "subject": {"type": "user", "id": "8"}}],
                }
                if request_id is not None
                else None
            ),
        }
    )


def _channel(request: CreateChannelRequest, *, payload_hash: str | None = None) -> Channel:
    return Channel(
        id="channel-1",
        name=request.name,
        source_list=request.source_list,
        visibility=request.visibility,
        description=request.description,
        filter_rules=[row.model_dump() for row in request.filter_rules or ()],
        user_id=7,
        tenant_id=3,
        creation_request_id=request.creation_request_id,
        creation_payload_hash=payload_hash,
    )


def _service(repository, adapter: _Adapter, grants: _InitialGrants | None = None):
    members = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[]),
        find_membership=AsyncMock(return_value=None),
        add_member=AsyncMock(),
    )
    info_sources = SimpleNamespace(find_by_ids=AsyncMock(return_value=[SimpleNamespace(id="source-a")]))
    service = ChannelService(
        channel_repository=repository,
        space_channel_member_repository=members,
        channel_info_source_repository=info_sources,
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
        initial_grant_application=grants,
    )
    service.update_channels_latest_article_time = AsyncMock()
    service._save_knowledge_sync = AsyncMock()
    return service, members, info_sources


@pytest.fixture(autouse=True)
def _runtime_stubs():
    information = SimpleNamespace(subscribe_information_source=AsyncMock())
    with (
        patch(f"{_CS}.QuotaService.get_effective_quota", new=AsyncMock(return_value=-1)),
        patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=information)),
        patch(f"{_CS}.resolve_permission_actor", new=AsyncMock(return_value=SimpleNamespace(user_id=7))),
    ):
        yield information


async def test_new_payload_preserves_filters_sync_and_applies_initial_grants() -> None:
    request = _request()
    adapter = _Adapter()
    grants = _InitialGrants()
    repository = SimpleNamespace(
        find_by_creation_request=AsyncMock(return_value=None),
        save_creation=AsyncMock(),
    )
    created = _channel(request)
    created.creation_payload_hash = ChannelService._creation_payload_hash(request)
    repository.save_creation.return_value = (created, True)
    service, members, _ = _service(repository, adapter, grants)

    with patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)):
        result = await service.create_channel(request, _LoginUser())

    saved = repository.save_creation.call_args.args[0]
    assert saved.creation_request_id == "req-1"
    assert len(saved.creation_payload_hash) == 64
    assert saved.filter_rules == [row.model_dump() for row in request.filter_rules]
    service._save_knowledge_sync.assert_awaited_once_with(
        channel_id="channel-1",
        cfg=request.knowledge_sync,
        user_id=7,
    )
    assert result.initial_permission_result.status == "succeeded"
    assert result.initial_permission_result.assignee_ids == ["92"]
    assert grants.requests[0]["request"].expected_catalog_release_id == 42
    members.add_member.assert_awaited_once()


async def test_retry_skips_completed_external_subscription_and_resumes_durable_steps(_runtime_stubs) -> None:
    request = _request()
    existing = _channel(request, payload_hash=ChannelService._creation_payload_hash(request))
    repository = SimpleNamespace(
        find_by_creation_request=AsyncMock(return_value=existing),
        save_creation=AsyncMock(),
    )
    adapter = _Adapter()
    grants = _InitialGrants()
    service, members, info_sources = _service(repository, adapter, grants)
    members.find_membership.return_value = SimpleNamespace(id=1)

    with patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)):
        result = await service.create_channel(request, _LoginUser())

    assert result.id == "channel-1"
    repository.save_creation.assert_not_awaited()
    info_sources.find_by_ids.assert_not_awaited()
    _runtime_stubs.subscribe_information_source.assert_not_awaited()
    members.add_member.assert_not_awaited()
    service._save_knowledge_sync.assert_awaited_once()
    assert adapter.authorized == 1
    assert len(grants.requests) == 1


async def test_owner_failure_propagates_before_initial_grants() -> None:
    request = _request()
    created = _channel(request, payload_hash=ChannelService._creation_payload_hash(request))
    repository = SimpleNamespace(
        find_by_creation_request=AsyncMock(return_value=None),
        save_creation=AsyncMock(return_value=(created, True)),
    )
    grants = _InitialGrants()
    adapter = _Adapter(owner_error=RuntimeError("owner failed"))
    service, _, _ = _service(repository, adapter, grants)

    with patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)):
        with pytest.raises(RuntimeError, match="owner failed"):
            await service.create_channel(request, _LoginUser())

    assert grants.requests == []


async def test_initial_grant_failure_returns_partial_success() -> None:
    request = _request()
    created = _channel(request, payload_hash=ChannelService._creation_payload_hash(request))
    repository = SimpleNamespace(
        find_by_creation_request=AsyncMock(return_value=None),
        save_creation=AsyncMock(return_value=(created, True)),
    )
    adapter = _Adapter()
    service, _, _ = _service(repository, adapter, _InitialGrants(error=RuntimeError("grant failed")))

    with patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)):
        result = await service.create_channel(request, _LoginUser())

    assert result.id == "channel-1"
    assert result.initial_permission_result.status == "failed"
    assert result.initial_permission_result.error_code == 500


async def test_same_key_with_changed_filter_or_sync_conflicts_before_owner() -> None:
    request = _request()
    existing = _channel(request, payload_hash="x" * 64)
    repository = SimpleNamespace(find_by_creation_request=AsyncMock(return_value=existing))
    adapter = _Adapter()
    service, _, _ = _service(repository, adapter)

    with pytest.raises(ChannelCreationRequestConflictError):
        await service.create_channel(request, _LoginUser())

    assert adapter.authorized == 0


async def test_unique_key_race_uses_winner_and_does_not_duplicate_creator() -> None:
    request = _request()
    existing = _channel(request, payload_hash=ChannelService._creation_payload_hash(request))
    repository = SimpleNamespace(
        find_by_creation_request=AsyncMock(return_value=None),
        save_creation=AsyncMock(return_value=(existing, False)),
    )
    adapter = _Adapter()
    service, members, _ = _service(repository, adapter, _InitialGrants())
    members.find_membership.return_value = SimpleNamespace(id=1)

    with patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter)):
        result = await service.create_channel(request, _LoginUser())

    assert result.id == "channel-1"
    members.add_member.assert_not_awaited()
