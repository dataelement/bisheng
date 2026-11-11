"""F050 Channel creation, retry, business settings, and initial Grant contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.common.errcode.channel import ChannelCreationRequestConflictError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business

_CS = "bisheng.channel.domain.services.channel_service"


class _Adapter:
    def __init__(
        self,
        owner_error: Exception | None = None,
        resolve_error: Exception | None = None,
    ) -> None:
        self.owner_error = owner_error
        self.resolve_error = resolve_error
        self.authorized = 0

    async def authorize_created(self, **kwargs):
        self.authorized += 1
        if self.owner_error is not None:
            raise self.owner_error

    async def resolve_permission_target(self, **kwargs):
        if self.resolve_error is not None:
            raise self.resolve_error
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=101,
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
                    "spaces": [{"knowledge_space_id": "10", "folder_id": "30"}],
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


def configure(context, adapter, grants=None):
    context.service.initial_grant_application = grants
    return patch(f"{_CS}.get_f048_resource_adapter", new=AsyncMock(return_value=adapter))


async def test_new_payload_preserves_filters_sync_and_applies_initial_grants(business):
    request, adapter, grants = _request(), _Adapter(), _InitialGrants()
    with configure(business, adapter, grants):
        result = await business.service.create_channel(request, business.user)
    state = await fixtures.state(business)
    saved = next(row for row in state["channel"] if row["id"] == result.id)
    assert saved["creation_request_id"] == "req-1"
    assert len(saved["creation_payload_hash"]) == 64
    assert saved["filter_rules"] == [row.model_dump() for row in request.filter_rules]
    selected = next(row for row in state["channel_knowledge_sync"] if row["channel_id"] == result.id)
    assert selected["knowledge_space_id"] == "10" and selected["folder_id"] == "30" and selected["user_id"] == 7
    assert result.initial_permission_result.status == "succeeded"
    assert result.initial_permission_result.assignee_ids == ["92"]
    assert grants.requests[0]["request"].expected_catalog_release_id == 42
    assert len([row for row in state["space_channel_member"] if row["business_id"] == result.id]) == 1


async def test_retry_skips_completed_external_subscription_and_resumes_durable_steps(business):
    request, adapter, grants = _request(), _Adapter(), _InitialGrants()
    with configure(business, adapter, grants):
        first = await business.service.create_channel(request, business.user)
        before = await fixtures.state(business)
        grants.requests.clear()
        again = await business.service.create_channel(request, business.user)
    assert again.id == first.id
    assert await fixtures.state(business) == before
    assert adapter.authorized == 1
    assert len(grants.requests) == 1
    # Existing sync row UUIDs, creator membership and source revision stay put;
    # external information subscriptions remain the reconcile worker's concern.


async def test_owner_failure_propagates_before_initial_grants(business):
    before = await fixtures.state(business)
    adapter, grants = _Adapter(owner_error=RuntimeError("owner failed")), _InitialGrants()
    with configure(business, adapter, grants), pytest.raises(RuntimeError, match="owner failed"):
        await business.service.create_channel(_request(), business.user)
    assert grants.requests == [] and await fixtures.state(business) == before


async def test_initial_grant_failure_returns_partial_success(business):
    adapter = _Adapter()
    with configure(business, adapter, _InitialGrants(error=RuntimeError("grant failed"))):
        result = await business.service.create_channel(_request(), business.user)
    assert any(row["id"] == result.id for row in (await fixtures.state(business))["channel"])
    assert result.initial_permission_result.status == "failed"
    assert result.initial_permission_result.error_code == 500
    assert result.initial_permission_result.message is None


async def test_initial_target_resolution_failure_returns_partial_success(business):
    adapter, grants = _Adapter(resolve_error=RuntimeError("target failed")), _InitialGrants()
    with configure(business, adapter, grants):
        result = await business.service.create_channel(_request(), business.user)
    assert any(row["id"] == result.id for row in (await fixtures.state(business))["channel"])
    assert result.initial_permission_result.status == "failed"
    assert result.initial_permission_result.error_code == 500
    assert grants.requests == []


async def test_same_key_with_changed_filter_or_sync_conflicts_before_owner(business):
    request, adapter = _request(), _Adapter()
    with configure(business, adapter, _InitialGrants()):
        await business.service.create_channel(request, business.user)
        before = await fixtures.state(business)
        adapter.authorized = 0
        changed = request.model_copy(update={"description": "changed configuration"})
        with pytest.raises(ChannelCreationRequestConflictError):
            await business.service.create_channel(changed, business.user)
    assert adapter.authorized == 0 and await fixtures.state(business) == before


async def test_unique_key_race_uses_winner_and_does_not_duplicate_creator(business, monkeypatch):
    from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository

    request, adapter, grants = _request(), _Adapter(), _InitialGrants()
    with configure(business, adapter, grants):
        response = await business.service.create_channel(request, business.user)
        async with business.sessions() as session:
            winner = await ChannelReferenceBindingRepository().aget(session, response.id)
        before = await fixtures.state(business)
        original = business.service._persist_channel_configuration

        async def raced(user, **kwargs):
            if kwargs.get("new_channel") is not None:
                raise IntegrityError("insert", {}, RuntimeError("unique request key"))
            return await original(user, **kwargs)

        monkeypatch.setattr(
            ChannelReferenceBindingRepository, "aget_by_creation_request", AsyncMock(side_effect=[None, winner])
        )
        monkeypatch.setattr(business.service, "_persist_channel_configuration", raced)
        result = await business.service.create_channel(request, business.user)
    assert result.id == winner.id
    assert await fixtures.state(business) == before
