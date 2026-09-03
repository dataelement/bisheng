"""F050 Knowledge Space creation, idempotency, and initial Grant contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.knowledge_space import SpaceCreationRequestConflictError
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import InitialPermissionsRequest
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class _Adapter:
    def __init__(
        self,
        owner_error: Exception | None = None,
        resolve_error: Exception | None = None,
    ) -> None:
        self.owner_error = owner_error
        self.resolve_error = resolve_error
        self.authorized = 0
        self.resolved = 0
        self.public_syncs = []

    async def authorize_created(self, **kwargs):
        self.authorized += 1
        if self.owner_error is not None:
            raise self.owner_error

    async def resolve_permission_target(self, **kwargs):
        self.resolved += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=kwargs["resource_id"],
            resource_version=1,
            context_version="created:v1",
        )

    async def sync_public_reader(self, **kwargs):
        self.public_syncs.append(kwargs)


class _InitialGrants:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests = []

    async def apply(self, **kwargs):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        source = SimpleNamespace(source_id=91, active=True, protected=False)
        grant = SimpleNamespace(sources=(source,))
        return SimpleNamespace(resource_version=2, grants=(grant,))


def _user():
    return SimpleNamespace(user_id=11, user_name="creator", tenant_id=7, role="user")


def _space(*, request_id: str | None = None, payload_hash: str | None = None) -> Knowledge:
    return Knowledge(
        id=101,
        tenant_id=7,
        user_id=11,
        name="Space",
        type=KnowledgeTypeEnum.SPACE.value,
        state=KnowledgeState.PUBLISHED.value,
        auth_type=AuthTypeEnum.PUBLIC,
        model="3",
        creation_request_id=request_id,
        creation_payload_hash=payload_hash,
    )


def _initial() -> InitialPermissionsRequest:
    return InitialPermissionsRequest.model_validate(
        {
            "expected_catalog_release_id": 42,
            "grants": [{"model_key": "viewer", "subject": {"type": "user", "id": "8"}}],
        }
    )


def _service(adapter: _Adapter, grants: _InitialGrants | None = None) -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(
        request=MagicMock(),
        login_user=_user(),
        initial_grant_application=grants,
    )
    service._resource_adapter = AsyncMock(return_value=adapter)
    service._permission_actor = AsyncMock(return_value=SimpleNamespace(user_id=11, current_tenant_id=7))
    service._is_auto_tag_feature_visible = AsyncMock(return_value=True)
    return service


def _creation_patches(space: Knowledge):
    return (
        patch.object(KnowledgeSpaceService, "_is_square_preview_space", return_value=False),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_count_spaces_by_user",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=3)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base",
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeAuditTelemetryService.audit_create_knowledge_space",
            new_callable=AsyncMock,
        ),
        # Creation quota is role-configurable; stub the lookup so these tests
        # stay about the permission/creation flow rather than the quota engine.
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_effective_quota",
            new_callable=AsyncMock,
            return_value=50,
        ),
    )


async def test_legacy_payload_preserves_original_response_and_side_effects() -> None:
    adapter = _Adapter()
    service = _service(adapter)
    patches = _creation_patches(_space())
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as create,
        patches[4] as member,
        patches[5] as audit,
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
        ) as lookup,
    ):
        result = await service.create_knowledge_space(name="Space")

    assert result.id == 101
    assert result.initial_permission_result is None
    assert create.call_args.args[2].creation_request_id is None
    assert adapter.authorized == 1
    member.assert_awaited_once()
    audit.assert_awaited_once()
    lookup.assert_not_awaited()


async def test_released_public_space_creation_does_not_sync_public_reader() -> None:
    adapter = _Adapter()
    service = _service(adapter)
    inserted = _space()
    inserted.is_released = True
    inserted.auth_type = AuthTypeEnum.PUBLIC
    patches = _creation_patches(inserted)
    with (
        patches[1],
        patches[2],
        patches[3],
        patches[4] as member,
        patches[5],
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
        ),
    ):
        result = await service.create_knowledge_space(
            name="Space",
            is_released=True,
            auth_type=AuthTypeEnum.PUBLIC,
        )

    assert result.id == 101
    assert adapter.authorized == 1
    assert adapter.public_syncs == []
    member.assert_awaited_once()


async def test_new_payload_persists_hash_preserves_auto_tag_and_applies_grants() -> None:
    adapter = _Adapter()
    grants = _InitialGrants()
    service = _service(adapter, grants)
    inserted = _space(request_id="req-1")
    patches = _creation_patches(inserted)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as create,
        patches[4],
        patches[5],
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            service,
            "_apply_auto_tag_binding",
            new_callable=AsyncMock,
            return_value=(True, 19),
        ) as tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            side_effect=lambda value: value,
        ),
    ):
        result = await service.create_knowledge_space(
            name="Space",
            auto_tag_enabled=True,
            auto_tag_custom_tags=["A", "B"],
            creation_request_id="req-1",
            initial_permissions=_initial(),
        )

    db_space = create.call_args.args[2]
    assert db_space.creation_request_id == "req-1"
    assert len(db_space.creation_payload_hash) == 64
    tags.assert_awaited_once()
    assert inserted.auto_tag_enabled is True
    assert inserted.auto_tag_library_id == 19
    assert result.initial_permission_result.status == "succeeded"
    assert result.initial_permission_result.assignee_ids == ["91"]
    assert grants.requests[0]["request"].command_key == "req-1"


async def test_owner_failure_propagates_without_attempting_initial_grants() -> None:
    adapter = _Adapter(owner_error=RuntimeError("owner failed"))
    grants = _InitialGrants()
    service = _service(adapter, grants)
    patches = _creation_patches(_space(request_id="req-1"))
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with pytest.raises(RuntimeError, match="owner failed"):
            await service.create_knowledge_space(
                name="Space",
                creation_request_id="req-1",
                initial_permissions=_initial(),
            )

    assert grants.requests == []


async def test_initial_grant_failure_is_returned_as_partial_success() -> None:
    adapter = _Adapter()
    service = _service(adapter, _InitialGrants(error=RuntimeError("grant failed")))
    patches = _creation_patches(_space(request_id="req-1"))
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await service.create_knowledge_space(
            name="Space",
            creation_request_id="req-1",
            initial_permissions=_initial(),
        )

    assert result.id == 101
    assert result.initial_permission_result.status == "failed"
    assert result.initial_permission_result.error_code == 500
    assert result.initial_permission_result.message is None


async def test_initial_target_resolution_failure_is_returned_as_partial_success() -> None:
    adapter = _Adapter(resolve_error=RuntimeError("target failed"))
    grants = _InitialGrants()
    service = _service(adapter, grants)
    patches = _creation_patches(_space(request_id="req-1"))
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await service.create_knowledge_space(
            name="Space",
            creation_request_id="req-1",
            initial_permissions=_initial(),
        )

    assert result.id == 101
    assert result.initial_permission_result.status == "failed"
    assert result.initial_permission_result.error_code == 500
    assert grants.requests == []


async def test_same_key_retry_resumes_permissions_without_business_side_effects() -> None:
    adapter = _Adapter()
    grants = _InitialGrants()
    service = _service(adapter, grants)
    payload_hash = service._creation_payload_hash(
        name="Space",
        description=None,
        icon=None,
        auth_type=AuthTypeEnum.PUBLIC,
        is_released=False,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        auto_tag_custom_tags=None,
        initial_permissions=_initial(),
    )
    existing = _space(request_id="req-1", payload_hash=payload_hash)
    with (
        patch.object(KnowledgeSpaceService, "_is_square_preview_space", return_value=False),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            return_value=existing,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base"
        ) as create,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member",
            new_callable=AsyncMock,
        ) as member,
    ):
        result = await service.create_knowledge_space(
            name="Space",
            creation_request_id="req-1",
            initial_permissions=_initial(),
        )

    assert result.id == 101
    assert adapter.authorized == 1
    assert len(grants.requests) == 1
    create.assert_not_called()
    member.assert_not_awaited()


async def test_same_key_with_different_payload_conflicts_before_owner() -> None:
    adapter = _Adapter()
    service = _service(adapter, _InitialGrants())
    existing = _space(request_id="req-1", payload_hash="x" * 64)
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        with pytest.raises(SpaceCreationRequestConflictError):
            await service.create_knowledge_space(name="Different", creation_request_id="req-1")

    assert adapter.authorized == 0


async def test_unique_key_race_loads_winner_and_skips_duplicate_side_effects() -> None:
    adapter = _Adapter()
    service = _service(adapter)
    payload_hash = service._creation_payload_hash(
        name="Space",
        description=None,
        icon=None,
        auth_type=AuthTypeEnum.PUBLIC,
        is_released=False,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        auto_tag_custom_tags=None,
        initial_permissions=None,
    )
    inserted = _space(request_id="req-1", payload_hash=payload_hash)
    patches = _creation_patches(inserted)
    lookups = [None, inserted]
    with (
        patches[0],
        patches[1],
        patches[2],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.create_knowledge_base",
            side_effect=IntegrityError("duplicate", None, Exception("duplicate")),
        ),
        patches[4] as member,
        patches[5] as audit,
        patches[6],
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aget_by_creation_request",
            new_callable=AsyncMock,
            side_effect=lookups,
        ),
    ):
        result = await service.create_knowledge_space(name="Space", creation_request_id="req-1")

    assert result.id == 101
    member.assert_not_awaited()
    audit.assert_not_awaited()
